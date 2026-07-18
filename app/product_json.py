from __future__ import annotations

from app.product_models import ProductCollection
from app.product_output_snapshot import (
    ProductOutputSnapshot,
    build_product_output_snapshot,
    product_payload,
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
