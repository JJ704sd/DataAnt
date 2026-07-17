from __future__ import annotations

from decimal import Decimal

from app.product_models import ProductCollection, ProductRecord


def fixture_collection(count: int) -> ProductCollection:
    if count not in {1, 5, 10}:
        raise ValueError("fixture collection count must be 1, 5, or 10")
    records = [
        ProductRecord(
            product_id=str(index),
            source_site="web-scraping.dev",
            product_url=f"https://web-scraping.dev/product/{index}",
            name=f"Product {index}",
            category="consumables",
            description=f"Description {index}",
            primary_image_url=(
                f"https://web-scraping.dev/assets/products/{index}.webp"
            ),
            current_price=Decimal("9.99"),
            currency="USD",
            brand=f"Brand {index}",
            variant_count=index % 3,
            collected_at="2026-07-16T20:00:00+08:00",
        )
        for index in range(1, count + 1)
    ]
    return ProductCollection.from_records(
        records,
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
