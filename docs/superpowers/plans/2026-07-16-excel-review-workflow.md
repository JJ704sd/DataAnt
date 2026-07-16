# Excel Candidate Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable two-worksheet human-review workflow and an explicit, resumable `apply-review` command without changing the existing 12-column movie result contract or weakening Douban live-run safeguards.

**Architecture:** `ExcelStore` remains the only workbook persistence boundary and atomically updates both `movies` and `review_queue`. `review_service.py` performs complete offline validation and emits immutable actions; `review_runner.py` executes only those actions, checkpoints after each item, and returns a structured summary that a future batch coordinator can reuse.

**Tech Stack:** Python 3.11/3.12, dataclasses and `StrEnum`, openpyxl, DrissionPage through the existing adapter, argparse, pytest, pytest-cov.

---

## Preconditions and invariants

- Work from repository root `D:\DataAnt`.
- Start from commit `f800337` or a descendant containing
  `docs/superpowers/specs/2026-07-16-excel-review-workflow-design.md`.
- Preserve unrelated untracked `.planning/` and `browser_bot_demo.egg-info/`.
- Do not run a real Douban command while implementing this plan.
- Every offline command must remain network-free.
- Any later real `apply-review` invocation must include `--live-approved`,
  `--max-queries N` with `1 <= N <= 10`, `--headed`, and
  `--min-interval 5` or greater.
- Stop immediately on CAPTCHA, rate limiting, login security checks,
  `sec.douban.com`, `BLOCKED`, or `SITE_PROTECTION_CHALLENGE`.
- Never add automatic login, challenge solving, unattended retry scheduling, or
  chained Douban batches.
- Keep `browser-profile/`, `outputs/`, `artifacts/`, logs, HTML, screenshots,
  workbooks, cookies, and sessions out of Git.

## File map

**Create**

- `app/review_service.py`: pure review-row validation and immutable execution
  plan construction.
- `app/review_runner.py`: execute validated actions, checkpoint results, enforce
  pacing, and return structured recovery information.
- `tests/test_review_service.py`: pure decision and URL validation.
- `tests/test_review_runner.py`: execution, stop, retry, and idempotency behavior.

**Modify**

- `app/models.py`: review enums, snapshots, actions, and summaries.
- `app/excel_store.py`: second worksheet schema, review snapshot upsert, pending
  row read, and paired atomic updates.
- `app/runner.py`: enqueue ambiguous candidate snapshots.
- `app/main.py`: `apply-review` parser, preflight, live gate, and exit mapping.
- `scripts/verify_core.py`: continue verifying the `movies` worksheet explicitly.
- `tests/test_models.py`: enum and immutable model contracts.
- `tests/test_excel_store.py`: two-sheet persistence and atomicity.
- `tests/test_runner.py`: review-queue integration.
- `tests/test_main.py`: parser, pre-browser rejection, and exit codes.
- `tests/test_verify_core.py`: verifier compatibility with a second sheet.
- `tests/test_project_config.py`: offline CI and tracked-artifact constraints.
- `README.md`: reviewer workflow and controlled command.

## Locked public contracts

Use these names consistently throughout the implementation:

```python
class ReviewDecisionType(StrEnum):
    CANDIDATE = "CANDIDATE"
    MANUAL_URL = "MANUAL_URL"
    SKIP = "SKIP"


class ReviewApplyStatus(StrEnum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    title: str
    year: str | None
    kind: str | None
    detail_url: str


@dataclass(frozen=True, slots=True)
class ReviewAction:
    review_id: str
    task: Task
    decision_type: ReviewDecisionType
    detail_url: str | None
    review_note: str


@dataclass(frozen=True, slots=True)
class ReviewPlan:
    actions: tuple[ReviewAction, ...]
    live_query_count: int


@dataclass(frozen=True, slots=True)
class ReviewRunSummary:
    processed: int = 0
    skipped: int = 0
    retryable: int = 0
    stopped: bool = False
    stop_status: Status | None = None
```

`MatchMethod` gains exactly one value:

```python
HUMAN_REVIEW = "HUMAN_REVIEW"
```

`review_queue` uses the exact column order constructed below:

```python
REVIEW_COLUMNS = [
    "review_id", "task_id", "query", "query_year", "candidate_count",
    *[
        field
        for number in range(1, 6)
        for field in (
            f"candidate_{number}_title",
            f"candidate_{number}_year",
            f"candidate_{number}_kind",
            f"candidate_{number}_url",
        )
    ],
    "created_at",
    "decision_type", "selected_candidate", "manual_detail_url", "review_note",
    "apply_status", "applied_url", "applied_at", "apply_error",
]
```

### Task 1: Add immutable review domain models

**Files:**

- Modify: `app/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Append to `tests/test_models.py`:

```python
from dataclasses import FrozenInstanceError

import pytest

from app.models import (
    CandidateSnapshot,
    MatchMethod,
    ReviewAction,
    ReviewApplyStatus,
    ReviewDecisionType,
    ReviewPlan,
    ReviewRunSummary,
    Status,
    Task,
)


def test_review_enums_and_human_match_method_are_stable() -> None:
    assert [item.value for item in ReviewDecisionType] == [
        "CANDIDATE", "MANUAL_URL", "SKIP"
    ]
    assert [item.value for item in ReviewApplyStatus] == [
        "PENDING", "APPLIED", "SKIPPED", "FAILED", "SUPERSEDED"
    ]
    assert MatchMethod.HUMAN_REVIEW.value == "HUMAN_REVIEW"


def test_review_plan_is_immutable_and_counts_live_actions() -> None:
    task = Task("task-1", "英雄", "2002")
    action = ReviewAction(
        review_id="review-1",
        task=task,
        decision_type=ReviewDecisionType.CANDIDATE,
        detail_url="https://movie.douban.com/subject/1/",
        review_note="confirmed",
    )
    plan = ReviewPlan(actions=(action,), live_query_count=1)
    assert plan.actions == (action,)
    with pytest.raises(FrozenInstanceError):
        plan.live_query_count = 2  # type: ignore[misc]


