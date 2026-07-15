# Core 07：串行 Runner、重试策略与断点续跑

## 操作提示词（可直接复制）

```text
你是实现 Core 07 的编码代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。
只读取本 spec（D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\core-07-runner-resume.md）以及“Base / prerequisites”列出的必要代码；不得读取总计划。
严格采用 TDD，仅可创建/修改 app/runner.py 与 tests/test_runner.py。不得改动其他文件，不得访问真实站点，不得生成或提交 runtime artifacts。
按本文命令验证。验证通过后只提交上述两个文件，commit message 必须是：feat: add resumable serial runner
完成时回报：DONE；变更文件；先失败后通过的测试命令及结果；commit hash。
无法完成时回报：BLOCKED；阻塞步骤；原始错误摘要；已执行命令；未提交文件列表。不要越界修复前置任务。
```

## Base / prerequisites

- 在仓库根目录 `D:\DataAnt\.worktrees\browser-bot-demo` 执行全部命令；使用现有 `.venv`，不要安装依赖。
- 以下模块必须已存在且测试通过：`app/models.py`、`app/matcher.py`、`app/excel_store.py`、`app/sites/douban_movie.py`。
- 必要数据契约：

```python
class Status(StrEnum):
    SUCCESS = "SUCCESS"
    NOT_FOUND = "NOT_FOUND"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PAGE_CHANGED = "PAGE_CHANGED"
    BLOCKED = "BLOCKED"
    OUTPUT_LOCKED = "OUTPUT_LOCKED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"

@dataclass(frozen=True, slots=True)
class RunSummary:
    processed: int = 0
    skipped: int = 0
    blocked: bool = False
```

- 调用契约：`choose_match(task, candidates) -> MatchDecision`；`MovieResult.from_task(task)`；`MovieResult.stamped()`；`adapter.search(tab, task)`；`adapter.fetch_detail(tab, task, candidate)`；`store.status_by_task_id() -> dict[str, Status]`；`store.upsert(result) -> None`。
- 站点异常：`BlockedError` 表示验证码、限流或 403/418/429，必须停止整批；`PageChangedError` 表示关键页面结构改变；`NetworkError` 是可重试的暂时网络错误，但本任务只建立状态边界，网络退避由 Core 08 增强。
- 浏览器技术栈为 DrissionPage；Runner 只接收 `tab`，不得直接读写 `browser-profile`。失败诊断的产物契约是截图 + 脱敏 HTML，但本任务不创建诊断模块或产物。

## Goal

实现 `Runner.run(tasks) -> RunSummary`：单个 `tab` 串行处理任务，读取已持久化状态以断点续跑，默认只重跑瞬态状态，逐条 upsert，遇到阻断立即 fail closed，并维持每条任务最小间隔。

## Files 边界

- Create: `app/runner.py`
- Create: `tests/test_runner.py`
- 禁止修改任何其他文件。

## 精确行为契约

```python
DEFAULT_RETRY = {
    Status.NETWORK_ERROR,
    Status.OUTPUT_LOCKED,
    Status.UNEXPECTED_ERROR,
}

class Runner:
    def __init__(
        self,
        adapter,
        store,
        tab,
        min_interval_seconds: float = 5,
        retry_statuses=None,
    ) -> None: ...

    def run(self, tasks: list[Task]) -> RunSummary: ...
```

- `retry_statuses` 只与 `DEFAULT_RETRY` 求并集，不能移除默认项。
- 已有状态不在重跑集合中则跳过；包括 `SUCCESS`、`NOT_FOUND`、`REVIEW_REQUIRED`、`PAGE_CHANGED`、`BLOCKED`。
- 无候选写 `NOT_FOUND`，`error_message="No candidates"`。
- 无唯一匹配写 `REVIEW_REQUIRED`，错误信息为 `MatchDecision.reason`。
- 唯一匹配才调用 `fetch_detail`，并把结果的 `match_method` 替换为决策方法。
- `BlockedError` 写 `BLOCKED` 后立即返回 `RunSummary(processed + 1, skipped, True)`，后续任务不得执行。
- `PageChangedError` 写 `PAGE_CHANGED` 并继续下一条。
- 每个写出的结果必须调用 `stamped()` 或保留详情解析器已写入的时间；同一 `task_id` 只能通过 `upsert` 更新。
- 每条实际处理的任务从开始计时；若耗时小于 `min_interval_seconds`，只补足差额。跳过任务不等待。
- 本任务不得吞掉 `NetworkError`、输出锁异常或未知异常；后续诊断增强会分类处理它们。

## TDD 步骤

### 1. 写失败测试

在 `tests/test_runner.py` 使用 `FakeStore`、`FakeAdapter` 和普通 `object()` 作为 `tab`，至少覆盖：

1. 已有 `SUCCESS` 被跳过，无候选写 `NOT_FOUND`；
2. 同名多候选且无年份时写 `REVIEW_REQUIRED`；
3. 默认重跑 `NETWORK_ERROR`，显式 `retry_statuses={Status.PAGE_CHANGED}` 额外重跑页面变化；
4. `BlockedError` 写入当前任务并阻止后续任务；
5. `PageChangedError` 写入后继续；
6. 唯一匹配调用详情接口并保留规则匹配方法；
7. 用 monkeypatch 的单调时钟和 `time.sleep` 断言只补足最小间隔。

运行：

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest tests/test_runner.py -v
```

Expected: FAIL，原因是 `app.runner` 尚不存在或 `Runner` 行为未实现；失败必须来自新断言，不得是测试语法错误。

### 2. 最小实现

创建 `app/runner.py`，只实现上述契约。适配器参数统一命名为 `tab`；不要建立额外浏览器实例。

### 3. 通过专项与全量测试

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest tests/test_runner.py -v
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q
```

Expected: runner 专项全部 PASS；全量测试退出码 0。

## Acceptance checklist

- [ ] `Runner.run()` 返回准确的 `processed/skipped/blocked`。
- [ ] 默认重跑集合严格为三个瞬态状态，显式状态只做加法。
- [ ] 终态跳过、upsert、阻断立即停止和页面变化继续均有测试。
- [ ] 匹配、详情读取都复用注入的同一 `tab`。
- [ ] 最小间隔测试不进行真实等待或网络访问。
- [ ] 专项与全量测试通过，范围外文件无变化。

## Commit 范围

```powershell
git add -- app/runner.py tests/test_runner.py
git diff --cached --name-only
git commit -m "feat: add resumable serial runner"
```

Expected: staged 列表只有 `app/runner.py` 与 `tests/test_runner.py`；一个 commit，不包含 runtime artifacts。
