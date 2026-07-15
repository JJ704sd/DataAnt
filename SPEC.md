# 浏览器自动化机器人 Demo — 可实施规划 Spec v1.0

> 状态：待评审  
> 场景：豆瓣电影查询作为首个站点适配器  
> 编写日期：2026-07-15  
> 工作目录：`D:\DataAnt`

---

## 1. 文档结论

本 Demo 采用以下最小技术栈：

> **Python 3.11/3.12 + DrissionPage 4.1 + openpyxl + pytest**

程序真实打开浏览器，在豆瓣电影页面输入查询词并提交，读取搜索结果和详情页字段，然后直接生成 `.xlsx` 文件。**不操控桌面 Excel，不依赖 LLM，不建设通用 RPA 平台。**

MiniMax LLM 作为可选能力，仅用于规则无法判断搜索结果时的候选排序；没有 API Key 或调用失败时，主流程仍能运行，并把该条标记为 `REVIEW_REQUIRED`。

### 1.1 第一性原理约束

方案从最终结果反推，而不是从工具清单出发：

1. 每个输入必须对应一个可追踪结果，因此需要稳定 `task_id`、显式状态和逐条持久化。
2. 用户要求看到网站输入与查询，所以浏览器是必要边界；桌面 Excel 点击不是结果要求，因此直接写 `.xlsx`。
3. 标题、年份、URL 是可观察事实，确定性规则必须先于概率性模型。
4. LLM 只能处理“多个候选仍无法唯一判断”这一剩余不确定性；Key 的存在不等于必须使用 LLM。
5. 外部站点权限、可访问性、阻断页和当前 DOM 都是实施前必须验证的事实；验证失败时停止或更换已授权测试站点，而不是增加绕过技术。
6. Demo 的优先级依次是：正确性、可恢复性、可审计性、安全与合规，最后才是吞吐量。

---

## 2. 目标、范围与成功定义

### 2.1 用户故事

技术人员提供一个 CSV，其中每行是电影名，可选年份。运行一条命令后，程序：

1. 打开可见 Chromium 浏览器；
2. 在豆瓣电影页面输入电影名并提交搜索；
3. 从候选结果中选择可信匹配；
4. 打开详情页，读取核心字段；
5. 将每条结果或失败原因写入 Excel；
6. 中断后再次运行时，跳过已成功任务并继续。

### 2.2 MVP 范围

- 输入：UTF-8 CSV，5–20 条用于首轮 Demo；支持扩展到 50 条稳定性验证。
- 站点：只支持豆瓣电影；架构保留站点适配器边界，但不实现第二个站点。
- 浏览器动作：打开、输入、提交、点击结果、读取 DOM。
- 输出：直接创建或更新 `.xlsx`，不要求本机安装 Microsoft Excel。
- 登录：默认不登录；仅当实测证明目标字段需要登录时，允许用户在可见浏览器中手动登录并保存浏览器状态。
- 并发：单浏览器、单页面、串行执行。

### 2.3 明确不做

- 桌面 Excel 点击、剪贴板复制粘贴、Windows UI Automation；
- 验证码识别、反检测浏览器、代理池、IP 或账号轮换；
- 评论、影评、剧照等大规模内容采集；
- 定时调度、分布式队列、Web UI、打包 `.exe`；
- 让 LLM 自主浏览、任意点击或直接决定最终数据；
- 对非公开数据、个人信息或登录后受限内容进行批量采集。

### 2.4 Demo 成功定义

使用一份固定的 10 条测试输入，在满足目标站可访问且未触发验证/限流的前提下：

- 10 条全部产生 Excel 行，不静默丢数据；
- 明确匹配的条目写出标题、年份、导演、评分和详情 URL；
- 无结果、歧义、页面变化和网络错误都有可识别状态；
- 强制中断后重跑，不重复写入已成功任务；
- 不提供 MiniMax Key 时仍能完成确定性流程；
- README 中的全新环境安装步骤能在 30 分钟内完成。

“固定失败率小于 10%”“200 条固定耗时”等指标必须来自试运行记录，本 Spec 不提前承诺。

---

## 3. 开源项目调研与选型

以下数据为 2026-07-15 的 GitHub 页面快照，star 数只用于说明社区规模，不作为唯一选型依据。