def test_review_run_summary_exposes_recovery_state() -> None:
    summary = ReviewRunSummary(
        processed=1,
        skipped=2,
        retryable=1,
        stopped=True,
        stop_status=Status.PAGE_CHANGED,
    )
    assert summary.retryable == 1
    assert summary.stop_status is Status.PAGE_CHANGED
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_models.py -v
```

Expected: collection fails because the review types and `HUMAN_REVIEW` do not
exist.

- [ ] **Step 3: Implement the domain types**

In `app/models.py`, add the enums and frozen dataclasses using the locked public
contracts above. Place review enums after `MatchMethod`, `CandidateSnapshot`
after `Candidate`, and plan/summary types after `RunSummary`.

`ReviewAction.detail_url` is `None` only for `SKIP`. Do not add validation inside
the dataclass; validation belongs in `review_service.py`.

- [ ] **Step 4: Run focused and full model tests**

Run:

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_models.py -v
```

Expected: all model tests pass.

- [ ] **Step 5: Commit the model contract**

```powershell
git add app/models.py tests/test_models.py
git commit -m "feat: add review workflow models"
```

### Task 2: Extend the workbook with an atomic review queue

**Files:**

- Modify: `app/excel_store.py`
- Modify: `tests/test_excel_store.py`

- [ ] **Step 1: Write failing schema and snapshot tests**

Append to `tests/test_excel_store.py`:

```python
from dataclasses import replace

from app.models import Candidate, ReviewApplyStatus, Task
from app.excel_store import REVIEW_COLUMNS


def ambiguous_candidates() -> list[Candidate]:
    return [
        Candidate("英雄", "2002", "电影", "https://movie.douban.com/subject/1/"),
        Candidate("英雄", "2022", "电影", "https://movie.douban.com/subject/2/"),
    ]


def test_review_upsert_creates_second_sheet_without_changing_movies_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "result.xlsx"
    store = ExcelStore(path)
    store.upsert(success("a", "英雄"))
    review_id = store.upsert_review(
        Task("a", "英雄", None), ambiguous_candidates(), "ambiguous"
    )

    workbook = load_workbook(path)
    assert workbook.sheetnames == ["movies", "review_queue"]
    assert [cell.value for cell in workbook["movies"][1]] == COLUMNS
    assert [cell.value for cell in workbook["review_queue"][1]] == REVIEW_COLUMNS
    row = list(workbook["review_queue"].iter_rows(min_row=2, values_only=True))[0]
    assert row[0] == review_id
    assert row[4] == 2
    assert row[5:9] == (
        "英雄", "2002", "电影", "https://movie.douban.com/subject/1/"
    )
    assert row[REVIEW_COLUMNS.index("apply_status")] == ReviewApplyStatus.PENDING


def test_same_snapshot_preserves_human_fields_and_does_not_duplicate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "result.xlsx"
    store = ExcelStore(path)
    first = store.upsert_review(
        Task("a", "英雄", None), ambiguous_candidates(), "ambiguous"
    )
    workbook = load_workbook(path)
    sheet = workbook["review_queue"]
    sheet.cell(2, REVIEW_COLUMNS.index("decision_type") + 1, "CANDIDATE")
    sheet.cell(2, REVIEW_COLUMNS.index("selected_candidate") + 1, 1)
    workbook.save(path)

    second = ExcelStore(path).upsert_review(
        Task("a", "英雄", None), ambiguous_candidates(), "ambiguous"
    )
    rows = list(load_workbook(path)["review_queue"].iter_rows(min_row=2, values_only=True))
    assert first == second
    assert len(rows) == 1
    assert rows[0][REVIEW_COLUMNS.index("decision_type")] == "CANDIDATE"


def test_changed_snapshot_supersedes_open_row(tmp_path: Path) -> None:
    path = tmp_path / "result.xlsx"
    store = ExcelStore(path)
    first = store.upsert_review(
        Task("a", "英雄", None), ambiguous_candidates(), "ambiguous"
    )
    changed = [Candidate(
        "英雄重制版", "2022", "电影",
        "https://movie.douban.com/subject/3/",
    )]
    second = store.upsert_review(Task("a", "英雄", None), changed, "changed")
    rows = list(load_workbook(path)["review_queue"].iter_rows(min_row=2, values_only=True))
    assert first != second
    assert len(rows) == 2
    status_index = REVIEW_COLUMNS.index("apply_status")
    assert rows[0][status_index] == "SUPERSEDED"
    assert rows[1][status_index] == "PENDING"
```

- [ ] **Step 2: Run the tests to verify RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_excel_store.py -v
```

Expected: import or attribute failures for `REVIEW_COLUMNS` and
`upsert_review`.

- [ ] **Step 3: Refactor save handling without changing existing behavior**

In `app/excel_store.py`, add:

```python
import hashlib
import json
from datetime import datetime

from app.models import (
    Candidate,
    ReviewApplyStatus,
    Task,
)

REVIEW_SHEET = "review_queue"
MAX_REVIEW_CANDIDATES = 5
REVIEW_COLUMNS = [
    "review_id", "task_id", "query", "query_year", "candidate_count",
    *[
        field
        for number in range(1, 6)
        for field in (
            f"candidate_{number}_title",
            f"candidate_{number}_year",
            f"candidate_{number}_kind",
            f"candidate_{number}_url",
        )
    ],
    "created_at",
    "decision_type", "selected_candidate", "manual_detail_url", "review_note",
    "apply_status", "applied_url", "applied_at", "apply_error",
]
```

Extract the existing atomic write into:

```python
def _save(self, workbook: WorkbookType) -> None:
    temporary = self.path.with_suffix(self.path.suffix + ".tmp")
    try:
        workbook.save(temporary)
        os.replace(temporary, self.path)
    except PermissionError as exc:
        raise OutputLockedError(f"Close Excel and retry: {self.path}") from exc
