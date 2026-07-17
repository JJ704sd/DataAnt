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
