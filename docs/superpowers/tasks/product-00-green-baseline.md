# 任务 0：恢复设计提交后的绿色离线基线

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-00-green-baseline.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：c109a13 docs: plan product collection gallery。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格执行本文件中的 RED → verify RED → GREEN → focused verify → full verify → commit 顺序。文件编辑使用 apply_patch。只允许修改文件小节列出的文件；不得安装或升级依赖，不得 amend、reset、force push，不得修改或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

本任务严格离线：不得启动浏览器，不得访问 web-scraping.dev、豆瓣或其他外网，不得传入 --live-approved。

提交前运行 git diff --check，并确认 git diff --name-only 只含本任务允许文件。除非本任务明确说明不需要提交，commit message 必须精确为：test: accept ignored brainstorm workspace

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-00-green-baseline
- preflight: <前置提交与初始状态>
- red: <精确命令、退出码、预期失败>
- green: <focused 命令与结果>
- full_verify: <全量命令与结果>
- changed: <逐行文件列表>
- commit: <短 SHA + message；无提交时写 none>
- live: NOT_RUN | SKIPPED_NOT_APPROVED | APPROVED_AND_RUN | STOPPED_ON_PROTECTION
- concerns: <无则写 none>

任何门禁失败都保留现场并报告，不得猜测、伪造绿色结果或扩大范围。
```

## Base / 前置条件

- 仓库根目录：`D:\DataAnt`。
- 批准设计：`docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md`。
- 前置提交：`c109a13 docs: plan product collection gallery`。
- 本任务提交：`test: accept ignored brainstorm workspace`。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


**文件：**

- 修改：`tests/test_project_config.py:21`
- 测试：`tests/test_project_config.py`

- [x] **步骤 1：更新精确 `.gitignore` 契约**

在期望列表的 `htmlcov/` 与 `.env` 之间加入：

```python
".superpowers/",
```

并增加以下断言，确认视觉草图不会被跟踪：

```python
assert ".superpowers/" in gitignore
assert not any(
    path.parts[:2] == (".superpowers", "brainstorm")
    for path in PROJECT_ROOT.rglob("*")
    if path.is_file() and path.name == ".gitkeep"
)
```

- [x] **步骤 2：运行配置测试**

运行：

```powershell
python -m pytest tests/test_project_config.py -q
```

预期：全部通过；不再出现 `.superpowers/` 列表差异。

- [x] **步骤 3：运行完整基线**

运行：

```powershell
python -m pytest -q
```

预期：164 项测试全部通过。

- [x] **步骤 4：提交基线修复**

```powershell
git add tests/test_project_config.py
git commit -m "test: accept ignored brainstorm workspace"
```
