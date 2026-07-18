import json

import pytest

from app.product_models import ProductCollection, ProductRecord
from app.product_output_snapshot import build_product_output_snapshot


def collection() -> ProductCollection:
    return ProductCollection.from_records(
        [ProductRecord.success_fixture("1"), ProductRecord.success_fixture("2")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )


def test_snapshot_payload_and_rows_are_recursively_read_only() -> None:
    snapshot = build_product_output_snapshot(collection())

    with pytest.raises(TypeError):
        snapshot.payload["schema_version"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.product_rows[0]["product_id"] = "changed"  # type: ignore[index]
    products = snapshot.payload["products"]
    assert isinstance(products, tuple)
    assert snapshot.product_ids == ("1", "2")


def test_snapshot_serializes_before_freezing() -> None:
    snapshot = build_product_output_snapshot(collection())
    payload = json.loads(snapshot.json_text)

    assert payload["schema_version"] == 1
    assert [item["product_id"] for item in payload["products"]] == ["1", "2"]
