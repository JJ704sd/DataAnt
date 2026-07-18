import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import app.product_artifact_writers as writer_module
import app.product_output_bundle as bundle_module
from app.product_artifact_writers import ProductArtifactWriters
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


def test_concurrent_writes_to_same_target_are_serialized(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    barrier = threading.Barrier(2)

    def write_one(product_id: str) -> None:
        barrier.wait(timeout=5.0)
        ProductOutputBundle(target).write(collection(product_id))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(write_one, "1"),
            executor.submit(write_one, "2"),
        ]
        for future in futures:
            future.result()

    assert set(ProductOutputBundle(target).read_product_ids()) == {"1", "2"}


def test_bundle_passes_shared_rows_to_excel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[tuple[object, ...]] = []
    original = bundle_module.ProductExcel.write

    def capture(path, records, *, primitive_rows=None):
        received.append(tuple(primitive_rows or ()))
        return original(path, records, primitive_rows=primitive_rows)

    monkeypatch.setattr(bundle_module.ProductExcel, "write", capture)
    bundle_module.ProductOutputBundle(tmp_path / "demo").write(collection("1"))

    assert len(received) == 1
    assert received[0][0]["product_id"] == "1"


def test_writer_failure_leaves_existing_bundle_and_cleans_siblings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"
    bundle = ProductOutputBundle(target)
    bundle.write(collection("1"))
    original_json = (target / "products.json").read_bytes()

    def fail_gallery(*args, **kwargs):
        raise RuntimeError("gallery writer failed")

    monkeypatch.setattr(writer_module, "render_gallery", fail_gallery)
    with pytest.raises(RuntimeError, match="gallery writer failed"):
        bundle.write(collection("2"))

    assert (target / "products.json").read_bytes() == original_json
    assert not list(target.parent.glob(f".{target.name}.staging-*"))
    assert not list(target.parent.glob(f".{target.name}.backup-*"))


def test_bundle_returns_complete_required_receipt(tmp_path: Path) -> None:
    receipt = ProductOutputBundle(tmp_path / "demo").write(collection("1"))

    assert receipt.product_ids == ("1",)
    assert sorted(receipt.bytes_by_file) == [
        "gallery.html",
        "products.json",
        "products.xlsx",
    ]
    assert receipt.payload_build_ms >= 0
    assert receipt.json_write_ms >= 0
    assert receipt.gallery_write_ms >= 0
    assert receipt.excel_write_ms >= 0
    assert receipt.verify_ms >= 0
    assert receipt.total_local_ms >= 0


def test_bundle_delegates_writes_to_extracted_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"count": 0}
    real_write = ProductArtifactWriters.write

    def counted(value, directory, *, snapshot):
        calls["count"] += 1
        return real_write(value, directory, snapshot=snapshot)

    monkeypatch.setattr(ProductArtifactWriters, "write", counted)
    ProductOutputBundle(tmp_path / "demo").write(collection("1"))

    assert calls["count"] == 1


def test_bundle_rejects_merged_records_above_ten(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    initial = ProductCollection.from_records(
        [ProductRecord.success_fixture(str(index)) for index in range(1, 11)],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    ProductOutputBundle(target).write(initial)

    with pytest.raises(ValueError, match="cannot exceed 10"):
        ProductOutputBundle(target).write(collection("11"))
