from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path

from app.models import Task


class InputError(ValueError):
    pass


def _task_id(query: str, year: str | None, occurrence: int) -> str:
    payload = f"{query.casefold()}\x1f{year or ''}\x1f{occurrence}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def load_tasks(path: Path) -> list[Task]:
    if not path.is_file():
        raise InputError(f"input path is not a file: {path}")

    tasks: list[Task] = []
    occurrences: Counter[tuple[str, str | None]] = Counter()

    with path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        if reader.fieldnames is None or "query" not in reader.fieldnames:
            raise InputError("input CSV must contain a query column")

        for row_number, row in enumerate(reader, start=2):
            query = (row.get("query") or "").strip()
            if not query:
                raise InputError(f"row {row_number}: query must not be empty")

            raw_year = row.get("year")
            year = raw_year.strip() if raw_year else None
            if year and (len(year) != 4 or not year.isdigit()):
                raise InputError(f"row {row_number}: year must be four digits")

            key = (query.casefold(), year)
            occurrences[key] += 1
            tasks.append(
                Task(
                    task_id=_task_id(query, year, occurrences[key]),
                    query=query,
                    query_year=year,
                )
            )

    return tasks
