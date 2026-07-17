# 任务 1：提取共享站点错误并建立商品领域模型

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-01-domain-models.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：test: accept ignored brainstorm workspace。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格执行本文件中的 RED → verify RED → GREEN → focused verify → full verify → commit 顺序。文件编辑使用 apply_patch。只允许修改文件小节列出的文件；不得安装或升级依赖，不得 amend、reset、force push，不得修改或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

本任务严格离线：不得启动浏览器，不得访问 web-scraping.dev、豆瓣或其他外网，不得传入 --live-approved。

提交前运行 git diff --check，并确认 git diff --name-only 只含本任务允许文件。除非本任务明确说明不需要提交，commit message 必须精确为：refactor: add shared site errors and product models

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-01-domain-models
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
- 前置提交：`test: accept ignored brainstorm workspace`。
- 本任务提交：`refactor: add shared site errors and product models`。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


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
