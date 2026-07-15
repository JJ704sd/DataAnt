from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import load_workbook


REQUIRED_COVERAGE = {
    "app/input_loader.py": 80.0,
    "app/matcher.py": 80.0,
    "app/sites/douban_movie.py": 80.0,
}


class CoverageThresholdError(AssertionError):
    pass


EXPECTED_COLUMNS = [
    "task_id", "query", "query_year", "matched_title", "matched_year", "director",
    "rating", "detail_url", "match_method", "status", "error_message", "collected_at",
]
VALID_STATUSES = {
    "SUCCESS", "NOT_FOUND", "REVIEW_REQUIRED", "NETWORK_ERROR",
    "PAGE_CHANGED", "BLOCKED", "SITE_PROTECTION_CHALLENGE",
    "OUTPUT_LOCKED", "UNEXPECTED_ERROR",
}


class WorkbookContractError(AssertionError):
    pass


def verify_controlled_workbook(workbook_path: Path) -> dict[str, int]:
    if not workbook_path.is_file():
        raise WorkbookContractError("workbook is required")
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    rows = list(workbook.active.values)
    if not rows or list(rows[0]) != EXPECTED_COLUMNS:
        raise WorkbookContractError("workbook columns do not match the contract")
    data = rows[1:]
    if not 1 <= len(data) <= 10:
        raise WorkbookContractError("workbook must contain between 1 and 10 tasks")
    ids = [str(row[0]) for row in data]
    if len(set(ids)) != len(ids):
        raise WorkbookContractError("workbook must contain unique task ids")
    if any(row[9] not in VALID_STATUSES for row in data):
        raise WorkbookContractError("workbook contains an invalid status")
    if any(not row[11] for row in data):
        raise WorkbookContractError("collected_at must be populated")
    return {"data_rows": len(data), "unique_ids": len(set(ids))}


def verify_coverage(path: Path) -> dict[str, float]:
    report = json.loads(path.read_text(encoding="utf-8"))
    files = {name.replace("\\", "/"): data for name, data in report["files"].items()}
    actual: dict[str, float] = {}
    for name, threshold in REQUIRED_COVERAGE.items():
        percent = float(files[name]["summary"]["percent_covered"])
        if percent < threshold:
            raise CoverageThresholdError(f"{name}: {percent:.2f}% is below {threshold:.2f}%")
        actual[name] = percent
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage-json", type=Path, required=True)
    args = parser.parse_args()
    for name, percent in verify_coverage(args.coverage_json).items():
        print(f"{name}: {percent:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
