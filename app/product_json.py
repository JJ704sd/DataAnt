from __future__ import annotations

import json

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


def render_product_json(collection: ProductCollection) -> str:
    return json.dumps(
        product_payload(collection),
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    ) + "\n"
