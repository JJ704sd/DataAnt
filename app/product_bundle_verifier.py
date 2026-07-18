from __future__ import annotations

import json
import time
from pathlib import Path

from app.product_artifact_writers import ArtifactWriteReceipt
from app.product_output_snapshot import ProductOutputSnapshot


class ProductBundleVerifier:
    @staticmethod
    def verify(
        snapshot: ProductOutputSnapshot,
        receipt: ArtifactWriteReceipt,
        directory: Path,
    ) -> float:
        started = time.perf_counter()
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
        return (time.perf_counter() - started) * 1000.0


__all__ = ["ProductBundleVerifier"]
