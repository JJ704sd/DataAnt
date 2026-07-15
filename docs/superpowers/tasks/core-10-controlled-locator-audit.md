# Core 10：受控定位器审计

## 操作提示词（可直接复制）

```text
你是执行 Core 10 的审计代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。
只读取本 spec（D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\core-10-controlled-locator-audit.md）以及“Base / prerequisites”列出的必要代码；不得读取总计划。
先检查 artifacts/locator-audit.md 中 Compliance approval reference 是否为真实非空值。这是硬门禁：缺失、空白或示例值时，禁止访问豆瓣及任何其他真实站点，只允许已授权的本地 fixture 或 data: 页面；不得用推测结果修改真实站点定位器。
文件边界仅为 app/sites/douban_movie.py、tests/fixtures/search_results.html、tests/fixtures/detail_movie.html、tests/test_douban_parser.py；审计记录、输入、截图、脱敏 HTML、输出和 browser-profile 都是本地 runtime artifacts，绝不提交。
若有有效审批，最多执行一个获批查询；遇到验证码、限流或 403/418/429 立即停止，不重试、不绕过。按本文验证后，仅在确有已验证变更时提交允许的代码/fixture，message：test: verify current Douban locator contracts
完成时回报：DONE；门禁结果（不得泄露审批内容）；审计模式 local-only 或 approved-live；验证证据；变更文件；commit hash 或“无代码变更”。
无法完成时回报：BLOCKED；门禁/阻塞步骤；原始错误摘要；已执行命令；未提交 runtime artifacts 列表。
```

## Base / prerequisites

- 仓库根目录：`D:\DataAnt\.worktrees\browser-bot-demo`；使用现有 `.venv`，不要安装依赖。
- `app/sites/douban_movie.py` 已定义 `DoubanMovieAdapter.search(tab, task)`、`fetch_detail(tab, task, candidate)`、`BlockedError`、`PageChangedError`、`NetworkError`。
- 浏览器层是 DrissionPage，页面对象术语统一为 `tab`。只使用 `tab.ele()`、`tab.eles()`、`tab.tree()`、`tab.get_screenshot()` 与 `tab.html`。
- 详情核心字段为标题和规范 `/subject/<数字>/` URL；年份、导演、评分是允许为空的非核心字段。
- 运行产物目录 `artifacts/`、`outputs/`、`browser-profile/` 必须保持不追踪，仅各自 `.gitkeep` 可被追踪。

## Goal

在合规硬门禁下验证当前搜索输入、候选容器、详情字段定位器；只把实际观察到的最小稳定 DOM 契约写回 adapter 和脱敏 fixture。没有真实访问批准时，完成 local-only 检查并明确不能声称完成真实站点验证。

## Files 边界

- Modify if verified: `app/sites/douban_movie.py`
- Modify if verified and sanitized: `tests/fixtures/search_results.html`
- Modify if verified and sanitized: `tests/fixtures/detail_movie.html`
- Modify if assertions need alignment: `tests/test_douban_parser.py`
- Runtime only, never commit: `artifacts/locator-audit.md`、`artifacts/locator-audit-input.csv`、审计截图、脱敏 HTML、`outputs/locator-audit.xlsx`、`browser-profile/**`。
- 禁止修改其他文件。

## 合规硬门禁

在本地创建 `artifacts/locator-audit.md`，所有字段填写真实值：

```markdown
# Locator audit
- Date/time: <ISO-8601 with timezone>
- Operator: <named operator>
- Compliance approval reference: <non-empty approval record identifier>
- Allowed target: movie.douban.com
- Allowed queries: 1
- Minimum interval: 5 seconds
- Browser: installed Chrome/Edge via DrissionPage
```

