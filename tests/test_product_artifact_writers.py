from pathlib import Path

import pytest

import app.product_artifact_writers as writer_module
from app.product_artifact_writers import ProductArtifactWriters
from app.product_models import ProductCollection, ProductRecord
from app.product_output_snapshot import build_product_output_snapshot


def collection() -> ProductCollection:
    return ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )


def test_writers_create_exact_artifacts_and_complete_receipt(tmp_path: Path) -> None:
    value = collection()
    snapshot = build_product_output_snapshot(value)

    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)

    assert sorted(receipt.bytes_by_file) == [
        "gallery.html",
        "products.json",
        "products.xlsx",
    ]
    assert receipt.product_ids == ("1",)
    assert receipt.excel.product_ids == ("1",)
    assert receipt.json_write_ms >= 0
    assert receipt.gallery_write_ms >= 0
    assert receipt.excel_write_ms >= 0


def test_writer_failure_is_propagated_and_executor_cancels_pending_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutdown_calls: list[tuple[bool, bool]] = []
    real_executor = writer_module.ThreadPoolExecutor

    class RecordingExecutor(real_executor):
        def shutdown(
            self, wait: bool = True, *, cancel_futures: bool = False
        ) -> None:
            shutdown_calls.append((wait, cancel_futures))
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(writer_module, "ThreadPoolExecutor", RecordingExecutor)
    monkeypatch.setattr(
        writer_module,
        "render_gallery",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("gallery failed")),
    )
    value = collection()

    with pytest.raises(RuntimeError, match="gallery failed"):
        ProductArtifactWriters.write(
            value,
            tmp_path,
            snapshot=build_product_output_snapshot(value),
        )

    assert shutdown_calls == [(True, True)]


def test_writer_pool_is_bounded_to_three_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_counts: list[int] = []
    real_executor = writer_module.ThreadPoolExecutor

    class RecordingExecutor(real_executor):
        def __init__(self, max_workers: int, **kwargs: object) -> None:
            worker_counts.append(max_workers)
            super().__init__(max_workers=max_workers, **kwargs)

    monkeypatch.setattr(writer_module, "ThreadPoolExecutor", RecordingExecutor)
    value = collection()
    ProductArtifactWriters.write(
        value,
        tmp_path,
        snapshot=build_product_output_snapshot(value),
    )

    assert worker_counts == [3]
