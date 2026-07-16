# 任务 2：实现 web-scraping.dev URL 和页面解析契约

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-02-site-adapter.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：refactor: add shared site errors and product models。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格执行本文件中的 RED → verify RED → GREEN → focused verify → full verify → commit 顺序。文件编辑使用 apply_patch。只允许修改文件小节列出的文件；不得安装或升级依赖，不得 amend、reset、force push，不得修改或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

本任务严格离线：不得启动浏览器，不得访问 web-scraping.dev、豆瓣或其他外网，不得传入 --live-approved。

提交前运行 git diff --check，并确认 git diff --name-only 只含本任务允许文件。除非本任务明确说明不需要提交，commit message 必须精确为：feat: add web scraping dev product adapter

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-02-site-adapter
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
- 前置提交：`refactor: add shared site errors and product models`。
- 本任务提交：`feat: add web scraping dev product adapter`。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


**文件：**

- 新建：`app/sites/web_scraping_dev.py`
- 新建：`tests/test_web_scraping_dev.py`
- 新建：`tests/fixtures/wsd_products_page_1.html`
- 新建：`tests/fixtures/wsd_products_page_2.html`
- 新建：`tests/fixtures/wsd_product_detail.html`
- 新建：`tests/fixtures/wsd_product_partial.html`
- 新建：`tests/fixtures/wsd_product_blocked.html`

- [ ] **步骤 1：创建最小脱敏 fixture**

`tests/fixtures/wsd_products_page_1.html`：

```html
<main>
  <a class="category" href="/products?category=consumables">consumables</a>
  <div class="product">
    <a href="/product/1"><h3>Box of Chocolate Candy</h3></a>
    <span class="price">24.99</span>
  </div>
  <div class="product">
    <a href="https://web-scraping.dev/product/2?ref=list#top">
      <h3>Dark Red Energy Potion</h3>
    </a>
    <span class="price">4.99</span>
  </div>
  <a rel="next" href="/products?page=2">2</a>
</main>
```

`tests/fixtures/wsd_products_page_2.html`：

```html
<main>
  <div class="product">
    <a href="/product/2"><h3>Dark Red Energy Potion</h3></a>
  </div>
  <div class="product">
    <a href="/product/3"><h3>Teal Energy Potion</h3></a>
  </div>
</main>
```

`tests/fixtures/wsd_product_detail.html`：

```html
<main>
  <nav><a href="/products?category=consumables">consumables</a></nav>
  <h3>Box of Chocolate Candy</h3>
  <section class="gallery">
    <img src="/assets/products/1.webp" alt="Box of Chocolate Candy">
  </section>
  <section>
    <h4>Description</h4>
    <p>Chocolate assortment with orange and cherry fillings.</p>
  </section>
  <span class="price">$9.99</span>
  <span class="price-original">from $12.99</span>
  <section>
    <h3>Variants</h3>
    <a href="/product/1?variant=orange-small">orange, small</a>
    <a href="/product/1?variant=orange-medium">orange, medium</a>
  </section>
  <table class="features">
    <tr><th>brand</th><td>ChocoDelight</td></tr>
  </table>
</main>
```

`tests/fixtures/wsd_product_partial.html`：

```html
<main>
  <h3>Plain Energy Potion</h3>
  <section><h4>Description</h4><p>Simple energy drink.</p></section>
  <span class="price">$4.99</span>
  <section><h3>Variants</h3></section>
</main>
```

`tests/fixtures/wsd_product_blocked.html`：

```html
<main>
  <h1>Access blocked</h1>
  <p>Too many requests. Please retry later.</p>
</main>
```

- [ ] **步骤 2：写 URL、列表和详情失败测试**

创建 `tests/test_web_scraping_dev.py`，至少覆盖：

```python
from decimal import Decimal
from pathlib import Path

import pytest

from app.product_models import ProductListing, ProductStatus
from app.site_errors import BlockedError, NetworkError, PageChangedError
from app.sites.web_scraping_dev import WebScrapingDevAdapter


FIXTURES = Path(__file__).parent / "fixtures"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_canonical_product_url_accepts_only_numeric_product_paths() -> None:
    adapter = WebScrapingDevAdapter()
    assert adapter.canonical_product_url("/product/1?ref=list#top") == (
        "https://web-scraping.dev/product/1"
    )
    with pytest.raises(ValueError, match="product URL"):
        adapter.canonical_product_url("https://example.com/product/1")
    with pytest.raises(ValueError, match="product URL"):
        adapter.canonical_product_url("/robots-disallowed")


def test_parse_product_page_preserves_order_and_next_page() -> None:
    page = WebScrapingDevAdapter.parse_products_html(
        html("wsd_products_page_1.html"),
        "https://web-scraping.dev/products",
    )
    assert [item.product_id for item in page.listings] == ["1", "2"]
    assert page.next_url == "https://web-scraping.dev/products?page=2"


def test_parse_detail_extracts_required_and_optional_fields() -> None:
    listing = ProductListing(
        "1", "https://web-scraping.dev/product/1", "consumables"
    )
    record = WebScrapingDevAdapter.parse_detail_html(
        html("wsd_product_detail.html"),
        listing,
        listing.product_url,
    )
    assert record.status is ProductStatus.SUCCESS
    assert record.name == "Box of Chocolate Candy"
    assert record.current_price == Decimal("9.99")
    assert record.original_price == Decimal("12.99")
    assert record.primary_image_url.endswith("/assets/products/1.webp")
    assert record.brand == "ChocoDelight"
    assert record.variant_count == 2


def test_missing_optional_fields_returns_partial() -> None:
    listing = ProductListing(
        "4", "https://web-scraping.dev/product/4", "consumables"
    )
    record = WebScrapingDevAdapter.parse_detail_html(
        html("wsd_product_partial.html"),
        listing,
        listing.product_url,
    )
    assert record.status is ProductStatus.PARTIAL
    assert "image" in record.error_message
    assert "brand" in record.error_message


@pytest.mark.parametrize(
    "body",
    [
        "<main><span class='price'>$9.99</span></main>",
        "<main><h3>Product</h3></main>",
        "<main><h3>Product</h3><span class='price'>not-money</span></main>",
    ],
)
def test_missing_required_detail_contract_is_page_changed(body: str) -> None:
    listing = ProductListing(
        "8", "https://web-scraping.dev/product/8", ""
    )
    record = WebScrapingDevAdapter.parse_detail_html(
        body, listing, listing.product_url
    )
    assert record.status is ProductStatus.PAGE_CHANGED


def test_blocked_page_is_detected_before_parsing() -> None:
    assert WebScrapingDevAdapter.is_blocked(
        html("wsd_product_blocked.html"), 200, "https://web-scraping.dev/blocked"
    )
    assert WebScrapingDevAdapter.is_blocked("", 429, "https://web-scraping.dev/products")
```

