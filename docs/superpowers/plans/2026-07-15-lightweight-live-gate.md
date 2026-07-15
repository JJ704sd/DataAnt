# Lightweight Live-Run Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace independent approval evidence with an explicit CLI authorization gate while retaining headed mode, query-count, rate, site-protection, offline-CI, and repository-hygiene safeguards.

**Architecture:** `app.main` becomes the pre-network enforcement point and rejects unsafe live-run arguments before constructing `BrowserSession`. `scripts.verify_core` becomes a workbook-only contract checker, while `DoubanMovieAdapter` recognizes security redirects as `BLOCKED`; documentation and tests are updated in the same branch.

**Tech Stack:** Python 3.11, argparse, pathlib, urllib.parse, pytest, openpyxl, DrissionPage.

---

## File Structure

- Modify `app/main.py`: live authorization arguments and pre-browser validation.
- Modify `tests/test_main.py`: parser contract, gate failures, and valid execution path.
- Modify `scripts/verify_core.py`: workbook-only validation for 1–10 rows.
- Modify `tests/test_verify_core.py`: new verifier API and safety cases.
- Modify `app/sites/douban_movie.py`: security redirect and login-required detection.
- Modify `tests/test_douban_parser.py`: URL/text blocking regressions.
- Modify `README.md`: new operator workflow and removal of independent approval language.
- Modify `docs/superpowers/tasks/core-13-release-readiness.md`: release gate aligned with workbook-only validation.
- Modify `tests/test_project_config.py`: offline CI remains forbidden from invoking live mode.
- Modify `.github/workflows/core-offline.yml`: allow only tracked `.gitkeep` placeholders in runtime directories.
- Create `AGENTS.md`: repository-level long-term live-run rules for future agents.

### Task 1: Enforce Explicit Live Authorization Before Browser Startup

**Files:**
- Modify: `tests/test_main.py`
- Modify: `app/main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Add parser contract tests for the two new arguments**

Update the parser-default test name to `test_run_parser_exposes_nine_arguments_with_defaults`, add these assertions:

```python
assert args.live_approved is False
assert args.max_queries is None
```

and add `"live_approved"` and `"max_queries"` to `custom_dests`.

Add:

```python
def test_run_command_parses_explicit_live_gate() -> None:
    args = build_parser().parse_args(
        [
            "run",
            "--input", "in.csv",
            "--output", "out.xlsx",
            "--live-approved",
            "--max-queries", "7",
        ]
    )
    assert args.live_approved is True
    assert args.max_queries == 7
```

- [ ] **Step 2: Add a reusable valid argument helper**

Add below `stub_dependencies`:

```python
def live_args(stub_dependencies: dict, *extra: str) -> list[str]:
    return [
        "run",
        "--input", str(stub_dependencies["csv"]),
        "--output", str(stub_dependencies["out"]),
        "--live-approved",
        "--max-queries", "1",
        *extra,
    ]
```

Use `live_args(stub_dependencies, ...)` in every existing `execute()` test that is intended to reach retry parsing, store construction, browser construction, Runner, or exit-code mapping. Keep the missing-input test explicit, but add `--live-approved --max-queries 1` so its asserted failure remains the missing file.

- [ ] **Step 3: Add RED tests for every pre-browser gate**

Add:

```python
def test_execute_requires_live_approval_before_browser(stub_dependencies: dict) -> None:
    rc = execute([
        "run", "--input", str(stub_dependencies["csv"]),
        "--output", str(stub_dependencies["out"]),
        "--max-queries", "1",
    ])
    assert rc == 2
    assert _FakeBrowserSession.instances == []


@pytest.mark.parametrize("value", [None, "0", "11"])
def test_execute_requires_max_queries_between_one_and_ten(
    stub_dependencies: dict, value: str | None
) -> None:
    arguments = [
        "run", "--input", str(stub_dependencies["csv"]),
        "--output", str(stub_dependencies["out"]),
        "--live-approved",
    ]
    if value is not None:
        arguments.extend(["--max-queries", value])
    assert execute(arguments) == 2
    assert _FakeBrowserSession.instances == []


def test_execute_rejects_more_tasks_than_live_max(
    stub_dependencies: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        main,
        "load_tasks",
        lambda _path: [Task("t1", "英雄", None), Task("t2", "英雄本色", None)],
    )
    assert execute(live_args(stub_dependencies)) == 2
    assert _FakeBrowserSession.instances == []


def test_execute_rejects_headless_live_run(stub_dependencies: dict) -> None:
    assert execute(live_args(stub_dependencies, "--no-headed")) == 2
    assert _FakeBrowserSession.instances == []