```

Update `upsert()` to call `_save(workbook)`. Existing tests must remain green
before review behavior is added.

Also stop relying on `workbook.active`. Add `MOVIES_SHEET = "movies"` and make
`_workbook()` explicitly select `workbook[MOVIES_SHEET]`. For an existing
workbook, reject a missing `movies` sheet. For a new workbook, name the initial
sheet `movies`. All movie reads and writes must use the named sheet even when a
reviewer saved Excel with `review_queue` active.

- [ ] **Step 4: Add deterministic review identity and worksheet helpers**

Add:

```python
def _candidate_payload(candidates: list[Candidate]) -> list[dict[str, str | None]]:
    return [
        {
            "title": item.title,
            "year": item.year,
            "kind": item.kind,
            "detail_url": item.detail_url,
        }
        for item in candidates[:MAX_REVIEW_CANDIDATES]
    ]


def _review_id(task: Task, candidates: list[Candidate]) -> str:
    payload = {
        "task_id": task.task_id,
        "candidates": _candidate_payload(candidates),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]
```

Add private `_review_sheet(workbook)` that creates the sheet and header when
missing, and rejects a wrong existing header with `ValueError`.

Add `upsert_review(task, candidates, reason) -> str`:

- reject an empty candidate list;
- cap candidates at five;
- compute `review_id`;
- mark other `PENDING` or `FAILED` rows for the same task as `SUPERSEDED`;
- preserve an existing identical row, including human fields;
- append a new row with candidate fields, ISO8601 `created_at`,
  `apply_status=PENDING`, and empty decision/application fields;
- call `_save()` exactly once;
- return `review_id`.

`reason` is accepted for the caller contract but is not stored in the first
schema version; do not add an undocumented column.

- [ ] **Step 5: Add read and paired-update APIs**

Add these persistence APIs:

```python
def review_rows(self) -> list[dict[str, object]]:
    workbook = self._workbook()
    if REVIEW_SHEET not in workbook.sheetnames:
        return []
    sheet = workbook[REVIEW_SHEET]
    header = [cell.value for cell in sheet[1]]
    if header != REVIEW_COLUMNS:
        raise ValueError("review_queue schema does not match the contract")
    return [
        {
            **dict(zip(REVIEW_COLUMNS, values, strict=True)),
            "_row_number": row_number,
        }
        for row_number, values in enumerate(
            sheet.iter_rows(min_row=2, values_only=True),
            start=2,
        )
    ]

def movie_status_by_task_id(self) -> dict[str, Status]:
    return self.status_by_task_id()

def apply_review_result(
    self,
    *,
    review_id: str,
    result: MovieResult | None,
    apply_status: ReviewApplyStatus,
    applied_url: str,
    apply_error: str,
) -> None:
    workbook = self._workbook()
    if REVIEW_SHEET not in workbook.sheetnames:
        raise ValueError("review_queue worksheet is required")
    sheet = workbook[REVIEW_SHEET]
    review_id_column = REVIEW_COLUMNS.index("review_id") + 1
    matches = [
        row_number
        for row_number in range(2, sheet.max_row + 1)
        if sheet.cell(row_number, review_id_column).value == review_id
    ]
    if len(matches) != 1:
        raise ValueError(f"review_id must identify one row: {review_id}")
    if result is not None:
        self._upsert_movie_in_workbook(workbook, result)
    row_number = matches[0]
    updates = {
        "apply_status": apply_status.value,
        "applied_url": applied_url,
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "apply_error": apply_error[:200],
    }
    for name, value in updates.items():
        sheet.cell(row_number, REVIEW_COLUMNS.index(name) + 1, value)
    self._save(workbook)
```

`review_rows()` returns every data row as a dictionary plus a private
`"_row_number"` integer used only for validation messages.

`apply_review_result()` must:

- load the workbook once;
- find exactly one review row;
- reject missing or duplicated `review_id`;
- if `result` is not `None`, upsert it into `movies` within the same workbook
  object;
- update `apply_status`, `applied_url`, `applied_at`, and bounded
  `apply_error[:200]`;
- call `_save()` once after both sheets are changed.

Extract a private `_upsert_movie_in_workbook(workbook, result)` so `upsert()` and
`apply_review_result()` share identical serialization.

- [ ] **Step 6: Add paired atomicity and idempotency tests**

Append tests proving:

```python
def test_apply_review_result_updates_both_sheets_in_one_save(tmp_path: Path) -> None:
    path = tmp_path / "result.xlsx"
    store = ExcelStore(path)
    store.upsert(MovieResult.from_task(Task("a", "英雄", None)).stamped())
    review_id = store.upsert_review(
        Task("a", "英雄", None), ambiguous_candidates(), "ambiguous"
    )
    result = success("a", "英雄")
    result = replace(result, match_method=MatchMethod.HUMAN_REVIEW)
    store.apply_review_result(
        review_id=review_id,
        result=result,
        apply_status=ReviewApplyStatus.APPLIED,
        applied_url=result.detail_url,
        apply_error="",
    )
    workbook = load_workbook(path)
    assert workbook["movies"]["I2"].value == "HUMAN_REVIEW"
    status_col = REVIEW_COLUMNS.index("apply_status") + 1
    assert workbook["review_queue"].cell(2, status_col).value == "APPLIED"
```

Also monkeypatch `os.replace` and prove that a lock preserves the original bytes
for a paired update.

- [ ] **Step 7: Run focused tests**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_excel_store.py -v
```

Expected: all Excel tests pass.

- [ ] **Step 8: Commit workbook support**

```powershell
git add app/excel_store.py tests/test_excel_store.py
git commit -m "feat: add atomic Excel review queue"
```

### Task 3: Build whole-batch offline review validation

**Files:**

- Create: `app/review_service.py`
- Create: `tests/test_review_service.py`