- [ ] **步骤 3：运行解析测试确认失败**

运行：

```powershell
python -m pytest tests/test_web_scraping_dev.py -q
```

预期：缺少 `app.sites.web_scraping_dev`。

- [ ] **步骤 4：实现纯解析和 URL 白名单**

创建 `app/sites/web_scraping_dev.py`，公开接口固定为：

```python
class WebScrapingDevAdapter:
    BASE_URL = "https://web-scraping.dev"
    PRODUCTS_URL = "https://web-scraping.dev/products"

    @staticmethod
    def canonical_product_url(url: str) -> str:
        """Return the canonical allowed product URL or raise ValueError."""

    @staticmethod
    def canonical_products_url(url: str) -> str:
        """Return an allowed /products pagination URL or raise ValueError."""

    @staticmethod
    def is_blocked(html: str, status_code: int | None, url: str) -> bool:
        """Detect 429, block text, login/challenge paths, and external redirects."""

    @classmethod
    def parse_products_html(cls, html: str, page_url: str) -> ProductPage:
        """Parse ordered product listings and the canonical next-page URL."""

    @classmethod
    def parse_detail_html(
        cls,
        html: str,
        listing: ProductListing,
        final_url: str,
    ) -> ProductRecord:
        """Parse one terminal SUCCESS, PARTIAL, or PAGE_CHANGED record."""

    def fetch_products_page(self, tab, url: str) -> ProductPage:
        """Navigate once, enforce the site boundary, and parse the list page."""

    def fetch_product(
        self,
        tab,
        listing: ProductListing,
    ) -> ProductRecord:
        """Navigate once, enforce the site boundary, and parse the detail page."""
```

实现要求：

- 使用 `urllib.parse.urljoin`、`urlsplit` 和 `urlunsplit` 规范化 URL。
- 商品 URL 正则固定为 `^/product/(\d+)/?$`。
- 分页 URL 只允许路径 `/products`，查询参数只允许 `page`、`category` 和 `sort`。
- `/robots-disallowed`、站外 host、非 HTTPS 和带用户名密码的 URL 直接拒绝。
- 使用 `html.parser.HTMLParser` 收集：
  商品卡片链接、`rel=next`、主标题、描述段落、图片、价格、
  原价、变体链接和特征表。
- 价格先移除 `$`、`from` 和空白，再用 `Decimal` 解析。
- 缺图片、品牌、分类或描述可形成 `PARTIAL`；错误文本按稳定顺序拼接：
  `missing optional fields: category, description, image, brand`。
- 商品 ID、名称、当前价格或规范详情 URL缺失时返回
  `ProductStatus.PAGE_CHANGED`。
- `fetch_products_page()` 和 `fetch_product()` 使用
  `tab.get(url, retry=0, timeout=20)`。
- `tab.get()` 返回假值时抛 `NetworkError`。
- 页面解析前检查最终 `tab.url`；站外跳转、登录、挑战或阻断抛 `BlockedError`。
- DrissionPage `ContextLostError` 和 `PageDisconnectedError` 复用豆瓣策略：
  适配器立即重试一次，第二次仍失败时转换为 `NetworkError`。

- [ ] **步骤 5：补写浏览器访问测试**

在 `tests/test_web_scraping_dev.py` 增加 fake tab，验证：

```python
def test_fetch_products_rejects_external_redirect() -> None:
    tab = LoadedTab(
        html("wsd_products_page_1.html"),
        final_url="https://example.com/products",
    )
    with pytest.raises(BlockedError, match="outside"):
        WebScrapingDevAdapter().fetch_products_page(
            tab, WebScrapingDevAdapter.PRODUCTS_URL
        )


def test_fetch_product_navigation_failure_is_network_error() -> None:
    with pytest.raises(NetworkError, match="navigation failed"):
        WebScrapingDevAdapter().fetch_product(
            NavigationFailureTab(),
            ProductListing("1", "https://web-scraping.dev/product/1", ""),
        )
```

- [ ] **步骤 6：运行适配器测试**

运行：

```powershell
python -m pytest tests/test_web_scraping_dev.py -q
```

预期：全部通过。

- [ ] **步骤 7：提交站点适配器**

```powershell
git add app/sites/web_scraping_dev.py tests/test_web_scraping_dev.py tests/fixtures/wsd_*.html
git commit -m "feat: add web scraping dev product adapter"
```
