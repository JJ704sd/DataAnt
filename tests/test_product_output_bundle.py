import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


def test_failed_initial_directory_swap_raises_output_locked_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"
    bundle = ProductOutputBundle(target)
    bundle.write(collection("1"))
    original_json = (target / "products.json").read_bytes()

    real_replace = bundle_module.os.replace

    def fail_first_replace(source: Path, destination: Path) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(bundle_module.os, "replace", fail_first_replace)
    with pytest.raises(OutputLockedError):
        bundle.write(collection("2"))

    assert (target / "products.json").read_bytes() == original_json


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

    monkeypatch.setattr(bundle_module, "render_gallery", fail_gallery)
    with pytest.raises(RuntimeError, match="gallery writer failed"):
        bundle.write(collection("2"))

    assert (target / "products.json").read_bytes() == original_json
    assert not list(target.parent.glob(f".{target.name}.staging-*"))
    assert not list(target.parent.glob(f".{target.name}.backup-*"))


def test_staging_cleanup_does_not_mask_writer_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"

    def fail_gallery(*args, **kwargs):
        raise RuntimeError("gallery writer failed")

    def fail_cleanup(*args, **kwargs):
        raise OSError("cleanup failed")

    monkeypatch.setattr(bundle_module, "render_gallery", fail_gallery)
    monkeypatch.setattr(bundle_module.shutil, "rmtree", fail_cleanup)

    with pytest.raises(RuntimeError, match="gallery writer failed"):
        ProductOutputBundle(target).write(collection("1"))


def test_lock_release_does_not_mask_writer_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"

    monkeypatch.setattr(
        bundle_module,
        "render_gallery",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("gallery writer failed")
        ),
    )
    monkeypatch.setattr(
        bundle_module,
        "_release_file_lock",
        lambda _handle: (_ for _ in ()).throw(OSError("unlock failed")),
    )

    with pytest.raises(RuntimeError, match="gallery writer failed"):
        ProductOutputBundle(target).write(collection("1"))


@pytest.mark.skipif(os.name != "nt", reason="Windows lock semantics only")
def test_windows_lock_acquisition_has_a_bounded_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "demo.lock"
    handle = lock_path.open("a+b")
    try:
        monkeypatch.setattr(bundle_module, "BUNDLE_LOCK_TIMEOUT_SECONDS", 0.0)
        monkeypatch.setattr(
            bundle_module.msvcrt,
            "locking",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                OSError("locked")
            ),
        )
        with pytest.raises(OutputLockedError):
            bundle_module._acquire_file_lock(handle)
    finally:
        handle.close()


def test_writer_shutdown_cancels_pending_futures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"
    shutdown_calls: list[bool] = []
    real_executor = bundle_module.ThreadPoolExecutor

    class RecordingExecutor(real_executor):
        def shutdown(
            self, wait: bool = True, *, cancel_futures: bool = False
        ) -> None:
            shutdown_calls.append(cancel_futures)
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(bundle_module, "ThreadPoolExecutor", RecordingExecutor)
    ProductOutputBundle(target).write(collection("1"))

    assert shutdown_calls == [True]


def test_writer_active_counter_peaks_at_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"
    counter_lock = threading.Lock()
    counter = {"active": 0, "peak": 0}
    # Barrier ensures all three writers are simultaneously active so the
    # counter records the true peak concurrency, not a transient snapshot.
    barrier = threading.Barrier(3, timeout=5.0)

    def track_active():
        with counter_lock:
            counter["active"] += 1
            if counter["active"] > counter["peak"]:
                counter["peak"] = counter["active"]

    def release_active():
        with counter_lock:
            counter["active"] -= 1

    real_excel = bundle_module.ProductExcel.write
    real_write_text = bundle_module._write_text
    real_render_gallery = bundle_module.render_gallery

    def gated_excel(*args, **kwargs):
        track_active()
        try:
            barrier.wait()
            return real_excel(*args, **kwargs)
        finally:
            release_active()

    def gated_json(path, content):
        track_active()
        try:
            barrier.wait()
            return real_write_text(path, content)
        finally:
            release_active()

    def gated_gallery(collection, directory, snapshot):
        track_active()
        try:
            barrier.wait()
            # Bypass the wrapped _write_text to avoid a second barrier hit.
            return real_write_text(
                directory / "gallery.html",
                real_render_gallery(collection, snapshot=snapshot),
            )
        finally:
            release_active()

    monkeypatch.setattr(bundle_module.ProductExcel, "write", gated_excel)
    monkeypatch.setattr(bundle_module, "_write_text", gated_json)
    monkeypatch.setattr(
        bundle_module, "_render_and_write_gallery", gated_gallery
    )

    ProductOutputBundle(target).write(collection("1"))

    assert counter["peak"] == 3


def test_cleanup_stale_siblings_only_removes_generated_old_dirs(
    tmp_path: Path,
) -> None:
    target = tmp_path / "demo"
    stale = target.with_name(".demo.staging-old")
    fresh = target.with_name(".demo.backup-fresh")
    unrelated = target.with_name(".demo-not-generated")
    stale.mkdir()
    fresh.mkdir()
    unrelated.mkdir()
    old = time.time() - 48 * 60 * 60
    os.utime(stale, (old, old))

    ProductOutputBundle(target).cleanup_stale_siblings(
        max_age_seconds=24 * 60 * 60,
    )

    assert not stale.exists()
    assert fresh.exists()
    assert unrelated.exists()


def test_cleanup_stale_siblings_rejects_non_positive_threshold(
    tmp_path: Path,
) -> None:
    target = tmp_path / "demo"
    with pytest.raises(ValueError, match="max_age_seconds"):
        ProductOutputBundle(target).cleanup_stale_siblings(
            max_age_seconds=0,
        )
