# Browser Bot Core Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic Python Demo that enters movie queries in a visible browser, extracts a verified Douban movie match, and idempotently writes every outcome to an `.xlsx` workbook.

**Architecture:** A CLI loads stable tasks from CSV and gives them to a serial runner. The runner owns retry/resume policy, while a DrissionPage session owns the local Chromium lifecycle, a Douban adapter owns site-specific actions/parsing, a pure matcher owns candidate selection, and an Excel store owns atomic upserts. Browser and storage interfaces remain injectable so most behavior is tested without live network access.

**Tech Stack:** Python 3.11/3.12, DrissionPage 4.1, installed Chrome/Edge, openpyxl, pytest, pytest-cov, standard-library argparse/logging/dataclasses/pathlib.

---

## Scope and execution prerequisites

- Source of truth: `SPEC.md` v1.0.
- This plan implements Spec stages 0–2 and the 10-query controlled Demo. It does not implement MiniMax; that is covered by `2026-07-15-minimax-candidate-matcher.md`.
- The current directory is not a Git repository. Task 1 initializes one so the frequent commit steps are executable.
- Before real Douban traffic, the named compliance owner must approve the target, fields, batch size, and request interval. If approval is unavailable, perform the browser smoke test against an authorized fixture/test page and do not bypass site controls.

## First-principles derivation

Build decisions must be justified from the outcome, not from framework popularity:

1. **Required outcome:** for every input query, produce exactly one durable row containing either verified data or an explicit failure state.
2. **Why a browser exists:** the user explicitly requires visible website input and query actions, and the target may render or navigate with JavaScript. If a documented, authorized API later satisfies the same requirement, prefer the API for data retrieval and retain the browser only for the required demonstration.
3. **Why Excel is not automated:** the required artifact is an `.xlsx` file, not a demonstration of desktop Excel clicks. Direct OOXML writing removes an unnecessary GUI, clipboard, focus, and installed-Office failure surface.
4. **Why matching is deterministic first:** exact title and year are observable facts. A probabilistic model cannot improve a unique factual match and must not sit on the success path.
5. **Why execution is serial:** correctness, auditability, and respectful request volume matter more than throughput for a 10-query Demo.
6. **Why every result is persisted immediately:** a browser or network process can fail between any two queries. Per-task atomic upsert makes completed work the recoverable state.
7. **Why live feasibility is checked before feature work:** site permission, reachability, block pages, and current locators are external facts. Execute Task 10's approval and one-query locator audit immediately after Task 1, before Tasks 2–9. Task 10 remains numbered by deliverable grouping, but it is an early gate, not a late polish step.

Non-negotiable invariants:

- one stable `task_id` maps to at most one workbook row;
- no silent drops and no first-result guessing;
- no bypass of a block, challenge, or authorization boundary;
- no secret in source, logs, workbook, screenshot, HTML snapshot, browser profile, or prompt;
- without network, login state, or LLM, deterministic logic and storage remain fully testable;
- a failed optional subsystem degrades to a named status instead of corrupting data.

## Final file map

```text
browser-bot-demo/
├── app/
│   ├── __init__.py
│   ├── main.py                 # CLI parsing, dependency wiring, exit codes
│   ├── models.py               # enums and immutable data records
│   ├── input_loader.py         # CSV validation and stable task IDs
│   ├── matcher.py              # pure deterministic matching rules
│   ├── excel_store.py          # workbook schema, idempotent upsert, atomic save
│   ├── browser_session.py      # DrissionPage Chromium/Tab/profile lifecycle
│   ├── runner.py               # serial orchestration, retries, resume policy
│   ├── diagnostics.py          # redacted logging and failure artifacts
│   └── sites/
│       ├── __init__.py
│       └── douban_movie.py     # Douban UI actions, candidates, detail parsing, block detection
├── tests/
│   ├── fixtures/
│   │   ├── search_results.html
│   │   ├── search_empty.html
│   │   ├── detail_movie.html
│   │   └── blocked.html
│   ├── test_input_loader.py
│   ├── test_matcher.py
│   ├── test_excel_store.py
│   ├── test_douban_parser.py
│   ├── test_runner.py
│   └── test_main.py
├── inputs/queries.example.csv
├── outputs/.gitkeep
├── artifacts/.gitkeep
├── browser-profile/.gitkeep
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

## Shared contracts used throughout the plan

The following names are fixed for all tasks:

- `Task(task_id, query, query_year)`
- `Candidate(title, year, kind, detail_url)`
- `MatchDecision(method, candidate_index, reason)`
- `MovieResult.from_task(task, ...)`
- `Status`: `SUCCESS`, `NOT_FOUND`, `REVIEW_REQUIRED`, `NETWORK_ERROR`, `PAGE_CHANGED`, `BLOCKED`, `OUTPUT_LOCKED`, `UNEXPECTED_ERROR`
- `MatchMethod`: `RULE_EXACT`, `RULE_YEAR`, `LLM`, `NONE`
- `DoubanMovieAdapter.search(tab, task)` and `DoubanMovieAdapter.fetch_detail(tab, task, candidate)`
- `ExcelStore.upsert(result)` and `ExcelStore.status_by_task_id()`
- `Runner.run(tasks)` returns a `RunSummary`

### Task 1: Initialize repository and installable skeleton

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `app/sites/__init__.py`
- Create: `inputs/queries.example.csv`
- Create: `.env.example`
- Create: `outputs/.gitkeep`
- Create: `artifacts/.gitkeep`
- Create: `browser-profile/.gitkeep`
- Test: `tests/test_main.py`

- [ ] **Step 1: Initialize Git and create the empty directory tree**

Run:

```powershell
git init
New-Item -ItemType Directory -Force app, app\sites, tests, tests\fixtures, inputs, outputs, artifacts, browser-profile
```

Expected: Git reports an initialized repository and every directory exists.

- [ ] **Step 2: Write the packaging and ignore files**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "browser-bot-demo"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
  "DrissionPage>=4.1.1,<4.2",
  "openpyxl>=3.1,<4",
]

[project.optional-dependencies]
dev = ["pytest>=8,<9", "pytest-cov>=5,<7"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

Create `.gitignore`:

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
htmlcov/
.env
browser-profile/*
!browser-profile/.gitkeep
outputs/*
!outputs/.gitkeep
artifacts/*
!artifacts/.gitkeep
```

