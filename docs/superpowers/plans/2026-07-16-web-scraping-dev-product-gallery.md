# web-scraping.dev 商品采集与可视化画廊实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 接入 `web-scraping.dev` 商品列表和详情页，在严格受控的真实联网门禁下采集最多 10 件商品，并从同一标准商品结果集生成 Excel、JSON 和可离线打开的静态 HTML 画廊。

**Architecture:** 保留现有豆瓣电影模型和运行链路不变，新增独立商品领域模型、`WebScrapingDevAdapter`、`ProductRunner` 和输出包。站点适配器只解析允许的 `/products` 与 `/product/<id>` 页面；输出包先在同级暂存目录生成完整的 `products.xlsx`、`products.json` 和 `gallery.html`，再以目录交换提交，确保三个产物对应同一结果集。

**Tech Stack:** Python 3.11、DrissionPage 4.1、`html.parser`、`decimal.Decimal`、openpyxl、原生 HTML/CSS/JavaScript、pytest、pytest-cov。

---

## 前提条件和不变量

- 批准的设计文档：
  `docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md`
- 当前提交基线：`f133b50`。
- 当前离线测试基线原为 164 项；提交 `f133b50` 后，
  `tests/test_project_config.py::test_browser_profile_placeholder_matches_gitignore_rules`
  因新增 `.superpowers/` 忽略规则而出现一项已知失败。任务 0 先恢复绿色基线。
- 不修改 `MovieResult` 的字段语义，不修改 `movies` 工作表 12 列契约。
- 不复用豆瓣 `run` 的 `--max-queries` 作为商品上限。
- `collect-products` 的真实联网必须同时满足：
  `--live-approved`、`--max-products 1..10`、`--headed`、
  `--min-interval >= 2`。
- 只允许访问：
  `https://web-scraping.dev/products`、正常分页 URL、
  `https://web-scraping.dev/product/<digits>`。
- 不访问登录、评论、GraphQL、购物车、文件下载、挑战页面或
  `/robots-disallowed`。
- 遇到 429、阻断页、登录/安全检查、站外跳转或挑战页立即停止。
- CI 始终离线，不启动浏览器，不访问任何真实站点。
- 真实运行产生的 Excel、JSON、HTML、日志、HTML 快照、截图和 profile
  始终位于已忽略目录中。

## 文件结构

### 新建

- `app/site_errors.py`：跨站点共享的访问与页面错误类型。
- `app/product_models.py`：商品候选、商品记录、商品状态和汇总。
- `app/sites/web_scraping_dev.py`：URL 白名单、列表解析、详情解析和浏览器访问。
- `app/product_runner.py`：分页发现、去重、节流、有限重试和停止条件。
- `app/product_excel.py`：商品工作簿读取、合并和序列化。
- `app/product_json.py`：稳定 JSON 快照渲染。
- `app/product_gallery.py`：自包含静态 HTML 画廊渲染。
- `app/product_output_bundle.py`：三个产物的暂存、目录交换和回滚。
- `scripts/verify_products.py`：离线校验 Excel、JSON 和 HTML 一致性。
- `tests/test_product_models.py`
- `tests/test_web_scraping_dev.py`
- `tests/test_product_runner.py`
- `tests/test_product_excel.py`
- `tests/test_product_json.py`
- `tests/test_product_gallery.py`
- `tests/test_product_output_bundle.py`
- `tests/test_verify_products.py`
- `tests/fixtures/wsd_products_page_1.html`
- `tests/fixtures/wsd_products_page_2.html`
- `tests/fixtures/wsd_product_detail.html`
- `tests/fixtures/wsd_product_partial.html`
- `tests/fixtures/wsd_product_blocked.html`

### 修改

- `.gitignore`：已包含 `.superpowers/`；不再增加新的运行时例外。
- `AGENTS.md`：增加 web-scraping.dev 的真实联网规则。
- `app/models.py`：不改电影类型，仅保留现状。
- `app/sites/douban_movie.py`：改为从 `app.site_errors` 导入共享异常。
- `app/runner.py`：改为从 `app.site_errors` 导入共享异常。
- `app/main.py`：增加 `collect-products` 子命令和独立门禁。
- `scripts/verify_core.py`：覆盖率门禁加入商品解析器和商品运行器。
- `tests/test_douban_parser.py`：更新共享异常导入。
- `tests/test_runner.py`：更新共享异常导入。
- `tests/test_main.py`：增加商品命令解析、门禁和退出码测试。
- `tests/test_project_config.py`：接受 `.superpowers/`，并禁止 CI 真实访问第二站点。
- `.github/workflows/core-offline.yml`：文档注释和离线扫描覆盖第二站点，不增加联网步骤。
- `README.md`：增加第二站点受控命令、输出和静态画廊说明。
- `pyproject.toml`：把新增顶层模块包含在现有 `app` 包中；不增加运行时依赖。

## 固定公共契约

### 商品状态

```python
class ProductStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    PAGE_CHANGED = "PAGE_CHANGED"
    NETWORK_ERROR = "NETWORK_ERROR"
    BLOCKED = "BLOCKED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"
```

### 商品工作簿列

