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

Task 4 of the product output pipeline refactor moved the target
locking, staging lifecycle, atomic swap, rollback, and stale sibling
cleanup into :mod:`app.product_bundle_transaction`. This module now
delegates the lock and transaction concerns to
:class:`ProductBundleTransaction` and keeps the writer/verifier
orchestration in place until Task 5 fully replaces this façade.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, TypeVar

from app.excel_store import OutputLockedError
from app.product_bundle_transaction import ProductBundleTransaction
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
_T = TypeVar("_T")


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
        self._transaction = ProductBundleTransaction(self.target_dir)

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

        Delegates to :meth:`ProductBundleTransaction.cleanup_stale_siblings`
        so all stale-sibling rules live in one place.
        """
        return self._transaction.cleanup_stale_siblings(
            max_age_seconds=max_age_seconds,
        )

    def write(self, new_collection: ProductCollection) -> BundleWriteReceipt:
        # The merge and directory swap must be one critical section. Without
        # this lock, two callers can both read the same old workbook and the
        # last directory rename silently drops one caller's records.
        with self._transaction.locked():
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

        with self._transaction.staging_directory() as staging_dir:
            receipt = self._write_three(
                merged_collection,
                staging_dir,
                snapshot=snapshot,
            )
            verify_started = time.perf_counter()
            self._verify_consistent(snapshot, receipt, staging_dir)
            verify_ms = (time.perf_counter() - verify_started) * 1000.0

            self._transaction.commit(staging_dir)

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


__all__ = [
    "ProductOutputBundle",
    "BundleWriteReceipt",
    "BUNDLE_LIMIT",
]