Create `.env.example`:

```dotenv
# The core Demo does not require secrets.
# MiniMax variables are documented in the separate optional plan.
```

- [ ] **Step 3: Write a failing CLI help test**

Create `tests/test_main.py`:

```python
from app.main import build_parser


def test_run_command_requires_input_and_output() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--input", "in.csv", "--output", "out.xlsx"])
    assert args.command == "run"
    assert args.input == "in.csv"
    assert args.output == "out.xlsx"
    assert args.headed is True
```

Run:

```powershell
python -m pytest tests/test_main.py -v
```

Expected: FAIL because `app.main.build_parser` does not exist.

- [ ] **Step 4: Implement the minimal parser and install the environment**

Create empty `app/__init__.py` and `app/sites/__init__.py`, then create `app/main.py`:

```python
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="browser-bot-demo")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--headed", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--retry-status", action="append", default=[])
    return parser


def main() -> int:
    build_parser().parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `inputs/queries.example.csv`:

```csv
query,year
肖申克的救赎,1994
霸王别姬,1993
不存在的电影测试词,
```

Run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest tests/test_main.py -v
```

Expected: PASS, and Chromium installation exits with code 0.

- [ ] **Step 5: Commit the skeleton**

```powershell
git add .gitignore pyproject.toml app tests inputs outputs artifacts browser-profile .env.example
git commit -m "chore: initialize browser bot demo"
```

### Task 2: Define domain records and stable CSV task loading

**Files:**
- Create: `app/models.py`
- Create: `app/input_loader.py`
- Test: `tests/test_input_loader.py`

- [ ] **Step 1: Write failing tests for validation, BOM support, and duplicate IDs**

Create `tests/test_input_loader.py`:

```python
from pathlib import Path

import pytest

from app.input_loader import InputError, load_tasks


def test_load_tasks_supports_bom_and_optional_year(tmp_path: Path) -> None:
    source = tmp_path / "queries.csv"
    source.write_text("\ufeffquery,year\n肖申克的救赎,1994\n阿甘正传,\n", encoding="utf-8")
    tasks = load_tasks(source)
    assert [(t.query, t.query_year) for t in tasks] == [
        ("肖申克的救赎", "1994"),
        ("阿甘正传", None),
    ]


def test_duplicate_queries_receive_distinct_stable_ids(tmp_path: Path) -> None:
    source = tmp_path / "queries.csv"
    source.write_text("query,year\n英雄,2002\n英雄,2002\n", encoding="utf-8")
    first = load_tasks(source)
    second = load_tasks(source)
    assert first[0].task_id != first[1].task_id
    assert [t.task_id for t in first] == [t.task_id for t in second]


@pytest.mark.parametrize("body", ["year\n1994\n", "query,year\n,1994\n", "query,year\n电影,94\n"])
def test_invalid_csv_is_rejected(tmp_path: Path, body: str) -> None:
    source = tmp_path / "queries.csv"
    source.write_text(body, encoding="utf-8")
    with pytest.raises(InputError):
        load_tasks(source)
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
python -m pytest tests/test_input_loader.py -v
```

Expected: FAIL because `app.input_loader` does not exist.

- [ ] **Step 3: Implement the domain records**

Create `app/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class Status(StrEnum):
    SUCCESS = "SUCCESS"
    NOT_FOUND = "NOT_FOUND"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PAGE_CHANGED = "PAGE_CHANGED"
    BLOCKED = "BLOCKED"
    OUTPUT_LOCKED = "OUTPUT_LOCKED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


class MatchMethod(StrEnum):
    RULE_EXACT = "RULE_EXACT"
    RULE_YEAR = "RULE_YEAR"
    LLM = "LLM"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    query: str
    query_year: str | None


@dataclass(frozen=True, slots=True)
class Candidate:
    title: str
    year: str | None
    kind: str | None
    detail_url: str


@dataclass(frozen=True, slots=True)
class MatchDecision:
    method: MatchMethod
    candidate_index: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class MovieResult:
    task_id: str
    query: str
    query_year: str | None
    matched_title: str = ""
    matched_year: str | None = None
    director: str = ""
    rating: float | None = None
    detail_url: str = ""
    match_method: MatchMethod = MatchMethod.NONE
    status: Status = Status.UNEXPECTED_ERROR
    error_message: str = ""
    collected_at: str = ""

    @classmethod
    def from_task(cls, task: Task) -> "MovieResult":
        return cls(task_id=task.task_id, query=task.query, query_year=task.query_year)

    def stamped(self) -> "MovieResult":
        return replace(self, collected_at=datetime.now().astimezone().isoformat(timespec="seconds"))


@dataclass(frozen=True, slots=True)
class RunSummary:
    processed: int = 0
    skipped: int = 0
    blocked: bool = False
```

- [ ] **Step 4: Implement CSV loading and run the tests**

Create `app/input_loader.py`:

```python
from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path

from app.models import Task


class InputError(ValueError):
    pass


def _task_id(query: str, year: str | None, occurrence: int) -> str:
    raw = f"{query.casefold()}\x1f{year or ''}\x1f{occurrence}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def load_tasks(path: Path) -> list[Task]:
    if not path.is_file():
        raise InputError(f"Input file does not exist: {path}")
    counts: Counter[tuple[str, str | None]] = Counter()
    tasks: list[Task] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "query" not in reader.fieldnames:
            raise InputError("CSV must contain a query column")
        for row_number, row in enumerate(reader, start=2):
            query = (row.get("query") or "").strip()
            year = (row.get("year") or "").strip() or None
            if not query:
                raise InputError(f"Row {row_number}: query is empty")
            if year is not None and (len(year) != 4 or not year.isdigit()):
                raise InputError(f"Row {row_number}: year must be four digits")
            key = (query.casefold(), year)
            counts[key] += 1
            tasks.append(Task(_task_id(query, year, counts[key]), query, year))
    return tasks
```

Run:

```powershell
python -m pytest tests/test_input_loader.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit the input contract**

```powershell
git add app/models.py app/input_loader.py tests/test_input_loader.py
git commit -m "feat: add validated CSV task loading"
```

### Task 3: Implement deterministic candidate matching

**Files:**
- Create: `app/matcher.py`
- Test: `tests/test_matcher.py`

- [ ] **Step 1: Write failing matching tests**

Create `tests/test_matcher.py`:

```python
from app.matcher import choose_match, normalize_title
from app.models import Candidate, MatchMethod, Task


def candidate(title: str, year: str | None) -> Candidate:
    return Candidate(title, year, "电影", "https://movie.douban.com/subject/1/")


def test_normalize_title_handles_nfkc_case_and_spaces() -> None:
    assert normalize_title("  Ａ  Movie  ") == "a movie"


def test_unique_exact_title_is_selected() -> None:
    task = Task("1", "英雄", None)
    result = choose_match(task, [candidate("英雄", "2002"), candidate("英雄本色", "1986")])
    assert result.method == MatchMethod.RULE_EXACT
    assert result.candidate_index == 0


def test_year_breaks_an_exact_title_tie() -> None:
    task = Task("1", "英雄", "2002")
    result = choose_match(task, [candidate("英雄", "2002"), candidate("英雄", "2022")])
    assert result.method == MatchMethod.RULE_YEAR
    assert result.candidate_index == 0


def test_ambiguous_candidates_require_review() -> None:
    task = Task("1", "英雄", None)
    result = choose_match(task, [candidate("英雄", "2002"), candidate("英雄", "2022")])
    assert result.method == MatchMethod.NONE
    assert result.candidate_index is None
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
python -m pytest tests/test_matcher.py -v
```

Expected: FAIL because `app.matcher` does not exist.

- [ ] **Step 3: Implement normalization and explicit matching rules**

Create `app/matcher.py`:

```python
from __future__ import annotations

import re
import unicodedata

from app.models import Candidate, MatchDecision, MatchMethod, Task


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"\s+", " ", normalized)


def choose_match(task: Task, candidates: list[Candidate]) -> MatchDecision:
    query = normalize_title(task.query)
    exact = [i for i, item in enumerate(candidates) if normalize_title(item.title) == query]
    if len(exact) == 1:
        return MatchDecision(MatchMethod.RULE_EXACT, exact[0], "unique normalized title")
    if len(exact) > 1 and task.query_year:
        year_matches = [i for i in exact if candidates[i].year == task.query_year]
        if len(year_matches) == 1:
            return MatchDecision(MatchMethod.RULE_YEAR, year_matches[0], "title and year")
    return MatchDecision(MatchMethod.NONE, None, "no unique deterministic match")
```

- [ ] **Step 4: Run matcher tests and the full suite**

```powershell
python -m pytest tests/test_matcher.py -v
python -m pytest -q
```

Expected: matcher tests PASS and the full suite exits 0.

- [ ] **Step 5: Commit the matching rules**

```powershell
git add app/matcher.py tests/test_matcher.py
git commit -m "feat: add deterministic movie matching"
```

### Task 4: Build the idempotent atomic Excel store

**Files:**
- Create: `app/excel_store.py`
- Test: `tests/test_excel_store.py`

- [ ] **Step 1: Write failing workbook tests**

Create `tests/test_excel_store.py`:

```python
from pathlib import Path

from openpyxl import load_workbook

from app.excel_store import COLUMNS, ExcelStore
from app.models import MatchMethod, MovieResult, Status, Task


def success(task_id: str, title: str) -> MovieResult:
    return MovieResult.from_task(Task(task_id, title, "1994")).__class__(
        task_id=task_id,
        query=title,
        query_year="1994",
        matched_title=title,
        matched_year="1994",
        director="Director",
        rating=9.0,
        detail_url="https://movie.douban.com/subject/1/",
        match_method=MatchMethod.RULE_EXACT,
        status=Status.SUCCESS,
        collected_at="2026-07-15T12:00:00+08:00",
    )


def test_upsert_creates_exact_schema_and_replaces_same_task(tmp_path: Path) -> None:
    path = tmp_path / "result.xlsx"
    store = ExcelStore(path)
    store.upsert(success("a", "First"))
    store.upsert(success("a", "Updated"))
    workbook = load_workbook(path)
    rows = list(workbook.active.values)
    assert list(rows[0]) == COLUMNS
    assert len(rows) == 2
    assert rows[1][1] == "Updated"


def test_status_index_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "result.xlsx"
    ExcelStore(path).upsert(success("a", "Movie"))
    assert ExcelStore(path).status_by_task_id() == {"a": Status.SUCCESS}
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
python -m pytest tests/test_excel_store.py -v
```

Expected: FAIL because `app.excel_store` does not exist.

- [ ] **Step 3: Implement schema, upsert, and atomic replacement**

Create `app/excel_store.py`:

```python
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from openpyxl import Workbook, load_workbook

from app.models import MovieResult, Status


COLUMNS = [
    "task_id", "query", "query_year", "matched_title", "matched_year", "director",
    "rating", "detail_url", "match_method", "status", "error_message", "collected_at",
]


class OutputLockedError(OSError):
    pass


class ExcelStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _workbook(self):
        if self.path.exists():
            workbook = load_workbook(self.path)
            if [cell.value for cell in workbook.active[1]] != COLUMNS:
                raise ValueError("Existing workbook schema does not match the 12-column contract")
            return workbook
        workbook = Workbook()
        workbook.active.title = "movies"
        workbook.active.append(COLUMNS)
        return workbook

    def status_by_task_id(self) -> dict[str, Status]:
        if not self.path.exists():
            return {}
        workbook = self._workbook()
        return {str(row[0]): Status(str(row[9])) for row in workbook.active.iter_rows(min_row=2, values_only=True)}

    def upsert(self, result: MovieResult) -> None:
        workbook = self._workbook()
        sheet = workbook.active
        row_number = next(
            (row[0].row for row in sheet.iter_rows(min_row=2) if row[0].value == result.task_id),
            sheet.max_row + 1,
        )
        values = asdict(result)
        for column_number, name in enumerate(COLUMNS, start=1):
            value = values[name]
            sheet.cell(row=row_number, column=column_number, value=getattr(value, "value", value))
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            workbook.save(temporary)
            os.replace(temporary, self.path)
        except PermissionError as exc:
            raise OutputLockedError(f"Close Excel and retry: {self.path}") from exc
