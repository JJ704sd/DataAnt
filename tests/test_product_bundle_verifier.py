from dataclasses import replace
from pathlib import Path

import pytest

from app.product_artifact_writers import ProductArtifactWriters
from app.product_bundle_verifier import ProductBundleVerifier
from app.product_models import ProductCollection, ProductRecord
from app.product_output_snapshot import build_product_output_snapshot


def collection() -> ProductCollection:
    return ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )


def test_verifier_accepts_three_consistent_artifacts(tmp_path: Path) -> None:
    value = collection()
    snapshot = build_product_output_snapshot(value)
    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)

    elapsed_ms = ProductBundleVerifier.verify(snapshot, receipt, tmp_path)

    assert elapsed_ms >= 0


def test_verifier_rejects_json_id_drift(tmp_path: Path) -> None:
    value = collection()
    snapshot = build_product_output_snapshot(value)
    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)
    (tmp_path / "products.json").write_text(
        '{"products":[{"product_id":"2"}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="JSON IDs"):
        ProductBundleVerifier.verify(snapshot, receipt, tmp_path)


def test_verifier_rejects_excel_id_drift(tmp_path: Path) -> None:
    value = collection()
    snapshot = build_product_output_snapshot(value)
    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)
    drifted_excel = replace(receipt.excel, product_ids=("2",))
    drifted_receipt = replace(receipt, excel=drifted_excel)

    with pytest.raises(ValueError, match="Excel IDs"):
        ProductBundleVerifier.verify(snapshot, drifted_receipt, tmp_path)


@pytest.mark.parametrize(
    "product_ids",
    [[], ["1", "1"], ["2", "1"]],
)
def test_verifier_rejects_missing_duplicate_or_reordered_json_ids(
    tmp_path: Path, product_ids: list[str]
) -> None:
    import json

    value = collection()
    snapshot = build_product_output_snapshot(value)
    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)
    payload = {
        "products": [{"product_id": product_id} for product_id in product_ids]
    }
    (tmp_path / "products.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="JSON IDs"):
        ProductBundleVerifier.verify(snapshot, receipt, tmp_path)


def test_verifier_rejects_missing_gallery(tmp_path: Path) -> None:
    value = collection()
    snapshot = build_product_output_snapshot(value)
    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)
    (tmp_path / "gallery.html").unlink()

    with pytest.raises(ValueError, match="gallery.html"):
        ProductBundleVerifier.verify(snapshot, receipt, tmp_path)
