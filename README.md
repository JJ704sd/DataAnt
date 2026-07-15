# browser-bot-demo

> 受控的豆瓣电影小助手 Demo：新人 30 分钟内即可读懂前置条件、安装、离线验证、受控运行、断点续跑、显式重试与故障处置。
> 本文档面向需要在本仓库 `D:\DataAnt\.worktrees\browser-bot-demo` 中复现 Demo 的人；所有命令均假定在 PowerShell 中以工作目录为根执行。

---

## 1. Prerequisites（前置条件）

- **操作系统**：Windows 10 / Windows 11。
- **Python**：3.11 或 3.12（项目 `pyproject.toml` 限定 `>=3.11,<3.13`）。
- **浏览器**：本机已安装 Google Chrome 或 Microsoft Edge，且 Chromium 内核版本 ≥ 100。DrissionPage 启动时按以下顺序自动探测可执行文件：
  1. `--browser-path` 显式指定的路径；
  2. `%ProgramFiles%\Google\Chrome\Application\chrome.exe`；
  3. `%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe`；
  4. `%LocalAppData%\Google\Chrome\Application\chrome.exe`；
  5. `%ProgramFiles%\Microsoft\Edge\Application\msedge.exe`；
  6. `%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe`。
  全部缺失时启动即抛 `FileNotFoundError`，退出码 5。
- **DrissionPage 许可**：DrissionPage 仅可用于非商业用途；若用于商业场景必须先取得版权方书面许可（见上游项目协议）。
- **Compliance 审批（合规门禁）**：任何对真实豆瓣（`movie.douban.com`）的 live run 都必须在开始前留下**非空**的审批记录（谁批、批多少、批多久、采集哪些字段），并在 run 日志中引用。**缺失审批时只允许跑离线 fixture / `data:` 页面**，不得上线浏览器。
- **数据边界**：只收集获批的公开字段（`task_id`、`query`、`query_year`、`matched_title`、`matched_year`、`director`、`rating`、`detail_url`、`match_method`、`status`、`error_message`、`collected_at` 共 12 列）。其它一切字段都不抓取。
- **运行节奏**：默认**串行**执行，相邻任务间隔至少 `5` 秒（`--min-interval`），**不**代表任何形式的站点授权。

---

## 2. Install & 离线检查