```

- [ ] **Step 4: Run workbook tests and inspect the generated workbook structurally**

```powershell
python -m pytest tests/test_excel_store.py -v
python -m pytest -q
```

Expected: both Excel tests PASS; full suite exits 0.

- [ ] **Step 5: Commit the store**

```powershell
git add app/excel_store.py tests/test_excel_store.py
git commit -m "feat: add atomic idempotent Excel output"
```

### Task 5: Parse Douban search/detail fixtures without network

**Files:**
- Create: `app/sites/douban_movie.py`
- Create: `tests/fixtures/search_results.html`
- Create: `tests/fixtures/search_empty.html`
- Create: `tests/fixtures/detail_movie.html`
- Create: `tests/fixtures/blocked.html`
- Test: `tests/test_douban_parser.py`

- [ ] **Step 1: Create minimal sanitized fixtures**

Create `tests/fixtures/search_results.html`:

```html
<html><body><div id="content"><div class="result-list">
  <div class="result"><a href="https://movie.douban.com/subject/1292052/">肖申克的救赎</a><span>1994 / 电影</span></div>
  <div class="result"><a href="https://movie.douban.com/subject/9999999/">肖申克</a><span>2010 / 短片</span></div>
</div></div></body></html>
```

Create `tests/fixtures/search_empty.html`:

```html
<html><body><div id="content"><div class="result-list"></div><p>没有找到相关内容</p></div></body></html>
```

Create `tests/fixtures/detail_movie.html`:

```html
<html><body><h1><span property="v:itemreviewed">肖申克的救赎</span><span class="year">(1994)</span></h1>
<div id="info"><a rel="v:directedBy">弗兰克·德拉邦特</a></div>
<strong property="v:average">9.7</strong></body></html>
```

Create `tests/fixtures/blocked.html`:

```html
<html><body><h1>检测到有异常请求</h1><p>你的 IP 访问频率过高</p></body></html>
```

- [ ] **Step 2: Write failing parser tests**

Create `tests/test_douban_parser.py`:

```python
from pathlib import Path

from app.models import Status, Task
from app.sites.douban_movie import DoubanMovieAdapter


FIXTURES = Path(__file__).parent / "fixtures"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_search_candidates() -> None:
    candidates = DoubanMovieAdapter.parse_search_html(html("search_results.html"))
    assert [(c.title, c.year) for c in candidates] == [("肖申克的救赎", "1994"), ("肖申克", "2010")]


def test_parse_detail_allows_rating_but_requires_title_and_url() -> None:
    task = Task("a", "肖申克的救赎", "1994")
    result = DoubanMovieAdapter.parse_detail_html(
        html("detail_movie.html"), task, "https://movie.douban.com/subject/1292052/"
    )
    assert result.status == Status.SUCCESS
    assert result.rating == 9.7
    assert result.director == "弗兰克·德拉邦特"


def test_blocked_text_is_detected() -> None:
    assert DoubanMovieAdapter.is_blocked(html("blocked.html"), 200)
    assert DoubanMovieAdapter.is_blocked("", 429)
```

- [ ] **Step 3: Run tests to verify failure**

```powershell
python -m pytest tests/test_douban_parser.py -v
```

Expected: FAIL because `DoubanMovieAdapter` does not exist.

- [ ] **Step 4: Implement pure HTML parsing without a browser process**

Create `app/sites/douban_movie.py` with pure helpers backed by the standard-library HTML parser, keeping live Page methods for Task 6:

```python
from __future__ import annotations

import re
from dataclasses import replace

from app.models import Candidate, MatchMethod, MovieResult, Status, Task


DETAIL_URL = re.compile(r"^https://movie\.douban\.com/subject/\d+/$")
BLOCK_TEXT = ("访问频率过高", "异常请求", "验证码")


class DoubanMovieAdapter:
    @staticmethod
    def is_blocked(html: str, status_code: int | None) -> bool:
        return status_code in {403, 418, 429} or any(marker in html for marker in BLOCK_TEXT)

    @staticmethod
    def parse_search_html(html: str) -> list[Candidate]:
        links = re.findall(r'<a[^>]+href="(https://movie\.douban\.com/subject/\d+/)"[^>]*>([^<]+)</a>\s*<span>(\d{4})\s*/\s*([^<]+)</span>', html)
        return [Candidate(title.strip(), year, kind.strip(), url) for url, title, year, kind in links[:5]]

    @staticmethod
    def parse_detail_html(html: str, task: Task, url: str) -> MovieResult:
        title = re.search(r'property="v:itemreviewed"[^>]*>([^<]+)', html)
        year = re.search(r'class="year"[^>]*>\((\d{4})\)', html)
        directors = re.findall(r'rel="v:directedBy"[^>]*>([^<]+)', html)
        rating = re.search(r'property="v:average"[^>]*>([^<]*)', html)
        if title is None or DETAIL_URL.fullmatch(url) is None:
            return replace(MovieResult.from_task(task), status=Status.PAGE_CHANGED, error_message="Missing title or canonical detail URL").stamped()
        rating_value = float(rating.group(1)) if rating and rating.group(1).strip() else None
        return replace(
            MovieResult.from_task(task),
            matched_title=title.group(1).strip(),
            matched_year=year.group(1) if year else None,
            director=" / ".join(directors),
            rating=rating_value,
            detail_url=url,
            match_method=MatchMethod.NONE,
            status=Status.SUCCESS,
        ).stamped()
```

Run:

```powershell
python -m pytest tests/test_douban_parser.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit fixtures and parser contract**

```powershell
git add app/sites/douban_movie.py tests/fixtures tests/test_douban_parser.py
git commit -m "feat: add fixture-backed Douban parsing"
```

### Task 6: Add DrissionPage browser lifecycle and live UI actions

**Files:**
- Create: `app/browser_session.py`
- Modify: `app/sites/douban_movie.py`
- Test: `tests/test_browser_session.py`
- Test: `tests/test_douban_parser.py`

