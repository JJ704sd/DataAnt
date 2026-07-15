# Core 11：README 与受控 Demo Runbook

## 操作提示词（可直接复制）

```text
你是实现 Core 11 的文档代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。
只读取本 spec（D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\core-11-readme-runbook.md）以及“Base / prerequisites”列出的必要代码；不得读取总计划。
仅可修改 README.md 与 inputs/queries.example.csv。不得改代码、配置或测试。验证文档命令时不得安装依赖；未经真实非空合规审批不得访问豆瓣，只运行帮助和离线测试。
按本文检查后只提交上述两个文件，commit message 必须是：docs: add controlled demo runbook
完成时回报：DONE；变更文件；文档检查命令及结果；是否因合规门禁跳过 live run；commit hash。
无法完成时回报：BLOCKED；阻塞步骤；原始错误摘要；已执行命令；未提交文件列表。不要越界修复产品缺陷。
```

## Base / prerequisites

- 仓库根目录：`D:\DataAnt\.worktrees\browser-bot-demo`；现有 `.venv` 已安装项目和 dev 依赖。
- CLI：`python -m app.main run --input <csv> --output <xlsx> [--headed|--no-headed] [--retry-status STATUS] [--min-interval 5] [--browser-path PATH] [--profile-dir DIR]`。
- 独立浏览器数据目录是 `browser-profile/douban`；页面对象为 DrissionPage `tab`。
- 状态为八个：`SUCCESS`、`NOT_FOUND`、`REVIEW_REQUIRED`、`NETWORK_ERROR`、`PAGE_CHANGED`、`BLOCKED`、`OUTPUT_LOCKED`、`UNEXPECTED_ERROR`。
- 退出码：0 已处理；2 输入/配置错误；3 站点阻断；4 输出文件无法保存；5 浏览器启动/全局异常。
- 默认重跑 `NETWORK_ERROR`、`OUTPUT_LOCKED`、`UNEXPECTED_ERROR`；`--retry-status` 只额外加入状态。所有结果按 `task_id` upsert。

## Goal

让新成员只读 README 就能在 30 分钟内理解前置条件、安装、离线验证、受控运行、断点续跑、显式重试、安全边界、诊断产物与故障处置；示例 CSV 不含敏感数据。

## Files 边界

- Modify: `README.md`
- Modify: `inputs/queries.example.csv`
- 禁止修改其他文件。

## README 必须包含的完整契约

### 1. 前置条件

- Windows 10/11；Python 3.11 或 3.12；已安装 Google Chrome 或 Microsoft Edge（Chromium 100+）。
- DrissionPage 用于非商业用途，或已取得版权方许可。
- 真实站点运行前必须有记录在案的授权/合规审批；缺失时只允许离线 fixture 或 `data:` 页面。
- 只收集获批的公开字段；默认串行、至少 5 秒间隔，不代表站点授权。

### 2. 安装与离线检查