下列命令在仓库根目录 `D:\DataAnt\.worktrees\browser-bot-demo` 下以 PowerShell 执行。**安装命令仅在首次克隆或重建环境时执行一次**；本任务以及 CI 中都禁止重建 venv 或重装依赖。

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
py -3.12 -m venv .venv
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\Activate.ps1'
python -m pip install -e ".[dev]"
python -m pytest -q
python -m app.main run --help
```

逐条说明：

| 命令 | 作用 | 预期 |
| ---- | ---- | ---- |
| `py -3.12 -m venv .venv` | 创建本地虚拟环境 | 退出码 0，生成 `.venv/` |
| `pip install -e ".[dev]"` | 安装项目本体 + pytest / pytest-cov | 退出码 0 |
| `python -m pytest -q` | 跑全量离线单测 | **所有用例通过，退出码 0** |
| `python -m app.main run --help` | 打印 CLI 帮助 | **退出码 0**，且参数表与本文第 3 节一致 |

> `python -m pytest -q` 期间**不会**连接真实豆瓣；所有测试都使用 `tests/fixtures/*.html` 的本地 HTML 快照。

---

## 3. 受控 run、resume 与 retry

### 3.1 第一次受控 run

仅在**审批记录非空**且**输入清单已获批**时执行。DrissionPage 启动的浏览器以 `--headed` 模式可见，**必须**使用项目自带的独立 `browser-profile/douban`，不得接管日常 Chrome 登录态。

```powershell
python -m app.main run --input .\inputs\queries.example.csv --output .\outputs\douban_movies.xlsx --headed --min-interval 5 --profile-dir .\browser-profile\douban
```

要点：

- 重跑时**稳定终态（`SUCCESS`、`NOT_FOUND`、`REVIEW_REQUIRED`）自动跳过**，默认仅对 `NETWORK_ERROR`、`OUTPUT_LOCKED`、`UNEXPECTED_ERROR` 三个瞬态状态重试；结果按 `task_id` upsert，不会重复追加行。
- 退出码 0 表示本次处理成功；非零见第 4 节故障矩阵。
- **网络瞬态**走内置退避：第 1 次立即重试，第 2 次等 2s，第 3 次等 5s；三次都失败才上报 `NETWORK_ERROR`，再由下一次 run 兜底。

### 3.2 显式追加重试（定位器修复后）

第二条命令只在**定位器已修复**、**离线 parser 单测全部通过**、且**重新获得合规审批**之后，才允许显式重跑 `PAGE_CHANGED`：

```powershell
python -m app.main run --input .\inputs\queries.example.csv --output .\outputs\douban_movies.xlsx --headed --min-interval 5 --profile-dir .\browser-profile\douban --retry-status PAGE_CHANGED
```

- `--retry-status` 只在默认三状态之上**追加**，不会覆盖。
- **不得**用 `--retry-status BLOCKED` 盲目重试。`BLOCKED` 是站点拒绝信号，先解决授权或站点保护条件，再决定是否重跑。

### 3.3 resume 的依据

`task_id = sha256(query.casefold() ‖ U+001F ‖ year ‖ U+001F ‖ occurrence)`，前 20 hex。Excel 12 列是按 `task_id` upsert，因此只要输入 CSV 顺序与内容不变，重跑不会产生重复行；重复 `query` 必须在 CSV 中显式出现并被 README 解释（示例 CSV 故意不重复，避免歧义）。

---

## 4. 登录、失败与安全

### 4.1 登录边界（MVP）

- **MVP 不假设登录**：除非显式接入登录流程，否则不应在受控 Demo 中凭账号运行。
- 若确实需要人工登录，**只能**使用项目自带 `browser-profile/douban/`，**不得**接管或复制日常浏览器的 profile / Cookie / 已登录会话。
- 任何"借号跑一下"都不在本 Demo 范围内。

### 4.2 故障矩阵（状态 → 行为 → 退出码）

| 状态 | 含义 | 推荐处置 | CLI 退出码 |
| ---- | ---- | -------- | ---------- |
| `SUCCESS` | 已匹配并落库 | 无 | 0 |
| `NOT_FOUND` | 搜索无候选 | 人工确认标题/年份写法 | 0 |
| `REVIEW_REQUIRED` | 匹配器犹豫 | 人工二选一后用新 query 跑 | 0 |
| `NETWORK_ERROR` | 网络瞬态失败 | 2s/5s 退避后下次 run 兜底 | 0 |
| `PAGE_CHANGED` | 页面结构变化 | 先修定位器 + 离线 parser，跑通后 `--retry-status PAGE_CHANGED` | 0 |
| `BLOCKED` | 站点拒绝（403/418/429 或敏感词） | **立即停止**，不绕过 | **3** |
| `OUTPUT_LOCKED` | Excel 被 Excel 打开占用 | 关闭 Excel，按原命令重跑 | **4** |
| `UNEXPECTED_ERROR` | 未归类异常 | 查看诊断，定位根因后再跑 | **5** |

补充说明：

- 出现 `BLOCKED` 或退出码 3 → **立即停止**，**不**添加代理、验证码识别、Cookie 注入、降低间隔等绕过手段。
- 出现 `OUTPUT_LOCKED` 或退出码 4 → 关闭打开该 Excel 的进程（任务管理器 / `Stop-Process -Name EXCEL`），再按原命令重跑；输出目录是 `outputs/`，文件后缀固定 `.xlsx`。
- `PAGE_CHANGED` → 先用 `tests/fixtures/*.html` 复现并修定位器；离线 `pytest` 通过后再显式 `--retry-status PAGE_CHANGED` 重跑。
- `NETWORK_ERROR` → 有限退避后由下次 run 兜底；不修改 `--min-interval` 来"补偿"。
- `UNEXPECTED_ERROR` → 先看 `artifacts/` 下的截图 + 脱敏 HTML，定位根因再修。
- 退出码 2 = 输入/配置错误（CSV 不存在、状态名拼错、`--output` 路径不可写等）；退出码 5 = 浏览器启动或未归类全局异常。

### 4.3 失败诊断（artifacts 契约）

- 仅当状态属于 `NETWORK_ERROR` / `PAGE_CHANGED` / `BLOCKED` / `UNEXPECTED_ERROR` 时捕获；`SUCCESS` / `NOT_FOUND` / `REVIEW_REQUIRED` 故意**不**截图。
- 每次失败落两个文件（都进 `artifacts/`，但**不**进 git）：
  - `<task_id>.png` — 全页截图（来自 DrissionPage `tab.get_screenshot(path, name, full_page=True)`）；
  - `<task_id>.html` — `tab.html` 经 `redact()` 脱敏后截到 ≤ 200,000 字符。
- 脱敏规则：API Key / Cookie 字面值替换为 `***`，日志和 HTML 都不出现明文。
- 诊断路径**仅限定在仓库内 `artifacts/` 目录**，不得指向目录外路径。下列命令**先预览再删除**，**不**跟随 `artifacts/` 之外的路径：
  ```powershell
  # 预览：列出 7 天前的失败产物（不会删除）
  Get-ChildItem -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo\artifacts' -File -Recurse |
      Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
      Select-Object FullName, LastWriteTime
  # 删除：确认上面输出后，单独跑
  Get-ChildItem -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo\artifacts' -File -Recurse |
      Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
      Remove-Item -Force
  ```
- **保留期默认 7 天**；超过 7 天的失败产物按上面命令清理，`artifacts/` 目录本身保留（`.gitkeep` 占位）。

### 4.4 永不提交（.gitignore 已托管）

`.env`、`browser-profile/`、`outputs/`、`artifacts/`、日志、截图、HTML、API Key、Cookie、请求头、用户身份相关字段一律**不得** commit。`.gitignore` 已托管上述路径，提交前 `git status` 应仅显示本次任务批准的 `README.md` 与 `inputs/queries.example.csv`。

---

## 5. 输出与验收

### 5.1 Excel 12 列契约

`outputs/<run>.xlsx` 表头严格 12 列，**每一列在每次 run 都存在**：

| # | 列名 | 说明 |
| - | ---- | ---- |
| 1 | `task_id` | sha256 前 20 hex，按 query+year+occurrence 派生 |
| 2 | `query` | 原始查询字符串 |
| 3 | `query_year` | 原始年份（4 位数字或空） |
| 4 | `matched_title` | 命中标题，空表示未匹配 |
| 5 | `matched_year` | 命中详情页年份 |
| 6 | `director` | 导演列表（` / ` 分隔） |
| 7 | `rating` | 评分（浮点，允许为空） |
| 8 | `detail_url` | `https://movie.douban.com/subject/<id>/` 形式的规范链接 |
| 9 | `match_method` | `RULE_EXACT` / `RULE_YEAR` / `LLM` / `NONE` |
| 10 | `status` | 八个状态之一 |
| 11 | `error_message` | 错误描述；成功行可为空 |
| 12 | `collected_at` | 本地时区 ISO8601 秒级时间戳 |

- **每个输入 query 在 Excel 中只有一行**（按 `task_id` upsert；稳定状态不会重复追加）。
- 评分允许为空（如 `NOT_FOUND` / `PAGE_CHANGED` 行）。
- `collected_at` 永远是本地时区、ISO8601、带秒级精度的字符串。

### 5.2 受控 Demo 流程（验收清单）

执行下列步骤完成一次受控 Demo 验收：

1. **审批记录非空**：确认 `Compliance` 审批表 / 邮件引用中存在本次采集范围；
2. **固定获批输入**：使用 `inputs/queries.example.csv`（表头 `query,year`，无敏感数据），必要时用本任务 commit 后的同一份文件；
3. **关闭 Excel**：在执行 run 命令前，关闭任何会打开 `outputs/douban_movies.xlsx` 的 Excel 进程；
4. **有头运行**：用第 3.1 节命令跑一次，目视确认浏览器以 `headed` 模式启动、`browser-profile/douban` 是独立目录；
5. **观察阻断**：故意把示例 CSV 里的 query 改成"高频敏感词"或临时阻断的样本，观察 `BLOCKED` 状态与退出码 3；
6. **核对**：每条 `task_id` 唯一一行；`artifacts/` 下的截图 + HTML 已脱敏（不含 Cookie / Key）；
7. **记录**：在项目日志里写明日期、环境、输入规模、状态数量、耗时。

完成上述七步且 `python -m pytest -q`、`python -m app.main run --help` 全部退出码 0，即视为本次受控 Demo 通过。

---

## 6. 示例 CSV 说明

`inputs/queries.example.csv` 是本仓库提供的最小示例：

- 编码：UTF-8，**无 BOM**；
- 表头严格 `query,year`；
- 内容只包含公开电影标题 + 公开年份，且**至少有一个空年份**（用于演示"年份未知"分支）；
- 不含姓名、账户、内部 ID、审批号、Cookie、API Key 等敏感数据；
- 不故意重复 query（重复会让 `task_id` 派生需要 `occurrence` 计数，本示例保持唯一以避免歧义；如确需重复，必须在 README 中显式说明）。

---

## 7. 离线 vs. Live run 自检清单

| 项 | 离线（fixture / `data:` 页面） | Live run（真实豆瓣） |
| -- | ---------------------------- | ------------------- |
| 是否需要 Compliance 审批 | 否 | **是**（非空记录 + 输入清单获批） |
| 跑什么 | `pytest -q` | `python -m app.main run ...` |
| 是否启浏览器 | 否 | 是（`headed` 模式） |
| 数据落盘 | 不落 Excel | `outputs/*.xlsx` |
| 失败诊断 | 不截图 | `artifacts/<task_id>.{png,html}` |
| 是否允许 `--retry-status BLOCKED` | n/a | **禁止** |

如果 Compliance 审批为空，本次任务**只跑离线自检**，不执行 live run，并在交付回报中显式说明"live run 因合规门禁跳过"，而不是测试失败。

---

## 8. CI 与 Release Readiness

### 8.1 CI 是什么、不是什么

`.github/workflows/core-offline.yml` 是**离线核心 release gate**，故意做得很窄：

- **CI 证明的**：在干净 Python 3.11 runner 上，离线确定性正确性（`pytest -q` + `pytest-cov` 覆盖率 JSON 通过 `scripts.verify_core` 阈值检查 + `git diff --check` + tracked runtime artifact / secret scan）。
- **CI 故意不做的**：
  - 不启动浏览器（`DrissionPage` / Chromium / Edge / `headed` 模式都不会出现）；
  - 不访问 `movie.douban.com` 或任何 live host；
  - 不读 `MINIMAX_API_KEY` 或调用 `api.minimax.com`；
  - 不执行真实 LLM 调用；
  - 不创建或伪造 `outputs/*.xlsx` 受控 workbook；
  - 不上传 `browser-profile/`、`outputs/`、`artifacts/` 为 workflow artifact；
  - 不重建本地 `.venv`，直接 `pip install -e ".[dev]"`。
- `tests/test_project_config.py::test_core_ci_is_offline_and_runs_portable_verification` 把上述约束编码成配置契约，CI 改了工作流就必须同步通过这个测试。

> **一句话：CI 绿 ≠ release 绿。** CI 只证明"在隔离环境里离线契约没破"，它无法证明"在 release host 上能起浏览器、能在真实豆瓣上工作、且本次 run 已被合规批准"。

### 8.2 Release Readiness 还需要哪些证据

一个 release 真正可发，**除 CI 绿以外**还至少需要：

1. **本地 `data:` browser smoke**：`scripts/browser_smoke.py`（data: URL、一次性、零网络）必须在 release host 上退出码 0；这证明浏览器路径在目标机器上仍可启动，CI runner 没机会验证这件事。
2. **已批准的受控 workbook + approval evidence**：
   - 落盘到 `outputs/<run>.xlsx` 的 12 列、10 行受控 workbook；
   - 对应的 `evidence.json` 包含 `approval_reference`、`compliance_approved=true`、`approved_query_count=10`、`run_id`、`completed_at`；
   - `scripts/verify_core.verify_controlled_workbook(workbook, evidence)` 必须通过。
3. **审批记录可追溯**：本次 run 在合规审批表 / 邮件里有非空引用（谁批、批多少、批多久、采集哪些字段），run 日志里要能引用到。

### 8.3 缺证据时的处置

- 缺本地 browser smoke → **BLOCKED**，不发布。
- 缺已批准 workbook / approval evidence → **BLOCKED**，不发布。
- 缺审批记录 → **BLOCKED**，**不允许**通过"跑一次真实豆瓣补一下"绕过 — 那等于把 CI 之外的 live 访问偷偷放进来，违反本仓库零网络、零 API Key 的红线。
- BLOCKED 必须显式记录在交付回报里（"因 X 证据缺失，release 仍处 BLOCKED"），而不是悄悄标"完成"。

### 8.4 MiniMax 集成延期

`MINIMAX_API_KEY` 继续延期接入，本轮 CI 与 release 流程**不读**这个变量、不调用 `api.minimax.com`，LLM 路径在 CI 里被彻底切断。等专门的 MiniMax 接入任务上线时，再把 secret scan pattern 同步扩展并复用同一份 `scripts.verify_core` 阈值。