- [ ] **Step 1: Add a failing URL canonicalization and locator-contract test**

Append to `tests/test_douban_parser.py`:

```python
def test_adapter_exposes_a_small_locator_contract() -> None:
    assert DoubanMovieAdapter.SEARCH_INPUTS == (
        "@role=searchbox",
        "css:input[name='search_text']",
    )
```

Run:

```powershell
python -m pytest tests/test_douban_parser.py::test_adapter_exposes_a_small_locator_contract -v
```

Expected: FAIL because `SEARCH_INPUTS` is undefined.

Create `tests/test_browser_session.py` before implementing the session:

```python
from pathlib import Path

import pytest

from app.browser_session import find_browser_executable


def test_explicit_browser_path_is_used(tmp_path: Path) -> None:
    executable = tmp_path / "chrome.exe"
    executable.touch()
    assert find_browser_executable(executable) == executable


def test_missing_explicit_browser_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        find_browser_executable(tmp_path / "missing.exe")
```

Run `python -m pytest tests/test_browser_session.py -v` and confirm collection fails because `app.browser_session` does not exist.

- [ ] **Step 2: Implement the browser session context manager**

Create `app/browser_session.py`:

```python
from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
import socket

from DrissionPage import Chromium, ChromiumOptions


WINDOWS_BROWSER_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def find_browser_executable(explicit: Path | None = None) -> Path:
    candidates = (explicit,) if explicit is not None else WINDOWS_BROWSER_PATHS
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError("Chrome or Edge executable was not found")


def _free_local_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class BrowserSession(AbstractContextManager[object]):
    def __init__(
        self,
        headed: bool,
        artifacts_dir: Path,
        profile_dir: Path,
        browser_path: Path | None = None,
    ) -> None:
        self.headed = headed
        self.artifacts_dir = artifacts_dir
        self.profile_dir = profile_dir
        self.browser_path = browser_path
        self._browser: Chromium | None = None

    def __enter__(self):
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        options = (
            ChromiumOptions()
            .set_browser_path(find_browser_executable(self.browser_path))
            .set_local_port(_free_local_port())
            .set_user_data_path(self.profile_dir)
        )
        if not self.headed:
            options.headless()
        self._browser = Chromium(addr_or_opts=options)
        return self._browser.latest_tab

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._browser:
            self._browser.quit()
```

- [ ] **Step 3: Add live search and detail methods to the adapter**

Add these imports and methods to `DoubanMovieAdapter`:

```python
from DrissionPage.common import wait_until


class BlockedError(RuntimeError):
    pass


class PageChangedError(RuntimeError):
    pass


class NetworkError(RuntimeError):
    pass


class DoubanMovieAdapter:
    SEARCH_INPUTS = (
        "@role=searchbox",
        "css:input[name='search_text']",
    )

    def _search_input(self, tab):
        for locator in self.SEARCH_INPUTS:
            element = tab.ele(locator, timeout=1)
            if element:
                return element
        raise PageChangedError("Search input was not found")

    def search(self, tab, task: Task) -> list[Candidate]:
        if not tab.get("https://movie.douban.com/", retry=0, timeout=20):
            raise NetworkError("Douban navigation failed")
        if self.is_blocked(tab.html, None):
            raise BlockedError("Douban blocked the batch")
        self._search_input(tab).input(f"{task.query}\n", clear=True)
        try:
            wait_until(
                lambda: bool(tab.ele("css:.result-list", timeout=0)) or "没有找到" in tab.html,
                timeout=10,
            )
        except TimeoutError as exc:
            raise PageChangedError("Search result marker was not found") from exc
        html = tab.html
        if self.is_blocked(html, None):
            raise BlockedError("Douban blocked the batch")
        return self.parse_search_html(html)

    def fetch_detail(self, tab, task: Task, candidate: Candidate) -> MovieResult:
        if not tab.get(candidate.detail_url, retry=0, timeout=20):
            raise NetworkError("Douban detail navigation failed")
        html = tab.html
        if self.is_blocked(html, None):
            raise BlockedError("Douban blocked the batch")
        return self.parse_detail_html(html, task, tab.url)
```

Do not add `time.sleep()` for page synchronization. The runner adds a request interval separately.

- [ ] **Step 4: Run offline tests and a local browser launch check**

```powershell
python -m pytest tests/test_douban_parser.py -v
python -c "from pathlib import Path; from app.browser_session import BrowserSession; s=BrowserSession(True, Path('artifacts'), Path('browser-profile/smoke')); t=s.__enter__(); print(t.url); s.__exit__(None,None,None)"
```

Expected: parser tests PASS, a visible installed Chrome/Edge opens, and the command exits 0. Delete `browser-profile/smoke/` after the check; never commit it.

- [ ] **Step 5: Commit browser integration**

```powershell
git add app/browser_session.py app/sites/douban_movie.py tests/test_browser_session.py tests/test_douban_parser.py
git commit -m "feat: add DrissionPage browser actions"
```

### Task 7: Implement serial orchestration, retry policy, and resume

**Files:**
- Create: `app/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write failing runner tests with fakes**

Create `tests/test_runner.py`:

```python
from app.models import Candidate, MovieResult, Status, Task
from app.runner import Runner


class FakeStore:
    def __init__(self, statuses=None):
        self.statuses = statuses or {}
        self.results = []

    def status_by_task_id(self):
        return dict(self.statuses)

    def upsert(self, result):
        self.results.append(result)
        self.statuses[result.task_id] = result.status


class FakeAdapter:
    def search(self, page, task):
        if task.query == "missing":
            return []
        return [Candidate(task.query, task.query_year, "电影", "https://movie.douban.com/subject/1/")]

    def fetch_detail(self, page, task, candidate):
        return MovieResult.from_task(task).__class__(
            task_id=task.task_id, query=task.query, query_year=task.query_year,
            matched_title=task.query, detail_url=candidate.detail_url, status=Status.SUCCESS,
        ).stamped()