- [ ] **Step 1: Write failing happy-path tests**

Create `tests/test_review_service.py` with helpers that produce dictionaries
matching `ExcelStore.review_rows()`, then add:

```python
from app.models import ReviewDecisionType, Status
from app.review_service import ReviewValidationError, build_review_plan


def test_candidate_manual_and_skip_rows_build_immutable_plan() -> None:
    rows = [
        review_row("r1", "t1", decision_type="CANDIDATE", selected_candidate=2),
        review_row(
            "r2", "t2", decision_type="MANUAL_URL",
            manual_detail_url="https://movie.douban.com/subject/42",
        ),
        review_row("r3", "t3", decision_type="SKIP"),
    ]
    plan = build_review_plan(
        rows,
        {"t1": Status.REVIEW_REQUIRED, "t2": Status.REVIEW_REQUIRED,
         "t3": Status.REVIEW_REQUIRED},
        max_queries=2,
    )
    assert plan.live_query_count == 2
    assert [action.decision_type for action in plan.actions] == [
        ReviewDecisionType.CANDIDATE,
        ReviewDecisionType.MANUAL_URL,
        ReviewDecisionType.SKIP,
    ]
    assert plan.actions[0].detail_url.endswith("/2/")
    assert plan.actions[1].detail_url == \
        "https://movie.douban.com/subject/42/"
    assert plan.actions[2].detail_url is None
```

- [ ] **Step 2: Add failing rejection matrix**

Parameterize rejection tests for:

- blank and unknown `decision_type`;
- candidate selection blank, non-integer, zero, negative, or greater than
  `candidate_count`;
- `CANDIDATE` with a manual URL;
- `MANUAL_URL` with a candidate selection;
- `SKIP` with either selection field;
- manual URL using HTTP, wrong host, credentials, port, query, fragment, or a
  non-subject path;
- missing task in `movies`;
- task status other than `REVIEW_REQUIRED`, `PAGE_CHANGED`, `NETWORK_ERROR`, or
  `UNEXPECTED_ERROR`;
- duplicate pending decisions for one task;
- one manual URL reused by two different tasks;
- more live actions than `max_queries`;
- `review_note` longer than 500 characters.

Add one aggregate test:

```python
def test_any_invalid_row_rejects_entire_batch_with_all_row_errors() -> None:
    with pytest.raises(ReviewValidationError) as exc_info:
        build_review_plan(
            [
                review_row("bad-1", "t1", decision_type=""),
                review_row("bad-2", "missing", decision_type="SKIP"),
            ],
            {"t1": Status.REVIEW_REQUIRED},
            max_queries=1,
        )
    message = str(exc_info.value)
    assert "bad-1" in message
    assert "bad-2" in message
    assert len(exc_info.value.errors) == 2
```

- [ ] **Step 3: Run tests to verify RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_review_service.py -v
```

Expected: collection fails because `app.review_service` does not exist.

- [ ] **Step 4: Implement canonical URL validation**

Create `app/review_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from app.models import (
    ReviewAction,
    ReviewApplyStatus,
    ReviewDecisionType,
    ReviewPlan,
    Status,
    Task,
)

_RETRYABLE_MOVIE_STATUSES = frozenset({
    Status.REVIEW_REQUIRED,
    Status.PAGE_CHANGED,
    Status.NETWORK_ERROR,
    Status.UNEXPECTED_ERROR,
})
_TERMINAL_REVIEW_STATUSES = frozenset({
    ReviewApplyStatus.APPLIED,
    ReviewApplyStatus.SKIPPED,
    ReviewApplyStatus.SUPERSEDED,
})


class ReviewValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("\n".join(errors))


def normalize_manual_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname != "movie.douban.com":
        raise ValueError("manual URL must use https://movie.douban.com")
    if parsed.username or parsed.password or parsed.port:
        raise ValueError("manual URL must not contain credentials or a port")
    if parsed.query or parsed.fragment:
        raise ValueError("manual URL must not contain query or fragment")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] != "subject" or not parts[1].isdigit():
        raise ValueError("manual URL path must be /subject/<digits>/")
    return urlunparse(("https", "movie.douban.com", f"/subject/{parts[1]}/", "", "", ""))