def test_execute_rejects_live_interval_below_five(stub_dependencies: dict) -> None:
    assert execute(live_args(stub_dependencies, "--min-interval", "4.99")) == 2
    assert _FakeBrowserSession.instances == []
```

- [ ] **Step 4: Run the CLI tests and verify RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\lightweight-live-gate'
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m pytest -q tests\test_main.py
```

Expected: new parser/gate tests fail because the two arguments and checks do not exist.

- [ ] **Step 5: Add CLI arguments and validation**

In `build_parser()` add:

```python
run_parser.add_argument("--live-approved", action="store_true")
run_parser.add_argument("--max-queries", type=int, default=None)
```

Add constants:

```python
_LIVE_MIN_INTERVAL = 5.0
_LIVE_MAX_QUERIES = 10
```

Add before `execute()`:

```python
def _validate_live_run(args: argparse.Namespace, task_count: int, logger) -> bool:
    if not args.live_approved:
        logger.error("Live run requires --live-approved")
        return False
    if args.max_queries is None or not 1 <= args.max_queries <= _LIVE_MAX_QUERIES:
        logger.error("--max-queries must be between 1 and %s", _LIVE_MAX_QUERIES)
        return False
    if task_count > args.max_queries:
        logger.error("Input has %s tasks but --max-queries is %s", task_count, args.max_queries)
        return False
    if not args.headed:
        logger.error("Live run requires headed browser mode")
        return False
    if args.min_interval < _LIVE_MIN_INTERVAL:
        logger.error("Live run requires --min-interval >= %.1f", _LIVE_MIN_INTERVAL)
        return False
    return True
```

Immediately after `load_tasks()` succeeds in `execute()` add:

```python
if not _validate_live_run(args, len(tasks), logger):
    return 2
```

Update the `execute()` docstring to state that input loading is followed by live-gate validation before retry parsing, store creation, or browser construction.

- [ ] **Step 6: Run CLI tests and verify GREEN**

Run the Task 1 Step 4 command.

Expected: all `tests/test_main.py` tests pass.

- [ ] **Step 7: Commit the CLI gate**

```powershell
git add -- app/main.py tests/test_main.py
git commit -m "feat: require explicit live-run authorization"
```

### Task 2: Decouple Workbook Validation From Approval Evidence

**Files:**
- Modify: `tests/test_verify_core.py`
- Modify: `scripts/verify_core.py`
- Test: `tests/test_verify_core.py`

- [ ] **Step 1: Replace evidence fixtures with configurable workbook fixtures**

Replace `write_workbook()` with:

```python
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
```

Delete `write_evidence()` and all evidence-file construction.

- [ ] **Step 2: Replace workbook tests with the new contract**

Add:

```python
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
```

Add the wrong-column contract test:

```python
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
```

- [ ] **Step 3: Run verifier tests and verify RED**

```powershell
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m pytest -q tests\test_verify_core.py
```

Expected: calls without an evidence argument fail and the old exact-ten-row contract rejects the one-row case.

- [ ] **Step 4: Implement workbook-only verification**

Remove approval JSON parsing from `verify_controlled_workbook()` and replace it with:

```python
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
        raise WorkbookContractError("workbook task ids must be unique")
    if any(row[9] not in VALID_STATUSES for row in data):
        raise WorkbookContractError("workbook contains an invalid status")
    if any(not row[11] for row in data):
        raise WorkbookContractError("collected_at must be populated")
    return {"data_rows": len(data), "unique_ids": len(set(ids))}
```

Keep `json` imported because coverage verification still reads JSON.

- [ ] **Step 5: Run verifier tests and verify GREEN**

Run the Task 2 Step 3 command.

Expected: all verifier tests pass.

- [ ] **Step 6: Commit the verifier contract**

```powershell
git add -- scripts/verify_core.py tests/test_verify_core.py
git commit -m "refactor: verify workbook without approval evidence"
```

### Task 3: Detect Security Redirects as BLOCKED

**Files:**
- Modify: `tests/test_douban_parser.py`
- Modify: `app/sites/douban_movie.py`
- Test: `tests/test_douban_parser.py`

- [ ] **Step 1: Add RED blocking tests**

Update existing `is_blocked()` calls to pass an optional URL only where needed, then add:

```python
@pytest.mark.parametrize(
    "url",
    [
        "https://sec.douban.com/c?r=https%3A%2F%2Fmovie.douban.com%2Fsubject%2F1%2F",
        "https://accounts.douban.com/passport/login",
    ],
)
def test_security_or_login_redirect_is_blocked(url: str) -> None:
    assert DoubanMovieAdapter.is_blocked("<html></html>", None, url)


@pytest.mark.parametrize("text", ["error code: 01004", "Please login"])
def test_login_required_text_is_blocked(text: str) -> None:
    assert DoubanMovieAdapter.is_blocked(text, 200, "https://movie.douban.com/")
```