def test_runner_skips_existing_success_and_upserts_not_found() -> None:
    store = FakeStore({"done": Status.SUCCESS})
    runner = Runner(FakeAdapter(), store, page=object(), min_interval_seconds=0)
    summary = runner.run([Task("done", "done", None), Task("new", "missing", None)])
    assert summary.skipped == 1
    assert store.results[0].status == Status.NOT_FOUND


def test_runner_sets_review_required_for_ambiguous_match() -> None:
    class Ambiguous(FakeAdapter):
        def search(self, page, task):
            return [
                Candidate(task.query, "2002", "电影", "https://movie.douban.com/subject/1/"),
                Candidate(task.query, "2022", "电影", "https://movie.douban.com/subject/2/"),
            ]
    store = FakeStore()
    Runner(Ambiguous(), store, object(), 0).run([Task("a", "英雄", None)])
    assert store.results[0].status == Status.REVIEW_REQUIRED
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
python -m pytest tests/test_runner.py -v
```

Expected: FAIL because `app.runner` does not exist.

- [ ] **Step 3: Implement terminal-state skipping and per-task state transitions**

Create `app/runner.py`:

```python
from __future__ import annotations

import time
from dataclasses import replace

from app.matcher import choose_match
from app.models import MatchMethod, MovieResult, RunSummary, Status, Task
from app.sites.douban_movie import BlockedError, NetworkError, PageChangedError


DEFAULT_RETRY = {Status.NETWORK_ERROR, Status.OUTPUT_LOCKED, Status.UNEXPECTED_ERROR}


class Runner:
    def __init__(self, adapter, store, page, min_interval_seconds: float = 5, retry_statuses=None) -> None:
        self.adapter = adapter
        self.store = store
        self.page = page
        self.min_interval_seconds = min_interval_seconds
        self.retry_statuses = DEFAULT_RETRY | set(retry_statuses or [])

    def run(self, tasks: list[Task]) -> RunSummary:
        statuses = self.store.status_by_task_id()
        processed = skipped = 0
        for task in tasks:
            previous = statuses.get(task.task_id)
            if previous is not None and previous not in self.retry_statuses:
                skipped += 1
                continue
            started = time.monotonic()
            try:
                candidates = self.adapter.search(self.page, task)
                if not candidates:
                    result = replace(MovieResult.from_task(task), status=Status.NOT_FOUND, error_message="No candidates").stamped()
                else:
                    decision = choose_match(task, candidates)
                    if decision.candidate_index is None:
                        result = replace(
                            MovieResult.from_task(task), status=Status.REVIEW_REQUIRED,
                            error_message=decision.reason,
                        ).stamped()
                    else:
                        result = self.adapter.fetch_detail(self.page, task, candidates[decision.candidate_index])
                        result = replace(result, match_method=decision.method)
                self.store.upsert(result)
                processed += 1
            except BlockedError as exc:
                self.store.upsert(replace(MovieResult.from_task(task), status=Status.BLOCKED, error_message=str(exc)).stamped())
                return RunSummary(processed + 1, skipped, True)
            except PageChangedError as exc:
                self.store.upsert(replace(MovieResult.from_task(task), status=Status.PAGE_CHANGED, error_message=str(exc)).stamped())
                processed += 1
            elapsed = time.monotonic() - started
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)
        return RunSummary(processed, skipped, False)
```

- [ ] **Step 4: Run runner tests and full suite**

```powershell
python -m pytest tests/test_runner.py -v
python -m pytest -q
```

Expected: runner tests PASS and full suite exits 0.

- [ ] **Step 5: Commit orchestration**

```powershell
git add app/runner.py tests/test_runner.py
git commit -m "feat: add resumable serial runner"
```

### Task 8: Add diagnostics, redaction, and failure artifacts

**Files:**
- Create: `app/diagnostics.py`
- Modify: `app/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write a failing redaction test**

Append to `tests/test_runner.py`:

```python
from app.diagnostics import redact


def test_redact_removes_secret_and_cookie_values() -> None:
    text = "MINIMAX_API_KEY=secret-value Cookie: bid=abc; dbcl2=xyz"
    cleaned = redact(text)
    assert "secret-value" not in cleaned
    assert "dbcl2=xyz" not in cleaned
```

- [ ] **Step 2: Run the test to verify failure**

```powershell
python -m pytest tests/test_runner.py::test_redact_removes_secret_and_cookie_values -v
```

Expected: FAIL because `app.diagnostics` does not exist.

- [ ] **Step 3: Implement log configuration, redaction, and screenshots**

Create `app/diagnostics.py`:

```python
from __future__ import annotations

import logging
import re
from pathlib import Path


SECRET_PATTERNS = (
    re.compile(r"(?i)(MINIMAX_API_KEY\s*=\s*)[^\s]+"),
    re.compile(r"(?i)(Cookie:\s*)[^\r\n]+"),
)


def redact(value: str) -> str:
    for pattern in SECRET_PATTERNS:
        value = pattern.sub(r"\1[REDACTED]", value)
    return value


def configure_logging(artifacts_dir: Path) -> logging.Logger:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("browser_bot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.StreamHandler(), logging.FileHandler(artifacts_dir / "run.log", encoding="utf-8")):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def capture_failure(tab, artifacts_dir: Path, task_id: str) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tab.get_screenshot(path=artifacts_dir, name=f"{task_id}.png", full_page=True)
    sanitized_html = redact(tab.html)[:200_000]
    (artifacts_dir / f"{task_id}.html").write_text(sanitized_html, encoding="utf-8")
```

- [ ] **Step 4: Replace Runner with an explicit fail-closed retry and diagnostics implementation**

Keep `DEFAULT_RETRY` and replace the `Runner` class in `app/runner.py` with the following. Import `logging`, `Path`, `Callable`, `TypeVar`, the adapter's `NetworkError`, `capture_failure`, and `OutputLockedError`; `OutputLockedError` is deliberately re-raised for CLI exit code 4.

