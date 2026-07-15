# Core Stabilization and Release Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current Core implementation into a repeatable, cross-platform, fail-closed release gate without adding MiniMax or requiring live Douban access in automated checks.

**Architecture:** Move repeated read-only validation into small Python scripts with unit-tested functions, while keeping browser and controlled-demo evidence as explicit local gates. CI runs only deterministic offline checks; the final release task combines CI evidence with a separately approved workbook and compliance record.

**Tech Stack:** Python 3.11, pytest, pytest-cov, openpyxl, DrissionPage, PowerShell, GitHub Actions.

---

## Scope and file map

- Create `scripts/__init__.py`: make verification helpers importable by tests.
- Create `scripts/verify_core.py`: validate coverage JSON, workbook schema, and controlled-demo evidence.
- Create `scripts/browser_smoke.py`: run the existing local `data:` browser lifecycle check.
- Create `tests/test_verify_core.py`: unit tests for portable coverage and workbook/evidence validation.
- Create `tests/test_browser_smoke_script.py`: verify the smoke script uses only a `data:` URL and closes the session.
- Create `.github/workflows/core-offline.yml`: deterministic, non-network release checks.
- Create `docs/superpowers/tasks/core-13-release-readiness.md`: final human-controlled release gate and handoff prompt.
- Modify `README.md`: point operators to offline CI and controlled release verification.

MiniMax files, production matching behavior, real Douban automation, and generated workbook contents are outside this plan.

### Task 1: Portable coverage threshold verifier

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/verify_core.py`
- Create: `tests/test_verify_core.py`

- [ ] **Step 1: Write failing tests for Windows and POSIX coverage keys**

```python
import argparse
import json
from pathlib import Path

import pytest

from scripts.verify_core import CoverageThresholdError, verify_coverage


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
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_verify_core.py -v
```

Expected: collection fails because `scripts.verify_core` does not exist.

- [ ] **Step 3: Add the minimal verifier**

Create an empty `scripts/__init__.py`, then create `scripts/verify_core.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


REQUIRED_COVERAGE = {
    "app/input_loader.py": 80.0,
    "app/matcher.py": 80.0,
    "app/sites/douban_movie.py": 80.0,
}


class CoverageThresholdError(AssertionError):
    pass


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
```

- [ ] **Step 4: Run focused and full tests**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_verify_core.py -v
& '.\.venv\Scripts\python.exe' -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit only Task 1 files**

```powershell
git add scripts/__init__.py scripts/verify_core.py tests/test_verify_core.py
git commit -m "test: add portable core coverage gate"
```

**操作提示词：**

```text
你是 DataAnt Core 稳定化 Task 1 实施代理。工作目录固定为
D:\DataAnt\.worktrees\browser-bot-demo。只执行
docs/superpowers/plans/2026-07-15-core-stabilization-release-readiness.md 的 Task 1。
先确认 git status 干净；只创建 scripts/__init__.py、scripts/verify_core.py、
tests/test_verify_core.py。严格先写测试并看到因模块不存在而失败，再写最小实现。
验证 Windows 反斜杠与 POSIX 正斜杠 coverage key 均可读取，任一指定模块低于 80%
必须 fail closed。不得安装依赖、不得访问网络、不得修改 app/、不得处理 MiniMax。
完成后运行聚焦测试、全套 pytest、git diff --check，只提交这三个文件。
失败时停止，不清理或改动范围外文件，并回报原始错误、git status 和未执行步骤。
```

### Task 2: Controlled workbook and approval evidence verifier

**Files:**
- Modify: `scripts/verify_core.py`
- Modify: `tests/test_verify_core.py`

- [ ] **Step 1: Add failing workbook/evidence tests**

Append tests that create a 12-column, 10-row workbook and a JSON evidence file:

```python
from openpyxl import Workbook

from scripts.verify_core import WorkbookContractError, verify_controlled_workbook


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
            None, None, "NONE", "NOT_FOUND", "controlled fixture", "2026-07-15T12:00:00+08:00",
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
    assert verify_controlled_workbook(workbook, evidence) == {"data_rows": 10, "unique_ids": 10}