```

Do not perform DNS, HTTP, or browser work here.

- [ ] **Step 5: Implement aggregate plan construction**

Implement:

```python
def build_review_plan(
    rows: list[dict[str, object]],
    movie_statuses: dict[str, Status],
    *,
    max_queries: int,
) -> ReviewPlan:
    errors: list[str] = []
    actions: list[ReviewAction] = []
    active_task_ids: set[str] = set()
    live_urls: dict[str, str] = {}

    for row in rows:
        review_id = str(row.get("review_id") or "")
        row_number = int(row.get("_row_number") or 0)
        prefix = f"row {row_number} review_id={review_id or '<blank>'}: "
        try:
            apply_status = ReviewApplyStatus(
                str(row.get("apply_status") or ReviewApplyStatus.PENDING)
            )
        except ValueError:
            errors.append(prefix + "invalid apply_status")
            continue
        if apply_status in _TERMINAL_REVIEW_STATUSES:
            continue

        task_id = str(row.get("task_id") or "")
        query = str(row.get("query") or "")
        raw_year = row.get("query_year")
        query_year = str(raw_year) if raw_year not in (None, "") else None
        if not review_id or not task_id or not query:
            errors.append(prefix + "review_id, task_id, and query are required")
            continue
        if task_id in active_task_ids:
            errors.append(prefix + f"duplicate active decision for task_id={task_id}")
            continue
        active_task_ids.add(task_id)
        if movie_statuses.get(task_id) not in _RETRYABLE_MOVIE_STATUSES:
            errors.append(prefix + "movies row is missing or not review-eligible")
            continue

        try:
            decision = ReviewDecisionType(str(row.get("decision_type") or ""))
        except ValueError:
            errors.append(prefix + "decision_type must be CANDIDATE, MANUAL_URL, or SKIP")
            continue
        selected = row.get("selected_candidate")
        manual = str(row.get("manual_detail_url") or "").strip()
        note = str(row.get("review_note") or "")
        if len(note) > 500:
            errors.append(prefix + "review_note must be at most 500 characters")
            continue

        detail_url: str | None
        if decision is ReviewDecisionType.CANDIDATE:
            if manual:
                errors.append(prefix + "CANDIDATE must not set manual_detail_url")
                continue
            try:
                selected_number = int(selected)
                candidate_count = int(row.get("candidate_count") or 0)
            except (TypeError, ValueError):
                errors.append(prefix + "selected_candidate must be an integer")
                continue
            if str(selected_number) != str(selected).strip() or not (
                1 <= selected_number <= candidate_count <= 5
            ):
                errors.append(prefix + "selected_candidate is outside the snapshot")
                continue
            detail_url = str(
                row.get(f"candidate_{selected_number}_url") or ""
            ).strip()
            try:
                detail_url = normalize_manual_url(detail_url)
            except ValueError as exc:
                errors.append(prefix + f"captured candidate URL is invalid: {exc}")
                continue
        elif decision is ReviewDecisionType.MANUAL_URL:
            if selected not in (None, ""):
                errors.append(prefix + "MANUAL_URL must not set selected_candidate")
                continue
            try:
                detail_url = normalize_manual_url(manual)
            except ValueError as exc:
                errors.append(prefix + str(exc))
                continue
        else:
            if selected not in (None, "") or manual:
                errors.append(prefix + "SKIP must not set a candidate or manual URL")
                continue
            detail_url = None

        if detail_url is not None:
            prior_task = live_urls.get(detail_url)
            if prior_task is not None and prior_task != task_id:
                errors.append(prefix + "selected URL is reused by another task")
                continue
            live_urls[detail_url] = task_id
        actions.append(ReviewAction(
            review_id=review_id,
            task=Task(task_id, query, query_year),
            decision_type=decision,
            detail_url=detail_url,
            review_note=note,
        ))

    live_query_count = sum(
        action.decision_type is not ReviewDecisionType.SKIP
        for action in actions
    )
    if live_query_count > max_queries:
        errors.append(
            f"live decision count {live_query_count} exceeds max_queries={max_queries}"
        )
    if errors:
        raise ReviewValidationError(errors)
    return ReviewPlan(tuple(actions), live_query_count)
```

Rules:

- ignore rows whose `apply_status` is `APPLIED`, `SKIPPED`, or `SUPERSEDED`;
- validate every remaining row and collect all errors;
- include `"_row_number"` and `review_id` in each error prefix;
- use the candidate URL from the numbered snapshot for `CANDIDATE`;
- normalize the manual URL for `MANUAL_URL`;
- set `detail_url=None` for `SKIP`;
- reject duplicate active task IDs;
- reject a normalized live URL used by different task IDs;
- count `CANDIDATE` and `MANUAL_URL`, but not `SKIP`;
- reject a count over `max_queries`;
- preserve workbook row order in `ReviewPlan.actions`;
- raise one `ReviewValidationError(errors)` after validating all rows;
- return an immutable tuple of actions.

- [ ] **Step 6: Run focused tests**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_review_service.py -v
```

Expected: all validation tests pass without filesystem or network access.

- [ ] **Step 7: Commit validation**

```powershell
git add app/review_service.py tests/test_review_service.py
git commit -m "feat: validate Excel review batches"
```

### Task 4: Enqueue ambiguous candidates during normal runs

**Files:**

- Modify: `app/runner.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: Extend the fake store and write failing tests**

Add to `FakeStore`:

```python
self.review_upserts: list[tuple[Task, list[Candidate], str]] = []

def upsert_review(
    self, task: Task, candidates: list[Candidate], reason: str
) -> str:
    self.review_upserts.append((task, list(candidates), reason))
    return f"review-{task.task_id}"
```

Add tests:

```python
def test_ambiguous_match_writes_bounded_candidate_snapshot() -> None:
    candidates = [
        Candidate(f"英雄 {i}", str(2000 + i), "电影",
                  f"https://movie.douban.com/subject/{i}/")
        for i in range(1, 7)
    ]
    store = FakeStore()
    runner = make_runner(FakeAdapter({"a": candidates}), store)
    runner.run([task("a", year=None)])
    assert len(store.review_upserts) == 1
    queued_task, queued, reason = store.review_upserts[0]
    assert queued_task.task_id == "a"
    assert len(queued) == 5
    assert reason == "no unique deterministic match"


def test_not_found_and_deterministic_success_do_not_write_review_rows() -> None:
    missing_store = FakeStore()
    make_runner(FakeAdapter(), missing_store).run([task("missing")])
    assert missing_store.review_upserts == []

    exact_task = task("exact", query="英雄", year="2002")
    exact_candidate = candidate("英雄", "2002")
    exact_adapter = FakeAdapter({"exact": [exact_candidate]})
    exact_adapter.detail_results["exact"] = successful_detail(exact_task)
    exact_store = FakeStore()
    make_runner(exact_adapter, exact_store).run([exact_task])
    assert exact_store.review_upserts == []
```

- [ ] **Step 2: Verify RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest `
  tests/test_runner.py::test_ambiguous_match_writes_bounded_candidate_snapshot -v
```

Expected: failure because `Runner` does not call `upsert_review`.

- [ ] **Step 3: Add the queue write**

In `Runner._process`, immediately before returning `REVIEW_REQUIRED`, call:

```python
self.store.upsert_review(task, candidates[:5], decision.reason)
```

If review persistence raises `OutputLockedError`, allow it to propagate through
the existing output-lock path. Do not catch it as `UNEXPECTED_ERROR`. Do not
queue `NOT_FOUND` or deterministic matches.

- [ ] **Step 4: Run runner and Excel tests**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest `
  tests/test_runner.py tests/test_excel_store.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit normal-run integration**

