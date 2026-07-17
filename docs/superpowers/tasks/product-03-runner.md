# 任务 3：实现商品分页运行器和停止策略

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-03-runner.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：feat: add web scraping dev product adapter。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格执行本文件中的 RED → verify RED → GREEN → focused verify → full verify → commit 顺序。文件编辑使用 apply_patch。只允许修改文件小节列出的文件；不得安装或升级依赖，不得 amend、reset、force push，不得修改或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

本任务严格离线：不得启动浏览器，不得访问 web-scraping.dev、豆瓣或其他外网，不得传入 --live-approved。

提交前运行 git diff --check，并确认 git diff --name-only 只含本任务允许文件。除非本任务明确说明不需要提交，commit message 必须精确为：feat: collect bounded product pages

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-03-runner
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
- 前置提交：`feat: add web scraping dev product adapter`。
- 本任务提交：`feat: collect bounded product pages`。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


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
