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
- **Live-run 授权门禁**：任何对真实豆瓣（`movie.douban.com`）的 live run 必须在 CLI 上**显式**传 `--live-approved` 与 `--max-queries <1–10>`，并且 `app.main` 在启浏览器前会校验 headed 模式与 `--min-interval >= 5`；缺任一参数直接返回退出码 2，浏览器根本不会启动。这条把"操作员是否知情同意"这件事从外部审批表挪到了 CLI 上的不可绕过开关。
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

任何对真实豆瓣的 run 都必须**显式**传 `--live-approved` 与 `--max-queries <N>`（1 ≤ N ≤ 10），并满足 headed 模式与 `--min-interval >= 5`，否则 `app.main` 会在启浏览器前直接拒绝（退出码 2）。DrissionPage 启动的浏览器以 `--headed` 模式可见，**必须**使用项目自带的独立 `browser-profile/douban`，不得接管日常 Chrome 登录态。

```powershell
python -m app.main run --input .\inputs\queries.example.csv --output .\outputs\douban_movies.xlsx --live-approved --max-queries 1 --headed --min-interval 5 --profile-dir .\browser-profile\douban
```

要点：

- 重跑时**稳定终态（`SUCCESS`、`NOT_FOUND`、`REVIEW_REQUIRED`）自动跳过**，默认仅对 `NETWORK_ERROR`、`OUTPUT_LOCKED`、`UNEXPECTED_ERROR` 三个瞬态状态重试；结果按 `task_id` upsert，不会重复追加行。
- 退出码 0 表示本次处理成功；非零见第 4 节故障矩阵。
- **网络瞬态**走内置退避：第 1 次立即重试，第 2 次等 2s，第 3 次等 5s；三次都失败才上报 `NETWORK_ERROR`，再由下一次 run 兜底。

### 3.2 显式追加重试（定位器修复后）

第二条命令只在**定位器已修复**、**离线 parser 单测全部通过**之后，才允许显式重跑 `PAGE_CHANGED`；同样要带 `--live-approved` 与 `--max-queries`：

