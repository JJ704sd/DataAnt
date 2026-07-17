from pathlib import Path

import pytest

import app.product_output_bundle as bundle_module
from app.excel_store import OutputLockedError
from app.product_models import ProductCollection, ProductRecord
from app.product_output_bundle import ProductOutputBundle


def collection(product_id: str) -> ProductCollection:
    return ProductCollection.from_records(
        [ProductRecord.success_fixture(product_id)],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )


def test_write_creates_exact_three_outputs(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    ProductOutputBundle(target).write(collection("1"))
    assert sorted(path.name for path in target.iterdir()) == [
        "gallery.html",
        "products.json",
        "products.xlsx",
    ]


def test_existing_bundle_is_merged_and_replaced_as_one_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "demo"
    bundle = ProductOutputBundle(target)
    bundle.write(collection("1"))
    bundle.write(collection("2"))
    assert bundle.read_product_ids() == ["1", "2"]


def test_failed_directory_swap_restores_previous_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"
    bundle = ProductOutputBundle(target)
    bundle.write(collection("1"))
    original_json = (target / "products.json").read_bytes()

    real_replace = bundle_module.os.replace
    calls = {"count": 0}

    def fail_second_replace(source: Path, destination: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise PermissionError("locked")
        real_replace(source, destination)

    monkeypatch.setattr(bundle_module.os, "replace", fail_second_replace)
    with pytest.raises(OutputLockedError):
        bundle.write(collection("2"))

    assert (target / "products.json").read_bytes() == original_json
