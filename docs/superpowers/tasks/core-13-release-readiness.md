# Core 13：Release Readiness 文档与最终交接

## 操作提示词（可直接复制）

```text
你是 Core 13 的文档与最终验证代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。
只读取本 spec（D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers/tasks/core-13-release-readiness.md）、README.md、scripts/、tests/、.github/workflows/ 与“Base / prerequisites”列出的工件；不得读取总计划。
本任务只创建 docs/superpowers/tasks/core-13-release-readiness.md 并修改 README.md。不得改其他代码、配置、测试、CI 工作流或示例 CSV。
按本文第 1–12 步逐条运行离线 release 门禁。所有命令必须从绝对 worktree cwd 执行；workbook 校验时先确认 outputs/<run>.xlsx 存在并通过 verify_controlled_workbook 校验（1–10 行唯一 task），缺失或不合规则报告 NOT_READY。
证据合规硬门禁：workbook 存在；workbook 12 列严格匹配；1 ≤ 数据行数 ≤ 10；task_id 唯一；状态合法；collected_at 全填；本任务自身不得访问豆瓣、不得伪造、下载或提交 workbook；不得实施或调用 MiniMax。
完成后报告：Status: READY_TO_PUSH | NOT_READY | BLOCKED；每个门禁的退出码和关键证据；workbook 校验摘要；已批准文件列表；commit hash；git status。
任一门禁失败或证据缺失时报告 NOT_READY；保留原状、保留 commit 留本地、绝不为得到绿色结果而访问真实豆瓣。
```

## Base / prerequisites

- 固定仓库：`D:\DataAnt\.worktrees\browser-bot-demo`。先验证 `git rev-parse --show-toplevel` 精确返回此路径。
- 使用已存在的 `D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe`；禁止创建环境或运行安装。
- Task 1–4 应当已合入 `feat/browser-bot-demo`，提交历史包含 `ci: add offline core release gate`。
- Release readiness 强依赖一项外部工件，**不**由本任务生成：
  - `outputs/<run>.xlsx` —— 受控 Demo 跑出的 12 列 workbook（1 ≤ N ≤ 10 行）。该 run 必须以 `--live-approved --max-queries N --headed --min-interval 5` 启动，作为可追溯的 CLI 授权记录；本任务不读独立的 evidence JSON。
- 若上述工件缺失或 `scripts.verify_core.verify_controlled_workbook(Path("outputs/<run>.xlsx"))` 失败，本任务**必须**报告 `NOT_READY`，**绝不能**为了得到绿色结果访问真实豆瓣、伪造或下载 workbook。
- 状态契约见 Core 12；八个合法状态：`SUCCESS`、`NOT_FOUND`、`REVIEW_REQUIRED`、`NETWORK_ERROR`、`PAGE_CHANGED`、`BLOCKED`、`OUTPUT_LOCKED`、`UNEXPECTED_ERROR`。
- 浏览器 lifecycle 用本地 `data:` 页面验证；profile 位于 `browser-profile/smoke`，是 runtime artifact，不提交。
- 离线 release gate 由 `scripts.verify_core` 负责，CI 与本地共用同一阈值；本任务必须显式跑它，不要绕过。

## Goal

把 release readiness 的全部可重复 PowerShell 门禁沉淀到本 spec，让任何持有该文件的人都能在工作目录内一行行复现 12 步验证；同时确认 workbook 校验这道合规硬门禁通过，把 `feat/browser-bot-demo` 推进到可以 push 的状态。"操作员知情同意"这件事已经从外部审批表挪到了 CLI 上的 `--live-approved` 开关 + 1–10 行 `--max-queries` 上限，本 spec 不再读取任何独立的 approval evidence。

## Files 边界

- Create: `docs/superpowers/tasks/core-13-release-readiness.md`（本文件）。
- Modify: `README.md`（追加 release readiness 索引 + 本 spec 的存在性，不改其它章节，不改示例 CSV）。
- 禁止修改：`app/`、`tests/`、`scripts/`、`inputs/`、`outputs/`、`artifacts/`、`browser-profile/`、`.github/`、`pyproject.toml`、`.gitignore`、`.env.example`、`SPEC.md`、`docs/superpowers/tasks/` 下除本文件外的任何文件。
- 离线命令可产生 cache、coverage、截图、HTML、`browser-profile` 数据；它们**不**进 commit。

## 12 步 Release Readiness 门禁（PowerShell，逐条可复制）

> 复制前先打开 PowerShell，所有命令都在工作目录根执行。第 1–4 步是结构与离线契约，第 5 步是 portable coverage gate，第 6–7 步是依赖与浏览器 lifecycle，第 8 步是 workbook + approval evidence 硬门禁，第 9–10 步是 secret 与 tracked artifact 审计，第 11–12 步是 diff/status 收尾并判定 READY_TO_PUSH。