Add a fake tab case proving `fetch_detail()` raises `BlockedError` when `tab.url` is a security redirect even if the HTML lacks old blocked markers.

- [ ] **Step 2: Run parser tests and verify RED**

```powershell
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m pytest -q tests\test_douban_parser.py
```

Expected: new URL/text cases fail because `is_blocked()` does not accept or inspect URL.

- [ ] **Step 3: Implement URL-aware blocking**

Add:

```python
from urllib.parse import urlparse

BLOCK_TEXT = (
    "访问频率过高", "异常请求", "验证码", "error code: 01004", "Please login",
)
BLOCK_HOSTS = {"sec.douban.com"}
LOGIN_PATH = "/passport/login"
```

Replace `is_blocked()` with:

```python
@staticmethod
def is_blocked(html: str, status_code: int | None, url: str = "") -> bool:
    parsed = urlparse(url)
    redirected_to_login = (
        parsed.hostname == "accounts.douban.com"
        and parsed.path.rstrip("/") == LOGIN_PATH
    )
    return (
        status_code in {403, 418, 429}
        or parsed.hostname in BLOCK_HOSTS
        or redirected_to_login
        or any(marker in html for marker in BLOCK_TEXT)
    )
```

Pass `tab.url` to all search/fetch blocking checks after navigation and after rendered HTML is captured.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run the Task 3 Step 2 command.

Expected: all parser tests pass.

- [ ] **Step 5: Commit blocking behavior**

```powershell
git add -- app/sites/douban_movie.py tests/test_douban_parser.py
git commit -m "fix: treat douban security redirects as blocked"
```

### Task 4: Align Documentation and Offline-CI Contract

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/tasks/core-13-release-readiness.md`
- Modify: `tests/test_project_config.py`

- [ ] **Step 1: Add a failing project-level documentation contract**

Add to `tests/test_project_config.py`:

```python
def test_readme_documents_lightweight_live_gate_without_approval_evidence() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "--live-approved" in readme
    assert "--max-queries" in readme
    assert "controlled-demo-evidence.json" not in readme
    assert "approval_reference" not in readme


def test_core_13_uses_workbook_only_release_evidence() -> None:
    spec = (
        PROJECT_ROOT / "docs/superpowers/tasks/core-13-release-readiness.md"
    ).read_text(encoding="utf-8")
    assert "verify_controlled_workbook(workbook)" in spec
    assert "controlled-demo-evidence.json" not in spec
    assert "approval_reference" not in spec


def test_repository_agent_rules_define_the_lightweight_live_gate() -> None:
    rules = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for required in (
        "--live-approved",
        "--max-queries",
        "--headed",
        "--min-interval 5",
        "BLOCKED",
        "sec.douban.com",
    ):
        assert required in rules


def test_runtime_artifact_scan_allows_only_gitkeep_placeholders() -> None:
    workflow = (
        PROJECT_ROOT / ".github/workflows/core-offline.yml"
    ).read_text(encoding="utf-8")
    assert "grep -vE '(^|/)(browser-profile|outputs|artifacts)/\\.gitkeep$'" in workflow
```

Extend `test_core_ci_is_offline_and_runs_portable_verification()` with:

```python
assert "--live-approved" not in body_lowered
assert "--max-queries" not in body_lowered
```

- [ ] **Step 2: Run project-config tests and verify RED**

```powershell
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m pytest -q tests\test_project_config.py
```

Expected: README/Core 13 assertions fail against old approval-evidence language.

- [ ] **Step 3: Update README**

Make these exact semantic changes throughout `README.md`:

- Replace independent Compliance approval with operator confirmation via `--live-approved`.
- State that `--max-queries` is required and limited to 1–10.
- Update every live command to include `--live-approved --max-queries <count> --headed --min-interval 5`.
- Replace the controlled-demo checklist evidence step with CLI flag, task-count, headed-mode, rate, and stop-on-blocked checks.
- Remove all `approval_reference`, approval email/form, and `controlled-demo-evidence.json` requirements.
- Document workbook verification as `verify_controlled_workbook(Path("outputs/<run>.xlsx"))` and accept 1–10 unique rows.
- Keep CI offline, runtime artifact exclusions, manual login only, and no CAPTCHA/bypass language.

- [ ] **Step 4: Update Core 13 release readiness**

In `docs/superpowers/tasks/core-13-release-readiness.md`:

- Replace the workbook + approval evidence gate with workbook-only validation.
- Use `verify_controlled_workbook(workbook)`.
- Accept 1–10 unique data rows.
- Remove evidence-file existence and approval-field checks.
- Keep the instruction that the release process itself never accesses live Douban.
- Keep secret scan, runtime artifact scan, coverage, pip check, browser smoke, diff check, and readiness summary unchanged.

- [ ] **Step 5: Fix the CI runtime-artifact false positive**

In `.github/workflows/core-offline.yml`, change the runtime scan pipeline to:

```bash
bad=$(git ls-files | \
      grep -E '(^|/)(browser-profile|outputs|artifacts)/.+$' | \
      grep -vE '(^|/)(browser-profile|outputs|artifacts)/\.gitkeep$' || true)