```powershell
git add app/runner.py tests/test_runner.py
git commit -m "feat: queue ambiguous movie candidates"
```

### Task 5: Execute validated review plans with checkpoints

**Files:**

- Create: `app/review_runner.py`
- Create: `tests/test_review_runner.py`

- [ ] **Step 1: Write failing success, skip, and idempotency tests**

Create fakes for an adapter and store. The fake store records
`apply_review_result` calls. Add:

```python
def test_candidate_action_fetches_detail_and_checkpoints_human_match() -> None:
    action = live_action("r1", "t1", "https://movie.douban.com/subject/1/")
    adapter = FakeReviewAdapter(successful_detail(action.task))
    store = FakeReviewStore()
    summary = ReviewRunner(adapter, store, object(), 0).run(
        ReviewPlan((action,), live_query_count=1)
    )
    assert summary == ReviewRunSummary(processed=1)
    saved = store.calls[0]
    assert saved["result"].match_method is MatchMethod.HUMAN_REVIEW
    assert saved["apply_status"] is ReviewApplyStatus.APPLIED


def test_skip_action_never_calls_adapter() -> None:
    action = skip_action("r1", "t1")
    adapter = FakeReviewAdapter()
    store = FakeReviewStore()
    summary = ReviewRunner(adapter, store, object(), 0).run(
        ReviewPlan((action,), live_query_count=0)
    )
    assert adapter.calls == []
    assert summary == ReviewRunSummary(processed=0, skipped=1)
    assert store.calls[0]["apply_status"] is ReviewApplyStatus.SKIPPED
```

- [ ] **Step 2: Write failing error and stop tests**

Cover:

- `NetworkError` becomes `NETWORK_ERROR`, `FAILED`, retryable count 1, and the
  next action continues;
- `PageChangedError` becomes `PAGE_CHANGED`, `FAILED`, retryable count 1;
- `BlockedError` becomes `BLOCKED`, checkpoints current action, and stops;
- `SiteProtectionChallenge` becomes its distinct status and stops;
- unexpected adapter errors become `UNEXPECTED_ERROR` without leaking exception
  text;
- `NetworkError` uses the existing three-attempt 0/2/5-second bounded retry;
- pacing sleeps only between adjacent live actions, not after `SKIP` or after the
  final live action;
- every completed action calls the store once before the next action starts.

- [ ] **Step 3: Verify RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_review_runner.py -v
```

Expected: collection fails because `app.review_runner` does not exist.

- [ ] **Step 4: Implement the review runner**

Create `app/review_runner.py` with:

```python
from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from app.models import (
    Candidate,
    MatchMethod,
    MovieResult,
    ReviewApplyStatus,
    ReviewDecisionType,
    ReviewPlan,
    ReviewRunSummary,
    Status,
)
from app.sites.douban_movie import (
    BlockedError,
    NetworkError,
    PageChangedError,
    SiteProtectionChallenge,
)

_NETWORK_BACKOFF_SECONDS = (0.0, 2.0, 5.0)