def test_verify_controlled_workbook_rejects_missing_compliance_approval(tmp_path: Path) -> None:
    workbook = tmp_path / "douban_movies.xlsx"
    evidence = tmp_path / "controlled-demo-evidence.json"
    write_workbook(workbook)
    write_evidence(evidence, approved=False)
    with pytest.raises(WorkbookContractError, match="compliance approval"):
        verify_controlled_workbook(workbook, evidence)
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_verify_core.py -v
```

Expected: import fails because `verify_controlled_workbook` is absent.

- [ ] **Step 3: Implement strict evidence and workbook checks**

Add the following imports, constants, exception, and function to `scripts/verify_core.py`:

```python
from openpyxl import load_workbook


EXPECTED_COLUMNS = [
    "task_id", "query", "query_year", "matched_title", "matched_year", "director",
    "rating", "detail_url", "match_method", "status", "error_message", "collected_at",
]
VALID_STATUSES = {
    "SUCCESS", "NOT_FOUND", "REVIEW_REQUIRED", "NETWORK_ERROR",
    "PAGE_CHANGED", "BLOCKED", "OUTPUT_LOCKED", "UNEXPECTED_ERROR",
}


class WorkbookContractError(AssertionError):
    pass


def verify_controlled_workbook(workbook_path: Path, evidence_path: Path) -> dict[str, int]:
    if not workbook_path.is_file() or not evidence_path.is_file():
        raise WorkbookContractError("approved workbook and evidence are required")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not str(evidence.get("approval_reference", "")).strip():
        raise WorkbookContractError("approval reference is required")
    if evidence.get("compliance_approved") is not True:
        raise WorkbookContractError("compliance approval is required")
    if evidence.get("approved_query_count") != 10:
        raise WorkbookContractError("approved query count must be 10")
    if not str(evidence.get("run_id", "")).strip() or not str(evidence.get("completed_at", "")).strip():
        raise WorkbookContractError("run identity and completion time are required")

    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    rows = list(workbook.active.values)
    if not rows or list(rows[0]) != EXPECTED_COLUMNS:
        raise WorkbookContractError("workbook columns do not match the contract")
    data = rows[1:]
    ids = [str(row[0]) for row in data]
    if len(data) != 10 or len(set(ids)) != 10:
        raise WorkbookContractError("workbook must contain 10 unique tasks")
    if any(row[9] not in VALID_STATUSES for row in data):
        raise WorkbookContractError("workbook contains an invalid status")
    if any(not row[11] for row in data):
        raise WorkbookContractError("collected_at must be populated")
    return {"data_rows": len(data), "unique_ids": len(set(ids))}
```

Do not add a live-site fallback or environment-key handling.

- [ ] **Step 4: Verify tests and ignored runtime paths**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_verify_core.py -v
& '.\.venv\Scripts\python.exe' -m pytest -q
git check-ignore outputs/douban_movies.xlsx artifacts/controlled-demo-evidence.json
```

Expected: tests pass and both runtime evidence paths are ignored.

- [ ] **Step 5: Commit Task 2**

```powershell
git add scripts/verify_core.py tests/test_verify_core.py
git commit -m "test: require approved workbook evidence"
```

**操作提示词：**

```text
你是 DataAnt Core 稳定化 Task 2 实施代理。只执行规划文档 Task 2，只修改
scripts/verify_core.py 和 tests/test_verify_core.py。先写并运行失败测试，再实现严格的
workbook + approval evidence 校验。测试只能创建临时 workbook 和虚构 approval reference；
不得读取或生成真实豆瓣数据。没有 approval_reference 或 compliance_approved=true 时必须
失败关闭，绝不访问豆瓣补跑。不要打印证据全文、cookies、HTML 或环境变量。完成后运行
聚焦测试、全套 pytest、git check-ignore、git diff --check，只提交两个指定文件。
```

### Task 3: Reusable local browser smoke

**Files:**
- Create: `scripts/browser_smoke.py`
- Create: `tests/test_browser_smoke_script.py`

- [ ] **Step 1: Write the failing lifecycle test**