```python
PRODUCT_COLUMNS = [
    "product_id",
    "source_site",
    "product_url",
    "name",
    "category",
    "description",
    "primary_image_url",
    "current_price",
    "original_price",
    "currency",
    "brand",
    "variant_count",
    "status",
    "error_message",
    "collected_at",
]
```

### 输出目录

```text
<output-dir>/
├── products.xlsx
├── products.json
└── gallery.html
```

### JSON 顶层结构

```json
{
  "schema_version": 1,
  "source_site": "web-scraping.dev",
  "generated_at": "2026-07-16T20:00:00+08:00",
  "summary": {
    "total": 2,
    "success": 1,
    "partial": 1,
    "failed": 0
  },
  "products": []
}
```

## 任务 0：恢复设计提交后的绿色离线基线

**文件：**

- 修改：`tests/test_project_config.py:21`
- 测试：`tests/test_project_config.py`

- [x] **步骤 1：更新精确 `.gitignore` 契约**

在期望列表的 `htmlcov/` 与 `.env` 之间加入：

```python
".superpowers/",
```

并增加以下断言，确认视觉草图不会被跟踪：

```python
assert ".superpowers/" in gitignore
assert not any(
    path.parts[:2] == (".superpowers", "brainstorm")
    for path in PROJECT_ROOT.rglob("*")
    if path.is_file() and path.name == ".gitkeep"
)
```

- [x] **步骤 2：运行配置测试**

运行：

```powershell
python -m pytest tests/test_project_config.py -q
```

预期：全部通过；不再出现 `.superpowers/` 列表差异。

- [x] **步骤 3：运行完整基线**

运行：

```powershell
python -m pytest -q
```

预期：164 项测试全部通过。

- [x] **步骤 4：提交基线修复**

```powershell
git add tests/test_project_config.py
git commit -m "test: accept ignored brainstorm workspace"
```

## 任务 1：提取共享站点错误并建立商品领域模型

**文件：**

- 新建：`app/site_errors.py`
- 新建：`app/product_models.py`
- 新建：`tests/test_product_models.py`
- 修改：`app/sites/douban_movie.py:164-177`
- 修改：`app/runner.py:11-17`
- 修改：`tests/test_douban_parser.py:8-16`
- 修改：`tests/test_runner.py:15-25`

- [x] **步骤 1：先写商品模型失败测试**

创建 `tests/test_product_models.py`：

```python
from decimal import Decimal

from app.product_models import (
    ProductCollection,
    ProductListing,
    ProductRecord,
    ProductStatus,
)


def test_product_listing_has_stable_identity() -> None:
    listing = ProductListing(
        product_id="1",
        product_url="https://web-scraping.dev/product/1",
        category="consumables",
    )
    assert listing.product_id == "1"
    assert listing.product_url.endswith("/product/1")


def test_product_record_serializes_decimal_and_enum_values() -> None:
    record = ProductRecord(
        product_id="1",
        source_site="web-scraping.dev",
        product_url="https://web-scraping.dev/product/1",
        name="Box of Chocolate Candy",
        category="consumables",
        description="Chocolate assortment",
        primary_image_url="https://web-scraping.dev/assets/products/1.webp",
        current_price=Decimal("9.99"),
        original_price=Decimal("12.99"),
        currency="USD",
        brand="ChocoDelight",
        variant_count=6,
        status=ProductStatus.SUCCESS,
        collected_at="2026-07-16T20:00:00+08:00",
    )

    payload = record.to_primitive()

    assert payload["current_price"] == 9.99
    assert payload["original_price"] == 12.99
    assert payload["status"] == "SUCCESS"


def test_collection_summary_counts_terminal_groups() -> None:
    success = ProductRecord.success_fixture("1")
    partial = ProductRecord.success_fixture(
        "2", status=ProductStatus.PARTIAL, error_message="brand missing"
    )
    failed = ProductRecord.failure(
        ProductListing("3", "https://web-scraping.dev/product/3", ""),
        ProductStatus.PAGE_CHANGED,
        "price missing",
    )

    collection = ProductCollection.from_records(
        [success, partial, failed],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )

    assert collection.summary.total == 3
    assert collection.summary.success == 1
    assert collection.summary.partial == 1
    assert collection.summary.failed == 1
```

- [x] **步骤 2：运行测试确认缺少模块**

运行：

```powershell
python -m pytest tests/test_product_models.py -q
```

预期：导入 `app.product_models` 失败。

- [x] **步骤 3：创建共享错误**

创建 `app/site_errors.py`：

```python
class BlockedError(RuntimeError):
    """The remote site denied or restricted access; stop the batch."""


class PageChangedError(RuntimeError):
    """The page no longer satisfies the adapter's required contract."""


class NetworkError(RuntimeError):
    """A bounded, retryable navigation or connection failure."""


class SiteProtectionChallenge(RuntimeError):
    """A site-protection challenge that must never be automated around."""
```

从 `app/sites/douban_movie.py` 删除四个本地异常定义，改为：

```python
from app.site_errors import (
    BlockedError,
    NetworkError,
    PageChangedError,
    SiteProtectionChallenge,
)
```

`app/runner.py` 与相关测试也改为从 `app.site_errors` 导入；豆瓣适配器仍可通过
模块级导入继续暴露相同名字，避免不必要的调用方破坏。