README 中写入：

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
py -3.12 -m venv .venv
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\Activate.ps1'
python -m pip install -e ".[dev]"
python -m pytest -q
python -m app.main run --help
```

说明安装命令只需首次执行；本任务验证时不得重建环境或安装。

### 3. 受控 run、resume 与 retry

README 中写入并解释：

```powershell
python -m app.main run --input .\inputs\queries.example.csv --output .\outputs\douban_movies.xlsx --headed --min-interval 5 --profile-dir .\browser-profile\douban
python -m app.main run --input .\inputs\queries.example.csv --output .\outputs\douban_movies.xlsx --headed --min-interval 5 --profile-dir .\browser-profile\douban --retry-status PAGE_CHANGED
```

- 第一条命令仅在合规批准和输入清单获批后运行；重跑时跳过稳定终态，默认重试三个瞬态状态，并按 `task_id` upsert。
- 第二条只在定位器修复、离线 parser 测试通过且重新获批后显式重跑 `PAGE_CHANGED`。
- 不得用 `--retry-status BLOCKED` 盲目重试；先解决授权或站点保护条件。

### 4. 登录、失败与安全

README 必须明确：

- MVP 不假设登录；若确需人工登录，只能使用项目专用 `browser-profile/douban`，不得接管日常浏览器 profile，也不得复制 Cookie。
- 程序报告 `BLOCKED` 或退出码 3 时立即停止，不添加绕过工具。
- `OUTPUT_LOCKED` 或退出码 4 时关闭 Excel，再按原命令重跑。
- `PAGE_CHANGED` 先修复定位器和 fixture，再显式重试。
- `NETWORK_ERROR` 有限退避后由下次运行重试；`UNEXPECTED_ERROR` 查看诊断后修复根因。
- 失败诊断是截图 + 脱敏 HTML；正常成功不截图。
- 永不提交 `.env`、`browser-profile/`、outputs、日志、截图、HTML、API Key、Cookie 或请求头。
- 诊断产物默认只保留 7 天；给出限定在仓库 `artifacts` 目录的 PowerShell 预览和删除命令，先预览再删除，不跟随目录外路径。

### 5. 输出与验收

列出 Excel 12 列：`task_id`、`query`、`query_year`、`matched_title`、`matched_year`、`director`、`rating`、`detail_url`、`match_method`、`status`、`error_message`、`collected_at`。说明每个输入只有一个 task 行，评分允许为空。

列出受控 Demo 流程：审批记录非空；固定获批输入；关闭 Excel；有头运行；观察阻断；核对退出码、每个 task 唯一行及诊断脱敏；记录日期、环境、输入规模、状态数量和耗时。

## 示例 CSV 契约

`inputs/queries.example.csv` 必须是 UTF-8 CSV，表头严格为 `query,year`；包含少量公开电影标题示例和至少一个空年份，不含姓名、账户、内部 ID、审批号、Cookie、Key 或其他敏感数据。重复查询只有在用于说明稳定 `task_id` 时才保留并在 README 解释。

## 可复现文档检查

### 1. 静态内容检查

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$Readme = Get-Content -Raw -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo\README.md'
$Required = @('Prerequisites','Install','run','resume','retry','browser-profile','BLOCKED','OUTPUT_LOCKED','PAGE_CHANGED','NETWORK_ERROR','UNEXPECTED_ERROR','截图','脱敏 HTML','7 天','退出码','task_id','collected_at','Compliance')
$Missing = $Required | Where-Object { $Readme -notmatch [regex]::Escape($_) }
if ($Missing) { throw "README missing: $($Missing -join ', ')" }
$Header = Get-Content -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo\inputs\queries.example.csv' -TotalCount 1
if ($Header -ne 'query,year') { throw "Unexpected CSV header: $Header" }
'README_STATIC_CHECK_OK'
```

Expected: 打印 `README_STATIC_CHECK_OK`。

### 2. 现有环境中的离线可执行性

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m app.main run --help
```

Expected: 测试退出 0；帮助命令退出 0 且参数与 README 一致。没有真实非空审批引用时，不执行 live run，并在 DONE 回报中说明是合规跳过而非测试失败。

## Acceptance checklist

- [ ] README 覆盖前置条件、安装、离线验证、受控运行、resume、retry、登录边界、退出码与 12 列。
- [ ] 明确 DrissionPage `tab`、独立 `browser-profile`、`NetworkError` 语义。
- [ ] 明确失败产物是截图 + 脱敏 HTML，且 runtime artifacts 不提交。
- [ ] 合规批准是 live run 前置条件，阻断时不绕过。
- [ ] 示例 CSV 表头正确且不含敏感数据。
- [ ] 静态检查、全量离线测试与 CLI 帮助检查通过。
- [ ] 范围外文件无变化。

## Commit 范围

```powershell
git add -- README.md inputs/queries.example.csv
git diff --cached --name-only
git commit -m "docs: add controlled demo runbook"
```

Expected: staged 列表只有 `README.md` 与 `inputs/queries.example.csv`。
