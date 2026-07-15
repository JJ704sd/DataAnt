# Core 12：最终验证

## 操作提示词（可直接复制）

```text
你是 Core 12 的只读验证代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。
只读取本 spec（D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\core-12-final-verification.md）以及“Base / prerequisites”列出的必要代码和验证产物；不得读取总计划。
本任务只验证，不擅自修复、格式化、安装依赖、修改文件或创建 commit。任何失败都保留原状并回报 BLOCKED；不要扩大权限，也不要启动真实站点补跑。
依次执行本文 pytest、coverage、pip check、本地 browser smoke、workbook、git diff/status、secret scan 和 tracked artifacts check。所有命令必须从绝对 worktree cwd 执行。
完成时回报：DONE；每个门禁的命令、退出码和关键证据；worktree cleanliness；“未创建 commit”。
任一门禁失败时回报：BLOCKED；第一个失败门禁；原始输出摘要；全部已执行命令；后续未执行项；worktree 状态。不得修复后重跑来掩盖初始失败。
```

## Base / prerequisites

- 固定仓库：`D:\DataAnt\.worktrees\browser-bot-demo`。先验证 `git rev-parse --show-toplevel` 精确返回此路径。
- 使用已存在的 `D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe`；禁止创建环境或运行安装。
- 应已存在：完整 `app/`、`tests/`、`README.md`、`inputs/queries.example.csv`。
- workbook 验收需要先前已获批的固定 10 条受控 Demo 产物 `outputs/douban_movies.xlsx` 及其审批/运行记录。若证据不存在，报告 BLOCKED；本任务不得访问豆瓣补跑。
- 页面对象为 DrissionPage `tab`；只允许用本地 `data:` 页面做 browser smoke。profile 位于 `browser-profile/smoke`，属于不提交的 runtime artifact。
- 八个合法状态：`SUCCESS`、`NOT_FOUND`、`REVIEW_REQUIRED`、`NETWORK_ERROR`、`PAGE_CHANGED`、`BLOCKED`、`OUTPUT_LOCKED`、`UNEXPECTED_ERROR`。
- `NetworkError` 必须落为 `NETWORK_ERROR`；异常页面的诊断契约是截图 + 脱敏 HTML。两类产物都只能作为本地 runtime artifacts，tracked artifacts check 必须排除它们。

## Goal

以可复现、无修复副作用的门禁证明：自动测试与覆盖率满足要求；依赖一致；DrissionPage browser lifecycle 可本地启动；10 条 workbook 满足 12 列、唯一 task 和状态契约；代码差异干净；无凭据及被追踪 runtime artifacts。

## Files 边界

- Create/Modify/Delete: none。
- pytest、coverage、browser smoke 可产生被 `.gitignore` 覆盖的 cache、coverage、截图/日志或 `browser-profile` 数据；它们不得 staged/提交。
- 发现缺陷只报告，不修改任何生产、测试、文档或配置文件。

## 验证步骤