```python
T = TypeVar("T")


class Runner:
    def __init__(
        self,
        adapter,
        store,
        page,
        min_interval_seconds: float = 5,
        retry_statuses=None,
        logger: logging.Logger | None = None,
        artifacts_dir: Path | None = None,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.page = page
        self.min_interval_seconds = min_interval_seconds
        self.retry_statuses = DEFAULT_RETRY | set(retry_statuses or [])
        self.logger = logger or logging.getLogger("browser_bot")
        self.artifacts_dir = artifacts_dir

    def _network_operation(self, operation: Callable[[], T]) -> T:
        last_error: NetworkError | None = None
        for wait_seconds in (0, 2, 5):
            if wait_seconds:
                time.sleep(wait_seconds)
            try:
                return operation()
            except NetworkError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _persist(self, result: MovieResult) -> None:
        self.store.upsert(result)
        self.logger.info("task_id=%s status=%s", result.task_id, result.status.value)
        if result.status in {Status.NETWORK_ERROR, Status.PAGE_CHANGED, Status.BLOCKED, Status.UNEXPECTED_ERROR}:
            if self.artifacts_dir is not None and hasattr(self.page, "get_screenshot"):
                capture_failure(self.page, self.artifacts_dir, result.task_id)

    def run(self, tasks: list[Task]) -> RunSummary:
        statuses = self.store.status_by_task_id()
        processed = skipped = 0
        for task in tasks:
            previous = statuses.get(task.task_id)
            if previous is not None and previous not in self.retry_statuses:
                skipped += 1
                continue
            started = time.monotonic()
            try:
                candidates = self._network_operation(lambda: self.adapter.search(self.page, task))
                if not candidates:
                    result = replace(MovieResult.from_task(task), status=Status.NOT_FOUND, error_message="No candidates").stamped()
                else:
                    decision = choose_match(task, candidates)
                    if decision.candidate_index is None:
                        result = replace(
                            MovieResult.from_task(task),
                            status=Status.REVIEW_REQUIRED,
                            error_message=decision.reason,
                        ).stamped()
                    else:
                        result = self._network_operation(
                            lambda: self.adapter.fetch_detail(self.page, task, candidates[decision.candidate_index])
                        )
                        result = replace(result, match_method=decision.method)
                self._persist(result)
                processed += 1
            except BlockedError as exc:
                result = replace(MovieResult.from_task(task), status=Status.BLOCKED, error_message=str(exc)).stamped()
                self._persist(result)
                return RunSummary(processed + 1, skipped, True)
            except PageChangedError as exc:
                result = replace(MovieResult.from_task(task), status=Status.PAGE_CHANGED, error_message=str(exc)).stamped()
                self._persist(result)
                processed += 1
            except NetworkError as exc:
                result = replace(MovieResult.from_task(task), status=Status.NETWORK_ERROR, error_message=str(exc)[:200]).stamped()
                self._persist(result)
                processed += 1
            except OutputLockedError:
                raise
            except Exception as exc:
                result = replace(MovieResult.from_task(task), status=Status.UNEXPECTED_ERROR, error_message=type(exc).__name__).stamped()
                self._persist(result)
                processed += 1
            elapsed = time.monotonic() - started
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)
        return RunSummary(processed, skipped, False)
```

Run:

```powershell
python -m pytest tests/test_runner.py -v
python -m pytest -q
```

Expected: all tests PASS and the redaction assertion proves secrets are absent.

- [ ] **Step 5: Commit diagnostics**

```powershell
git add app/diagnostics.py app/runner.py tests/test_runner.py
git commit -m "feat: add redacted failure diagnostics"
```

### Task 9: Wire the CLI and exit codes end to end

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write failing CLI wiring tests using dependency injection**

Append to `tests/test_main.py`:

```python
from pathlib import Path

from app.main import execute


def test_missing_input_returns_exit_2(tmp_path: Path) -> None:
    code = execute(["run", "--input", str(tmp_path / "missing.csv"), "--output", str(tmp_path / "out.xlsx")])
    assert code == 2
```

- [ ] **Step 2: Run the test to verify failure**

```powershell
python -m pytest tests/test_main.py::test_missing_input_returns_exit_2 -v
```

Expected: FAIL because `execute` does not exist.

- [ ] **Step 3: Implement CLI wiring and status parsing**

Replace `app/main.py` with:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from app.browser_session import BrowserSession
from app.diagnostics import configure_logging
from app.excel_store import ExcelStore, OutputLockedError
from app.input_loader import InputError, load_tasks
from app.models import Status
from app.runner import Runner
from app.sites.douban_movie import DoubanMovieAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="browser-bot-demo")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--headed", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--retry-status", action="append", default=[])
    run.add_argument("--min-interval", type=float, default=5.0)
    run.add_argument("--browser-path")
    run.add_argument("--profile-dir", default="browser-profile/douban")
    return parser


