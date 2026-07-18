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

This module is a thin orchestration façade. The immutable payload
snapshot lives in :mod:`app.product_output_snapshot`, the bounded
local artifact generation lives in :mod:`app.product_artifact_writers`,
the staging consistency check lives in :mod:`app.product_bundle_verifier`,
and the target locking, staging lifecycle, atomic swap, rollback, and
stale sibling cleanup live in :mod:`app.product_bundle_transaction`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from app.product_artifact_writers import ProductArtifactWriters
from app.product_bundle_transaction import ProductBundleTransaction
from app.product_bundle_verifier import ProductBundleVerifier
from app.product_excel import ProductExcel, ProductWriteReceipt
from app.product_models import ProductCollection, ProductRecord
from app.product_output_snapshot import build_product_output_snapshot


# Hard cap on the merged bundle. Mirrors the controlled
# ``--max-products`` ceiling (1..10) so multi-run accumulation cannot
# silently exceed the approved batch size.
BUNDLE_LIMIT: int = 10


@dataclass(frozen=True, slots=True)
class BundleWriteReceipt:
    product_ids: tuple[str, ...]
    excel: ProductWriteReceipt
    bytes_by_file: dict[str, int]
    payload_build_ms: float
    json_write_ms: float
    gallery_write_ms: float
    excel_write_ms: float
    verify_ms: float
    total_local_ms: float


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

        with self._transaction.staging_directory() as staging:
            artifact_receipt = ProductArtifactWriters.write(
                merged_collection,
                staging,
                snapshot=snapshot,
            )
            verify_ms = ProductBundleVerifier.verify(
                snapshot,
                artifact_receipt,
                staging,
            )
            self._transaction.commit(staging)

        return BundleWriteReceipt(
            product_ids=artifact_receipt.product_ids,
            excel=artifact_receipt.excel,
            bytes_by_file=dict(artifact_receipt.bytes_by_file),
            payload_build_ms=payload_build_ms,
            json_write_ms=artifact_receipt.json_write_ms,
            gallery_write_ms=artifact_receipt.gallery_write_ms,
            excel_write_ms=artifact_receipt.excel_write_ms,
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


__all__ = [
    "ProductOutputBundle",
    "BundleWriteReceipt",
    "BUNDLE_LIMIT",
]
