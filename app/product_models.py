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