class ReviewRunner:
    def __init__(
        self, adapter, store, tab: Any, min_interval_seconds: float = 5
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.tab = tab
        self.min_interval_seconds = float(min_interval_seconds)

    def run(self, plan: ReviewPlan) -> ReviewRunSummary:
        processed = skipped = retryable = 0
        live_indexes = [
            index
            for index, action in enumerate(plan.actions)
            if action.decision_type is not ReviewDecisionType.SKIP
        ]
        final_live_index = live_indexes[-1] if live_indexes else None
        for index, action in enumerate(plan.actions):
            if action.decision_type is ReviewDecisionType.SKIP:
                self.store.apply_review_result(
                    review_id=action.review_id,
                    result=None,
                    apply_status=ReviewApplyStatus.SKIPPED,
                    applied_url="",
                    apply_error="",
                )
                skipped += 1
                continue

            started = time.monotonic()
            result, stop = self._fetch(action)
            apply_status = (
                ReviewApplyStatus.APPLIED
                if result.status is Status.SUCCESS
                else ReviewApplyStatus.FAILED
            )
            self.store.apply_review_result(
                review_id=action.review_id,
                result=result,
                apply_status=apply_status,
                applied_url=action.detail_url or "",
                apply_error=result.error_message,
            )
            processed += 1
            if result.status in {
                Status.NETWORK_ERROR,
                Status.PAGE_CHANGED,
                Status.UNEXPECTED_ERROR,
            }:
                retryable += 1
            elapsed = time.monotonic() - started
            if (
                not stop
                and index != final_live_index
                and elapsed < self.min_interval_seconds
            ):
                time.sleep(self.min_interval_seconds - elapsed)
            if stop:
                return ReviewRunSummary(
                    processed, skipped, retryable, True, result.status
                )
        return ReviewRunSummary(processed, skipped, retryable)
```

Implement `_network_operation(operation)` with the same three attempts and
0/2/5-second backoff as `Runner`; only `NetworkError` is retryable. Implement
`_fetch(action)` by creating a `Candidate` from the selected URL and calling:

```python
self._network_operation(
    lambda: self.adapter.fetch_detail(self.tab, action.task, candidate)
)
```

Convert successful results with:

```python
replace(result, match_method=MatchMethod.HUMAN_REVIEW)
```

Map adapter exceptions to stamped `MovieResult` values exactly as the normal
runner does. Bound network error text to 200 characters and unexpected error
text to the exception type name only. `BlockedError` and
`SiteProtectionChallenge` set `stop=True`.

Do not retry `PageChangedError`, blocking, site-protection challenges, or
unexpected exceptions. This runner performs one selected-detail operation per
action, with bounded retries only for transient `NetworkError`.

- [ ] **Step 5: Run focused tests**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_review_runner.py -v
```

Expected: all review runner tests pass.

- [ ] **Step 6: Commit execution support**

```powershell
git add app/review_runner.py tests/test_review_runner.py
git commit -m "feat: apply validated review actions"
```

### Task 6: Add the explicit `apply-review` CLI

**Files:**

- Modify: `app/main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write failing parser tests**

Add:

```python
def test_apply_review_parser_exposes_controlled_arguments() -> None:
    args = build_parser().parse_args([
        "apply-review",
        "--workbook", "out.xlsx",
        "--live-approved",
        "--max-queries", "3",
    ])
    assert args.command == "apply-review"
    assert args.workbook == "out.xlsx"
    assert args.headed is True
    assert args.min_interval == 5.0
    assert args.profile_dir == "browser-profile/douban"
```

Assert that `apply-review` does not expose `--retry-status`.

- [ ] **Step 2: Write failing preflight-order tests**

Monkeypatch `ExcelStore.review_rows`, `movie_status_by_task_id`,
`build_review_plan`, and `BrowserSession`. Prove:

- invalid workbook or `ReviewValidationError` returns 2;
- every invalid row is logged;
- browser construction count remains zero;
- workbook bytes are unchanged;
- a plan with two live actions and `--max-queries 1` returns 2;
- missing approval, headless mode, interval below five, and max outside 1..10
  return 2 before browser construction;
- a plan containing only `SKIP` still requires explicit live authorization,
  because `apply-review` is a live-capable command and approval must not be
  inferred from plan contents.

- [ ] **Step 3: Write failing exit mapping tests**

Use a fake `ReviewRunner` to prove:

- ordinary summary returns 0;
- `stop_status=BLOCKED` returns 3;
- `stop_status=SITE_PROTECTION_CHALLENGE` returns 3;
- `OutputLockedError` returns 4;
- unexpected browser failure returns 5.

- [ ] **Step 4: Verify RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_main.py -v
```

Expected: failures because `apply-review` is unknown.

- [ ] **Step 5: Refactor shared live arguments and validation**

In `build_parser()`, create a helper that adds:

```python
--headed / --no-headed
--min-interval
--browser-path
--profile-dir
--live-approved
--max-queries
```

Use it for both `run` and `apply-review`. Keep `--input`, `--output`, and
`--retry-status` only on `run`; add required `--workbook` only to
`apply-review`.

Refactor `_validate_live_run` to accept `live_query_count` rather than CSV task
count, while preserving all existing run tests and messages.

- [ ] **Step 6: Implement command dispatch and offline-first preflight**

Move the current `run` body without semantic changes into
`_execute_run(args, logger)`. Make `execute()` parse once, configure logging
once, and dispatch explicitly:

```python
if args.command == "run":
    return _execute_run(args, logger)
if args.command == "apply-review":
    return _execute_apply_review(args, logger)
raise AssertionError(f"unhandled command: {args.command}")
```

The apply function must execute in this order:

```python
workbook_path = Path(args.workbook)
if not workbook_path.is_file():
    logger.error("Review workbook is required: %s", workbook_path)
    return 2
store = ExcelStore(workbook_path)
rows = store.review_rows()
statuses = store.movie_status_by_task_id()
plan = build_review_plan(rows, statuses, max_queries=10)
if not _validate_live_run(args, plan.live_query_count, logger):
    return 2
browser_path = Path(args.browser_path) if args.browser_path else None
with BrowserSession(
    args.headed,
    _ARTIFACTS_DIR,
    Path(args.profile_dir),
    browser_path,
) as tab:
    summary = ReviewRunner(
        DoubanMovieAdapter(), store, tab, args.min_interval
    ).run(plan)
```

Catch `ValueError` and `ReviewValidationError` before browser construction and
return 2. Catch `OutputLockedError` as 4 and unexpected browser/global errors as
5. Return 3 when `summary.stop_status` is `BLOCKED` or
`SITE_PROTECTION_CHALLENGE`.

Important ordering detail: because `max_queries` itself must be validated as
1..10, parse the workbook with a safe temporary ceiling of 10, validate CLI
arguments, then reject when `plan.live_query_count > args.max_queries`. Do not
pass `0` to `build_review_plan` for a missing value. The final implementation
should therefore be:

```python
plan = build_review_plan(rows, statuses, max_queries=10)
if not _validate_live_run(args, plan.live_query_count, logger):
    return 2
```

- [ ] **Step 7: Run focused CLI tests**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_main.py -v
```

Expected: all main tests pass and no real browser is launched.

- [ ] **Step 8: Verify help text manually**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m app.main apply-review --help
```

Expected: exit 0; output contains `--workbook`, `--live-approved`,
`--max-queries`, `--headed`, `--min-interval`, and does not contain
`--retry-status`.

- [ ] **Step 9: Commit CLI wiring**

```powershell
git add app/main.py tests/test_main.py
git commit -m "feat: add controlled apply-review command"
```

### Task 7: Preserve release verification and document operations

**Files:**

- Modify: `scripts/verify_core.py`
- Modify: `tests/test_verify_core.py`
- Modify: `tests/test_project_config.py`
- Modify: `README.md`

- [ ] **Step 1: Write a failing verifier compatibility test**

Append to `tests/test_verify_core.py`:

```python
def test_workbook_verifier_uses_movies_sheet_when_review_queue_exists(
    tmp_path: Path,
) -> None:
    path = tmp_path / "controlled.xlsx"
    workbook = Workbook()
    movies = workbook.active
    movies.title = "movies"
    movies.append(EXPECTED_COLUMNS)
    movies.append(valid_row("task-1"))
    review = workbook.create_sheet("review_queue")
    review.append(["review-only"])
    workbook.active = 1
    workbook.save(path)
    assert verify_controlled_workbook(path) == {
        "data_rows": 1, "unique_ids": 1
    }
```

This test deliberately makes `review_queue` active, proving the verifier does
not rely on `workbook.active`.

- [ ] **Step 2: Verify RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest `
  tests/test_verify_core.py::test_workbook_verifier_uses_movies_sheet_when_review_queue_exists -v
```

Expected: failure because the verifier reads the active sheet.

- [ ] **Step 3: Select `movies` explicitly**

Change:

```python
rows = list(workbook.active.values)
```

to:

```python
if "movies" not in workbook.sheetnames:
    raise WorkbookContractError("movies worksheet is required")
rows = list(workbook["movies"].values)
```

Keep the existing 12-column, row-count, status, ID, and timestamp checks.

- [ ] **Step 4: Strengthen offline CI configuration tests**

In `tests/test_project_config.py`, assert:

- `.github/workflows/core-offline.yml` does not contain `apply-review`;
- it does not contain `--live-approved`;
- tracked runtime scan still allows only `.gitkeep` below `outputs/`,
  `artifacts/`, and `browser-profile/`;
- `README.md` examples never omit the live gate for a real `apply-review`
  command.

- [ ] **Step 5: Update README**

Add a concise “Excel human review” section containing:

1. normal `run` creates `review_queue` for ambiguity;
2. only `decision_type`, `selected_candidate`, `manual_detail_url`, and
   `review_note` are editable;
3. legal decision combinations;
4. canonical manual URL examples;
5. the exact controlled command:

```powershell
python -m app.main apply-review `
  --workbook .\outputs\douban_movies.xlsx `
  --live-approved `
  --max-queries 5 `
  --headed `
  --min-interval 5 `
  --profile-dir .\browser-profile\douban
```

6. whole-batch preflight rejection and exit code 2;
7. `SKIP`, checkpoint, resume, and already-applied behavior;
8. stop behavior for block/challenge;
9. “close Excel before applying”;
10. runtime artifacts never enter Git.

Do not describe unattended scheduling or approval reuse.

- [ ] **Step 6: Run focused verification**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest `
  tests/test_verify_core.py tests/test_project_config.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit verification and docs**

```powershell
git add scripts/verify_core.py tests/test_verify_core.py `
  tests/test_project_config.py README.md
git commit -m "docs: add Excel review operations"
```

### Task 8: Complete offline release verification

**Files:**

- No planned source changes; repair only failures directly caused by Tasks 1–7.

- [ ] **Step 1: Run the full suite**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest -q
```

Expected: all tests pass; count is greater than the 164-test baseline.

- [ ] **Step 2: Run coverage and the portable gate**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest `
  --cov=app `
  --cov-report=term-missing `
  --cov-report=json:artifacts/coverage.json -v
if ($LASTEXITCODE -ne 0) { throw 'coverage run failed' }
& '.\.venv\Scripts\python.exe' -m scripts.verify_core `
  --coverage-json artifacts/coverage.json
if ($LASTEXITCODE -ne 0) { throw 'verify_core failed' }
```

Expected: exit 0; the three existing required modules remain at or above 80%.

- [ ] **Step 3: Run package and local browser checks**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pip check
if ($LASTEXITCODE -ne 0) { throw 'pip check failed' }
& '.\.venv\Scripts\python.exe' -m scripts.browser_smoke
if ($LASTEXITCODE -ne 0) { throw 'browser smoke failed' }
```

Expected: no broken requirements; local `data:` smoke exits 0 and does not
access Douban.

- [ ] **Step 4: Run CLI refusal checks without a browser**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m app.main apply-review `
  --workbook .\outputs\missing.xlsx `
  --max-queries 1 `
  --headed `
  --min-interval 5
if ($LASTEXITCODE -ne 2) {
    throw "expected exit 2, got $LASTEXITCODE"
}
```

Expected: exit 2; no browser/profile creation and no network access.

- [ ] **Step 5: Run secret and tracked-artifact scans**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
$SecretPattern = '(sk-[A-Za-z0-9_-]{20,}|MINIMAX_API_KEY\s*=\s*["'']?[A-Za-z0-9_-]{16,}|Cookie:\s*[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
$SecretMatches = git grep -n -I -E $SecretPattern -- .
$SecretExit = $LASTEXITCODE
if ($SecretExit -eq 0) { $SecretMatches; throw 'Possible tracked secret found' }
if ($SecretExit -gt 1) { throw "git grep failed with exit $SecretExit" }

$TrackedRuntime = @(git ls-files -- outputs artifacts browser-profile)
$Unexpected = @(
  $TrackedRuntime |
    Where-Object { $_ -notmatch '^(outputs|artifacts|browser-profile)/\.gitkeep$' }
)
if ($Unexpected.Count -gt 0) {
  $Unexpected
  throw 'Tracked runtime artifacts found'
}
```

Expected: no secret match; only allowed `.gitkeep` runtime entries.

- [ ] **Step 6: Inspect scope and whitespace**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
git diff --check
git status --short
git log --oneline -10
```

Expected: `git diff --check` is clean. `.planning/` and
`browser_bot_demo.egg-info/` may remain unrelated and untracked; do not stage or
delete them.

- [ ] **Step 7: Record implementation handoff**

Report:

- final test count;
- coverage gate values;
- CLI help/refusal evidence;
- files changed;
- commits created;
- confirmation that no real Douban or MiniMax request occurred;
- remaining concern, if any.

Do not claim a live review success until an operator separately runs a valid
1–10 row workbook with explicit approval.

## Plan self-review checklist

- Every design acceptance criterion maps to Tasks 2–8.
- `movies` remains exactly 12 columns.
- `review_queue` has one declared column order.
- Validation happens before browser construction and before workbook mutation.
- `SKIP` performs no network action.
- Manual URLs cannot escape the canonical Douban subject path.
- Paired movie/review updates use one atomic workbook save.
- Completed rows are idempotently skipped; changed snapshots are superseded.
- `ReviewPlan` and `ReviewRunSummary` provide the future batch/recovery seams.
- Douban approval is per invocation and cannot be persisted or scheduled.
- MiniMax, second-site support, and unattended live batches remain out of scope.
- No plan step requires real network access.
