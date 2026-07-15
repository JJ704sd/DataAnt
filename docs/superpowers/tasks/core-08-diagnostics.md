# Core 08：诊断、脱敏与失败产物

## 操作提示词（可直接复制）

```text
你是实现 Core 08 的编码代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。
只读取本 spec（D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\core-08-diagnostics.md）以及“Base / prerequisites”列出的必要代码；不得读取总计划。
严格采用 TDD，仅可创建 app/diagnostics.py，并修改 app/runner.py、tests/test_runner.py。不得改动其他文件，不得访问真实站点；测试产物只能写入 pytest 的 tmp_path。
按本文命令验证。验证通过后只提交这三个文件，commit message 必须是：feat: add redacted failure diagnostics
完成时回报：DONE；变更文件；先失败后通过的测试命令及结果；commit hash。
无法完成时回报：BLOCKED；阻塞步骤；原始错误摘要；已执行命令；未提交文件列表。不要越界修复前置任务。
```

## Base / prerequisites

- 在 `D:\DataAnt\.worktrees\browser-bot-demo` 执行；使用现有 `.venv`，不要安装依赖。
- `app/runner.py` 已提供串行 `Runner`、`DEFAULT_RETRY`、终态跳过、upsert、`BlockedError`/`PageChangedError` 分类和 `RunSummary`。
- 必要异常契约：`NetworkError` 只代表超时、DNS、连接中断等暂时故障；`OutputLockedError` 必须继续向 CLI 抛出；`BlockedError` 必须写状态后终止整批；`PageChangedError` 写状态后继续。
- 必要状态仍为：`SUCCESS`、`NOT_FOUND`、`REVIEW_REQUIRED`、`NETWORK_ERROR`、`PAGE_CHANGED`、`BLOCKED`、`OUTPUT_LOCKED`、`UNEXPECTED_ERROR`。
- 浏览器对象是 DrissionPage `tab`，截图接口为 `tab.get_screenshot(path=..., name=..., full_page=True)`，页面 HTML 为 `tab.html`。

## Goal

增加标准日志、统一文本脱敏、失败截图与脱敏 HTML，并增强 Runner 的网络退避及异常分类。失败诊断不得泄露 API Key、Cookie、请求头或浏览器配置数据。

## Files 边界

- Create: `app/diagnostics.py`
- Modify: `app/runner.py`
- Modify: `tests/test_runner.py`
- 禁止修改其他文件；`artifacts/` 下的实际运行产物不得提交。

## 精确接口与行为契约

```python
def redact(value: str) -> str: ...
def configure_logging(artifacts_dir: Path) -> logging.Logger: ...
def capture_failure(tab, artifacts_dir: Path, task_id: str) -> None: ...

class Runner:
    def __init__(
        self,
        adapter,
        store,
        tab,
        min_interval_seconds: float = 5,
        retry_statuses=None,
        logger: logging.Logger | None = None,
        artifacts_dir: Path | None = None,
    ) -> None: ...
```

- `redact()` 至少替换不区分大小写的 `MINIMAX_API_KEY=<value>` 与 `Cookie: <value>`；输出中不得保留原值。保持非敏感文本可读。
- `configure_logging()` 创建目录，返回名为 `browser_bot` 的 INFO logger；清理旧 handler，配置控制台与 UTF-8 文件 handler。文件名必须为 `run-<timestamp>.log`，避免覆盖历史运行。
- `capture_failure()` 只生成 `<task_id>.png` 和 `<task_id>.html`。HTML 先脱敏再截断至 200,000 字符；禁止保存原始 HTML。
- Runner 的 `tab` 字段和适配器调用均使用同一个 `tab`。
- `_network_operation(operation)` 共尝试 3 次，只捕获 `NetworkError`；首次立即执行，失败后分别等待 2 秒、5 秒再试。第三次仍失败则抛出最后一个 `NetworkError`。
- `_persist(result)` 先 `store.upsert`，再记录 `task_id` 与状态。仅 `NETWORK_ERROR`、`PAGE_CHANGED`、`BLOCKED`、`UNEXPECTED_ERROR` 触发截图 + 脱敏 HTML；成功和普通业务终态不生成诊断产物。
- 若 `artifacts_dir is None`，或 `tab` 没有截图能力，不生成页面产物；不得因此覆盖原业务异常。
- `NetworkError` 最终写 `NETWORK_ERROR`，错误消息最多 200 字符；未知异常写 `UNEXPECTED_ERROR`，错误消息只保存异常类型名。
- `OutputLockedError` 原样重抛，不能写成其他状态；这保证 CLI 可返回退出码 4。

## TDD 步骤

### 1. 先写失败测试

在 `tests/test_runner.py` 增加测试，至少覆盖：

1. API Key 和 Cookie 值都被脱敏；
2. fake tab 在异常状态下得到一次截图调用，落盘 HTML 不含秘密且不超过 200,000 字符；
3. `SUCCESS` 不截图、不写 HTML；
4. 网络操作调用三次，等待序列严格为 `[2, 5]`，最终结果为 `NETWORK_ERROR`；
5. 网络第二次成功时不再重试；
6. `OutputLockedError` 被原样抛出；
7. 未分类异常写 `UNEXPECTED_ERROR`，不把异常 message 写入工作簿。

运行一个最小红灯：

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest tests/test_runner.py -v
```

Expected: FAIL，因为诊断模块或增强行为尚未实现；不得因真实等待而拖慢测试，需 monkeypatch `time.sleep`。

### 2. 最小实现

创建 `app/diagnostics.py`，增强 `app/runner.py`。日志和 HTML 中的任何异常文本在写入前必须经过 `redact()`；截图是图像文件，不能宣称内容已自动脱敏，因此只在规定失败状态生成，并禁止提交。

### 3. 专项、全量与泄露断言

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest tests/test_runner.py -v
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q
```

Expected: 全部 PASS；测试明确读取落盘 HTML 并证明秘密不存在；无真实 `artifacts/` 产物被追踪。

## Acceptance checklist

- [ ] 网络退避仅处理 `NetworkError`，次数和 2/5 秒退避正确。
- [ ] 输出锁原样抛出，阻断仍立即停止。
- [ ] 失败状态生成截图 + 脱敏 HTML；成功状态不生成。
- [ ] HTML 脱敏与 200,000 字符上限有落盘测试。
- [ ] logger 不重复 handler，日志文件不覆盖旧运行。
- [ ] 专项与全量测试通过，范围外文件无变化。
- [ ] `artifacts/`、`browser-profile/`、输出文件没有进入提交。

## Commit 范围

```powershell
git add -- app/diagnostics.py app/runner.py tests/test_runner.py
git diff --cached --name-only
git commit -m "feat: add redacted failure diagnostics"
```

Expected: staged 列表严格为这三个文件；不提交截图、HTML、日志或浏览器配置。