```powershell
python -m app.main run --input .\inputs\queries.example.csv --output .\outputs\douban_movies.xlsx --live-approved --max-queries 1 --headed --min-interval 5 --profile-dir .\browser-profile\douban --retry-status PAGE_CHANGED
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

1. **显式传 `--live-approved`**：在 CLI 上确认本次 run 由操作员显式授权；
2. **`--max-queries` 1–10**：确认 `--max-queries` 与输入 CSV 的查询数相匹配（输入不能多于上限）；
3. **固定输入**：使用 `inputs/queries.example.csv`（表头 `query,year`，无敏感数据），必要时用本任务 commit 后的同一份文件；
4. **关闭 Excel**：在执行 run 命令前，关闭任何会打开 `outputs/douban_movies.xlsx` 的 Excel 进程；
5. **有头运行**：用第 3.1 节命令（含 `--live-approved --max-queries --headed --min-interval 5`）跑一次，目视确认浏览器以 `headed` 模式启动、`browser-profile/douban` 是独立目录；
6. **观察阻断**：故意把示例 CSV 里的 query 改成"高频敏感词"或临时阻断的样本，观察 `BLOCKED` 状态与退出码 3；sec.douban.com 重定向、accounts.douban.com/passport/login 跳转会立即被 `is_blocked()` 捕获并抛 `BlockedError`；
7. **核对**：每条 `task_id` 唯一一行；`artifacts/` 下的截图 + HTML 已脱敏（不含 Cookie / Key）；
8. **记录**：在项目日志里写明日期、环境、输入规模、状态数量、耗时。

完成上述八步且 `python -m pytest -q`、`python -m app.main run --help` 全部退出码 0，即视为本次受控 Demo 通过。

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
| 是否需要 CLI 显式授权 | 否 | **是**（`--live-approved --max-queries N`） |
| 跑什么 | `pytest -q` | `python -m app.main run --live-approved --max-queries N ...` |
| 是否启浏览器 | 否 | 是（`headed` 模式） |
| `--min-interval` | n/a | `>= 5` 秒（CLI 强校验） |
| 数据落盘 | 不落 Excel | `outputs/*.xlsx`（1–10 行，verify_core 校验） |
| 失败诊断 | 不截图 | `artifacts/<task_id>.{png,html}` |
| 是否允许 `--retry-status BLOCKED` | n/a | **禁止** |
| sec.douban.com / accounts.douban.com 重定向 | n/a | 立即判定 `BLOCKED`，停止批次 |

如果操作员没有显式传 `--live-approved`，本次任务**只跑离线自检**，不执行 live run，并在交付回报中显式说明"live run 因 CLI 授权门禁跳过"，而不是测试失败。

---

## 8. 第二站点：web-scraping.dev 商品采集与离线画廊

本仓库在豆瓣电影 Demo 之外，**独立**接入第二个明确用于网页抓取练习的目标网站 `web-scraping.dev`。`web-scraping.dev` 自述为面向网页抓取开发者的安全、合法的练习平台，其 `robots.txt` 声明 2 秒抓取间隔并显式禁止 `/robots-disallowed` 路径。本节只描述受控受权的商品采集与本地画廊验收，不复用豆瓣的 12 列电影契约、不复用豆瓣适配器、也不复用电影 Excel schema。

### 8.1 站点定位与访问边界

**为什么是第二个站点**

- 提供服务端分页的商品列表（`/products`）和稳定 ID 的商品详情（`/product/<id>`），适合作为新增站点适配器的最小目标。
- 与豆瓣电影契约完全独立：商品价格、分类、品牌、变体等信息不会被塞进 12 列电影工作簿。
- 离线 fixture 友好：列表/详情/阻断等场景可被完全本地化为 HTML 快照，CI 永远不连真实站点。

**允许访问的路径**

- `https://web-scraping.dev/products` 列表首页；
- `/products` 服务端分页产生的合法下一页 URL；
- 由列表页发现、经 URL 规范化校验后的 `https://web-scraping.dev/product/<id>` 详情页。

**禁止访问（命中立即停止）**

- `/robots-disallowed` 及其下属任何路径；
- 登录 / iframe 登录 / 凭证检查页面；
- 购物车、购买与评论 Load More 等交互接口；
- GraphQL、CSRF、文件下载、Antibot Challenge；
- 任意站外 URL（含被重定向后的 `sec.douban.com` 之类）。

### 8.2 受控采集命令（可复制）

```powershell
python -m app.main collect-products `
  --site web-scraping.dev `
  --output-dir .\outputs\web-scraping-dev-demo `
  --live-approved `
  --max-products 10 `
  --headed `
  --min-interval 2 `
  --profile-dir .\browser-profile\web-scraping-dev
```

要点：

- 必须在浏览器启动前显式传入 `--live-approved`，否则 `app.main` 直接返回退出码 2；
- `--max-products` 取值 `[1, 10]`，命令在启浏览器前完成强校验；
- `--min-interval 2` 是平台声明的下限，命令禁止下调到 2 秒以下；
- `--profile-dir` 必须落在仓库 `browser-profile/` 内（`browser-profile/web-scraping-dev`），禁止接管日常浏览器 profile；
- `--output-dir` 必须落在仓库 `outputs/` 内（`outputs/web-scraping-dev-demo`），禁止写到仓库外；
- 受控验收必须至少跨两个 `/products` 分页，证明分页发现 + 去重 + 详情解析共同工作。

### 8.3 输出三件套

`--output-dir` 指定目录内同时生成三个产物，**必须**来自同一次不可变的 `ProductCollection`：

| 产物 | 角色 | 用途 |
| ---- | ---- | ---- |
| `products.xlsx` | 结构化主表 | 12 列固定顺序、按 `product_id` upsert；列顺序与商品领域模型一致，**不**复用豆瓣电影 12 列。 |
| `products.json` | 机器可读快照 | 含 `schema_version` / `source_site` / `generated_at` / `summary` / `products`；金额为 JSON number，时间为带时区的 ISO 8601。 |
| `gallery.html` | 静态可视化画廊 | 商品卡片 + 采集证据侧栏；嵌入本地数据，离线双击即可打开。 |

输出被 Excel 占用时返回 `OUTPUT_LOCKED` 语义（退出码 4），不覆盖也不损坏旧文件。任何单个输出器失败都不会产生彼此不一致的产物。

### 8.4 打开静态画廊（本地，无网络）

```powershell
# 推荐：用默认浏览器直接打开
Start-Process .\outputs\web-scraping-dev-demo\gallery.html

# 或在文件资源管理器双击
explorer .\outputs\web-scraping-dev-demo\gallery.html
```

打开前请确认：

- 当前网络已**断开**，或 DevTools Network 面板已开启；
- 页面加载完成后 Network 面板**无任何自动请求**到 `web-scraping.dev`、CDN 或外部域名；
- 商品卡片封面始终由内置 CSS/SVG 按分类和名称**本地**生成，不下载任何远程图片。

### 8.5 画廊交互能力

`gallery.html` 在纯 HTML + CSS + 原生 JavaScript 下提供以下能力，**不**依赖任何 CDN、字体或前端框架：

- 按商品名称模糊搜索；
- 按 `category` 分类下拉筛选；
- 按 `status` 采集状态下拉筛选；
- 按 `current_price` 升序 / 降序切换；
- 点击任意商品卡片 → 右侧/下方证据侧栏更新，展示完整名称、描述、价格、原价、币种、品牌、变体数、`product_id`、采集时间、规范来源 URL、状态徽标与失败/部分成功原因；
- 窄屏下卡片网格自动折叠为单列，侧栏始终可读；
- 失败商品仍以卡片形式展示，并在侧栏明确写出 `error_message`。

### 8.6 状态与故障处置

| 状态 | 含义 | 推荐处置 | CLI 退出码 |
| ---- | ---- | -------- | ---------- |
| `SUCCESS` | 必填字段全部解析成功 | 无 | 0 |
| `PARTIAL` | 商品身份与价格成立，可选展示字段缺失 | 接受结果，记录原因 | 0 |
| `PAGE_CHANGED` | 列表或详情关键结构不符合契约 | 先修适配器 + 离线 parser，跑通后再受控重跑 | 0 |
| `NETWORK_ERROR` | 有限重试（2s / 5s 退避）后仍无法访问 | 下次 run 兜底 | 0 |
| `BLOCKED` | 429、阻断页或明确访问限制 | **立即停止**，不绕过 | 3 |
| `UNEXPECTED_ERROR` | 未归类异常 | 查看诊断，定位根因后再跑 | 5 |

补充：

- `PARTIAL` **不**用于掩盖必填字段缺失（缺 ID / 缺名称 / 缺当前价 / 页面已不是详情形态）—— 这些情况必须落到 `PAGE_CHANGED`。
- 失败记录仍进入 `products.xlsx` / `products.json` / `gallery.html`，保留 `product_id`、来源 URL、状态、错误信息与采集时间，**不**为缺失字段编造默认值。
- 任何状态都不修改豆瓣电影 12 列 schema、不复用 `movies` 工作表。

### 8.7 立即停止条件

下列任意一种命中，适配器立即抛错、运行器立即终止本批，**不**做代理、验证码识别、Cookie 注入、降速绕过等任何形式的“再试一次”：

- HTTP 429；
- 明确阻断页（站方声明的 block / challenge 页面）；
- 重定向到目标站阻断或挑战页；
- 登录、安全检查或凭证页面；
- 跳转到 `web-scraping.dev` 之外域名；
- 命中 `/robots-disallowed` 等 robots 禁止路径；
- 连续多页表明适配器已失效。

### 8.8 CI 与离线验收

- CI（`.github/workflows/core-offline.yml`）**只**做离线 fixture 测试：跑全量 `pytest`、跑 `scripts.verify_core` 覆盖率门禁、跑 `pip check`、跑 `git diff --check`。**不**启动浏览器、**不**访问 `web-scraping.dev`、**不**生成或上传 `products.xlsx` / `products.json` / `gallery.html`。
- 验收离线产物时直接跑 `python -m pytest tests/test_product_output_bundle.py tests/test_product_gallery.py -q`，使用 fixture 在临时目录构造 `products.xlsx` / `products.json` / `gallery.html`；不要把临时文件复制到 Git 跟踪目录。
- 人工受控验收必须显式传 `--live-approved --max-products N`，有头浏览器运行、至少跨两个列表分页、间隔 `>= 2` 秒；至少要核对三个产物的商品数与 `product_id` 完全一致。

### 8.9 永不提交

`outputs/`、`browser-profile/`、`artifacts/`、日志、截图、HTML 证据、API Key、Cookie、请求头、用户身份相关字段一律**不**进 Git。`.gitignore` 已托管上述路径，本节新增的 `outputs/web-scraping-dev-demo/`、`browser-profile/web-scraping-dev/` 也只保留 `.gitkeep` 占位。提交前 `git diff --name-only` 应只看到本任务批准的 `README.md`、`tests/test_project_config.py`（必要时加上 `pyproject.toml`）。

---

## 9. CI 与 Release Readiness

### 9.1 CI 是什么、不是什么

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

### 9.2 Release Readiness 还需要哪些证据

一个 release 真正可发，**除 CI 绿以外**还至少需要：

1. **本地 `data:` browser smoke**：`scripts/browser_smoke.py`（data: URL、一次性、零网络）必须在 release host 上退出码 0；这证明浏览器路径在目标机器上仍可启动，CI runner 没机会验证这件事。
2. **受控 workbook 校验**：
   - 落盘到 `outputs/<run>.xlsx` 的 12 列、1–10 行（任意 1 ≤ N ≤ 10）受控 workbook；
   - `scripts/verify_core.verify_controlled_workbook(Path("outputs/<run>.xlsx"))` 必须返回 `{"data_rows": N, "unique_ids": N}`，workbook 任务 id 唯一、状态合法、`collected_at` 全填；
   - 本任务不再要求独立的受控 evidence 文件，也不再读取任何外部审批字段 —— 那个责任现在落到 CLI 上的 `--live-approved` 开关 + 1–10 行 `--max-queries` 上限。
3. **CLI 授权记录可追溯**：本次 run 的命令行必须能复现出来（`--live-approved --max-queries N --headed --min-interval 5`），run 日志里要能引用到。

### 9.3 缺证据时的处置

- 缺本地 browser smoke → **BLOCKED**，不发布。
- 缺受控 workbook / `verify_controlled_workbook` 不通过 → **BLOCKED**，不发布。
- 缺 CLI 授权的运行日志（`--live-approved` 与 `--max-queries`）→ **BLOCKED**，**不允许**通过"跑一次真实豆瓣补一下"绕过 — 那等于把 CI 之外的 live 访问偷偷放进来，违反本仓库零网络、零 API Key 的红线。
- BLOCKED 必须显式记录在交付回报里（"因 X 证据缺失，release 仍处 BLOCKED"），而不是悄悄标"完成"。

### 9.4 MiniMax 集成延期

`MINIMAX_API_KEY` 继续延期接入，本轮 CI 与 release 流程**不读**这个变量、不调用 `api.minimax.com`，LLM 路径在 CI 里被彻底切断。等专门的 MiniMax 接入任务上线时，再把 secret scan pattern 同步扩展并复用同一份 `scripts.verify_core` 阈值。

### 9.5 Release Readiness 12 步门禁

把 release 从"CI 绿"推进到"READY_TO_PUSH"需要 12 步可逐条复制的 PowerShell 门禁：

1. 精确 worktree 路径；
2. 初始 git status 干净；
3. `pytest -q`；
4. `pytest --cov=app --cov-report=json:artifacts/coverage.json -v`；
5. `python -m scripts.verify_core --coverage-json artifacts/coverage.json`；
6. `python -m pip check`；
7. `python -m scripts.browser_smoke`（本地 `data:` 页面）；
8. 受控 workbook 校验（`verify_controlled_workbook(Path("outputs/<run>.xlsx"))` 必须返回 1–10 个唯一 task）；
9. secret scan；
10. tracked runtime artifact scan；
11. `git diff --check` + `git status --short`；
12. 全部通过才能输出 `READY_TO_PUSH`。

每一步的命令、退出码、关键证据与失败处置都写在 [`docs/superpowers/tasks/core-13-release-readiness.md`](docs/superpowers/tasks/core-13-release-readiness.md)。本 README 不复制完整 PowerShell，避免与该 spec 漂移；遇到 release 决策时直接打开该 spec 跑第 1–12 步，再按 spec 末尾的 Acceptance checklist 与最终报告模板汇报。

> 第 8 步是合规硬门禁：`outputs/<run>.xlsx` **必须**由本任务之外的真实受控 Demo run 落盘（带 `--live-approved --max-queries N` 启动），**不**能由 release 流程自己跑、不能伪造、不能下载。workbook 验证失败时整轮报告 `NOT_READY`，**绝不能**为了得到绿色结果而访问真实豆瓣。
