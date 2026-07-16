# 任务 9：完成 README、帮助文本和离线交付验证

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-09-readme-delivery.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：test: verify offline product output contract。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格执行本文件中的 RED → verify RED → GREEN → focused verify → full verify → commit 顺序。文件编辑使用 apply_patch。只允许修改文件小节列出的文件；不得安装或升级依赖，不得 amend、reset、force push，不得修改或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

本任务严格离线：不得访问 web-scraping.dev、豆瓣或其他外网，不得传入 --live-approved。
仅允许为了人工检查 fixture 生成的本地 gallery.html 而打开浏览器；打开前断开网络或使用
开发者工具确认页面没有自动网络请求。

提交前运行 git diff --check，并确认 git diff --name-only 只含本任务允许文件。除非本任务明确说明不需要提交，commit message 必须精确为：docs: add product collection gallery runbook

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-09-readme-delivery
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
- 前置提交：`test: verify offline product output contract`。
- 本任务提交：`docs: add product collection gallery runbook`。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


**文件：**

- 修改：`README.md`
- 修改：`tests/test_project_config.py`
- 修改：`pyproject.toml`（仅在包发现测试表明新模块未安装时）

- [ ] **步骤 1：写 README 契约测试**

在 `tests/test_project_config.py` 增加：

```python
def test_readme_documents_product_collection_gate_and_gallery() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    for required in (
        "collect-products",
        "--max-products",
        "--min-interval 2",
        "products.xlsx",
        "products.json",
        "gallery.html",
        "web-scraping.dev",
        "/robots-disallowed",
    ):
        assert required in readme
```

- [ ] **步骤 2：更新 README**

新增独立章节，包含：

1. 第二站点用途和练习平台性质；
2. 明确的允许/禁止路径；
3. 可复制命令：

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

4. 三个输出文件的说明；
5. 双击或浏览器打开 `gallery.html` 的说明；
6. 搜索、分类筛选、状态筛选、价格排序和证据侧栏；
7. `SUCCESS`、`PARTIAL`、`PAGE_CHANGED`、`NETWORK_ERROR`、
   `BLOCKED`、`UNEXPECTED_ERROR` 的处置；
8. 遇到 429、挑战、登录或站外跳转立即停止；
9. CI 只做离线 fixture 测试；
10. 输出、profile、日志和诊断文件不进入 Git。

- [ ] **步骤 3：验证安装后的模块发现**

运行：

```powershell
python -c "from app.product_runner import ProductRunner; from app.sites.web_scraping_dev import WebScrapingDevAdapter; print('PRODUCT_IMPORT_OK')"
python -m app.main collect-products --help
```

预期：

- 打印 `PRODUCT_IMPORT_OK`；
- 帮助输出包含全部八个商品参数；
- 不启动浏览器。

如果 editable install 无法导入新增模块，再将 `pyproject.toml` 从显式
`packages = ["app", "app.sites"]` 改为 setuptools package discovery：

```toml
[tool.setuptools.packages.find]
include = ["app*"]
```

随后重新运行导入测试。

- [ ] **步骤 4：运行全量离线测试和覆盖率**

```powershell
python -m pytest --cov=app --cov-report=json:coverage.json --cov-report=term-missing -q
python -m scripts.verify_core --coverage-json coverage.json
python -m pip check
git diff --check
```

预期：

- 全部测试通过；
- 五个覆盖率门禁模块均达到 80%；
- `pip check` 无依赖冲突；
- `git diff --check` 无错误。

- [ ] **步骤 5：生成完全离线的演示包用于验证**

在测试临时目录使用 fixture 和 `ProductOutputBundle` 生成演示包，不访问真实网站：

```powershell
python -m pytest tests/test_product_output_bundle.py tests/test_product_gallery.py -q
```

随后通过测试中生成的临时文件验证结构；不要把临时输出复制到 Git 跟踪目录。

- [ ] **步骤 6：人工打开静态画廊**

使用由 fixture 构造的本地 `gallery.html`，人工检查：

- 商品卡片响应式排列；
- 搜索、分类和状态筛选；
- 价格升降序；
- 点击卡片后证据侧栏更新；
- 每张卡片显示稳定的本地视觉封面；
- 页面断网时仍可使用；
- 开发者工具 Network 面板没有自动访问 `web-scraping.dev`。

这一步只验证本地 HTML，不执行真实采集。

- [ ] **步骤 7：提交文档和交付收口**

```powershell
git add README.md tests/test_project_config.py pyproject.toml
git commit -m "docs: add product collection gallery runbook"
```

只在 `pyproject.toml` 实际发生修改时将其加入提交。