- [x] **步骤 4：实现商品模型**

创建 `app/product_models.py`，包含：

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class ProductStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    PAGE_CHANGED = "PAGE_CHANGED"
    NETWORK_ERROR = "NETWORK_ERROR"
    BLOCKED = "BLOCKED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


@dataclass(frozen=True, slots=True)
class ProductListing:
    product_id: str
    product_url: str
    category: str = ""


@dataclass(frozen=True, slots=True)
class ProductPage:
    listings: tuple[ProductListing, ...]
    next_url: str | None


@dataclass(frozen=True, slots=True)
class ProductRecord:
    product_id: str
    source_site: str
    product_url: str
    name: str = ""
    category: str = ""
    description: str = ""
    primary_image_url: str = ""
    current_price: Decimal | None = None
    original_price: Decimal | None = None
    currency: str = ""
    brand: str = ""
    variant_count: int = 0
    status: ProductStatus = ProductStatus.UNEXPECTED_ERROR
    error_message: str = ""
    collected_at: str = ""

    def stamped(self) -> ProductRecord:
        return replace(
            self,
            collected_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )

    def to_primitive(self) -> dict[str, object]:
        values = asdict(self)
        values["current_price"] = (
            float(self.current_price) if self.current_price is not None else None
        )
        values["original_price"] = (
            float(self.original_price) if self.original_price is not None else None
        )
        values["status"] = self.status.value
        return values

    @classmethod
    def failure(
        cls,
        listing: ProductListing,
        status: ProductStatus,
        error_message: str,
    ) -> ProductRecord:
        return cls(
            product_id=listing.product_id,
            source_site="web-scraping.dev",
            product_url=listing.product_url,
            category=listing.category,
            status=status,
            error_message=error_message,
        ).stamped()

    @classmethod
    def success_fixture(
        cls,
        product_id: str,
        *,
        status: ProductStatus = ProductStatus.SUCCESS,
        error_message: str = "",
    ) -> ProductRecord:
        return cls(
            product_id=product_id,
            source_site="web-scraping.dev",
            product_url=f"https://web-scraping.dev/product/{product_id}",
            name=f"Product {product_id}",
            current_price=Decimal("9.99"),
            currency="USD",
            status=status,
            error_message=error_message,
            collected_at="2026-07-16T20:00:00+08:00",
        )


@dataclass(frozen=True, slots=True)
class ProductSummary:
    total: int
    success: int
    partial: int
    failed: int
    blocked: bool


@dataclass(frozen=True, slots=True)
class ProductCollection:
    records: tuple[ProductRecord, ...]
    generated_at: str
    summary: ProductSummary

    @classmethod
    def from_records(
        cls,
        records: list[ProductRecord],
        *,
        generated_at: str,
        blocked: bool,
    ) -> ProductCollection:
        frozen = tuple(records)
        success = sum(r.status is ProductStatus.SUCCESS for r in frozen)
        partial = sum(r.status is ProductStatus.PARTIAL for r in frozen)
        return cls(
            records=frozen,
            generated_at=generated_at,
            summary=ProductSummary(
                total=len(frozen),
                success=success,
                partial=partial,
                failed=len(frozen) - success - partial,
                blocked=blocked,
            ),
        )
```

`success_fixture()` 只作为测试构造器；如果实现者更偏好放在测试辅助模块，可在本任务中
将其移动到 `tests/product_fixtures.py`，但后续所有测试必须统一使用一个位置。

- [x] **步骤 5：运行共享错误和模型测试**

运行：

```powershell
python -m pytest tests/test_product_models.py tests/test_douban_parser.py tests/test_runner.py -q
```

预期：全部通过，豆瓣错误语义没有变化。

- [x] **步骤 6：提交领域边界**

```powershell
git add app/site_errors.py app/product_models.py app/sites/douban_movie.py app/runner.py tests/test_product_models.py tests/test_douban_parser.py tests/test_runner.py
git commit -m "refactor: add shared site errors and product models"
```

## 任务 2：实现 web-scraping.dev URL 和页面解析契约

**文件：**

- 新建：`app/sites/web_scraping_dev.py`
- 新建：`tests/test_web_scraping_dev.py`
- 新建：`tests/fixtures/wsd_products_page_1.html`
- 新建：`tests/fixtures/wsd_products_page_2.html`
- 新建：`tests/fixtures/wsd_product_detail.html`
- 新建：`tests/fixtures/wsd_product_partial.html`
- 新建：`tests/fixtures/wsd_product_blocked.html`

- [x] **步骤 1：创建最小脱敏 fixture**

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

- [x] **步骤 2：写 URL、列表和详情失败测试**

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

- [x] **步骤 3：运行解析测试确认失败**

运行：

```powershell
python -m pytest tests/test_web_scraping_dev.py -q
```

预期：缺少 `app.sites.web_scraping_dev`。

- [x] **步骤 4：实现纯解析和 URL 白名单**

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

- [x] **步骤 5：补写浏览器访问测试**

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

- [x] **步骤 6：运行适配器测试**

运行：

```powershell
python -m pytest tests/test_web_scraping_dev.py -q
```

预期：全部通过。

- [x] **步骤 7：提交站点适配器**

```powershell
git add app/sites/web_scraping_dev.py tests/test_web_scraping_dev.py tests/fixtures/wsd_*.html
git commit -m "feat: add web scraping dev product adapter"
```

## 任务 3：实现商品分页运行器和停止策略

**文件：**

- 新建：`app/product_runner.py`
- 新建：`tests/test_product_runner.py`

- [x] **步骤 1：写分页、去重和上限失败测试**

创建 `tests/test_product_runner.py`，使用 fake adapter：

```python
from decimal import Decimal

