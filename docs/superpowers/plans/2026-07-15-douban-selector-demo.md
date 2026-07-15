# Douban Selector Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the headed-browser movie query flow with minimal adapter changes so rendered Douban search results can be parsed and written through the existing Excel output path.

**Architecture:** Keep `Runner`, matching, detail parsing, and `ExcelStore` unchanged. Make search readiness depend on observable rendered HTML rather than the obsolete `.result-list` selector, and extend the adapter's pure HTML parser to recognize canonical subject links with nested React-style title and metadata markup while retaining the legacy fixture contract.

**Tech Stack:** Python 3.11, DrissionPage 4.1, pytest, standard-library `html` and `re`, openpyxl through the existing `ExcelStore`.

---

## File Structure

- Create `tests/fixtures/search_results_react.html`: small, synthetic, credential-free representation of rendered React search cards.
- Modify `tests/test_douban_parser.py`: regression coverage for nested result markup and HTML-based readiness.
- Modify `app/sites/douban_movie.py`: pure candidate parsing helpers and result readiness predicate.
- No changes to `Runner`, `ExcelStore`, CLI arguments, output schema, CI, or release gates.

### Task 1: Reproduce the React Search Result Failure

**Files:**
- Create: `tests/fixtures/search_results_react.html`
- Modify: `tests/test_douban_parser.py`
- Test: `tests/test_douban_parser.py`

- [ ] **Step 1: Add a sanitized nested-markup fixture**

Create `tests/fixtures/search_results_react.html` with no cookies, headers, scripts, tracking identifiers, or copied live-page payload:

```html
<html><body><div id="root">
  <div class="search-result-card">
    <a href="https://movie.douban.com/subject/1292052/">
      <div class="title"><span>肖申克的救赎</span></div>
    </a>
    <div class="meta"><span>1994</span><span> / </span><span>电影</span></div>
  </div>
  <div class="search-result-card">
    <a href="https://movie.douban.com/subject/9999999/">
      <div class="title"><span>肖申克</span></div>
    </a>
    <div class="meta"><span>2010</span><span> / </span><span>短片</span></div>
  </div>
</div></body></html>
```

- [ ] **Step 2: Add one failing parser regression test**

Append to `tests/test_douban_parser.py`:

```python
def test_parse_react_search_candidates_with_nested_markup() -> None:
    candidates = DoubanMovieAdapter.parse_search_html(
        html("search_results_react.html")
    )
    assert [(c.title, c.year, c.kind, c.detail_url) for c in candidates] == [
        ("肖申克的救赎", "1994", "电影", DETAIL_URL),
        ("肖申克", "2010", "短片", "https://movie.douban.com/subject/9999999/"),
    ]
```

- [ ] **Step 3: Run the regression test and verify RED**

Run:

```powershell
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q 'D:\DataAnt\.worktrees\browser-bot-demo\tests\test_douban_parser.py::test_parse_react_search_candidates_with_nested_markup'
```

Expected: FAIL because the current single regex requires plain anchor text immediately followed by a plain `<span>`.

- [ ] **Step 4: Commit the failing fixture and test**

```powershell
git -C 'D:\DataAnt\.worktrees\browser-bot-demo' add -- 'tests/fixtures/search_results_react.html' 'tests/test_douban_parser.py'
git -C 'D:\DataAnt\.worktrees\browser-bot-demo' commit -m 'test: reproduce react search result markup'
```

### Task 2: Parse Nested Rendered Search Cards

**Files:**
- Modify: `app/sites/douban_movie.py`
- Test: `tests/test_douban_parser.py`

- [ ] **Step 1: Implement the smallest parser compatible with both fixtures**

Add `from html import unescape` to `app/sites/douban_movie.py`, define these module-level expressions, and replace `parse_search_html`:

```python
_SUBJECT_LINK = re.compile(
    r'<a\b[^>]*href=["\'](https://movie\.douban\.com/subject/\d+/)["\'][^>]*>'
    r'(.*?)</a>(.*?)(?=<a\b[^>]*href=["\']https://movie\.douban\.com/subject/\d+/|$)',
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")
_YEAR_AND_KIND = re.compile(r"\b((?:19|20)\d{2})\b\s*/\s*([^<\n]+)")


def _text(fragment: str) -> str:
    return " ".join(unescape(_TAG.sub(" ", fragment)).split())


@staticmethod
def parse_search_html(html: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for url, anchor_html, trailing_html in _SUBJECT_LINK.findall(html):
        title = _text(anchor_html)
        metadata = _text(trailing_html)
        match = _YEAR_AND_KIND.search(metadata)
        if not title or match is None:
            continue
        candidates.append(
            Candidate(title, match.group(1), match.group(2).strip(), url)
        )
        if len(candidates) == 5:
            break
    return candidates
```

The implementation deliberately reads only canonical movie links and nearby rendered text. It does not execute embedded data, inspect scripts, or broaden accepted domains.

- [ ] **Step 2: Run the new regression test and verify GREEN**

Run the exact targeted command from Task 1 Step 3.

Expected: `1 passed`.

- [ ] **Step 3: Run all parser tests to verify backward compatibility**

```powershell
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q 'D:\DataAnt\.worktrees\browser-bot-demo\tests\test_douban_parser.py'
```

Expected: all tests pass, including source order, five-item limit, empty results, blocking, detail parsing, and the new React fixture.

- [ ] **Step 4: Commit the minimal parser fix**

```powershell
git -C 'D:\DataAnt\.worktrees\browser-bot-demo' add -- 'app/sites/douban_movie.py'
git -C 'D:\DataAnt\.worktrees\browser-bot-demo' commit -m 'fix: parse rendered douban search cards'
```

