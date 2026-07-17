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
import uuid
from pathlib import Path

from app.excel_store import OutputLockedError
from app.product_excel import ProductExcel
from app.product_gallery import render_gallery
from app.product_json import render_product_json
from app.product_models import ProductCollection, ProductRecord


# Hard cap on the merged bundle. Mirrors the controlled
# ``--max-products`` ceiling (1..10) so multi-run accumulation cannot
# silently exceed the approved batch size.
BUNDLE_LIMIT: int = 10


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

    def write(self, new_collection: ProductCollection) -> None:
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

        staging_dir = self._sibling_path("staging")
        backup_dir: Path | None = None
        try:
            staging_dir.mkdir(parents=True)
            self._write_three(merged_collection, staging_dir)
            self._verify_consistent(merged_records, staging_dir)

            if self.target_dir.exists():
                backup_dir = self._sibling_path("backup")
                os.replace(self.target_dir, backup_dir)

            try:
                os.replace(staging_dir, self.target_dir)
            except OSError as exc:
                if (
                    backup_dir is not None
                    and backup_dir.exists()
                    and not self.target_dir.exists()
                ):
                    os.replace(backup_dir, self.target_dir)
                raise OutputLockedError(
                    f"Close open output files and retry: {self.target_dir}"
                ) from exc

            if backup_dir is not None and backup_dir.exists():
                shutil.rmtree(backup_dir)
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

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
        collection: ProductCollection, directory: Path
    ) -> None:
        ProductExcel.write(
            directory / "products.xlsx", list(collection.records)
        )
        (directory / "products.json").write_text(
            render_product_json(collection), encoding="utf-8"
        )
        (directory / "gallery.html").write_text(
            render_gallery(collection), encoding="utf-8"
        )

    @staticmethod
    def _verify_consistent(
        expected_records: list[ProductRecord], directory: Path
    ) -> None:
        expected_ids = [record.product_id for record in expected_records]
        excel_ids = [
            record.product_id
            for record in ProductExcel.read(directory / "products.xlsx")
        ]
        json_payload = json.loads(
            (directory / "products.json").read_text(encoding="utf-8")
        )
        json_ids = [
            str(item.get("product_id"))
            for item in json_payload.get("products", [])
        ]
        if excel_ids != expected_ids or json_ids != expected_ids:
            raise ValueError(
                "staging artifacts have inconsistent product order"
            )

    def _sibling_path(self, role: str) -> Path:
        suffix = uuid.uuid4().hex
        return self.target_dir.with_name(
            f".{self.target_dir.name}.{role}-{suffix}"
        )


__all__ = ["ProductOutputBundle", "BUNDLE_LIMIT"]