```python
from pathlib import Path

from scripts import browser_smoke


class FakeTab:
    url = "data:text/html,<h1>ok</h1>"

    def get(self, url: str) -> None:
        assert url.startswith("data:text/html,")

    def ele(self, locator: str):
        assert locator == "tag:h1"
        return type("Heading", (), {"text": "ok"})()


class FakeSession:
    exited = False

    def __init__(self, headed: bool, artifacts: Path, profile: Path):
        assert headed is True

    def __enter__(self):
        return FakeTab()

    def __exit__(self, exc_type, exc, traceback):
        self.exited = True


def test_run_uses_local_data_page_and_closes_session(monkeypatch) -> None:
    session = FakeSession(True, Path("artifacts"), Path("browser-profile/smoke"))
    monkeypatch.setattr(browser_smoke, "BrowserSession", lambda *args: session)
    assert browser_smoke.run() == "BROWSER_SMOKE_OK"
    assert session.exited is True
```

- [ ] **Step 2: Verify RED**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_browser_smoke_script.py -v
```

Expected: import fails because `scripts.browser_smoke` is absent.

- [ ] **Step 3: Implement the local-only smoke script**

```python
from pathlib import Path

from app.browser_session import BrowserSession


def run() -> str:
    with BrowserSession(True, Path("artifacts"), Path("browser-profile/smoke")) as tab:
        tab.get("data:text/html,<title>browser-smoke</title><h1>ok</h1>")
        assert tab.url.startswith("data:")
        assert tab.ele("tag:h1").text == "ok"
    return "BROWSER_SMOKE_OK"


if __name__ == "__main__":
    print(run())
```

- [ ] **Step 4: Run unit and real local smoke checks**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_browser_smoke_script.py -v
& '.\.venv\Scripts\python.exe' -m scripts.browser_smoke
```

Expected: unit test passes and the real command prints `BROWSER_SMOKE_OK`. No HTTP(S) URL is opened.

- [ ] **Step 5: Commit Task 3**

```powershell
git add scripts/browser_smoke.py tests/test_browser_smoke_script.py
git commit -m "test: make browser smoke repeatable"
```

**操作提示词：**

```text
你是 DataAnt Core 稳定化 Task 3 实施代理。只创建 scripts/browser_smoke.py 和
tests/test_browser_smoke_script.py。严格 RED→GREEN；测试隔离 BrowserSession 边界，但断言
真实脚本只使用 data: URL 并正常退出 session。实现不得接受外部 URL，不得访问豆瓣，
不得保存 screenshot/HTML，不得引入 Playwright。先跑单元测试，再跑一次本地 data: smoke。
若浏览器无法启动，保留现场并回报，不要安装浏览器或改配置。只提交两个指定文件。
```

### Task 4: Offline CI gate

**Files:**
- Create: `.github/workflows/core-offline.yml`
- Modify: `README.md`

- [ ] **Step 1: Add a failing configuration contract test**

Append to `tests/test_project_config.py`:

```python
def test_core_ci_is_offline_and_runs_portable_verification() -> None:
    workflow = Path(".github/workflows/core-offline.yml").read_text(encoding="utf-8")
    assert "python -m pytest" in workflow
    assert "scripts.verify_core" in workflow
    assert "movie.douban.com" not in workflow
    assert "MINIMAX_API_KEY" not in workflow
```

- [ ] **Step 2: Verify RED**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_project_config.py::test_core_ci_is_offline_and_runs_portable_verification -v
```

Expected: fail because the workflow does not exist.

- [ ] **Step 3: Create the workflow**

Create `.github/workflows/core-offline.yml`:

```yaml
name: core-offline

on:
  push:
  pull_request:

jobs:
  verify:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Install project
        run: python -m pip install -e ".[dev]"
      - name: Check dependencies
        run: python -m pip check
      - name: Run tests and coverage
        run: python -m pytest --cov=app --cov-report=term-missing --cov-report=json:artifacts/coverage.json -v
      - name: Enforce module coverage
        run: python -m scripts.verify_core --coverage-json artifacts/coverage.json
      - name: Check diffs
        run: git diff --check
      - name: Reject tracked runtime artifacts
        shell: pwsh
        run: |
          $tracked = @(git ls-files -- outputs artifacts browser-profile)
          $unexpected = @($tracked | Where-Object { $_ -notmatch '^(outputs|artifacts|browser-profile)/\.gitkeep$' })
          if ($unexpected.Count -gt 0) { $unexpected; throw 'Tracked runtime artifacts found' }
      - name: Scan tracked files for secrets
        shell: pwsh
        run: |
          $pattern = '(sk-[A-Za-z0-9_-]{20,}|MINIMAX_API_KEY\s*=\s*["'']?[A-Za-z0-9_-]{16,}|Cookie:\s*[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
          $matches = git grep -n -I -E $pattern -- .
          $exitCode = $LASTEXITCODE
          if ($exitCode -eq 0) { $matches; throw 'Possible tracked secret found' }
          if ($exitCode -gt 1) { throw "git grep failed with exit $exitCode" }