### Task 3: Replace the Obsolete Result-List Readiness Marker

**Files:**
- Modify: `tests/test_douban_parser.py`
- Modify: `app/sites/douban_movie.py`
- Test: `tests/test_douban_parser.py`

- [ ] **Step 1: Add a failing search readiness regression**

Add the following test; it models a rendered page that has candidates but no `.result-list` element:

```python
def test_search_accepts_rendered_candidates_without_legacy_marker() -> None:
    tab = LoadedTab(html("search_results_react.html"), result_marker=False)
    candidates = DoubanMovieAdapter().search(
        tab, Task("a", "肖申克的救赎", "1994")
    )
    assert [candidate.title for candidate in candidates] == [
        "肖申克的救赎",
        "肖申克",
    ]
```

- [ ] **Step 2: Run the new test and verify RED**

```powershell
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q 'D:\DataAnt\.worktrees\browser-bot-demo\tests\test_douban_parser.py::test_search_accepts_rendered_candidates_without_legacy_marker'
```

Expected: FAIL with `PageChangedError: Search result marker was not found` after the old readiness condition cannot see `.result-list`.

- [ ] **Step 3: Make readiness depend on parsed rendered content or explicit empty text**

In `DoubanMovieAdapter`, add:

```python
EMPTY_RESULT_TEXT = ("没有找到", "暂无搜索结果")

@classmethod
def _search_is_ready(cls, html: str) -> bool:
    return bool(cls.parse_search_html(html)) or any(
        marker in html for marker in cls.EMPTY_RESULT_TEXT
    )
```

Replace the current `wait_until` predicate in `search()` with:

```python
wait_until(lambda: self._search_is_ready(tab.html), timeout=10)
```

Keep the existing timeout-to-`PageChangedError`, blocking checks, and final parsing unchanged.

- [ ] **Step 4: Run the targeted test and verify GREEN**

Run the exact targeted command from Task 3 Step 2.

Expected: `1 passed`.

- [ ] **Step 5: Run the complete parser test module**

```powershell
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q 'D:\DataAnt\.worktrees\browser-bot-demo\tests\test_douban_parser.py'
```

Expected: all parser tests pass; the explicit timeout test still raises `PageChangedError` because its monkeypatched `wait_until` controls that boundary.

- [ ] **Step 6: Commit readiness behavior**

```powershell
git -C 'D:\DataAnt\.worktrees\browser-bot-demo' add -- 'tests/test_douban_parser.py' 'app/sites/douban_movie.py'
git -C 'D:\DataAnt\.worktrees\browser-bot-demo' commit -m 'fix: detect rendered search readiness'
```

### Task 4: Verify the Offline Demo Contract

**Files:**
- No production changes expected.
- Generated ignored files may appear under `artifacts/` and `browser-profile/`.

- [ ] **Step 1: Run the complete test suite**

```powershell
& 'D:\DataAnt\.worktrees\browser-bot-demo\.venv\Scripts\python.exe' -m pytest -q 'D:\DataAnt\.worktrees\browser-bot-demo\tests'
```

Expected: zero failures.

- [ ] **Step 2: Generate coverage JSON and run the portable core verification**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
& '.\.venv\Scripts\python.exe' -m pytest --cov=app --cov-report=term-missing --cov-report=json:artifacts/coverage.json -v
if ($LASTEXITCODE -ne 0) { throw 'coverage run failed' }
& '.\.venv\Scripts\python.exe' -m scripts.verify_core --coverage-json artifacts/coverage.json
```

Expected: exit code 0 and each core module at or above the configured 80% threshold.

- [ ] **Step 3: Run the zero-network browser smoke**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
& '.\.venv\Scripts\python.exe' -m scripts.browser_smoke
```

Expected: exit code 0 with `BROWSER_SMOKE_OK`.

- [ ] **Step 4: Inspect repository hygiene**

```powershell
git -C 'D:\DataAnt\.worktrees\browser-bot-demo' diff --check
git -C 'D:\DataAnt\.worktrees\browser-bot-demo' status --short
```

Expected: no whitespace errors and no uncommitted source changes. Ignored browser profiles, logs, screenshots, HTML, workbooks, and coverage artifacts must not be staged.

### Task 5: Controlled Live Acceptance After Approval

**Files:**
- Runtime only: `outputs/douban_movies.xlsx`
- Runtime only: `browser-profile/douban/`
- Runtime only: `artifacts/controlled-demo-evidence.json` and diagnostics if generated

- [ ] **Step 1: Validate the approval gate before any network access**

Confirm a real independent approval record exists and obtain its non-empty reference. Do not proceed when the only evidence is conversational authorization.

Expected: a traceable work item, approval email identifier, or signed approval reference covering the approved query count and Douban access.

- [ ] **Step 2: Create the controlled evidence record from the real approval**

Populate the fields required by `scripts.verify_core`: `approval_reference`, `compliance_approved: true`, approved query count, run ID, and completion timestamp. Never invent or infer the approval reference.

- [ ] **Step 3: Run the approved headed demo**

From the worktree, use the existing CLI with the approved input, isolated profile, output workbook, and `--min-interval 5`. Do not use `--retry-status BLOCKED`, and stop if site protection is detected.

Expected: exit code 0 unless the site returns a documented blocked/network/page-changed state.

- [ ] **Step 4: Inspect the workbook and release evidence**

Use the existing workbook verification path in `docs/superpowers/tasks/core-13-release-readiness.md` without modifying that document. Check headers, approved row count, statuses, canonical detail URLs, and representative title/year/director/rating values.

Expected: `WORKBOOK_EVIDENCE_OK`, followed by the documented release readiness result. Runtime evidence remains ignored and uncommitted.