```

This keeps all real runtime files forbidden while allowing the three intentional tracked placeholders.

- [ ] **Step 6: Create repository-level long-term rules**

Create root `AGENTS.md` with these binding project rules:

```markdown
# DataAnt Agent Rules

## Real-network live runs

- Real Douban access requires the operator's explicit `--live-approved` flag.
- Every live command must include `--max-queries N`, where `1 <= N <= 10`.
- Live runs must use `--headed` and `--min-interval 5` or greater.
- Stop immediately on CAPTCHA, rate limiting, `sec.douban.com`, login security checks, or `BLOCKED`.
- Never automate login, CAPTCHA solving, or site-protection bypasses.
- Never use `--retry-status BLOCKED`.
- Keep browser profiles, cookies, sessions, HTML, screenshots, logs, evidence, and workbooks out of Git.

## Offline CI

- CI must never invoke `--live-approved`, launch a live browser, or access `movie.douban.com`.
- Only `.gitkeep` placeholders may be tracked under `browser-profile/`, `outputs/`, and `artifacts/`.

## Scope

These rules apply to the repository root and every subdirectory unless a more specific `AGENTS.md` strengthens them. A nested file may not weaken the real-network or artifact rules.
```

- [ ] **Step 7: Run project-config tests and verify GREEN**

Run the Task 4 Step 2 command.

Expected: all project configuration tests pass.

- [ ] **Step 8: Commit documentation, agent rules, and CI contract**

```powershell
git add -- AGENTS.md README.md .github/workflows/core-offline.yml docs/superpowers/tasks/core-13-release-readiness.md tests/test_project_config.py
git commit -m "docs: make lightweight live gate a repository rule"
```

### Task 5: Full Offline Verification

**Files:**
- No tracked changes expected.
- Ignored outputs may appear in `artifacts/` and `browser-profile/`.

- [ ] **Step 1: Run the complete test suite**

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\lightweight-live-gate'
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Generate coverage JSON and verify core thresholds**

```powershell
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m pytest --cov=app --cov-report=term-missing --cov-report=json:artifacts/coverage.json -q
if ($LASTEXITCODE -ne 0) { throw 'coverage run failed' }
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m scripts.verify_core --coverage-json artifacts/coverage.json
```

Expected: zero test failures; input loader, matcher, and Douban adapter each meet the 80% threshold.

- [ ] **Step 3: Verify dependencies and zero-network browser lifecycle**

```powershell
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m pip check
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m scripts.browser_smoke
```

Expected: `No broken requirements found.` and `BROWSER_SMOKE_OK`.

- [ ] **Step 4: Verify CLI help and pre-browser rejection manually**

```powershell
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m app.main run --help
& 'D:\DataAnt\.worktrees\title-prefix-year-match\.venv\Scripts\python.exe' -m app.main run --input inputs/queries.example.csv --output outputs/denied.xlsx
```

Expected: help lists both new flags; the second command exits 2 with `Live run requires --live-approved` and does not start a browser.

- [ ] **Step 5: Verify repository hygiene**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors and a clean worktree; ignored runtime artifacts are not staged.

### Task 6: Optional Controlled Live Confirmation

**Files:**
- Runtime only under ignored directories.

- [ ] **Step 1: Ask the operator before real network access**

Do not infer live-run authorization from implementation approval. Obtain an explicit request to perform a real Douban run after the new gate is implemented.

- [ ] **Step 2: Run one-query smoke with the new gate**

Use a manually authenticated isolated profile and:

```powershell
python -m app.main run --input <one-row.csv> --output outputs/live-gate-smoke.xlsx --live-approved --max-queries 1 --headed --min-interval 5 --profile-dir browser-profile/live-gate-smoke
```

Expected: either a valid business status or `BLOCKED`; stop on login, CAPTCHA, security redirect, or rate limiting.

- [ ] **Step 3: Verify the one-row workbook without evidence JSON**

```python
from pathlib import Path
from scripts.verify_core import verify_controlled_workbook
print(verify_controlled_workbook(Path("outputs/live-gate-smoke.xlsx")))
```

Expected for a completed one-row run: `{"data_rows": 1, "unique_ids": 1}`.