### 1. 精确 worktree 路径

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$Root = (git rev-parse --show-toplevel).Trim().Replace('/', '\')
if ($Root -ne 'D:\DataAnt\.worktrees\browser-bot-demo') { throw "Wrong worktree: $Root" }
if (-not (Test-Path -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe')) { throw 'Missing worktree Python' }
"WORKTREE_OK=$Root"
```

Expected: 打印 `WORKTREE_OK=D:\DataAnt\.worktrees\browser-bot-demo` 后正常结束。

### 2. 初始 git status 干净

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$Initial = git status --short
if ($Initial) { $Initial; throw 'worktree is dirty at start' }
$Commits = git log --oneline -3
$Commits
"INITIAL_GIT_CLEAN_OK"
```

Expected: `$Initial` 为空；`git log --oneline -3` 顶部包含 `ci: add offline core release gate`；打印 `INITIAL_GIT_CLEAN_OK`。若 Task 4 提交尚未合入，立即报告 `BLOCKED`，不要清理 dirty 文件。

### 3. pytest

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
"PYTEST_OK"
```

Expected: 退出码 0，所有用例通过；不连接真实豆瓣，不读 `MINIMAX_API_KEY`。

### 4. coverage（写入 `artifacts/coverage.json`）

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest `
    --cov=app `
    --cov-report=term-missing `
    --cov-report=json:artifacts/coverage.json -v
if ($LASTEXITCODE -ne 0) { throw 'coverage run failed' }
if (-not (Test-Path -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo\artifacts\coverage.json')) { throw 'coverage.json missing' }
"COVERAGE_RUN_OK"
```

Expected: 退出码 0；`artifacts/coverage.json` 存在；`--cov-report=term-missing` 终端输出三个纯逻辑/解析模块各 ≥ 80%。

### 5. `scripts.verify_core`（portable core release gate）

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m scripts.verify_core `
    --coverage-json artifacts/coverage.json
if ($LASTEXITCODE -ne 0) { throw 'verify_core failed' }
"VERIFY_CORE_OK"
```

Expected: 退出码 0；按行打印 `app/input_loader.py`、`app/matcher.py`、`app/sites/douban_movie.py` 各自 ≥ 80% 实际覆盖率，并打印 `VERIFY_CORE_OK`。

### 6. pip check

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pip check
if ($LASTEXITCODE -ne 0) { throw 'pip check failed' }
"PIP_CHECK_OK"
```

Expected: 输出 `No broken requirements found.`，退出码 0。

### 7. `scripts.browser_smoke`（本地 `data:` 页面）

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m scripts.browser_smoke
if ($LASTEXITCODE -ne 0) { throw 'browser smoke failed' }
"BROWSER_SMOKE_OK"
```

Expected: 退出码 0，stdout 含 `BROWSER_SMOKE_OK`；不发起任何 live host 请求，`browser-profile/smoke` 是 runtime artifact。

### 8. 受控 workbook 校验（合规硬门禁）

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$Workbook = 'D:\DataAnt\.worktrees\browser-bot-demo\outputs\douban_movies.xlsx'

if (-not (Test-Path -LiteralPath $Workbook)) {
    Write-Error 'NOT_READY: outputs/douban_movies.xlsx is missing'
    exit 11
}

@'
import sys
from pathlib import Path

from scripts.verify_core import verify_controlled_workbook

workbook = Path(r'D:\DataAnt\.worktrees\browser-bot-demo\outputs\douban_movies.xlsx')

try:
    summary = verify_controlled_workbook(workbook)
except AssertionError as exc:
    print(f'WORKBOOK_REJECTED: {exc}')
    sys.exit(2)

print('summary:', summary)
'@ | & 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -
if ($LASTEXITCODE -ne 0) { throw 'workbook contract failed' }
"WORKBOOK_OK"
```

Expected:

- 退出码 0；打印 `summary: {'data_rows': N, 'unique_ids': N}`，其中 `1 <= N <= 10`。
- workbook 缺失时退出码非 0（`11`），整轮报告 `NOT_READY`，不要继续提交。
- workbook 违反契约（列不匹配、task_id 不唯一、状态非法、`collected_at` 缺失、行数不在 1–10）都直接 `WORKBOOK_REJECTED`，报告 `NOT_READY`。
- **本任务自身不得访问豆瓣补跑、不得伪造、不得下载 workbook**；对应的运行命令行（`--live-approved --max-queries N --headed --min-interval 5`）应当能在 run 日志里复现，作为可追溯的 CLI 授权记录。

### 9. secret scan

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$SecretPattern = '(sk-[A-Za-z0-9_-]{20,}|MINIMAX_API_KEY\s*=\s*["'']?[A-Za-z0-9_-]{16,}|Cookie:\s*[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
$SecretMatches = git grep -n -I -E $SecretPattern -- .
$SecretExit = $LASTEXITCODE
if ($SecretExit -eq 0) { $SecretMatches; throw 'Possible tracked secret found' }
if ($SecretExit -gt 1) { throw "git grep failed with exit $SecretExit" }
"SECRET_SCAN_OK"
```

Expected: `git grep` 退出码 1（无匹配），打印 `SECRET_SCAN_OK`。命中即整轮 `BLOCKED`。

### 10. tracked runtime artifact scan

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$TrackedRuntime = @(git ls-files -- outputs artifacts browser-profile)
$Unexpected = @($TrackedRuntime | Where-Object { $_ -notmatch '^(outputs|artifacts|browser-profile)/\.gitkeep$' })
if ($Unexpected.Count -gt 0) { $Unexpected; throw 'Tracked runtime artifacts found' }
$TrackedRuntime
"TRACKED_ARTIFACTS_OK"
```

Expected: 仅列出 `outputs/.gitkeep`、`artifacts/.gitkeep`、`browser-profile/.gitkeep`（缺失某个占位文件也允许）；打印 `TRACKED_ARTIFACTS_OK`。

### 11. git diff/status

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'git diff --check failed' }
git status --short
"DIFF_STATUS_OK"
```

Expected: `git diff --check` 无 whitespace 警告；`git status --short` 仅有本任务计划提交的两份文件（`docs/superpowers/tasks/core-13-release-readiness.md` 与 `README.md`），且未 staged。

### 12. 全部通过才能输出 `READY_TO_PUSH`

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$AllSteps = @(
    'WORKTREE_OK',
    'INITIAL_GIT_CLEAN_OK',
    'PYTEST_OK',
    'COVERAGE_RUN_OK',
    'VERIFY_CORE_OK',
    'PIP_CHECK_OK',
    'BROWSER_SMOKE_OK',
    'WORKBOOK_OK',
    'SECRET_SCAN_OK',
    'TRACKED_ARTIFACTS_OK',
    'DIFF_STATUS_OK'
)
$AllSteps -join ', '
"READY_TO_PUSH"
```

Expected: 把 11 个步骤标记（`WORKBOOK_OK` 是合规硬门禁）逐一回放后打印 `READY_TO_PUSH`。任一缺失或失败，**整轮报告 `NOT_READY` 或 `BLOCKED`**，禁止手动拼接绿色结果。

## 文档自审（提交前必跑）

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$needles = @(('T'+'BD'), ('T'+'ODO'), ('implement'+' later'), ('fill'+' in'))
$PlaceholderHits = Select-String `
    -Path 'docs/superpowers/tasks/core-13-release-readiness.md' `
    -Pattern $needles `
    -CaseSensitive:$false
if ($PlaceholderHits) { $PlaceholderHits; throw 'placeholder content found in spec' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'git diff --check failed' }
"SPEC_SELF_AUDIT_OK"
```

Expected: `Select-String` 无匹配，`git diff --check` 无输出，打印 `SPEC_SELF_AUDIT_OK`。本命令的输出规则：未匹配时 `Select-String` 不写 stdout、不写 stderr、退出码 0；命中即抛出并把命中行回显。

## 提交范围

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
git add -- `
    docs/superpowers/tasks/core-13-release-readiness.md `
    README.md
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'git diff --cached --check failed' }
git diff --cached --name-only
git commit -m "docs: add core release handoff"
```

Expected: staged 列表仅含 `docs/superpowers/tasks/core-13-release-readiness.md` 与 `README.md`；`git commit` 退出码 0；commit message 严格 `docs: add core release handoff`。

## Acceptance checklist

- [ ] worktree cwd 与解释器均为指定绝对路径；Task 4 提交 `ci: add offline core release gate` 已在历史中。
- [ ] 12 步门禁全部绿；`outputs/douban_movies.xlsx` 存在并通过 `verify_controlled_workbook`。
- [ ] workbook 严格 12 列、1 ≤ 数据行 ≤ 10、task_id 唯一、八个合法状态、`collected_at` 全填；不再要求任何外部审批字段或独立 evidence 文件。
- [ ] pytest 全绿；`scripts.verify_core` 三个纯逻辑/解析模块覆盖率各 ≥ 80%。
- [ ] `pip check` 通过；本地 `data:` browser smoke 通过并正常关闭。
- [ ] secret scan 无匹配；`outputs/`、`artifacts/`、`browser-profile/` 仅含允许的 `.gitkeep`。
- [ ] `git diff --check`、staged diff 与最终 `git status` 干净，staged 范围只含 spec + README。
- [ ] commit message 严格 `docs: add core release handoff`；没有越界修改 `app/`、`tests/`、`scripts/`、`inputs/`、`.github/`、CI 工作流、示例 CSV。
- [ ] 没有访问真实豆瓣、没有伪造 / 下载 / 提交 workbook、没有调用 MiniMax。
- [ ] 缺任一证据或任一门禁失败时报告 `NOT_READY` 或 `BLOCKED`，绝不为得到绿色结果而补跑。

## Commit 范围与 message

- Commit scope: `docs/superpowers/tasks/core-13-release-readiness.md`、`README.md`。
- Commit message: `docs: add core release handoff`（单行 message；不要追加 body；不要带敏感 token、Cookie、Key、审批号）。
- 本任务禁止其他任何 commit；禁止 amend 之前提交；禁止 force push。
