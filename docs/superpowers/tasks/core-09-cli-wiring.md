# Core 09：CLI 端到端装配与退出码

## 操作提示词（可直接复制）

```text
你是实现 Core 09 的编码代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。
只读取本 spec（D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\core-09-cli-wiring.md）以及“Base / prerequisites”列出的必要代码；不得读取总计划。
严格采用 TDD，仅可修改 app/main.py 与 tests/test_main.py。不得改动其他文件，不得访问真实站点；所有 CLI 单元测试必须替换浏览器和 Runner 依赖。
按本文命令验证。验证通过后只提交上述两个文件，commit message 必须是：feat: wire browser bot CLI
完成时回报：DONE；变更文件；先失败后通过的测试命令及结果；帮助输出检查；commit hash。
无法完成时回报：BLOCKED；阻塞步骤；原始错误摘要；已执行命令；未提交文件列表。不要越界修复前置任务。
```

## Base / prerequisites

- 在 `D:\DataAnt\.worktrees\browser-bot-demo` 使用现有 `.venv`，不要安装依赖。
- 必要接口：`load_tasks(Path) -> list[Task]` 并可能抛 `InputError`；`ExcelStore(Path)` 并可能抛 `OutputLockedError`；`configure_logging(Path)`；`BrowserSession(headed, artifacts_dir, profile_dir, browser_path)` 是返回 DrissionPage `tab` 的上下文管理器；`Runner(...).run(tasks) -> RunSummary`；`DoubanMovieAdapter()`。
- `RunSummary.blocked=True` 表示站点保护已触发。
- `Status(value)` 负责验证 `--retry-status`；合法值严格为八个状态：`SUCCESS`、`NOT_FOUND`、`REVIEW_REQUIRED`、`NETWORK_ERROR`、`PAGE_CHANGED`、`BLOCKED`、`OUTPUT_LOCKED`、`UNEXPECTED_ERROR`。
- `NetworkError` 由 Runner 分类为 `NETWORK_ERROR`，CLI 不重复捕获单条网络异常；失败诊断由 Runner 写入截图 + 脱敏 HTML，CLI 只提供 `artifacts` 路径，且不得提交这些产物。

## Goal

把 CSV 加载、Excel store、独立 `browser-profile`、BrowserSession、豆瓣 adapter、Runner 和诊断日志装配进 `run` 子命令，并稳定映射进程退出码。

## Files 边界

- Modify: `app/main.py`
- Modify: `tests/test_main.py`
- 禁止修改其他文件。

## CLI 与异常契约

`build_parser()` 的 `run` 参数必须为：

| 参数 | 契约 |
|---|---|
| `--input` | 必填字符串 |
| `--output` | 必填字符串 |
| `--headed/--no-headed` | `BooleanOptionalAction`，默认有头 |
| `--retry-status` | 可重复，默认空列表 |
| `--min-interval` | `float`，默认 `5.0` |
| `--browser-path` | 可选本机 Chrome/Edge 路径 |
| `--profile-dir` | 默认 `browser-profile/douban` |

```python
def build_parser() -> argparse.ArgumentParser: ...
def execute(argv: list[str] | None = None) -> int: ...
def main() -> int: ...
```

`execute()` 顺序固定：解析参数；配置 `artifacts` 日志；加载输入；把每个重跑字符串转换为 `Status`；构造 store；把可选浏览器路径转成 `Path | None`；进入 `BrowserSession` 得到 `tab`；调用 `Runner(DoubanMovieAdapter(), store, tab, min_interval, retry, logger, artifacts).run(tasks)`；退出上下文。

退出码：

- `0`：所有任务已处理，即使存在 `NOT_FOUND` 或 `REVIEW_REQUIRED`；
- `2`：`InputError`、非法 `Status` 或其他输入/配置 `ValueError`；
- `3`：`RunSummary.blocked` 为真；
- `4`：`OutputLockedError`；
- `5`：浏览器启动或全局未预期异常。

所有错误通过 logger 输出；全局未知错误使用 exception 级日志。`main()` 只返回 `execute()`，模块入口使用 `raise SystemExit(main())`。

## TDD 步骤

### 1. 写失败测试

在 `tests/test_main.py` 保留现有 parser 测试，并新增 monkeypatch 驱动的测试：

1. 缧失输入文件返回 2，且 BrowserSession 未构造；
2. 非法 `--retry-status` 返回 2；
3. fake BrowserSession 返回的同一 `tab` 被传给 Runner，profile 默认路径正确；
4. summary 未阻断返回 0，阻断返回 3；
5. fake store/Runner 抛 `OutputLockedError` 返回 4；
6. BrowserSession 入口抛未知异常返回 5；
7. parser 的七个参数、默认值和可重复状态正确。

测试不得启动浏览器、读写真实 Excel 或访问网络。运行：

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest tests/test_main.py -v
```

Expected: 新测试先 FAIL，因为 `execute` 或完整装配尚不存在。

### 2. 实现最小装配

仅替换 `app/main.py`。为便于测试，测试可 monkeypatch `app.main` 中已导入的类/函数；不要为此新增生产模块或全局浏览器实例。

### 3. 运行专项、帮助与全量测试

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest tests/test_main.py -v
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m app.main --help
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m app.main run --help
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q
```

Expected: 测试 PASS；两个帮助命令退出 0；`run --help` 列出七个参数；全量测试退出 0。不要执行真实 `run`。

## Acceptance checklist

- [ ] CLI 参数、默认值和 profile 路径精确。
- [ ] `Status` 转换发生在启动浏览器之前。
- [ ] BrowserSession 只创建一次，向 Runner 传入 DrissionPage `tab`。
- [ ] 0/2/3/4/5 退出码各有隔离测试。
- [ ] 所有单元测试无浏览器、网络和真实工作簿副作用。
- [ ] 专项、帮助与全量检查通过，范围外文件无变化。

## Commit 范围

```powershell
git add -- app/main.py tests/test_main.py
git diff --cached --name-only
git commit -m "feat: wire browser bot CLI"
```

Expected: staged 列表只有 `app/main.py` 与 `tests/test_main.py`。
