import json

from app.product_json import (
    build_product_output_snapshot,
    render_product_json,
)
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


def test_snapshot_calls_to_primitive_once_per_record(monkeypatch) -> None:
    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1"), ProductRecord.success_fixture("2")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    calls = {"count": 0}
    original = ProductRecord.to_primitive

    def counted(record):
        calls["count"] += 1
        return original(record)

    monkeypatch.setattr(ProductRecord, "to_primitive", counted)
    snapshot = build_product_output_snapshot(collection)

    assert calls["count"] == 2
    assert snapshot.product_ids == ("1", "2")
    assert json.loads(snapshot.json_text)["products"][1]["product_id"] == "2"


def test_render_product_json_is_compact_without_schema_change() -> None:
    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    rendered = render_product_json(collection)
    payload = json.loads(rendered)

    assert payload["schema_version"] == 1
    assert payload["products"][0]["product_id"] == "1"
    assert "\n  " not in rendered
    assert rendered.endswith("\n")


def test_product_json_reexports_snapshot_api() -> None:
    from app import product_json, product_output_snapshot

    assert (
        product_json.ProductOutputSnapshot
        is product_output_snapshot.ProductOutputSnapshot
    )
    assert (
        product_json.build_product_output_snapshot
        is product_output_snapshot.build_product_output_snapshot
    )
    assert product_json.product_payload is product_output_snapshot.product_payload
