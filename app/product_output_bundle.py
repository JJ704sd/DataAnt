"""Atomic directory-level commit for the three product deliverables.

Wraps the standalone Excel, JSON, and HTML writers behind a single
``write`` call that always commits the three artifacts as one
immutable bundle. Writes go to a sibling staging directory first, then
the staging directory is renamed onto ``target_dir`` so the three files
on disk always correspond to the same :class:`ProductCollection`.

The previous bundle is held in a sibling backup directory during the
swap. If the second rename fails (typical cause: Excel or another
process has the workbook open), the backup is restored and a
:class:`OutputLockedError` is raised so the caller can surface the
existing ``OUTPUT_LOCKED`` semantic without losing the prior bundle.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, TypeVar

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - exercised by the Linux CI runner.
    import fcntl

from app.excel_store import OutputLockedError
from app.product_excel import ProductExcel, ProductWriteReceipt
from app.product_gallery import render_gallery
from app.product_json import (
    ProductOutputSnapshot,
    build_product_output_snapshot,
)
from app.product_models import ProductCollection, ProductRecord


# Hard cap on the merged bundle. Mirrors the controlled
# ``--max-products`` ceiling (1..10) so multi-run accumulation cannot
# silently exceed the approved batch size.
BUNDLE_LIMIT: int = 10
BUNDLE_LOCK_TIMEOUT_SECONDS: float = 30.0

_BUNDLE_LOCKS: dict[str, threading.RLock] = {}
_BUNDLE_LOCKS_GUARD = threading.Lock()
_T = TypeVar("_T")


def _lock_for_target(target_dir: Path) -> threading.RLock:
    """Return the process-wide lock for one canonical output directory."""
    key = str(target_dir.resolve())
    with _BUNDLE_LOCKS_GUARD:
        lock = _BUNDLE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _BUNDLE_LOCKS[key] = lock
        return lock


@contextmanager
def _target_lock(target_dir: Path):
    """Serialize writes in this process and across cooperating processes."""
    with _lock_for_target(target_dir):
        lock_path = target_dir.with_name(f".{target_dir.name}.lock")
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
            _acquire_file_lock(handle)
            try:
                yield
            finally:
                had_active_exception = sys.exc_info()[0] is not None
                try:
                    _release_file_lock(handle)
                except OSError:
                    if not had_active_exception:
                        raise


def _acquire_file_lock(handle) -> None:
    if os.name == "nt":
        deadline = time.monotonic() + BUNDLE_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise OutputLockedError(
                        "Timed out waiting for the product output lock"
                    ) from exc
                time.sleep(0.05)
    else:  # pragma: no cover - exercised by the Linux CI runner.
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_file_lock(handle) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover - exercised by the Linux CI runner.
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True, slots=True)
class BundleWriteReceipt:
    product_ids: tuple[str, ...]
    excel: ProductWriteReceipt
    bytes_by_file: dict[str, int]
    payload_build_ms: float = 0.0
    json_write_ms: float = 0.0
    gallery_write_ms: float = 0.0
    excel_write_ms: float = 0.0
    verify_ms: float = 0.0
    total_local_ms: float = 0.0


def _write_text(path: Path, content: str) -> int:
    path.write_text(content, encoding="utf-8")
    return path.stat().st_size


def _render_and_write_gallery(
    collection: ProductCollection,
    directory: Path,
    snapshot: ProductOutputSnapshot,
) -> int:
    return _write_text(
        directory / "gallery.html",
        render_gallery(collection, snapshot=snapshot),
    )


def _timed_call(
    function: Callable[..., _T], *args: object, **kwargs: object
) -> tuple[_T, float]:
    started = time.perf_counter()
    result = function(*args, **kwargs)
    return result, (time.perf_counter() - started) * 1000.0


class ProductOutputBundle:
    """Atomic three-file commit at a target directory.

    The constructor does not touch the target; the boundary check (that
    ``target_dir`` lives inside the caller's approved ``outputs/``
    root) is performed by the CLI before this class is instantiated.
    """

    def __init__(self, target_dir: Path) -> None:
        self.target_dir = Path(target_dir)
        self.target_dir.parent.mkdir(parents=True, exist_ok=True)

    def read_product_ids(self) -> list[str]:
        return [
            record.product_id
            for record in ProductExcel.read(self.target_dir / "products.xlsx")
        ]

    def cleanup_stale_siblings(
        self,
        *,
        max_age_seconds: float,
    ) -> tuple[Path, ...]:
        """Remove sibling staging/backup directories older than the threshold.

        Only matches the ``.{name}.staging-*`` and ``.{name}.backup-*``
        naming convention produced by :meth:`_sibling_path`; unrelated
        dotfiles in the same parent directory are left untouched. The
        caller is expected to invoke this once before creating a new
        staging directory so crashed runs cannot accumulate forever.
        """
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        prefix = f".{self.target_dir.name}."
        now = time.time()
        removed: list[Path] = []
        for candidate in self.target_dir.parent.iterdir():
            if not candidate.is_dir() or not candidate.name.startswith(prefix):
                continue
            if ".staging-" not in candidate.name and ".backup-" not in candidate.name:
                continue
            if now - candidate.stat().st_mtime > max_age_seconds:
                shutil.rmtree(candidate)
                removed.append(candidate)
        return tuple(removed)

    def write(self, new_collection: ProductCollection) -> BundleWriteReceipt:
        # The merge and directory swap must be one critical section. Without
        # this lock, two callers can both read the same old workbook and the
        # last directory rename silently drops one caller's records.
        with _target_lock(self.target_dir):
            return self._write_locked(new_collection)

    def _write_locked(
        self, new_collection: ProductCollection
    ) -> BundleWriteReceipt:
        started = time.perf_counter()
        merged_records = self._merged_records(new_collection)
        if len(merged_records) > BUNDLE_LIMIT:
            raise ValueError(
                f"product bundle cannot exceed {BUNDLE_LIMIT} products"
            )
        merged_collection = ProductCollection.from_records(
            list(merged_records),
            generated_at=new_collection.generated_at,
            blocked=new_collection.summary.blocked,
        )

        snapshot_started = time.perf_counter()
        snapshot = build_product_output_snapshot(merged_collection)
        payload_build_ms = (time.perf_counter() - snapshot_started) * 1000.0

        self.cleanup_stale_siblings(max_age_seconds=24 * 60 * 60)

        staging_dir = self._sibling_path("staging")
        backup_dir: Path | None = None
        try:
            staging_dir.mkdir(parents=True)
            receipt = self._write_three(
                merged_collection,
                staging_dir,
                snapshot=snapshot,
            )
            verify_started = time.perf_counter()
            self._verify_consistent(snapshot, receipt, staging_dir)
            verify_ms = (time.perf_counter() - verify_started) * 1000.0

            try:
                if self.target_dir.exists():
                    backup_dir = self._sibling_path("backup")
                    os.replace(self.target_dir, backup_dir)
                os.replace(staging_dir, self.target_dir)
            except OSError as exc:
                if (
                    backup_dir is not None
                    and backup_dir.exists()
                    and not self.target_dir.exists()
                ):
                    try:
                        os.replace(backup_dir, self.target_dir)
                    except OSError as restore_exc:
                        raise OutputLockedError(
                            "Close open output files and retry; "
                            f"previous bundle could not be restored: "
                            f"{self.target_dir}"
                        ) from restore_exc
                raise OutputLockedError(
                    f"Close open output files and retry: {self.target_dir}"
                ) from exc

            if backup_dir is not None and backup_dir.exists():
                shutil.rmtree(backup_dir)
        finally:
            if staging_dir.exists():
                had_active_exception = sys.exc_info()[0] is not None
                try:
                    shutil.rmtree(staging_dir)
                except OSError:
                    if not had_active_exception:
                        raise

        return replace(
            receipt,
            payload_build_ms=payload_build_ms,
            verify_ms=verify_ms,
            total_local_ms=(time.perf_counter() - started) * 1000.0,
        )

    # -- Internal helpers --------------------------------------------- #

    def _merged_records(
        self, new_collection: ProductCollection
    ) -> list[ProductRecord]:
        existing_workbook = self.target_dir / "products.xlsx"
        if not existing_workbook.exists():
            return list(new_collection.records)
        return ProductExcel.merge_existing(
            existing_workbook, list(new_collection.records)
        )

    @staticmethod
    def _write_three(
        collection: ProductCollection,
        directory: Path,
        *,
        snapshot: ProductOutputSnapshot,
    ) -> BundleWriteReceipt:
        executor = ThreadPoolExecutor(
            max_workers=3,
            thread_name_prefix="product-output",
        )
        try:
            excel_future = executor.submit(
                _timed_call,
                ProductExcel.write,
                directory / "products.xlsx",
                list(collection.records),
                primitive_rows=snapshot.product_rows,
            )
            json_future = executor.submit(
                _timed_call,
                _write_text,
                directory / "products.json",
                snapshot.json_text,
            )
            gallery_future = executor.submit(
                _timed_call,
                _render_and_write_gallery,
                collection,
                directory,
                snapshot,
            )
            excel_receipt, excel_ms = excel_future.result()
            json_bytes, json_ms = json_future.result()
            gallery_bytes, gallery_ms = gallery_future.result()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        return BundleWriteReceipt(
            product_ids=snapshot.product_ids,
            excel=excel_receipt,
            bytes_by_file={
                "products.xlsx": excel_receipt.bytes_written,
                "products.json": json_bytes,
                "gallery.html": gallery_bytes,
            },
            json_write_ms=json_ms,
            gallery_write_ms=gallery_ms,
            excel_write_ms=excel_ms,
        )

    @staticmethod
    def _verify_consistent(
        snapshot: ProductOutputSnapshot,
        receipt: BundleWriteReceipt,
        directory: Path,
    ) -> None:
        expected_ids = list(snapshot.product_ids)
        if list(receipt.excel.product_ids) != expected_ids:
            raise ValueError("staging Excel IDs do not match snapshot")
        payload = json.loads(
            (directory / "products.json").read_text(encoding="utf-8")
        )
        json_ids = [
            str(item.get("product_id"))
            for item in payload.get("products", [])
        ]
        if json_ids != expected_ids:
            raise ValueError("staging JSON IDs do not match snapshot")
        for filename in ("products.xlsx", "products.json", "gallery.html"):
            if not (directory / filename).is_file():
                raise ValueError(f"staging output is missing {filename}")

    def _sibling_path(self, role: str) -> Path:
        suffix = uuid.uuid4().hex
        return self.target_dir.with_name(
            f".{self.target_dir.name}.{role}-{suffix}"
        )


__all__ = [
    "ProductOutputBundle",
    "BundleWriteReceipt",
    "BUNDLE_LIMIT",
]
