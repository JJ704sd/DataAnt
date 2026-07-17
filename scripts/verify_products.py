"""Offline contract verifier for the three-file product bundle.

The product collection command always commits its results as one
immutable bundle of three files inside a target directory:

- ``products.xlsx`` (15-column product workbook)
- ``products.json`` (versioned JSON snapshot)
- ``gallery.html`` (self-contained static gallery)

This module provides :func:`verify_product_bundle` which asserts the
three files are present, share the same product set, and contain no
external script / network dependencies. The verifier runs offline; it
never touches the live web-scraping.dev host and never launches a
browser. The CLI form is intentionally identical in shape to
``scripts.verify_core`` so the same portable gate pattern can be
reused.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import load_workbook

from app.product_excel import PRODUCT_COLUMNS
from app.product_models import ProductStatus


__all__ = [
    "ProductBundleContractError",
    "verify_product_bundle",
    "main",
]


class ProductBundleContractError(AssertionError):
    """Raised when a product bundle fails the offline contract check."""


_REQUIRED_BUNDLE_FILES: tuple[str, ...] = (
    "products.xlsx",
    "products.json",
    "gallery.html",
)

# HTML cannot include any of these tokens; each is a sign the gallery
# would reach outside its own embedded data on open.
_HTML_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "<script src=",
    "fetch(",
    "XMLHttpRequest",
    "WebSocket",
    "@import url(",
    "@font-face",
)


def _require_three_files(output_dir: Path) -> None:
    for name in _REQUIRED_BUNDLE_FILES:
        if not (output_dir / name).is_file():
            raise ProductBundleContractError(
                f"product bundle is missing required file: {name}"
            )


def _read_excel(output_dir: Path) -> tuple[list[str], list[tuple[object, ...]]]:
    workbook = load_workbook(
        output_dir / "products.xlsx", read_only=True, data_only=True
    )
    rows = list(workbook.active.values)
    if not rows:
        raise ProductBundleContractError(
            "workbook must contain a header row and at least one data row"
        )
    header = [str(cell) for cell in rows[0]]
    if header != list(PRODUCT_COLUMNS):
        raise ProductBundleContractError(
            "workbook columns do not match the 15-column product contract"
        )
    data = [tuple(row) for row in rows[1:]]
    return header, data


def _validate_excel_rows(
    header: list[str], data: list[tuple[object, ...]]
) -> list[str]:
    if not 1 <= len(data) <= 10:
        raise ProductBundleContractError(
            "workbook must contain between 1 and 10 products"
        )
    product_ids: list[str] = []
    for index, row in enumerate(data, start=1):
        if len(row) < len(header):
            raise ProductBundleContractError(
                f"workbook row {index} is shorter than the header"
            )
        product_id = str(row[0] or "").strip()
        if not product_id:
            raise ProductBundleContractError(
                f"workbook row {index} has an empty product_id"
            )
        product_ids.append(product_id)
        status = str(row[12] or "").strip()
        if status not in {member.value for member in ProductStatus}:
            raise ProductBundleContractError(
                f"workbook row {index} has invalid status {status!r}"
            )
        collected_at = row[14]
        if not collected_at or not str(collected_at).strip():
            raise ProductBundleContractError(
                f"workbook row {index} is missing collected_at"
            )
    if len(set(product_ids)) != len(product_ids):
        raise ProductBundleContractError(
            "workbook must contain unique product ids"
        )
    return product_ids


def _validate_json(
    output_dir: Path, expected_ids: list[str]
) -> list[dict[str, object]]:
    payload = json.loads((output_dir / "products.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ProductBundleContractError(
            "JSON schema_version must equal 1"
        )
    if payload.get("source_site") != "web-scraping.dev":
        raise ProductBundleContractError(
            "JSON source_site must be 'web-scraping.dev'"
        )
    if not isinstance(payload.get("summary"), dict):
        raise ProductBundleContractError(
            "JSON must include a summary block"
        )
    products = payload.get("products")
    if not isinstance(products, list):
        raise ProductBundleContractError(
            "JSON must include a products array"
        )
    json_ids = [str(item.get("product_id")) for item in products]
    if json_ids != expected_ids:
        raise ProductBundleContractError(
            "workbook and JSON have inconsistent product ids"
        )
    return products


def _validate_html(output_dir: Path, expected_ids: list[str]) -> None:
    html = (output_dir / "gallery.html").read_text(encoding="utf-8")
    for product_id in expected_ids:
        if product_id not in html:
            raise ProductBundleContractError(
                f"gallery.html is missing embedded product id {product_id!r}"
            )
    for token in _HTML_FORBIDDEN_TOKENS:
        if token in html:
            raise ProductBundleContractError(
                f"gallery.html contains an external dependency: {token!r}"
            )


def _count_statuses(products: list[dict[str, object]]) -> dict[str, int]:
    success = 0
    partial = 0
    for item in products:
        status = str(item.get("status") or "")
        if status == "SUCCESS":
            success += 1
        elif status == "PARTIAL":
            partial += 1
    failed = len(products) - success - partial
    return {"success": success, "partial": partial, "failed": failed}


def verify_product_bundle(output_dir: Path) -> dict[str, int]:
    """Validate the three-file product bundle and return status counts."""
    directory = Path(output_dir)
    _require_three_files(directory)
    _header, data = _read_excel(directory)
    product_ids = _validate_excel_rows(_header, data)
    products = _validate_json(directory, product_ids)
    _validate_html(directory, product_ids)
    counts = _count_statuses(products)
    return {
        "products": len(data),
        "unique_ids": len(set(product_ids)),
        "success": counts["success"],
        "partial": counts["partial"],
        "failed": counts["failed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the offline three-file product bundle in a target directory."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory containing products.xlsx, products.json and gallery.html",
    )
    args = parser.parse_args()
    summary = verify_product_bundle(args.output_dir)
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
