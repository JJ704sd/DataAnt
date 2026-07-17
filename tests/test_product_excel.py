from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from app.product_excel import PRODUCT_COLUMNS, ProductExcel
from app.product_models import ProductRecord


def test_render_creates_products_sheet_with_exact_columns(tmp_path: Path) -> None:
    path = tmp_path / "products.xlsx"
    ProductExcel.write(path, [ProductRecord.success_fixture("1")])
    workbook = load_workbook(path)
    assert workbook.active.title == "products"
    rows = list(workbook.active.values)
    assert list(rows[0]) == PRODUCT_COLUMNS
    assert rows[1][0] == "1"
    assert rows[1][12] == "SUCCESS"


def test_merge_replaces_product_id_without_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "products.xlsx"
    ProductExcel.write(path, [ProductRecord.success_fixture("1")])
    updated = ProductRecord.success_fixture("1")
    merged = ProductExcel.merge_existing(path, [updated])
    assert [record.product_id for record in merged] == ["1"]


def test_wrong_existing_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "products.xlsx"
    workbook = Workbook()
    workbook.active.append(["wrong"])
    workbook.save(path)
    with pytest.raises(ValueError, match="product workbook schema"):
        ProductExcel.read(path)