import pytest

from app.product_models import (
    ProductListing,
    ProductPage,
    ProductRecord,
    ProductStatus,
)
from app.product_runner import ProductRunner
from app.site_errors import BlockedError, NetworkError, PageChangedError


def record(product_id: str) -> ProductRecord:
    return ProductRecord(
        product_id=product_id,
        source_site="web-scraping.dev",
        product_url=f"https://web-scraping.dev/product/{product_id}",
        name=f"Product {product_id}",
        current_price=Decimal("9.99"),
        currency="USD",
        status=ProductStatus.SUCCESS,
        collected_at="2026-07-16T20:00:00+08:00",
    )


def test_runner_crosses_pages_deduplicates_and_honors_limit() -> None:
    adapter = FakeAdapter(
        pages={
            "https://web-scraping.dev/products": ProductPage(
                (
                    ProductListing("1", "https://web-scraping.dev/product/1"),
                    ProductListing("2", "https://web-scraping.dev/product/2"),
                ),
                "https://web-scraping.dev/products?page=2",
            ),
            "https://web-scraping.dev/products?page=2": ProductPage(
                (
                    ProductListing("2", "https://web-scraping.dev/product/2"),
                    ProductListing("3", "https://web-scraping.dev/product/3"),
                ),
                None,
            ),
        },
        products={"1": record("1"), "2": record("2"), "3": record("3")},
    )

    collection = ProductRunner(
        adapter, object(), max_products=3, min_interval_seconds=0
    ).run()

    assert [r.product_id for r in collection.records] == ["1", "2", "3"]
    assert adapter.product_calls == ["1", "2", "3"]


def test_blocked_detail_stops_remaining_products() -> None:
    adapter = FakeAdapter.single_page("1", "2", "3")
    adapter.products["1"] = record("1")
    adapter.products["2"] = BlockedError("429 rate limited")

    collection = ProductRunner(
        adapter, object(), max_products=3, min_interval_seconds=0
    ).run()

    assert [r.product_id for r in collection.records] == ["1", "2"]
    assert collection.records[1].status is ProductStatus.BLOCKED
    assert collection.summary.blocked is True
    assert adapter.product_calls == ["1", "2"]
```

Fake adapter 必须记录所有列表和详情调用，并允许返回对象或抛异常。

- [x] **步骤 2：运行测试确认缺少运行器**

运行：

```powershell
python -m pytest tests/test_product_runner.py -q
```

预期：缺少 `app.product_runner`。

- [x] **步骤 3：实现运行器**

创建 `app/product_runner.py`，核心结构：

```python
class ProductRunner:
    def __init__(
        self,
        adapter,
        tab,
        *,
        max_products: int,
        min_interval_seconds: float,
        logger=None,
        artifacts_dir: Path | None = None,
    ) -> None:
        """Store collaborators and validate max_products and interval."""

    def run(self) -> ProductCollection:
        """Discover, fetch, stop safely, and return one immutable collection."""

    def _discover(self) -> tuple[list[ProductListing], bool]:
        """Return ordered unique listings and whether discovery was blocked."""

    def _fetch(self, listing: ProductListing) -> tuple[ProductRecord, bool]:
        """Return one terminal record and whether the batch must stop."""

    def _network_operation(self, operation):
        """Retry NetworkError at most three times with 2/5-second backoff."""

    def _paced(self, operation):
        """Execute one network operation and enforce the minimum interval."""
```

固定行为：

- 从 `WebScrapingDevAdapter.PRODUCTS_URL` 开始。
- 使用 `dict[str, ProductListing]` 保持首次发现顺序并去重。
- 达到 `max_products` 立即停止继续翻页。
- 每一次列表页和详情页访问都由 `_paced()` 包裹。
- `_paced()` 从单次访问开始计时，访问完成后补足最小间隔。
- `_network_operation()` 只重试 `NetworkError`，三次上限，退避为 0、2、5 秒。
- 列表页 `PageChangedError` 终止发现；若已有 listing，继续处理已发现商品。
- 列表页 `BlockedError` 立即返回 blocked 汇总，不访问详情。
- 详情页异常映射：
  `BlockedError -> BLOCKED`、
  `PageChangedError -> PAGE_CHANGED`、
  `NetworkError -> NETWORK_ERROR`、
  其他异常只记录类型名为 `UNEXPECTED_ERROR`。
- `BLOCKED` 记录当前商品后立即停止剩余详情。
- 错误消息最多 200 字符。
- `generated_at` 在整批结束时生成带时区、秒级 ISO 8601 时间。
- 失败诊断沿用 `capture_failure()`，文件名使用 `product-<product_id>`。
- 日志只包含脱敏后的 `product_id`、阶段和状态。

- [x] **步骤 4：补齐节流和重试测试**

增加测试验证：

- 两次列表访问和三次详情访问分别执行节流。
- 第一次 `NetworkError`、第二次成功时只等待 2 秒。
- 三次失败时等待 2 秒和 5 秒，形成 `NETWORK_ERROR`。
- `PageChangedError` 不重试。
- 未分类异常错误信息只包含异常类名。
- `max_products=1` 不访问第二个详情。

- [x] **步骤 5：运行运行器测试**

运行：

```powershell
python -m pytest tests/test_product_runner.py -q
```

预期：全部通过。

- [x] **步骤 6：提交运行器**

```powershell
git add app/product_runner.py tests/test_product_runner.py
git commit -m "feat: collect bounded product pages"
```

## 任务 4：实现商品 Excel 合并与原子序列化

**文件：**

- 新建：`app/product_excel.py`
- 新建：`tests/test_product_excel.py`

- [x] **步骤 1：写工作簿失败测试**

创建 `tests/test_product_excel.py`：

```python
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from app.product_excel import PRODUCT_COLUMNS, ProductExcel
from app.product_models import ProductRecord