### 0. 确认 cwd、解释器与初始 Git 状态

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$Root = (git rev-parse --show-toplevel).Trim().Replace('/', '\')
if ($Root -ne 'D:\DataAnt\.worktrees\browser-bot-demo') { throw "Wrong worktree: $Root" }
if (-not (Test-Path -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe')) { throw 'Missing worktree Python' }
git status --short
git diff --check
```

Expected: root 精确匹配；解释器存在；`git status --short` 为空；`git diff --check` 无输出。若验证开始时不干净，立即 BLOCKED，不要清理。

### 1. pytest 与 coverage

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest --cov=app --cov-report=term-missing --cov-report=json:artifacts/coverage.json -v
if ($LASTEXITCODE -ne 0) { throw 'coverage run failed' }
@'
import json
from pathlib import Path
report = json.loads(Path('artifacts/coverage.json').read_text(encoding='utf-8'))
files = {name.replace('\\', '/'): data for name, data in report['files'].items()}
required = ('app/input_loader.py', 'app/matcher.py', 'app/sites/douban_movie.py')
for name in required:
    percent = files[name]['summary']['percent_covered']
    assert percent >= 80, (name, percent)
    print(f'{name}: {percent:.2f}%')
'@ | & 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -
if ($LASTEXITCODE -ne 0) { throw 'module coverage threshold failed' }
```

Expected: 两次 pytest 均 0 failures；输入、匹配和站点解析模块各至少 80% statement coverage。

### 2. 依赖完整性

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pip check
if ($LASTEXITCODE -ne 0) { throw 'pip check failed' }
```

Expected: 输出 `No broken requirements found.`，退出码 0。

### 3. 本地 browser lifecycle smoke

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
@'
from pathlib import Path
from app.browser_session import BrowserSession

session = BrowserSession(True, Path('artifacts'), Path('browser-profile/smoke'))
tab = session.__enter__()
try:
    tab.get('data:text/html,<title>browser-smoke</title><h1>ok</h1>')
    assert tab.url.startswith('data:')
    assert tab.ele('tag:h1').text == 'ok'
    print('BROWSER_SMOKE_OK')
finally:
    session.__exit__(None, None, None)
'@ | & 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -
if ($LASTEXITCODE -ne 0) { throw 'browser smoke failed' }
```

Expected: 有头 Chrome/Edge 打开本地页面并关闭，打印 `BROWSER_SMOKE_OK`，不产生真实站点请求。

### 4. 10 条 workbook 契约

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
@'
from pathlib import Path
from openpyxl import load_workbook

path = Path('outputs/douban_movies.xlsx')
assert path.is_file(), 'approved 10-query workbook is missing'
expected_columns = [
    'task_id', 'query', 'query_year', 'matched_title', 'matched_year', 'director',
    'rating', 'detail_url', 'match_method', 'status', 'error_message', 'collected_at',
]
valid_statuses = {
    'SUCCESS', 'NOT_FOUND', 'REVIEW_REQUIRED', 'NETWORK_ERROR',
    'PAGE_CHANGED', 'BLOCKED', 'OUTPUT_LOCKED', 'UNEXPECTED_ERROR',
}
wb = load_workbook(path, read_only=True, data_only=True)
rows = list(wb.active.values)
assert list(rows[0]) == expected_columns, rows[0]
data = rows[1:]
assert len(data) == 10, len(data)
ids = [str(row[0]) for row in data]
assert len(ids) == len(set(ids)) == 10, ids
assert all(row[9] in valid_statuses for row in data), [row[9] for row in data]
assert all(row[11] for row in data), 'collected_at must be populated'
print({'data_rows': len(data), 'unique_ids': len(set(ids))})
'@ | & 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -
if ($LASTEXITCODE -ne 0) { throw 'workbook contract failed' }
```

Expected: 输出 `data_rows: 10` 和 `unique_ids: 10`；表头严格 12 列；每行状态合法且有采集时间。

### 5. Git diff/status 与 secret scan

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'git diff --check failed' }
git diff --exit-code
if ($LASTEXITCODE -ne 0) { throw 'unstaged tracked changes exist' }
git diff --cached --exit-code
if ($LASTEXITCODE -ne 0) { throw 'staged changes exist' }
$Status = git status --short
if ($Status) { $Status; throw 'worktree is not clean' }

$SecretPattern = '(sk-[A-Za-z0-9_-]{20,}|MINIMAX_API_KEY\s*=\s*["'']?[A-Za-z0-9_-]{16,}|Cookie:\s*[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
$SecretMatches = git grep -n -I -E $SecretPattern -- .
$SecretExit = $LASTEXITCODE
if ($SecretExit -eq 0) { $SecretMatches; throw 'Possible tracked secret found' }
if ($SecretExit -gt 1) { throw "git grep failed with exit $SecretExit" }
'SECRET_SCAN_OK'
```

Expected: diff/status 全部干净；secret scan 无匹配并打印 `SECRET_SCAN_OK`。被忽略的 runtime 文件不会让 status 变脏，但仍需下一步检查追踪清单。

### 6. tracked artifacts check

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$TrackedRuntime = @(git ls-files -- outputs artifacts browser-profile)
$Unexpected = @($TrackedRuntime | Where-Object { $_ -notmatch '^(outputs|artifacts|browser-profile)/\.gitkeep$' })
if ($Unexpected.Count -gt 0) { $Unexpected; throw 'Tracked runtime artifacts found' }
$TrackedRuntime
'TRACKED_ARTIFACTS_OK'
```

Expected: 只列出 `outputs/.gitkeep`、`artifacts/.gitkeep`、`browser-profile/.gitkeep`（缺少某个空目录占位文件也允许）；打印 `TRACKED_ARTIFACTS_OK`。

## Acceptance checklist

- [ ] worktree cwd 与解释器均为指定绝对路径。
- [ ] pytest 全绿；三个纯逻辑/解析模块覆盖率各至少 80%。
- [ ] `pip check` 通过；本地 `data:` browser smoke 通过并正常关闭。
- [ ] 已批准的 10 条 workbook 严格 12 列、10 个唯一 task、合法状态与采集时间。
- [ ] `git diff --check`、unstaged/staged diff 和最终 status 均干净。
- [ ] secret scan 无匹配；追踪目录仅含允许的 `.gitkeep`。
- [ ] 任一失败均原样报告，未擅自修复或补跑真实站点。

## Commit 范围与 message

- Commit scope: none。
- Commit message: none。
- 本任务禁止 `git add` 和 `git commit`；验证成功也不创建空 commit。