```

Do not run the headed browser or workbook gate in CI because both require controlled local resources.

- [ ] **Step 4: Document the split gate**

Append this section to `README.md`:

```markdown
## Core verification layers

`core-offline` is the deterministic CI gate. It runs tests, coverage thresholds,
dependency checks, secret scanning, and tracked-runtime checks without opening a
browser or visiting Douban.

Release readiness additionally requires the local `data:` browser smoke and the
pre-existing pair `outputs/douban_movies.xlsx` plus
`artifacts/controlled-demo-evidence.json`. The evidence must contain a non-empty
approval reference and explicit compliance approval. Missing evidence blocks the
release; it never authorizes an automatic live run. MiniMax remains deferred.
```

- [ ] **Step 5: Verify and commit**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_project_config.py -v
& '.\.venv\Scripts\python.exe' -m pytest -q
git diff --check
git add .github/workflows/core-offline.yml README.md tests/test_project_config.py
git commit -m "ci: add offline core release gate"
```

**操作提示词：**

```text
你是 DataAnt Core 稳定化 Task 4 实施代理。只创建 .github/workflows/core-offline.yml，
修改 README.md 与 tests/test_project_config.py。先写配置契约测试并看到 workflow 缺失失败，
再实现最小 CI。CI 只运行离线 pytest、coverage、pip check、diff、secret 和 tracked artifact
检查；禁止启动浏览器、访问豆瓣、读取 MiniMax Key 或伪造 workbook。README 必须清楚区分
offline CI 与人工受控 release gate。完成后运行指定测试和 git diff --check，只提交三个文件。
```

### Task 5: Final release-readiness handoff

**Files:**
- Create: `docs/superpowers/tasks/core-13-release-readiness.md`
- Modify: `README.md`

- [ ] **Step 1: Write the final task document**

Create `docs/superpowers/tasks/core-13-release-readiness.md` with this complete content:

````markdown
# Core 13: Release readiness

## Operating prompt

```text
你是 DataAnt Core 只读发布验证代理。固定工作目录为
D:\DataAnt\.worktrees\browser-bot-demo。只执行本文门禁，不修改文件、不安装依赖、不提交。
任何失败立即停止。没有 artifacts/controlled-demo-evidence.json 中的非空 approval_reference
与 compliance_approved=true 时，不得访问豆瓣补跑；本任务本身永不访问豆瓣。MiniMax 延期，
不得实施或调用。最终只在每个门禁都通过时报告 READY_TO_PUSH，否则报告 NOT_READY、首个
失败门禁、已执行命令、未执行项和 git status。
```

## Gates

All commands run from the absolute worktree:

```powershell
Set-Location -LiteralPath 'D:\DataAnt\.worktrees\browser-bot-demo'
$root = (git rev-parse --show-toplevel).Trim().Replace('/', '\')
if ($root -ne 'D:\DataAnt\.worktrees\browser-bot-demo') { throw "Wrong worktree: $root" }
$status = @(git status --short)
if ($status.Count -gt 0) { $status; throw 'Worktree is not clean' }
```

Run offline verification:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'pytest failed' }
& '.\.venv\Scripts\python.exe' -m pytest --cov=app --cov-report=term-missing --cov-report=json:artifacts/coverage.json -v
if ($LASTEXITCODE -ne 0) { throw 'coverage run failed' }
& '.\.venv\Scripts\python.exe' -m scripts.verify_core --coverage-json artifacts/coverage.json
if ($LASTEXITCODE -ne 0) { throw 'coverage threshold failed' }
& '.\.venv\Scripts\python.exe' -m pip check
if ($LASTEXITCODE -ne 0) { throw 'pip check failed' }
```

Run the local-only browser lifecycle:

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.browser_smoke
if ($LASTEXITCODE -ne 0) { throw 'browser smoke failed' }
```

Require pre-existing approved runtime evidence, without visiting Douban:

```powershell
@'
from pathlib import Path
from scripts.verify_core import verify_controlled_workbook

print(verify_controlled_workbook(
    Path('outputs/douban_movies.xlsx'),
    Path('artifacts/controlled-demo-evidence.json'),
))
'@ | & '.\.venv\Scripts\python.exe' -
if ($LASTEXITCODE -ne 0) { throw 'approved workbook gate failed' }
```

Run publication safety scans:

```powershell
$pattern = '(sk-[A-Za-z0-9_-]{20,}|MINIMAX_API_KEY\s*=\s*["'']?[A-Za-z0-9_-]{16,}|Cookie:\s*[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
$matches = git grep -n -I -E $pattern -- .
$secretExit = $LASTEXITCODE
if ($secretExit -eq 0) { $matches; throw 'Possible tracked secret found' }
if ($secretExit -gt 1) { throw "git grep failed with exit $secretExit" }

$tracked = @(git ls-files -- outputs artifacts browser-profile)
$unexpected = @($tracked | Where-Object { $_ -notmatch '^(outputs|artifacts|browser-profile)/\.gitkeep$' })
if ($unexpected.Count -gt 0) { $unexpected; throw 'Tracked runtime artifacts found' }

git diff --check
if ($LASTEXITCODE -ne 0) { throw 'git diff --check failed' }
$finalStatus = @(git status --short)
if ($finalStatus.Count -gt 0) { $finalStatus; throw 'Final worktree is not clean' }
'READY_TO_PUSH'
```

Do not run a controlled live collection from this task. If the workbook or evidence
is absent, report `NOT_READY` and request separately documented compliance approval.
````

- [ ] **Step 2: Add the README handoff link**

Link `Core 13` as the authoritative release-readiness entry point and state that a missing approved workbook is a release blocker, not a reason to run the site automatically.

- [ ] **Step 3: Self-review the task document**

```powershell
$needles = @(('T'+'BD'), ('T'+'ODO'), ('implement'+' later'), ('fill'+' in'))
Select-String -Path 'docs/superpowers/tasks/core-13-release-readiness.md' -Pattern $needles -CaseSensitive:$false
git diff --check
```

Expected: no placeholder matches and no whitespace errors.

- [ ] **Step 4: Run the full offline verification**

```powershell
& '.\.venv\Scripts\python.exe' -m pytest --cov=app --cov-report=term-missing --cov-report=json:artifacts/coverage.json -v
& '.\.venv\Scripts\python.exe' -m scripts.verify_core --coverage-json artifacts/coverage.json
& '.\.venv\Scripts\python.exe' -m pip check
& '.\.venv\Scripts\python.exe' -m scripts.browser_smoke
```

Expected: all offline gates pass. Workbook verification may run only when the approved runtime files already exist.

- [ ] **Step 5: Commit Task 5**

```powershell
git add docs/superpowers/tasks/core-13-release-readiness.md README.md
git commit -m "docs: add core release handoff"
```

**操作提示词：**

```text
你是 DataAnt Core 稳定化 Task 5 文档与最终验证代理。只创建
docs/superpowers/tasks/core-13-release-readiness.md 并修改 README.md。写出可以逐条复制执行的
PowerShell 门禁，任何一步失败立即停止。没有 artifacts/controlled-demo-evidence.json 中的
非空 approval_reference 与 compliance_approved=true，绝对不得访问豆瓣；不得伪造、下载或
提交 workbook。MiniMax 明确延期。先完成占位符与 diff 自审，再运行全部离线验证和本地
data: browser smoke。只有所有门禁及已批准 workbook 都通过时才能报告 READY_TO_PUSH；否则
报告 NOT_READY、首个失败项、已执行命令、未执行项和 git status。
```

## Final plan verification

After all five tasks:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' -m pytest --cov=app --cov-report=term-missing --cov-report=json:artifacts/coverage.json -v
& '.\.venv\Scripts\python.exe' -m scripts.verify_core --coverage-json artifacts/coverage.json
& '.\.venv\Scripts\python.exe' -m pip check
& '.\.venv\Scripts\python.exe' -m scripts.browser_smoke
git diff --check
git status --short
```

Expected: offline checks pass and the worktree is clean after task commits. Run the controlled workbook gate only with pre-existing approved evidence. Do not declare release readiness merely because offline checks pass.