def test_render_creates_products_sheet_with_exact_columns(tmp_path: Path) -> None:
    path = tmp_path / "products.xlsx"
    ProductExcel.write(path, [ProductRecord.success_fixture("1")])
    workbook = load_workbook(path)
    assert workbook.active.title == "products"
    rows = list(workbook.active.values)
    assert list(rows[0]) == PRODUCT_COLUMNS
    assert rows[1][0] == "1"
    assert rows[1][12] == "SUCCESS"


def test_merge_replaces_product_id_without_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "products.xlsx"
    ProductExcel.write(path, [ProductRecord.success_fixture("1")])
    updated = ProductRecord.success_fixture("1")
    merged = ProductExcel.merge_existing(path, [updated])
    assert [record.product_id for record in merged] == ["1"]


def test_wrong_existing_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "products.xlsx"
    workbook = Workbook()
    workbook.active.append(["wrong"])
    workbook.save(path)
    with pytest.raises(ValueError, match="product workbook schema"):
        ProductExcel.read(path)
```

- [x] **步骤 2：运行测试确认缺少模块**

```powershell
python -m pytest tests/test_product_excel.py -q
```

预期：缺少 `app.product_excel`。

- [x] **步骤 3：实现商品工作簿**

创建 `app/product_excel.py`：

- `PRODUCT_COLUMNS` 使用固定 15 列契约。
- `ProductExcel.read(path)` 将工作簿行还原为 `ProductRecord`；
  金额使用 `Decimal(str(value))`。
- `ProductExcel.merge_existing(path, new_records)`：
  读取旧记录，以 `product_id` 为键；旧顺序保留，新 ID 追加，同 ID 替换。
- `ProductExcel.write(path, records)`：
  新建 `products` 工作表，将 enum 写为 `.value`，Decimal 写为 float，
  空值写 `None`。
- 写入调用方提供的暂存路径；目录交换由后续输出包负责。
- 错误 schema 明确抛 `ValueError`。

- [x] **步骤 4：运行工作簿测试**

```powershell
python -m pytest tests/test_product_excel.py -q
```

预期：全部通过。

- [x] **步骤 5：提交 Excel 输出**

```powershell
git add app/product_excel.py tests/test_product_excel.py
git commit -m "feat: add product workbook output"
```

## 任务 5：实现稳定 JSON 与自包含静态画廊

**文件：**

- 新建：`app/product_json.py`
- 新建：`app/product_gallery.py`
- 新建：`tests/test_product_json.py`
- 新建：`tests/test_product_gallery.py`

- [x] **步骤 1：写 JSON 快照失败测试**

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

- [x] **步骤 2：写画廊结构和安全失败测试**

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

- [x] **步骤 3：运行测试确认缺少渲染器**

```powershell
python -m pytest tests/test_product_json.py tests/test_product_gallery.py -q
```

预期：缺少两个模块。

- [x] **步骤 4：实现 JSON 渲染器**

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

- [x] **步骤 5：实现画廊渲染器**

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

- [x] **步骤 6：运行 JSON 和画廊测试**

```powershell
python -m pytest tests/test_product_json.py tests/test_product_gallery.py -q
```

预期：全部通过。

- [x] **步骤 7：提交报告渲染**

```powershell
git add app/product_json.py app/product_gallery.py tests/test_product_json.py tests/test_product_gallery.py
git commit -m "feat: render product json and gallery"
```

## 任务 6：实现三产物原子输出包

**文件：**

- 新建：`app/product_output_bundle.py`
- 新建：`tests/test_product_output_bundle.py`

- [x] **步骤 1：写完整输出和回滚失败测试**

创建 `tests/test_product_output_bundle.py`，覆盖：

```python
from pathlib import Path

import pytest

import app.product_output_bundle as bundle_module
from app.excel_store import OutputLockedError
from app.product_models import ProductCollection, ProductRecord
from app.product_output_bundle import ProductOutputBundle


