# 任务 5：实现稳定 JSON 与自包含静态画廊

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-05-json-gallery.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：feat: add product workbook output。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格执行本文件中的 RED → verify RED → GREEN → focused verify → full verify → commit 顺序。文件编辑使用 apply_patch。只允许修改文件小节列出的文件；不得安装或升级依赖，不得 amend、reset、force push，不得修改或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

本任务严格离线：不得启动浏览器，不得访问 web-scraping.dev、豆瓣或其他外网，不得传入 --live-approved。

提交前运行 git diff --check，并确认 git diff --name-only 只含本任务允许文件。除非本任务明确说明不需要提交，commit message 必须精确为：feat: render product json and gallery

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-05-json-gallery
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
- 前置提交：`feat: add product workbook output`。
- 本任务提交：`feat: render product json and gallery`。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


**文件：**

- 新建：`app/product_json.py`
- 新建：`app/product_gallery.py`
- 新建：`tests/test_product_json.py`
- 新建：`tests/test_product_gallery.py`

- [ ] **步骤 1：写 JSON 快照失败测试**

创建 `tests/test_product_json.py`：

```python
import json

from app.product_json import render_product_json
from app.product_models import ProductCollection, ProductRecord


def test_json_snapshot_has_stable_schema_and_summary() -> None:
    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    payload = json.loads(render_product_json(collection))
    assert payload["schema_version"] == 1
    assert payload["source_site"] == "web-scraping.dev"
    assert payload["summary"] == {
        "total": 1,
        "success": 1,
        "partial": 0,
        "failed": 0,
    }
    assert payload["products"][0]["product_id"] == "1"
```

- [ ] **步骤 2：写画廊结构和安全失败测试**

创建 `tests/test_product_gallery.py`：

```python
from dataclasses import replace

from app.product_gallery import render_gallery
from app.product_models import ProductCollection, ProductRecord


def gallery() -> str:
    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    return render_gallery(collection)


def test_gallery_is_self_contained_and_has_required_controls() -> None:
    page = gallery()
    assert '<input id="search"' in page
    assert '<select id="category-filter"' in page
    assert '<select id="status-filter"' in page
    assert '<select id="price-sort"' in page
    assert 'id="product-grid"' in page
    assert 'id="evidence-panel"' in page
    assert "function renderProducts()" in page
    assert "function selectProduct(productId)" in page


def test_gallery_embeds_data_without_external_script_or_font_dependencies() -> None:
    page = gallery()
    assert '<script src=' not in page
    assert '@import url(' not in page
    assert 'fetch(' not in page
    assert '"product_id": "1"' in page


def test_gallery_escapes_product_content_before_embedding() -> None:
    dangerous = ProductRecord.success_fixture("1")
    dangerous = replace(
        dangerous,
        name="</script><script>alert(1)</script>",
    )
    collection = ProductCollection.from_records(
        [dangerous],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    page = render_gallery(collection)
    assert "</script><script>alert(1)</script>" not in page
    assert "\\u003c/script\\u003e" in page
```

- [ ] **步骤 3：运行测试确认缺少渲染器**

```powershell
python -m pytest tests/test_product_json.py tests/test_product_gallery.py -q
```

预期：缺少两个模块。

- [ ] **步骤 4：实现 JSON 渲染器**

创建 `app/product_json.py`：

```python
def product_payload(collection: ProductCollection) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_site": "web-scraping.dev",
        "generated_at": collection.generated_at,
        "summary": {
            "total": collection.summary.total,
            "success": collection.summary.success,
            "partial": collection.summary.partial,
            "failed": collection.summary.failed,
        },
        "products": [record.to_primitive() for record in collection.records],
    }


def render_product_json(collection: ProductCollection) -> str:
    return json.dumps(
        product_payload(collection),
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    ) + "\n"
```

- [ ] **步骤 5：实现画廊渲染器**

创建 `app/product_gallery.py`，返回完整 `<!doctype html>` 文档。

页面必须包含：

- CSS 变量和响应式布局；
- 五个摘要卡片：总数、成功、部分成功、失败、生成时间；
- 搜索框、分类筛选、状态筛选、价格排序；
- 商品卡片网格；
- 右侧采集证据面板；
- 根据分类和商品名称生成的内置 CSS/SVG 视觉封面；
- 原生 JS 的 `renderProducts()`、`selectProduct()`、
  `applyFilters()` 和 `formatMoney()`。

嵌入 JSON 时必须执行：

```python
embedded = json.dumps(
    product_payload(collection),
    ensure_ascii=False,
).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
```

JS 行为固定为：

- 首次加载显示全部商品并选中第一项。
- 搜索对名称、品牌和描述做小写包含匹配。
- 分类和状态使用精确匹配。
- 价格为空的记录排序到末尾。
- 点击卡片通过 `product_id` 更新证据侧栏。
- 卡片不使用远程 `primary_image_url` 作为 `img src`；
  `visualFor(product)` 根据分类和名称返回稳定的本地渐变、图标和首字母。
- `primary_image_url` 只在证据侧栏作为可复制文本展示。
- 来源链接使用 `target="_blank"` 和 `rel="noopener noreferrer"`。
- 不调用 `fetch()`、XHR、WebSocket 或任何外部脚本。

- [ ] **步骤 6：运行 JSON 和画廊测试**

```powershell
python -m pytest tests/test_product_json.py tests/test_product_gallery.py -q
```

预期：全部通过。

- [ ] **步骤 7：提交报告渲染**

```powershell
git add app/product_json.py app/product_gallery.py tests/test_product_json.py tests/test_product_gallery.py
git commit -m "feat: render product json and gallery"
```
