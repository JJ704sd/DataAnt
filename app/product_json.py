from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from app.product_models import ProductCollection


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


@dataclass(frozen=True, slots=True)
class ProductOutputSnapshot:
    payload: dict[str, object]
    product_rows: tuple[dict[str, object], ...]
    json_text: str
    product_ids: tuple[str, ...]


def build_product_output_snapshot(
    collection: ProductCollection,
) -> ProductOutputSnapshot:
    payload = product_payload(collection)
    raw_products = payload.get("products")
    if not isinstance(raw_products, list):
        raise TypeError("product payload products must be a list")
    rows = tuple(cast(dict[str, object], item) for item in raw_products)
    compact = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ) + "\n"
    return ProductOutputSnapshot(
        payload=payload,
        product_rows=rows,
        json_text=compact,
        product_ids=tuple(str(row["product_id"]) for row in rows),
    )


def render_product_json(
    collection: ProductCollection,
    *,
    snapshot: ProductOutputSnapshot | None = None,
) -> str:
    return (snapshot or build_product_output_snapshot(collection)).json_text


__all__ = [
    "ProductOutputSnapshot",
    "build_product_output_snapshot",
    "product_payload",
    "render_product_json",
]
