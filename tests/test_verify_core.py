import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from scripts.verify_core import (
    CoverageThresholdError,
    WorkbookContractError,
    verify_controlled_workbook,
    verify_coverage,
)


def write_coverage(path: Path, names: dict[str, float]) -> None:
    report = {
        "files": {
            name: {"summary": {"percent_covered": percent}}
            for name, percent in names.items()
        }
    }
    path.write_text(json.dumps(report), encoding="utf-8")


@pytest.mark.parametrize(
    "names",
    [
        {"app/input_loader.py": 90, "app/matcher.py": 95, "app/sites/douban_movie.py": 91},
        {"app\\input_loader.py": 90, "app\\matcher.py": 95, "app\\sites\\douban_movie.py": 91},
    ],
)
def test_verify_coverage_accepts_platform_specific_keys(tmp_path: Path, names: dict[str, float]) -> None:
    report = tmp_path / "coverage.json"
    write_coverage(report, names)
    assert verify_coverage(report) == {
        "app/input_loader.py": 90,
        "app/matcher.py": 95,
        "app/sites/douban_movie.py": 91,
    }


def test_verify_coverage_rejects_a_module_below_80(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    write_coverage(
        report,
        {"app/input_loader.py": 90, "app/matcher.py": 95, "app/sites/douban_movie.py": 79},
    )
    with pytest.raises(CoverageThresholdError, match="douban_movie.py: 79.00%"):
        verify_coverage(report)


COLUMNS = [
    "task_id", "query", "query_year", "matched_title", "matched_year", "director",
    "rating", "detail_url", "match_method", "status", "error_message", "collected_at",
]


def write_workbook(
    path: Path,
    *,
    row_count: int = 10,
    duplicate_last_id: bool = False,
    status: str = "NOT_FOUND",
    collected_at: str | None = "2026-07-15T12:00:00+08:00",
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(COLUMNS)
    for index in range(row_count):
        task_id = "task-0" if duplicate_last_id and index == row_count - 1 else f"task-{index}"
        sheet.append([
            task_id, f"query-{index}", None, None, None, None,
            None, None, "NONE", status, "controlled fixture", collected_at,
        ])
    workbook.save(path)


@pytest.mark.parametrize("row_count", [1, 10])
def test_verify_controlled_workbook_accepts_one_to_ten_rows(
    tmp_path: Path, row_count: int
) -> None:
    workbook = tmp_path / "douban_movies.xlsx"
    write_workbook(workbook, row_count=row_count)
    assert verify_controlled_workbook(workbook) == {
        "data_rows": row_count,
        "unique_ids": row_count,
    }


@pytest.mark.parametrize("row_count", [0, 11])
def test_verify_controlled_workbook_rejects_row_count_outside_live_limit(
    tmp_path: Path, row_count: int
) -> None:
    workbook = tmp_path / "douban_movies.xlsx"
    write_workbook(workbook, row_count=row_count)
    with pytest.raises(WorkbookContractError, match="between 1 and 10"):
        verify_controlled_workbook(workbook)


def test_verify_controlled_workbook_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    workbook = tmp_path / "douban_movies.xlsx"
    write_workbook(workbook, duplicate_last_id=True)
    with pytest.raises(WorkbookContractError, match="unique task"):
        verify_controlled_workbook(workbook)


def test_verify_controlled_workbook_rejects_invalid_status(tmp_path: Path) -> None:
    workbook = tmp_path / "douban_movies.xlsx"
    write_workbook(workbook, status="INVALID")
    with pytest.raises(WorkbookContractError, match="invalid status"):
        verify_controlled_workbook(workbook)


def test_verify_controlled_workbook_rejects_missing_collected_at(tmp_path: Path) -> None:
    workbook = tmp_path / "douban_movies.xlsx"
    write_workbook(workbook, collected_at=None)
    with pytest.raises(WorkbookContractError, match="collected_at"):
        verify_controlled_workbook(workbook)


def test_verify_controlled_workbook_rejects_wrong_columns(tmp_path: Path) -> None:
    workbook_path = tmp_path / "douban_movies.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["wrong", *COLUMNS[1:]])
    sheet.append([
        "task-1", "query", None, None, None, None,
        None, None, "NONE", "NOT_FOUND", "fixture",
        "2026-07-15T12:00:00+08:00",
    ])
    workbook.save(workbook_path)
    with pytest.raises(WorkbookContractError, match="columns do not match"):
        verify_controlled_workbook(workbook_path)