def collection(product_id: str) -> ProductCollection:
    return ProductCollection.from_records(
        [ProductRecord.success_fixture(product_id)],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )


def test_write_creates_exact_three_outputs(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    ProductOutputBundle(target).write(collection("1"))
    assert sorted(path.name for path in target.iterdir()) == [
        "gallery.html",
        "products.json",
        "products.xlsx",
    ]


def test_existing_bundle_is_merged_and_replaced_as_one_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "demo"
    bundle = ProductOutputBundle(target)
    bundle.write(collection("1"))
    bundle.write(collection("2"))
    assert bundle.read_product_ids() == ["1", "2"]


def test_failed_directory_swap_restores_previous_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"
    bundle = ProductOutputBundle(target)
    bundle.write(collection("1"))
    original_json = (target / "products.json").read_bytes()

    real_replace = bundle_module.os.replace
    calls = {"count": 0}

    def fail_second_replace(source: Path, destination: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise PermissionError("locked")
        real_replace(source, destination)

    monkeypatch.setattr(bundle_module.os, "replace", fail_second_replace)
    with pytest.raises(OutputLockedError):
        bundle.write(collection("2"))

    assert (target / "products.json").read_bytes() == original_json
```

- [x] **步骤 2：运行测试确认缺少输出包**

```powershell
python -m pytest tests/test_product_output_bundle.py -q
```

预期：缺少模块。

- [x] **步骤 3：实现目录级提交**

创建 `app/product_output_bundle.py`：

1. 验证 `target_dir` 位于调用方允许的 `outputs/` 边界内；CLI 负责传入已解析边界。
2. 如果存在 `products.xlsx`，用 `ProductExcel.read()` 读取旧记录并按 ID 合并。
3. 使用合并后的记录重新构建 `ProductCollection`，确保三个产物一致。
   合并结果超过 10 件时抛
   `ValueError("product bundle cannot exceed 10 products")`，
   避免跨多次运行绕过受控上限。
4. 在目标同级创建唯一暂存目录：
   `.<target-name>.staging-<uuid>`。
5. 在暂存目录写：
   `products.xlsx`、`products.json`、`gallery.html`。
6. 重新读取暂存 Excel 和 JSON，确认商品 ID 顺序一致。
7. 若目标存在，将目标重命名为
   `.<target-name>.backup-<uuid>`。
8. 将暂存目录重命名为目标目录。
9. 成功后用 `shutil.rmtree()` 删除 backup。
10. 第二次重命名失败时，将 backup 重命名回目标，并抛
    `OutputLockedError(f"Close open output files and retry: {self.target_dir}")`。
11. 无论成功失败，清理仍存在的 staging；不得删除已恢复的目标。

增加：

```python
def read_product_ids(self) -> list[str]:
    return [
        record.product_id
        for record in ProductExcel.read(self.target_dir / "products.xlsx")
    ]
```

供测试和后续验证脚本使用。

- [x] **步骤 4：运行输出包测试**

```powershell
python -m pytest tests/test_product_output_bundle.py -q
```

预期：全部通过。

- [x] **步骤 5：提交原子输出**

```powershell
git add app/product_output_bundle.py tests/test_product_output_bundle.py
git commit -m "feat: commit product outputs as one bundle"
```

## 任务 7：接入独立 `collect-products` CLI

**文件：**

- 修改：`app/main.py:23-128`
- 修改：`tests/test_main.py`
- 修改：`AGENTS.md`

- [x] **步骤 1：写 CLI 参数失败测试**

在 `tests/test_main.py` 增加：

```python
def test_collect_products_parser_has_safe_defaults() -> None:
    args = build_parser().parse_args(
        [
            "collect-products",
            "--site", "web-scraping.dev",
            "--output-dir", "outputs/demo",
        ]
    )
    assert args.site == "web-scraping.dev"
    assert args.output_dir == "outputs/demo"
    assert args.headed is True
    assert args.min_interval == 2.0
    assert args.profile_dir == "browser-profile/web-scraping-dev"
    assert args.live_approved is False
    assert args.max_products is None
```

- [x] **步骤 2：写浏览器创建前门禁测试**

使用独立 `_FakeProductRunner` 和 `_FakeProductOutputBundle`，验证：

- 缺 `--live-approved` 返回 2，浏览器未创建。
- `--max-products` 为 0、11 或缺失返回 2。
- `--no-headed` 返回 2。
- `--min-interval 1.99` 返回 2。
- `--site other.example` 返回 2。
- 输出目录在仓库 `outputs/` 外返回 2。
- profile 在仓库 `browser-profile/` 外返回 2。
- 合法参数只创建一次浏览器和一次运行器。
- 汇总 blocked 返回 3。
- 输出锁定返回 4。
- 浏览器或运行器未分类异常返回 5。

- [x] **步骤 3：运行新增 CLI 测试确认失败**

```powershell
python -m pytest tests/test_main.py -q
```

预期：`collect-products` 子命令不存在。

- [x] **步骤 4：重构命令分派并实现商品门禁**

在 `app/main.py`：

- 保留 `run` 参数和执行顺序不变。
- `execute()` 根据 `args.command` 分派：

```python
if args.command == "run":
    return _execute_douban(args, logger)
if args.command == "collect-products":
    return _execute_products(args, logger)
raise AssertionError(f"unsupported command: {args.command}")
```

- 新增常量：

```python
_PRODUCT_PROFILE_DEFAULT = "browser-profile/web-scraping-dev"
_PRODUCT_MIN_INTERVAL_DEFAULT = 2.0
_PRODUCT_LIVE_MIN_INTERVAL = 2.0
_PRODUCT_LIVE_MAX = 10
```

- 新增参数：

```python
products_parser.add_argument("--site", required=True)
products_parser.add_argument("--output-dir", required=True)
products_parser.add_argument(
    "--headed", action=argparse.BooleanOptionalAction, default=True
)
products_parser.add_argument("--min-interval", type=float, default=2.0)
products_parser.add_argument("--browser-path", default=None)
products_parser.add_argument(
    "--profile-dir", default="browser-profile/web-scraping-dev"
)
products_parser.add_argument("--live-approved", action="store_true")
products_parser.add_argument("--max-products", type=int, default=None)
```

- `_validate_product_live_run()` 在任何 `BrowserSession`、adapter、runner
  或输出器构造前完成验证。
- 路径边界使用 `Path.resolve()` 和 `is_relative_to()`：
  输出必须位于 `<repo>/outputs/`，
  profile 必须位于 `<repo>/browser-profile/`。
- `_execute_products()`：
  创建 `BrowserSession`；
  创建 `WebScrapingDevAdapter`；
  运行 `ProductRunner`；
  用 `ProductOutputBundle.write()` 提交产物。
- blocked 汇总返回 3；`OutputLockedError` 返回 4；
  未分类异常返回 5；验证失败返回 2；成功返回 0。

- [x] **步骤 5：在 AGENTS.md 固化第二站点规则**

增加：

```markdown
## web-scraping.dev live runs

- Real access requires explicit `--live-approved`.
- Every command must include `--max-products N`, where `1 <= N <= 10`.
- Runs must use `--headed` and `--min-interval 2` or greater.
- Only `/products`, valid product pagination, and `/product/<digits>` may be accessed.
- Never access `/robots-disallowed`, login, cart, reviews, GraphQL, CSRF,
  downloads, or challenge endpoints.
- Stop immediately on 429, blocking, login/security checks, challenge pages,
  or redirects outside `web-scraping.dev`.
- Never automate protection bypasses.
```

- [x] **步骤 6：运行 CLI 和现有豆瓣测试**

```powershell
python -m pytest tests/test_main.py tests/test_runner.py tests/test_douban_parser.py -q
```

预期：全部通过，现有 `run` 参数和退出码保持不变。

- [x] **步骤 7：提交 CLI 接线**

```powershell
git add app/main.py tests/test_main.py AGENTS.md
git commit -m "feat: add controlled product collection command"
```

## 任务 8：增加跨产物验证、覆盖率门禁和离线 CI 保护

**文件：**

- 新建：`scripts/verify_products.py`
- 新建：`tests/test_verify_products.py`
- 修改：`scripts/verify_core.py:10-14`
- 修改：`tests/test_verify_core.py`
- 修改：`tests/test_project_config.py:45-94`
- 修改：`.github/workflows/core-offline.yml`

- [x] **步骤 1：写三产物一致性失败测试**

创建 `tests/test_verify_products.py`，使用测试输出包生成基线，然后验证：

```python
def test_verify_bundle_accepts_matching_outputs(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    ProductOutputBundle(target).write(collection("1"))
    assert verify_product_bundle(target) == {
        "products": 1,
        "unique_ids": 1,
        "success": 1,
        "partial": 0,
        "failed": 0,
    }


def test_verify_bundle_rejects_json_id_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    ProductOutputBundle(target).write(collection("1"))
    payload = json.loads((target / "products.json").read_text(encoding="utf-8"))
    payload["products"][0]["product_id"] = "other"
    (target / "products.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    with pytest.raises(ProductBundleContractError, match="product ids"):
        verify_product_bundle(target)
```

另测：

- 缺任一产物；
- Excel 列错误；
- JSON `schema_version != 1`；
- 重复 ID；
- 超过 10 个商品；
- `collected_at` 缺失；
- HTML 不含对应嵌入 ID；
- HTML 含 `<script src=`、`fetch(` 或外部字体。

- [x] **步骤 2：实现 `scripts/verify_products.py`**

公开：

```python
class ProductBundleContractError(AssertionError):
    pass


def verify_product_bundle(output_dir: Path) -> dict[str, int]:
    """Validate the three-file product bundle and return status counts."""
```

验证：

- 三个文件存在；
- Excel 1 到 10 行、ID 唯一、15 列匹配；
- JSON 版本、来源、摘要和 ID 顺序匹配 Excel；
- HTML 包含安全嵌入数据和必要控件；
- HTML 无外部脚本、字体、`fetch(`、XHR 或 WebSocket；
- 返回状态计数摘要。

CLI：

```powershell
python -m scripts.verify_products --output-dir .\outputs\web-scraping-dev-demo
```

- [x] **步骤 3：扩展覆盖率门禁**

在 `scripts/verify_core.py`：

```python
REQUIRED_COVERAGE = {
    "app/input_loader.py": 80.0,
    "app/matcher.py": 80.0,
    "app/sites/douban_movie.py": 80.0,
    "app/sites/web_scraping_dev.py": 80.0,
    "app/product_runner.py": 80.0,
}
```

更新 `tests/test_verify_core.py` 的平台路径、通过和失败用例。

- [x] **步骤 4：强化 CI 静态保护**

更新 `tests/test_project_config.py`：

- CI job body 不得包含 `web-scraping.dev`；
- 不得包含 `collect-products`；
- 不得包含 `--max-products`；
- 不得上传 `products.xlsx`、`products.json` 或 `gallery.html`。

更新 `.github/workflows/core-offline.yml` 顶部注释，明确第二站点也禁止真实访问。
工作流执行步骤仍只有安装、pytest、覆盖率门禁、diff 检查和 tracked 文件扫描。

- [x] **步骤 5：运行验证测试**

```powershell
python -m pytest tests/test_verify_products.py tests/test_verify_core.py tests/test_project_config.py -q
```

预期：全部通过。

- [x] **步骤 6：提交验证门禁**

```powershell
git add scripts/verify_products.py scripts/verify_core.py tests/test_verify_products.py tests/test_verify_core.py tests/test_project_config.py .github/workflows/core-offline.yml
git commit -m "test: verify offline product output contract"
```

## 任务 9：完成 README、帮助文本和离线交付验证

**文件：**

- 修改：`README.md`
- 修改：`tests/test_project_config.py`
- 修改：`pyproject.toml`（仅在包发现测试表明新模块未安装时）

- [x] **步骤 1：写 README 契约测试**

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

- [x] **步骤 2：更新 README**

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

- [x] **步骤 3：验证安装后的模块发现**

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

- [x] **步骤 4：运行全量离线测试和覆盖率**

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

- [x] **步骤 5：生成完全离线的演示包用于验证**

在测试临时目录使用 fixture 和 `ProductOutputBundle` 生成演示包，不访问真实网站：

```powershell
python -m pytest tests/test_product_output_bundle.py tests/test_product_gallery.py -q
```

随后通过测试中生成的临时文件验证结构；不要把临时输出复制到 Git 跟踪目录。

- [x] **步骤 6：人工打开静态画廊**

使用由 fixture 构造的本地 `gallery.html`，人工检查：

- 商品卡片响应式排列；
- 搜索、分类和状态筛选；
- 价格升降序；
- 点击卡片后证据侧栏更新；
- 每张卡片显示稳定的本地视觉封面；
- 页面断网时仍可使用；
- 开发者工具 Network 面板没有自动访问 `web-scraping.dev`。

这一步只验证本地 HTML，不执行真实采集。

- [x] **步骤 7：提交文档和交付收口**

```powershell
git add README.md tests/test_project_config.py pyproject.toml
git commit -m "docs: add product collection gallery runbook"
```

只在 `pyproject.toml` 实际发生修改时将其加入提交。

## 任务 10：最终离线发布验证与可选受控现场验收

**文件：**

- 验证：全仓库
- 运行时输出：`outputs/web-scraping-dev-demo/`（忽略，不提交）
- 浏览器 profile：`browser-profile/web-scraping-dev/`（忽略，不提交）
- 诊断：`artifacts/`（忽略，不提交）

- [x] **步骤 1：运行最终离线发布门禁**

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

- [x] **步骤 2：确认禁止的 tracked 产物为空**

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

- [x] **步骤 3：仅在操作者再次明确批准时运行真实网站**

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

- [x] **步骤 4：若已获授权且运行成功，验证输出包**

```powershell
python -m scripts.verify_products `
  --output-dir .\outputs\web-scraping-dev-demo
```

预期：

- 商品数量为 1 到 10；
- ID 唯一；
- Excel、JSON、HTML 数量和顺序一致；
- HTML 无自动网络依赖。

- [x] **步骤 5：人工验收画廊**

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

- [x] **步骤 6：最终提交**

只有离线门禁全部通过后：

```powershell
git status --short
git log --oneline -10
```

确认没有运行时文件进入暂存区。若收口过程中产生必要的小修复：

```powershell
git add <仅本轮源码、测试和文档文件>
git commit -m "chore: finalize product gallery release gate"
```

## 计划自我复核清单

- [x] 每项批准需求都有对应任务：
  第二站点、分页、详情、10 件上限、2 秒间隔、Excel、JSON、HTML、
  搜索、筛选、排序、证据侧栏、离线 CI 和阻断停止。
- [x] 商品模型没有复用或改变电影 12 列契约。
- [x] `ProductStatus.PARTIAL` 只用于可选字段缺失。
- [x] 商品 ID、名称、当前价格或规范 URL 缺失时为 `PAGE_CHANGED`。
- [x] 输出包通过暂存目录和目录交换保持三产物一致。
- [x] 所有真实联网命令都包含明确授权、数量上限、有头模式和最小间隔。
- [x] 没有任务实现登录、GraphQL、评论、购物车、CSRF、挑战或绕过。
- [x] CI 没有真实网站、浏览器或 live flag。
- [x] 所有代码修改先有失败测试，再有最小实现和通过命令。
- [x] 每个任务都有独立提交点。
