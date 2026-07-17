from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).parents[1]


def test_project_dependencies_use_drissionpage_without_playwright() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as config_file:
        config = tomllib.load(config_file)

    dependencies = config["project"]["dependencies"]

    assert dependencies == [
        "DrissionPage>=4.1.1,<4.2",
        "openpyxl>=3.1,<4",
    ]
    assert all("playwright" not in dependency.casefold() for dependency in dependencies)


def test_browser_profile_placeholder_matches_gitignore_rules() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert gitignore == [
        ".worktrees/",
        ".venv/",
        "__pycache__/",
        "*.py[cod]",
        ".pytest_cache/",
        ".coverage",
        "htmlcov/",
        ".superpowers/",
        ".env",
        "browser-profile/*",
        "!browser-profile/.gitkeep",
        "outputs/*",
        "!outputs/.gitkeep",
        "artifacts/*",
        "!artifacts/.gitkeep",
    ]
    assert all("playwright/.auth" not in rule.casefold() for rule in gitignore)
    assert (PROJECT_ROOT / "browser-profile" / ".gitkeep").is_file()
    assert not (PROJECT_ROOT / "playwright" / ".auth" / ".gitkeep").exists()
    assert ".superpowers/" in gitignore
    assert not any(
        path.parts[:2] == (".superpowers", "brainstorm")
        for path in PROJECT_ROOT.rglob("*")
        if path.is_file() and path.name == ".gitkeep"
    )


def test_core_ci_is_offline_and_runs_portable_verification() -> None:
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "core-offline.yml"
    assert workflow_path.is_file(), "core-offline workflow must exist"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "python-version" in workflow, "workflow must pin a Python version"
    assert "3.11" in workflow, "workflow must run on Python 3.11"
    assert "pytest" in workflow, "workflow must run pytest"
    assert "scripts.verify_core" in workflow, (
        "workflow must invoke the portable core coverage gate"
    )
    assert ".venv" not in workflow, (
        "workflow must not rebuild the local venv; install dev deps directly"
    )

    # The header (name + on + permissions + concurrency + top comment) is
    # allowed to mention forbidden tokens when explaining WHY they are
    # forbidden. Audit only the executable body: everything from the
    # first `jobs:` block onwards.
    jobs_marker = "\njobs:\n"
    jobs_start = workflow.find(jobs_marker)
    assert jobs_start != -1, "workflow must define a jobs: block"
    body = workflow[jobs_start + len(jobs_marker):]
    body_lowered = body.casefold()

    assert "movie.douban.com" not in body_lowered, (
        "CI job body must not reference the live Douban host"
    )
    assert "api.minimax.com" not in body_lowered, (
        "CI job body must not call the MiniMax API"
    )
    assert "actions/upload-artifact" not in body_lowered, (
        "CI must not upload workflow artifacts (browser-profile/ outputs/ artifacts/)"
    )
    assert "DrissionPage" not in body, (
        "CI must not import or invoke the browser driver"
    )
    assert "playwright" not in body_lowered, (
        "CI must not install or run playwright"
    )
    assert "headed" not in body_lowered, (
        "CI must not launch a browser in headed mode"
    )
    assert "minimax_api_key" not in body_lowered, (
        "CI job body must not read the MiniMax API key"
    )
    assert "--live-approved" not in body_lowered, (
        "CI job body must not enable the live-run CLI flag"
    )
    assert "--max-queries" not in body_lowered, (
        "CI job body must not enable the max-queries CLI flag"
    )


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


def test_secret_scan_targets_credentials_not_public_hosts() -> None:
    workflow = (
        PROJECT_ROOT / ".github/workflows/core-offline.yml"
    ).read_text(encoding="utf-8")
    patterns_line = next(
        line.strip() for line in workflow.splitlines() if line.strip().startswith("patterns=")
    )
    assert "sk-[A-Za-z0-9_-]{16,}" in patterns_line
    assert "movie\\.douban\\.com" not in patterns_line
    assert "api\\.minimax\\.com" not in patterns_line.casefold()


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