门禁检查命令：

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$Audit = Get-Content -Raw -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo\artifacts\locator-audit.md'
$Approval = [regex]::Match($Audit, '(?mi)^- Compliance approval reference:\s*(.+?)\s*$').Groups[1].Value.Trim()
if ([string]::IsNullOrWhiteSpace($Approval) -or $Approval -match '^<.*>$|^(none|n/a|pending|example)$') { throw 'LIVE_AUDIT_FORBIDDEN: compliance approval reference is missing' }
'LIVE_AUDIT_APPROVED'
```

Expected with valid approval: prints `LIVE_AUDIT_APPROVED`. Any other result means live access is forbidden. Approval existence does not authorize more than one listed query.

## 可复现审计步骤

### 1. 无批准：local-only 路径

只用已授权 fixture 或 `data:` 页面启动本地浏览器检查，不得请求 `movie.douban.com`：

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -c "from pathlib import Path; from urllib.parse import quote; from app.browser_session import BrowserSession; html=Path('tests/fixtures/search_results.html').read_text(encoding='utf-8'); s=BrowserSession(True, Path('artifacts'), Path('browser-profile/locator-audit-local')); tab=s.__enter__(); tab.get('data:text/html;charset=utf-8,'+quote(html)); print(tab.url.startswith('data:')); s.__exit__(None,None,None)"
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest tests/test_douban_parser.py -v
```

Expected: 打印 `True`；parser 测试 PASS；网络日志中没有真实站点请求。此路径只能验证本地解析契约，不能把定位器标记为“当前真实站点已验证”。

### 2. 有批准：恰好一个 headed 查询

创建未追踪的 `artifacts/locator-audit-input.csv`，内容只能有表头和一条获批行。先再次运行硬门禁命令，再运行：

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m app.main run --input 'D:\DataAnt\.worktrees\browser-bot-demo\artifacts\locator-audit-input.csv' --output 'D:\DataAnt\.worktrees\browser-bot-demo\outputs\locator-audit.xlsx' --headed --min-interval 5 --profile-dir 'D:\DataAnt\.worktrees\browser-bot-demo\browser-profile\locator-audit'
```

Expected: Chrome/Edge 通过 DrissionPage 有头打开，只执行一条批准查询后关闭。退出码 3、验证码、限流、403/418/429 任一出现都必须立即停止，不得重试或绕过。

### 3. 只更新观察到的契约

- 搜索输入候选优先顺序只能在实际观察支持时使用：`@role=searchbox`，再 `css:input[name='search_text']`。
- 候选使用最小稳定容器和规范 `/subject/<id>/` 链接；最多解析前 5 个电影候选。
- 详情优先语义属性：标题 `h1 span[property="v:itemreviewed"]`、年份 `h1 .year`、导演 `#info a[rel="v:directedBy"]`、评分 `strong[property="v:average"]`。
- 禁止长布局链、位置序号选择器和与视觉层级绑定的 XPath。
- fixture 只保留 parser 必需节点；移除账户名、Cookie、请求头、推荐、评论及其他个人信息。诊断产物只允许截图 + 脱敏 HTML。

### 4. 离线验证与提交前产物检查

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest tests/test_douban_parser.py -v
git diff --check
$Runtime = git status --short --untracked-files=all | Select-String -Pattern '(artifacts/|outputs/|browser-profile/)'
$Runtime
git diff -- app/sites/douban_movie.py tests/fixtures/search_results.html tests/fixtures/detail_movie.html tests/test_douban_parser.py
```

Expected: parser 测试 PASS；`git diff --check` 无输出；runtime 文件可在 status 中被忽略或显示为未追踪，但不得 staged；代码差异仅含已验证定位器和最小脱敏 fixture。

## Acceptance checklist

- [ ] 非空真实审批引用是访问真实站点的硬门禁。
- [ ] 无审批时只运行本地 fixture/`data:` 页面，并报告 local-only。
- [ ] 有审批时仅一个有头查询，最小间隔 5 秒，阻断立即停止。
- [ ] 定位器来自 DrissionPage `tab` 的实际元素树观察，无布局脆弱选择器。
- [ ] fixture 已最小化和脱敏，parser 测试通过。
- [ ] 截图、脱敏 HTML、日志、输入、输出、browser-profile 均未 staged/提交。
- [ ] 若没有可验证的定位器变更，不创建空 commit。

## Commit 范围

只有实际验证并产生代码/fixture 变更时执行：

```powershell
git add -- app/sites/douban_movie.py tests/fixtures/search_results.html tests/fixtures/detail_movie.html tests/test_douban_parser.py
git diff --cached --name-only
git commit -m "test: verify current Douban locator contracts"
```

Expected: staged 文件只来自上述四个路径；任何 `artifacts/`、`outputs/`、`browser-profile/` 文件出现时必须取消提交并回报 BLOCKED。
