from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from app.product_excel import ProductExcel, ProductWriteReceipt
from app.product_gallery import render_gallery
from app.product_models import ProductCollection
from app.product_output_snapshot import ProductOutputSnapshot


_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class ArtifactWriteReceipt:
    product_ids: tuple[str, ...]
    excel: ProductWriteReceipt
    bytes_by_file: dict[str, int]
    json_write_ms: float
    gallery_write_ms: float
    excel_write_ms: float


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


class ProductArtifactWriters:
    @staticmethod
    def write(
        collection: ProductCollection,
        directory: Path,
        *,
        snapshot: ProductOutputSnapshot,
    ) -> ArtifactWriteReceipt:
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
        return ArtifactWriteReceipt(
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


__all__ = ["ArtifactWriteReceipt", "ProductArtifactWriters"]
