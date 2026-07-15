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


def write_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(COLUMNS)
    for index in range(10):
        sheet.append([
            f"task-{index}", f"query-{index}", None, None, None, None,
            None, None, "NONE", "NOT_FOUND", "controlled fixture",
            "2026-07-15T12:00:00+08:00",
        ])
    workbook.save(path)


def write_evidence(path: Path, approved: bool = True) -> None:
    path.write_text(
        json.dumps({
            "approval_reference": "APPROVAL-2026-07-15-001",
            "compliance_approved": approved,
            "approved_query_count": 10,
            "run_id": "controlled-demo-001",
            "completed_at": "2026-07-15T12:00:00+08:00",
        }),
        encoding="utf-8",
    )


def test_verify_controlled_workbook_accepts_approved_ten_rows(tmp_path: Path) -> None:
    workbook = tmp_path / "douban_movies.xlsx"
    evidence = tmp_path / "controlled-demo-evidence.json"
    write_workbook(workbook)
    write_evidence(evidence)
    assert verify_controlled_workbook(workbook, evidence) == {
        "data_rows": 10,
        "unique_ids": 10,
    }


def test_verify_controlled_workbook_rejects_missing_compliance_approval(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "douban_movies.xlsx"
    evidence = tmp_path / "controlled-demo-evidence.json"
    write_workbook(workbook)
    write_evidence(evidence, approved=False)
    with pytest.raises(WorkbookContractError, match="compliance approval"):
        verify_controlled_workbook(workbook, evidence)