def execute(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifacts = Path("artifacts")
    logger = configure_logging(artifacts)
    try:
        tasks = load_tasks(Path(args.input))
        retry = {Status(value) for value in args.retry_status}
        store = ExcelStore(Path(args.output))
        browser_path = Path(args.browser_path) if args.browser_path else None
        with BrowserSession(args.headed, artifacts, Path(args.profile_dir), browser_path) as tab:
            summary = Runner(DoubanMovieAdapter(), store, tab, args.min_interval, retry, logger, artifacts).run(tasks)
        return 3 if summary.blocked else 0
    except (InputError, ValueError) as exc:
        logger.error(str(exc))
        return 2
    except OutputLockedError as exc:
        logger.error(str(exc))
        return 4
    except Exception as exc:
        logger.exception("Global failure: %s", exc)
        return 5


def main() -> int:
    return execute()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests and print help**

```powershell
python -m pytest tests/test_main.py -v
python -m app.main --help
python -m app.main run --help
```

Expected: tests PASS and both help commands exit 0 with documented options.

- [ ] **Step 5: Commit the executable CLI**

```powershell
git add app/main.py tests/test_main.py
git commit -m "feat: wire browser bot CLI"
```

### Task 10: Verify current live locators with DrissionPage headed audit

**Files:**
- Modify: `app/sites/douban_movie.py`
- Modify: `tests/fixtures/search_results.html`
- Modify: `tests/fixtures/detail_movie.html`
- Create: `artifacts/locator-audit.md` (runtime artifact; do not commit)

- [ ] **Step 1: Record approval and test constraints before opening Douban**

Create `artifacts/locator-audit.md` locally with this filled record:

```markdown
# Locator audit
- Date/time:
- Operator:
- Compliance approval reference:
- Allowed target: movie.douban.com
- Allowed queries: 1
- Minimum interval: 5 seconds
- Browser: installed Chrome/Edge via DrissionPage
```

Expected: every field has a real value; if approval reference cannot be filled, stop this task.

- [ ] **Step 2: Run exactly one approved query in headed mode**

Run:

```powershell
python -m app.main run --input .\artifacts\locator-audit-input.csv --output .\outputs\locator-audit.xlsx --headed --min-interval 5
```

Before running, create the untracked runtime file `artifacts/locator-audit-input.csv` with exactly `query,year` and the one approved query row. Expected: installed Chrome/Edge opens through DrissionPage, executes exactly the approved query, and then closes. If a block or challenge appears, stop immediately; do not retry or bypass it.

- [ ] **Step 3: Update only verified locator candidates**

For the search input, prefer this order:

```python
SEARCH_INPUTS = (
    "@role=searchbox",
    "css:input[name='search_text']",
)
```

Use DrissionPage's `ele()`/`eles()` and `tree()` output only for the approved page. For candidates, use the smallest stable container and canonical `/subject/<id>/` links observed in the headed audit. For details, retain semantic property attributes only if present. Do not add long `nth-child` selectors or XPath tied to layout.

- [ ] **Step 4: Refresh sanitized fixtures and rerun offline tests**

Copy only the minimal DOM nodes needed by the parser into fixtures; remove account names, cookies, request headers, recommendations, and comments.

Run:

```powershell
python -m pytest tests/test_douban_parser.py -v
```

Expected: all parser tests PASS against the refreshed fixtures.

- [ ] **Step 5: Commit verified contracts, not runtime artifacts**

```powershell
git add app/sites/douban_movie.py tests/fixtures tests/test_douban_parser.py
git commit -m "test: verify current Douban locator contracts"
```

### Task 11: Add README and controlled Demo procedure

**Files:**
- Create: `README.md`
- Modify: `inputs/queries.example.csv`

- [ ] **Step 1: Write README prerequisites and exact install commands**

Include:

````markdown
# Browser Bot Demo

## Prerequisites
- Windows 10/11
- Python 3.11 or 3.12
- Installed Google Chrome or Microsoft Edge (Chromium 100+)
- Non-commercial DrissionPage use or permission from its copyright holder
- Permission to automate the selected target and collect the listed public fields

## Install
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```
````

- [ ] **Step 2: Document run, resume, and retry commands**

Include these commands with their behavior:

```powershell
python -m app.main run --input .\inputs\queries.example.csv --output .\outputs\douban_movies.xlsx --headed
python -m app.main run --input .\inputs\queries.example.csv --output .\outputs\douban_movies.xlsx --headed --retry-status PAGE_CHANGED
```

Explain that the first command skips terminal results and upserts transient retries; the second is used only after locator repair.

- [ ] **Step 3: Document security and failure handling**

Include explicit statements:

```markdown
- Stop when the program reports BLOCKED; do not add bypass tooling.
- Close the output workbook in Excel before retrying OUTPUT_LOCKED.
- Never commit `.env`, `browser-profile/`, outputs, screenshots, HTML snapshots, API keys, cookies, or request headers.
- Delete artifacts older than seven days after confirming they are no longer needed.
```

- [ ] **Step 4: Test README commands in a clean virtual environment**

Run from the repository root:

```powershell
python -m pytest -q
python -m app.main run --input .\inputs\queries.example.csv --output .\outputs\douban_movies.xlsx --headed
```

Expected: tests exit 0. The controlled live run writes one row per approved input or stops with documented exit code 3; a block is not a reason to bypass controls.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md inputs/queries.example.csv
git commit -m "docs: add controlled demo runbook"
```

### Task 12: Final verification against Spec v1.0

**Files:**
- Modify only if a verification failure identifies a defect.

- [ ] **Step 1: Run the complete automated suite with coverage**

```powershell
python -m pytest --cov=app --cov-report=term-missing -v
```

Expected: 0 failures; pure logic and parser modules each report at least 80% statement coverage.

- [ ] **Step 2: Verify package and browser startup**

```powershell
python -m pip check
python -c "from pathlib import Path; from app.browser_session import BrowserSession; s=BrowserSession(True, Path('artifacts'), Path('browser-profile/smoke')); t=s.__enter__(); print(t.url); s.__exit__(None,None,None)"
```

Expected: `No broken requirements found`, Chromium version printed, exit 0.

- [ ] **Step 3: Verify workbook schema and task uniqueness**

After the controlled 10-query Demo, run:

```powershell
@'
from openpyxl import load_workbook
wb = load_workbook('outputs/douban_movies.xlsx', read_only=True)
rows = list(wb.active.values)
assert len(rows[0]) == 12, rows[0]
ids = [row[0] for row in rows[1:]]
assert len(ids) == len(set(ids)), ids
assert all(row[9] for row in rows[1:])
print({'data_rows': len(rows) - 1, 'unique_ids': len(set(ids))})
'@ | python -
```

Expected: `data_rows` equals the number of processed approved inputs and equals `unique_ids`.

- [ ] **Step 4: Scan tracked files for credentials and forbidden artifacts**

```powershell
git status --short
$matches = git grep -n -I -E "(sk-[A-Za-z0-9_-]{20,}|MINIMAX_API_KEY=.+|Cookie:)" -- . ':!*.example'
if ($LASTEXITCODE -eq 0) { $matches; throw "Possible secret found" }
git ls-files outputs artifacts browser-profile
```

Expected: no secret matches; only `.gitkeep` files appear under ignored runtime directories.

- [ ] **Step 5: Review Spec coverage and commit any final corrections**

Confirm evidence exists for: CSV validation, visible UI input, candidate rules, five core fields, 12 Excel columns, eight statuses, atomic upsert, resume, blocked stop, redaction, exit codes, README, and 10-query controlled run.

If a correction was required:

```powershell
git add app tests README.md pyproject.toml
git commit -m "fix: close core demo verification gaps"
```

If no correction was required, do not create an empty commit.
