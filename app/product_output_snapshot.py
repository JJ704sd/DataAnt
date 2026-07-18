from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
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


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ProductOutputSnapshot:
    payload: Mapping[str, object]
    product_rows: tuple[Mapping[str, object], ...]
    json_text: str
    product_ids: tuple[str, ...]


def build_product_output_snapshot(
    collection: ProductCollection,
) -> ProductOutputSnapshot:
    mutable_payload = product_payload(collection)
    raw_products = mutable_payload.get("products")
    if not isinstance(raw_products, list):
        raise TypeError("product payload products must be a list")
    json_text = json.dumps(
        mutable_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ) + "\n"
    frozen_payload = cast(Mapping[str, object], _freeze(mutable_payload))
    frozen_products = frozen_payload.get("products")
    if not isinstance(frozen_products, tuple):
        raise TypeError("frozen product payload products must be a tuple")
    rows = cast(tuple[Mapping[str, object], ...], frozen_products)
    return ProductOutputSnapshot(
        payload=frozen_payload,
        product_rows=rows,
        json_text=json_text,
        product_ids=tuple(str(row["product_id"]) for row in rows),
    )


__all__ = [
    "ProductOutputSnapshot",
    "build_product_output_snapshot",
    "product_payload",
]
