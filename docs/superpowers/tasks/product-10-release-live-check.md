# 任务 10：最终离线发布验证与可选受控现场验收

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-10-release-live-check.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：docs: add product collection gallery runbook。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格按本文件的离线发布门禁 → tracked 产物审计 → 条件式 live gate → 输出包验证
顺序执行。本任务不编辑任何文件，不安装或升级依赖，不得 amend、reset、force push，
不得暂存或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

先完成全部离线门禁。真实 web-scraping.dev 运行是条件步骤：只有操作者在本次执行中再次明确批准后，才可使用 --live-approved --max-products 1..10 --headed --min-interval 2；否则记录 SKIPPED，不得把历史批准当作本次授权。遇到 429、阻断、登录/安全检查、挑战或站外跳转立即停止。

本任务是验证任务，不修改源码、测试或文档，也不创建提交。结束前运行
git diff --check，并确认没有新增 tracked 修改；commit 必须报告 none。

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-10-release-live-check
- preflight: <前置提交与初始状态>
- offline_gates: <每条命令、退出码与结果>
- artifact_audit: <tracked 产物检查结果>
- bundle_verify: <命令与结果；未获 live 授权时写 SKIPPED_NOT_APPROVED>
- changed: <逐行文件列表>
- commit: <短 SHA + message；无提交时写 none>
- live: NOT_RUN | SKIPPED_NOT_APPROVED | APPROVED_AND_RUN | STOPPED_ON_PROTECTION
- concerns: <无则写 none>

任何门禁失败都保留现场并报告，不得猜测、伪造绿色结果或扩大范围。
```

## Base / 前置条件

- 仓库根目录：`D:\DataAnt`。
- 批准设计：`docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md`。
- 前置提交：`docs: add product collection gallery runbook`。
- 本任务提交：无；验证失败时返回 `NOT_READY`，修复必须回到对应的 Product 00–09 任务。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


**文件：**

- 验证：全仓库
- 运行时输出：`outputs/web-scraping-dev-demo/`（忽略，不提交）
- 浏览器 profile：`browser-profile/web-scraping-dev/`（忽略，不提交）
- 诊断：`artifacts/`（忽略，不提交）

- [ ] **步骤 1：运行最终离线发布门禁**

```powershell
python -m pytest --cov=app --cov-report=json:coverage.json --cov-report=term-missing -q
python -m scripts.verify_core --coverage-json coverage.json
python -m scripts.browser_smoke
python -m pip check
git diff --check
git status --short
```

预期：

- 所有测试通过；
- 核心覆盖率门禁通过；
- `BROWSER_SMOKE_OK`；
- 无依赖冲突和空白错误；
- `git status` 只显示本轮预期文件或已忽略运行时产物。

- [ ] **步骤 2：确认禁止的 tracked 产物为空**

```powershell
git ls-files browser-profile outputs artifacts .superpowers
```

预期：

```text
artifacts/.gitkeep
browser-profile/.gitkeep
outputs/.gitkeep
```

`.superpowers/` 不应有 tracked 文件。

- [ ] **步骤 3：仅在操作者再次明确批准时运行真实网站**

本计划、设计批准或历史授权都不等于本次真实联网授权。
只有操作者在执行时明确要求 live run，才运行：

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

现场要求：

- 浏览器必须可见；
- 确认列表发现跨至少两页；
- 不主动打开任何范围外页面；
- 遇到 429、阻断、登录、安全检查、挑战或站外跳转立即停止；
- 不降低间隔，不增加商品上限，不自动重试阻断状态。

- [ ] **步骤 4：若已获授权且运行成功，验证输出包**

```powershell
python -m scripts.verify_products `
  --output-dir .\outputs\web-scraping-dev-demo
```

预期：

- 商品数量为 1 到 10；
- ID 唯一；
- Excel、JSON、HTML 数量和顺序一致；
- HTML 无自动网络依赖。

- [ ] **步骤 5：人工验收画廊**

打开：

```text
outputs/web-scraping-dev-demo/gallery.html
```

确认：

- 顶部摘要与 JSON 一致；
- 商品图片、名称、价格和状态可读；
- 搜索、筛选和排序正常；
- 证据侧栏显示来源 URL、ID、状态和采集时间；
- `PARTIAL` 或失败记录显示原因；
- 页面加载后不自动访问目标站。

- [ ] **步骤 6：最终状态确认**

只有离线门禁全部通过后：

```powershell
git status --short
git log --oneline -10
```

确认没有运行时文件进入暂存区，也没有新增 tracked 修改：

```powershell
$TrackedChanges = git status --short | Where-Object {
    $_ -notmatch '^\?\? (\.codex-tmp/|\.planning/|browser_bot_demo\.egg-info/)'
}
if ($TrackedChanges) {
    $TrackedChanges
    throw 'NOT_READY: tracked changes exist after verification'
}
"PRODUCT_RELEASE_READY"
```

预期：打印 `PRODUCT_RELEASE_READY`。本任务不提交；任何失败都返回 `NOT_READY`
并指出应回到 Product 00–09 中哪个任务修复。