| 项目 | GitHub 规模 | 适合场景 | 本项目结论 |
|---|---:|---|---|
| [DrissionPage](https://github.com/g1879/DrissionPage) | 约 12.2k stars | Python Chromium 自动化、静态 DOM 解析 | **采用**；可直接使用本机 Chrome/Edge、无需 WebDriver，并提供统一元素查找与等待能力；本项目按非商业/已授权前提使用 |
| [Microsoft Playwright](https://github.com/microsoft/playwright) | 约 92.8k stars | 现代浏览器测试与确定性自动化 | 可行但不选；本机已有兼容 Chromium，Demo 无需额外下载 bundled Chromium |
| [Selenium](https://github.com/SeleniumHQ/selenium) | 约 34.3k stars | 跨语言、WebDriver 生态、Grid | 可行但不选；本地 Demo 用不到 WebDriver 与 Grid |
| [Robot Framework Browser](https://github.com/MarketSquare/robotframework-browser) | 约 647 stars | 关键字驱动、测试报告 | 不选；增加 DSL 和 Node 侧依赖层，技术团队直接维护 Python 更简单 |
| [Robocorp RPA Framework](https://github.com/robocorp/rpaframework) | 约 1.5k stars | 浏览器、桌面、Office 等跨应用 RPA | 不选；能力全面但当前范围只需浏览器和文件写入 |
| [OpenRPA](https://github.com/open-rpa/openrpa) | 约 3k stars | Windows 可视化工作流和企业编排 | 不选；设计器和编排平台超过 Demo 需要 |
| [TagUI](https://github.com/aisingapore/TagUI) | 约 6.3k stars | 低代码 RPA | 不选；项目页面说明 AI Singapore 已停止维护和支持 |
| [Browser Use](https://github.com/browser-use/browser-use) | 约 105k stars | LLM 驱动的开放式浏览器任务 | 不选作主流程；固定页面使用 Agent 会增加费用和概率性 |
| [Stagehand](https://github.com/browserbase/stagehand) | 约 23.5k stars | 代码与自然语言混合自动化 | 暂不采用；已知页面优先使用可审计的确定性代码 |

### 3.1 为什么选 DrissionPage

- 直接控制本机 Chromium 内核浏览器，无需 WebDriver，也无需为 Demo 下载独立浏览器二进制。
- `Chromium`、`ChromiumOptions` 与 Tab/Element API 覆盖有头启动、页面访问、元素输入/点击、等待、截图和网络监听。
- `make_session_ele()` 可从脱敏 HTML 生成静态元素树，使解析器测试不依赖真实浏览器或网络。
- 独立用户数据目录可保存登录状态；程序不得接管操作者日常浏览器配置目录。
- 本项目明确以非商业或已取得版权方授权为前提，并继续遵守目标站协议与 robots 约束。

参考：[DrissionPage 浏览器控制](https://www.drissionpage.cn/browser_control/intro/)、[浏览器启动设置](https://www.drissionpage.cn/browser_control/browser_options/)、[make_session_ele](https://www.drissionpage.cn/advance/tools/)、[官方仓库使用条款](https://github.com/g1879/DrissionPage)。

### 3.2 为什么用 openpyxl

openpyxl 可直接创建、读取和保存 `.xlsx`，不依赖桌面 Excel。保存会覆盖同名文件，因此实现必须采用临时文件加原子替换，并在文件被 Excel 占用时给出明确错误。参考：[openpyxl Tutorial](https://openpyxl.readthedocs.io/en/3.1/tutorial.html)。

---

## 4. 系统架构

### 4.1 目录结构

```text
browser-bot-demo/
├── app/
│   ├── main.py                 # CLI 与退出码
│   ├── models.py               # Task、Candidate、MovieResult
│   ├── runner.py               # 单条/批量调度、断点续跑
│   ├── browser_session.py      # DrissionPage/Chromium 生命周期与独立用户目录
│   ├── matcher.py              # 确定性匹配规则
│   ├── llm_matcher.py          # 可选 MiniMax 候选排序
│   ├── excel_store.py          # xlsx 读写、去重、原子保存
│   └── sites/
│       └── douban_movie.py     # 页面动作、定位器、字段解析、阻断页检测
├── tests/
│   ├── fixtures/               # 已脱敏的搜索页/详情页 HTML
│   ├── test_matcher.py
│   ├── test_douban_parser.py
│   ├── test_excel_store.py
│   └── test_resume.py
├── inputs/queries.example.csv
├── outputs/.gitkeep
├── artifacts/.gitkeep          # 失败截图、HTML 快照；不提交真实运行产物
├── browser-profile/.gitkeep    # 独立浏览器用户目录；内容不提交
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

### 4.2 组件职责

| 组件 | 输入 | 输出 | 责任边界 |
|---|---|---|---|
| CLI | 参数、CSV 路径 | 退出码 | 参数校验、启动 runner，不包含站点逻辑 |
| Runner | Task 列表 | Result 流 | 串行调度、节流、状态机、断点续跑 |
| BrowserSession | 浏览器配置 | Chromium/Tab | 生命周期、独立用户目录、截图、最小 HTML 快照 |
| DoubanMovieAdapter | query | candidates/result | 只负责豆瓣页面动作与解析 |
| Matcher | query/candidates | MatchDecision | 确定性选择；不访问网页 |
| Optional LLM Matcher | 最小候选文本 | MatchDecision | 只在歧义时调用 MiniMax；不得直接操作浏览器 |
| ExcelStore | Result | `.xlsx` | 幂等 upsert、列顺序、原子保存 |

### 4.3 数据流

```text
queries.csv
    │
    ▼
CSV 校验 ──失败──> 明确退出，不启动浏览器
    │
    ▼
按 task_id 查询现有 Excel ──终态且未指定重跑──> 跳过
    │
    ▼
浏览器输入并搜索 → 候选列表 → 确定性匹配
                                  │
                   唯一匹配 ─────┤───── 歧义
                       │          │          │
                       │          │   MiniMax 已启用？
                       │          │      │是      │否/失败
                       │          │      ▼        ▼
                       │          │   LLM 排序  REVIEW_REQUIRED
                       ▼          ▼
                    详情页字段解析
                           │
                           ▼
                  Excel upsert + 原子保存
```

---

## 5. 输入、输出与状态模型

### 5.1 输入 CSV

```csv
query,year
肖申克的救赎,1994
霸王别姬,1993
阿甘正传,1994
```

- `query`：必填，去除首尾空白后不能为空；
- `year`：可选，四位数字；
- UTF-8 with BOM 和 UTF-8 均需支持；
- 重复查询允许存在，用“规范化查询词 + 年份 + 重复序号”生成稳定 `task_id`。

### 5.2 Excel 固定列（MVP）

| 列 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务稳定标识 |
| `query` | string | 原始查询词 |
| `query_year` | string | 输入年份，可空 |
| `matched_title` | string | 匹配后的站点标题 |
| `matched_year` | string | 详情页年份 |
| `director` | string | 多导演用 ` / ` 连接 |
| `rating` | number/blank | 0–10；无评分留空，不写 0 |
| `detail_url` | string | 规范化详情 URL |
| `match_method` | enum | `RULE_EXACT`、`RULE_YEAR`、`LLM`、`NONE` |
| `status` | enum | 见状态表 |
| `error_message` | string | 面向操作者的短错误信息 |
| `collected_at` | ISO-8601 | 含本地时区的采集时间 |

列数、配置、解析器和验收标准统一使用上述 12 列。扩展字段必须同时修改模型、解析器、Excel 表头和测试，不能宣称“只改配置即可”。

### 5.3 状态与重跑规则

| 状态 | 是否默认重跑 | 含义 |
|---|---:|---|
| `SUCCESS` | 否 | 已取得并校验核心字段 |
| `NOT_FOUND` | 否 | 搜索完成但没有候选 |
| `REVIEW_REQUIRED` | 否 | 候选存在但无法可信判断 |
| `NETWORK_ERROR` | 是 | 超时、DNS、连接中断等暂时错误 |
| `PAGE_CHANGED` | 否，修复后显式重跑 | 关键定位器/字段结构变化 |
| `BLOCKED` | 否，整批停止 | 验证码、访问频率提示或 403/418/429 |
| `OUTPUT_LOCKED` | 是 | Excel 被其他程序占用或无法替换 |
| `UNEXPECTED_ERROR` | 是 | 未分类异常，必须保存诊断产物 |

再次运行时，默认重跑 `NETWORK_ERROR`、`OUTPUT_LOCKED` 和 `UNEXPECTED_ERROR`，跳过 `SUCCESS`、`NOT_FOUND`、`REVIEW_REQUIRED`、`PAGE_CHANGED` 和 `BLOCKED`。CLI 提供 `--retry-status` 显式增加需重跑的状态，例如修复定位器后使用 `--retry-status PAGE_CHANGED`。所有状态都采用 upsert，不新增重复行。

---

## 6. 浏览器工作流

### 6.1 启动

- Demo 默认 `headless=false`，方便操作者确认真实浏览器动作；稳定后可通过 `--headless` 切换。
- 使用配置指定或自动发现的本机 Chrome/Edge，并保留浏览器默认 User-Agent，不伪造过期 Chrome UA。
- 一个 batch 复用一个 DrissionPage `Chromium` 实例和一个 Tab；使用独立的 `browser-profile/` 用户数据目录，禁止接管日常浏览器配置。
- 默认 viewport、语言和时区保持运行机器设置；不实现指纹伪装。

### 6.2 单条任务

1. 打开 `https://movie.douban.com/`；
2. 定位搜索输入框，优先使用可访问名称/placeholder，站点 CSS 属性作为短 fallback；
3. 对输入元素调用 `input(query, clear=True)` 后按 Enter 或点击搜索按钮；
4. 等待“结果列表或无结果提示”之一出现，不用 `time.sleep()` 判断页面加载；
5. 解析最多前 5 个电影候选：标题、年份、类型、详情 URL；
6. 执行匹配规则；
7. 唯一可信匹配则打开详情页；否则进入可选 LLM 或人工复核状态；
8. 从详情页解析标题、年份、导演、评分和 URL；
9. 校验并写入 Excel；
10. 达到配置的最小请求间隔后处理下一条。

定位器初始候选需在实施阶段用 DrissionPage 有头模式和元素树检查对当前页面确认，并固化到 `douban_movie.py` 与 HTML fixture。不要把搜索结果第一项作为默认答案。

### 6.3 详情页初始解析契约

以下是实现起点，必须由受控冒烟测试确认后才能视为有效：

| 字段 | 首选定位器/解析方式 |
|---|---|
| 标题 | `h1 span[property="v:itemreviewed"]` |
| 年份 | `h1 .year`，去除括号 |
| 导演 | `#info a[rel="v:directedBy"]`，多个连接 |
| 评分 | `strong[property="v:average"]`，空文本表示暂无评分 |
| URL | 当前页面 URL，必须匹配 `https://movie.douban.com/subject/<数字>/` |

任一非核心字段缺失不应让整条失败。核心字段定义为标题和规范化详情 URL；评分允许为空。

### 6.4 匹配规则

按顺序执行：

1. 标准化：Unicode NFKC、转小写、移除首尾空白、合并连续空格；保留中文和字母数字；
2. 标题完全相等且只有一个候选：`RULE_EXACT`；
3. 多个标题完全相等，且输入年份与其中一个候选年份唯一相等：`RULE_YEAR`；
4. 不满足以上条件：进入可选 LLM；
5. LLM 未启用、失败、低置信度或输出不合法：`REVIEW_REQUIRED`。

不使用“评分最高”选择电影，因为评分与查询意图没有可靠因果关系。

---

## 7. MiniMax LLM 可选扩展

### 7.1 使用边界

LLM **不负责浏览器控制和字段提取**，只对最多 5 个候选做排序。这样可以控制费用、数据暴露和不可预测操作。

发送给 MiniMax 的内容仅包括：查询词、可选年份、候选标题、候选年份和候选类型。不发送 Cookie、API Key、完整页面 HTML、用户信息或评论内容。

### 7.2 接口

MiniMax 官方提供 OpenAI API 兼容接口，可通过 `OPENAI_BASE_URL=https://api.minimax.io/v1` 调用。实现使用独立环境变量，避免与其他 OpenAI 兼容服务冲突：

```dotenv
MINIMAX_API_KEY=
MINIMAX_BASE_URL=https://api.minimax.io/v1
MINIMAX_MODEL=MiniMax-M2.7
```

API Key 只能在本地服务端进程读取，不能写入代码、Excel、日志、截图或 Git。模型名必须配置化，并可通过模型列表接口核对，因为可用模型会变化。

参考：[MiniMax API Overview](https://platform.minimax.io/docs/api-reference/api-overview)、[OpenAI Compatible API](https://platform.minimax.io/docs/api-reference/text-openai-api)、[API Key 安全说明](https://platform.minimax.io/docs/faq/about-apis)。

### 7.3 输出契约

LLM 必须返回可校验 JSON：

```json
{
  "chosen_index": 0,
  "confidence": 0.91,
  "reason": "标题一致且年份匹配"
}
```

接受条件：

- `chosen_index` 必须指向现有候选；
- `confidence >= 0.85`；
- 候选标题与查询词至少有可解释的文本相似性；
- 超时 10 秒，最多调用一次，不自动重试消费；
- 任一校验失败均返回 `REVIEW_REQUIRED`，不猜测。

依赖通过可选 extra 安装，例如 `pip install -e ".[llm]"`；基础安装不包含 OpenAI SDK。

---

## 8. 登录状态、安全与合规

### 8.1 登录状态

MVP 首先验证公开页面，不假设登录必需，也不宣称登录能“突破限制”。确需登录时：

1. 运行 `python -m app.main login --headed`；
2. 用户在打开的浏览器中自行登录；
3. 用户确认后关闭浏览器；登录状态保存在项目专用 `browser-profile/douban/` 用户目录；
4. 正常任务复用该专用目录启动，不读取系统 Chrome/Edge 的日常用户目录。

`browser-profile/` 必须加入 `.gitignore`，仅保留 `.gitkeep`。用户目录可能包含可冒用账号的 Cookie 和 token，不允许通过聊天、邮件或工单传播。

### 8.2 站点保护与停止策略

- 默认串行，最小查询间隔配置为 5 秒；这只是保守节流基线，不代表站点授权。
- 网络超时最多重试 2 次，退避 2 秒、5 秒。
- `NOT_FOUND`、`PAGE_CHANGED`、验证码和限流不得盲目重试。
- 检测到验证码、访问频率提示或 403/418/429：写入 `BLOCKED`，保存一次脱敏截图和最小 HTML 快照，立即关闭 batch。
- 不加入 stealth 插件、代理池、验证码识别、Cookie 轮换或其他规避措施。

### 8.3 上线前合规门禁

豆瓣现行协议允许其设置服务次数/时间限制，并禁止干扰正常运营、未经授权收集或不当使用数据；版权声明也约束对站点服务和数据的使用。因此进入真实批量运行前，项目负责人必须记录：

- 使用目的和责任人；
- 目标字段是否属于公开信息；
- 是否获得必要授权；
- 请求频率和单批上限；
- 数据保存期限、访问范围和删除方式；
- 目标站协议或政策变化的复核日期。

参考：[豆瓣使用协议](https://www.douban.com/about/agreement)、[豆瓣版权声明](https://www.douban.com/about/copyright)。本节是工程门禁，不构成法律意见。

---

## 9. 可靠性与可观测性

### 9.1 Excel 幂等与断点续跑

- 启动时读取已有输出，建立 `task_id -> row` 索引；
- 同一 `task_id` 使用 upsert 更新，不追加重复行；
- 每完成一条，将工作簿保存到同目录临时文件，成功后用 `os.replace()` 原子替换目标文件；
- 输出文件被 Excel 占用时返回 `OUTPUT_LOCKED`，保留临时文件并停止，避免数据丢失；
- 重跑状态遵循 5.3 节的统一规则；`--retry-status` 只用于显式增加状态，不改变 upsert 语义。

### 9.2 日志与诊断产物

使用标准库 `logging`，控制台和 `artifacts/run-<timestamp>.log` 同时输出：

- run_id、task_id、阶段、状态、耗时；
- 不记录 API Key、Cookie、完整浏览器用户目录或请求头；
- 页面异常保存 `task_id.png` 和经最小化、脱敏的 `task_id.html`；
- 正常成功不截图，减少敏感数据和磁盘占用；
- 诊断产物默认保存 7 天，由 README 提供清理命令。

### 9.3 进程退出码

| 退出码 | 含义 |
|---:|---|
| 0 | 所有任务已处理，允许存在 `NOT_FOUND/REVIEW_REQUIRED` |
| 2 | 输入或配置错误 |
| 3 | 被站点验证/限流阻断 |
| 4 | 输出文件无法保存 |
| 5 | 浏览器启动或全局未预期错误 |

---

## 10. 配置与运行命令

MVP 使用 CLI 参数和环境变量，不引入 YAML、loguru、tenacity、python-dotenv。`.env.example` 只作为变量名说明；若后续需要自动加载 `.env`，再引入 `python-dotenv`。

### 10.1 基础依赖

```toml
[project]
requires-python = ">=3.11,<3.13"
dependencies = [
  "DrissionPage>=4.1.1,<4.2",
  "openpyxl>=3.1,<4"
]

[project.optional-dependencies]
dev = ["pytest>=8,<9", "pytest-cov>=5,<7"]
llm = ["openai>=1,<3"]
```

实施时生成锁文件或使用 constraints 固定已验证版本；Spec 不锁死未经本机验证的精确补丁版本。

### 10.2 安装与运行

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m app.main run `
  --input .\inputs\queries.example.csv `
  --output .\outputs\douban_movies.xlsx `
  --headed
```

启用 MiniMax：

```powershell
python -m pip install -e ".[dev,llm]"
$env:MINIMAX_API_KEY="在本机安全设置，不写入脚本"
$env:MINIMAX_BASE_URL="https://api.minimax.io/v1"
$env:MINIMAX_MODEL="MiniMax-M2.7"
python -m app.main run --input .\inputs\queries.example.csv --output .\outputs\douban_movies.xlsx --headed --llm-match
```

---

## 11. 实施计划

### 阶段 0：环境与页面侦察（0.5 天）

- [ ] 建立项目目录、虚拟环境、`pyproject.toml` 和 `.gitignore`；
- [ ] 检测本机 Chrome/Edge 路径，安装 DrissionPage，运行最小有头启动脚本；
- [ ] 用 DrissionPage 有头模式和元素树检查确认当前搜索框、候选和详情字段；
- [ ] 保存脱敏 HTML fixture，并记录页面检查日期；
- [ ] 用 1 个电影名人工确认公开页面是否满足字段需求。

**退出条件**：可见浏览器能完成一次搜索，定位器已通过受控元素树检查验证；若站点要求验证或不允许当前访问，停止项目而非继续开发绕过方案。

### 阶段 1：最小闭环（1 天）

- [ ] CSV 校验和 Task 模型；
- [ ] BrowserSession 生命周期；
- [ ] 豆瓣搜索输入、候选解析、详情解析；
- [ ] 确定性匹配规则；
- [ ] Excel 12 列写入和原子保存；
- [ ] 1 条成功、1 条无结果的手工冒烟测试。

**验收**：输入 2 条，Excel 恰好 2 行；成功条包含核心字段，无结果条为 `NOT_FOUND`。

### 阶段 2：可靠性（1 天）

- [ ] 错误分类、有限重试、退出码；
- [ ] task_id upsert 和断点续跑；
- [ ] `BLOCKED` 检测与整批停止；
- [ ] 失败截图、最小 HTML 快照和日志脱敏；
- [ ] 单元测试和 Excel round-trip 测试。

**验收**：10 条固定输入运行后强制中断，再次运行不重复 `SUCCESS`；页面 fixture 测试和 Excel 测试全部通过。

### 阶段 3：可选 MiniMax 匹配（0.5 天）

- [ ] 独立 `llm` extra 与环境变量检查；
- [ ] 最小候选 JSON、结构化输出校验、10 秒超时；
- [ ] 使用 mock 测试合法、低置信度、超时和非法 JSON；
- [ ] 实测前确认 API 计费和数据使用要求。

**验收**：没有 Key 时主流程不受影响；模拟 LLM 失败时产生 `REVIEW_REQUIRED`；不会将 Key 写入任何产物。

### 阶段 4：50 条受控验证（0.5 天 + 运行时间）

- [ ] 经合规门禁确认后运行 50 条；
- [ ] 记录成功、无结果、需复核、技术失败和阻断数量；
- [ ] 根据实测形成耗时/稳定性基线；
- [ ] 决定是否允许 200 条批量运行。

**退出条件**：只有在无阻断且数据质量可接受时，才评估扩大批次；不把扩大规模作为 Demo 完成条件。

---

## 12. 测试与验收清单

### 12.1 自动测试

- [ ] 标题标准化：中英文、全半角、大小写、连续空格；
- [ ] 唯一精确匹配、多同名年份匹配、歧义匹配；
- [ ] 无候选、评分为空、多导演、详情 URL 非法；
- [ ] Excel 新建、upsert、不重复、临时文件替换；
- [ ] 断点续跑和 `--retry-status`；
- [ ] fixture 中关键 selector 缺失时返回 `PAGE_CHANGED`；
- [ ] LLM 关闭、超时、非法 JSON、低置信度；
- [ ] 日志中不出现测试 API Key 和测试 Cookie。

目标：纯逻辑和解析模块语句覆盖率不低于 80%；浏览器端到端测试不以覆盖率衡量。

### 12.2 受控端到端测试

- [ ] 1 条明确电影成功；
- [ ] 1 条不存在查询为 `NOT_FOUND`；
- [ ] 1 条同名/歧义查询为规则匹配或 `REVIEW_REQUIRED`；
- [ ] 中途关闭进程后可续跑；
- [ ] 打开输出 Excel 占用文件时明确报 `OUTPUT_LOCKED`；
- [ ] MiniMax 未配置时无需安装 `openai` 也可运行；
- [ ] 若出现验证码/限流，程序停止且不自动绕过。

### 12.3 文档验收

- [ ] README 包含安装、运行、登录状态、MiniMax 可选配置、故障排查和安全说明；
- [ ] 新环境严格复制 README 命令可完成安装；
- [ ] 示例 CSV 不含真实敏感数据；
- [ ] `.gitignore` 覆盖 `.env`、`browser-profile/`、`outputs/`、`artifacts/`。

---

## 13. 风险与决策门槛

| 风险 | 早期信号 | 处理 |
|---|---|---|
| 目标站协议或授权不允许 | 合规复核无法通过 | 不运行真实批量任务；改用已授权测试站点演示框架 |
| 验证码/限流 | 验证页、403/418/429 | 立即停止，不绕过；降低规模需先确认站点规则 |
| 页面改版 | fixture/冒烟测试 selector 失败 | 返回 `PAGE_CHANGED`，用 Inspector 更新适配器和 fixture |
| 搜索结果误匹配 | 同名、多版本、外文名 | 精确规则 + 年份；否则人工复核，可选 MiniMax 只做建议 |
| LLM 误判或服务失败 | 低置信度、非法 JSON、超时 | 不影响主流程，降级 `REVIEW_REQUIRED` |
| API Key 泄漏 | 日志/配置检查命中 | 立即撤销 Key；Key 仅从环境变量读取并做日志脱敏 |
| Excel 被占用 | `os.replace` 失败 | 返回 `OUTPUT_LOCKED`，不覆盖原文件，提示关闭 Excel 后重跑 |
| 200 条规模不稳定 | 50 条基线出现阻断或错误上升 | 不扩大批次，先评估授权、频率和站点适配稳定性 |

---

## 14. Demo 完成定义（Definition of Done）

以下条件全部满足，才可称为“可落地 Demo”：

- [ ] 阶段 0–2 完成，阶段 3 MiniMax 为可选；
- [ ] 自动测试通过，覆盖率达到约定；
- [ ] 固定 10 条受控输入生成结构正确的 `.xlsx`；
- [ ] 每个输入都有唯一 Excel 行和明确状态；
- [ ] 断点续跑、输出占用、页面变化和阻断场景均有验证证据；
- [ ] 无 API Key、Cookie 或 browser-profile 数据泄漏；
- [ ] DrissionPage 使用场景为非商业用途，或已有版权方商业授权记录；
- [ ] 合规门禁已有负责人确认记录；
- [ ] 新成员按照 README 在 30 分钟内跑通 2 条冒烟输入；
- [ ] 实测记录包含环境、日期、输入规模、各状态数量和总耗时。

完成 Demo 后，再根据 50 条实测结果决定是否增加 200 条批量、定时运行、第二站点适配器或 LLM Agent。不得在缺少实际数据时提前把这些扩展纳入 MVP。

---

## 15. 实施前只需确认的事项

1. 合规负责人确认豆瓣作为真实 Demo 目标站是否可用；否则换成已授权测试站点，但架构不变。
2. 确认首轮 10 条测试电影及其中至少 1 条同名/歧义样本。
3. MiniMax 功能默认关闭；只有阶段 1–2 通过后才启用。
4. API Key 由操作者在本机环境变量中设置，不写入任何项目文件。
5. DrissionPage 仅用于非商业用途；如项目用途改变，先取得版权方商业授权再继续。
