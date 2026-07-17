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
