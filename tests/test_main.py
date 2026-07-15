from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app import main
from app.excel_store import OutputLockedError
from app.input_loader import InputError
from app.main import build_parser, execute
from app.models import RunSummary, Status, Task


def test_run_command_requires_input_and_output() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--input", "in.csv", "--output", "out.xlsx"])
    assert args.command == "run"
    assert args.input == "in.csv"
    assert args.output == "out.xlsx"
    assert args.headed is True


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--input", "in.csv"],
        ["--output", "out.xlsx"],
    ],
)
def test_run_command_rejects_missing_required_arguments(arguments: list[str]) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["run", *arguments])

    assert exc_info.value.code == 2


def test_run_command_can_disable_headed_mode() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["run", "--input", "in.csv", "--output", "out.xlsx", "--no-headed"]
    )

    assert args.headed is False


def test_run_command_collects_repeated_retry_statuses() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run",
            "--input",
            "in.csv",
            "--output",
            "out.xlsx",
            "--retry-status",
            "failed",
            "--retry-status",
            "missing",
        ]
    )

    assert args.retry_status == ["failed", "missing"]


def test_parser_uses_stable_program_name() -> None:
    parser = build_parser()

    assert parser.prog == "browser-bot-demo"


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


# --------------------------------------------------------------------------- #
# Test doubles for execute()
# --------------------------------------------------------------------------- #


class _FakeStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def status_by_task_id(self) -> dict[str, Status]:
        return {}

    def upsert(self, result: object) -> None:
        # No-op stand-in; real ExcelStore is exercised in test_excel_store.py.
        return None


class _FakeAdapter:
    """Empty stand-in for DoubanMovieAdapter — never invoked in unit tests."""


class _FakeRunner:
    """Records every construction call and returns a configurable summary."""

    instances: list = []
    next_summary = RunSummary(processed=0, skipped=0, blocked=False)

    def __init__(
        self,
        adapter: object,
        store: object,
        tab: object,
        min_interval: float,
        retry: object,
        logger: logging.Logger,
        artifacts: Path,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.tab = tab
        self.min_interval = min_interval
        self.retry = retry
        self.logger = logger
        self.artifacts = artifacts
        _FakeRunner.instances.append(self)

    def run(self, tasks: list[Task]) -> RunSummary:  # type: ignore[override]
        return _FakeRunner.next_summary


class _FakeBrowserSession:
    """Records construction parameters; yields a sentinel tab from __enter__."""

    instances: list = []

    def __init__(
        self,
        headed: bool,
        artifacts_dir: Path,
        profile_dir: Path,
        browser_path: Path | None,
    ) -> None:
        self.headed = headed
        self.artifacts_dir = artifacts_dir
        self.profile_dir = profile_dir
        self.browser_path = browser_path
        self._tab = object()
        _FakeBrowserSession.instances.append(self)

    def __enter__(self) -> object:
        return self._tab

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


@pytest.fixture
def stub_dependencies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Replace heavy collaborators with fakes; reset shared state per test."""
    _FakeRunner.instances.clear()
    _FakeRunner.next_summary = RunSummary(processed=0, skipped=0, blocked=False)
    _FakeBrowserSession.instances.clear()

    monkeypatch.setattr(main, "load_tasks", lambda p: [Task("t1", "英雄", None)])
    monkeypatch.setattr(main, "ExcelStore", _FakeStore)
    monkeypatch.setattr(main, "BrowserSession", _FakeBrowserSession)
    monkeypatch.setattr(main, "DoubanMovieAdapter", _FakeAdapter)
    monkeypatch.setattr(main, "Runner", _FakeRunner)
    monkeypatch.setattr(
        main, "configure_logging", lambda p: logging.getLogger("browser_bot")
    )

    csv = tmp_path / "in.csv"
    csv.write_text("query\n英雄\n", encoding="utf-8")
    out = tmp_path / "out.xlsx"

    return {"csv": csv, "out": out}


def live_args(stub_dependencies: dict, *extra: str) -> list[str]:
    return [
        "run",
        "--input", str(stub_dependencies["csv"]),
        "--output", str(stub_dependencies["out"]),
        "--live-approved",
        "--max-queries", "1",
        *extra,
    ]


# --------------------------------------------------------------------------- #
# Parser contract — nine arguments + defaults
# --------------------------------------------------------------------------- #


def test_run_parser_exposes_nine_arguments_with_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--input", "in.csv", "--output", "out.xlsx"])

    assert args.input == "in.csv"
    assert args.output == "out.xlsx"
    assert args.headed is True
    assert args.retry_status == []
    assert args.min_interval == 5.0
    assert args.browser_path is None
    assert args.profile_dir == "browser-profile/douban"
    assert args.live_approved is False
    assert args.max_queries is None

    run_subparser = next(
        action.choices["run"]
        for action in parser._actions
        if action.dest == "command"
    )
    custom_dests = {
        action.dest
        for action in run_subparser._actions
        if action.dest != "help"
    }
    assert custom_dests == {
        "input",
        "output",
        "headed",
        "retry_status",
        "min_interval",
        "browser_path",
        "profile_dir",
        "live_approved",
        "max_queries",
    }


# --------------------------------------------------------------------------- #
# Pre-browser live authorization gate
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# execute() — exit code mapping
# --------------------------------------------------------------------------- #


def test_execute_returns_2_for_missing_input_file(
    stub_dependencies: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(path: Path) -> list[Task]:
        raise InputError(f"input path is not a file: {path}")

    monkeypatch.setattr(main, "load_tasks", _raise)

    rc = execute(
        [
            "run",
            "--input",
            "missing.csv",
            "--output",
            str(stub_dependencies["out"]),
            "--live-approved",
            "--max-queries", "1",
        ]
    )

    assert rc == 2
    assert _FakeBrowserSession.instances == []


def test_execute_returns_2_for_invalid_retry_status(
    stub_dependencies: dict,
) -> None:
    rc = execute(
        [
            "run",
            "--input",
            str(stub_dependencies["csv"]),
            "--output",
            str(stub_dependencies["out"]),
            "--live-approved",
            "--max-queries", "1",
            "--retry-status",
            "BOGUS",
        ]
    )

    assert rc == 2
    assert _FakeBrowserSession.instances == []


def test_execute_passes_session_tab_to_runner_with_default_profile(
    stub_dependencies: dict,
) -> None:
    rc = execute(live_args(stub_dependencies))

    assert rc == 0
    assert len(_FakeRunner.instances) == 1
    assert len(_FakeBrowserSession.instances) == 1
    runner = _FakeRunner.instances[0]
    session = _FakeBrowserSession.instances[0]
    assert runner.tab is session._tab
    assert session.profile_dir == Path("browser-profile/douban")


def test_execute_returns_0_when_summary_not_blocked(
    stub_dependencies: dict,
) -> None:
    _FakeRunner.next_summary = RunSummary(processed=0, skipped=0, blocked=False)

    rc = execute(live_args(stub_dependencies))

    assert rc == 0


def test_execute_returns_3_when_summary_blocked(
    stub_dependencies: dict,
) -> None:
    _FakeRunner.next_summary = RunSummary(processed=1, skipped=0, blocked=True)

    rc = execute(live_args(stub_dependencies))

    assert rc == 3


def test_execute_returns_4_for_output_locked_error(
    stub_dependencies: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(*_args: object, **_kwargs: object) -> None:
        raise OutputLockedError("locked")

    monkeypatch.setattr(main, "Runner", _explode)

    rc = execute(live_args(stub_dependencies))

    assert rc == 4


def test_execute_returns_5_for_browser_session_unexpected_error(
    stub_dependencies: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _BoomSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> object:
            raise RuntimeError("browser boom")

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

    monkeypatch.setattr(main, "BrowserSession", _BoomSession)

    rc = execute(live_args(stub_dependencies))

    assert rc == 5


def test_execute_accepts_valid_retry_statuses(stub_dependencies: dict) -> None:
    rc = execute(
        live_args(
            stub_dependencies,
            "--retry-status", "NOT_FOUND",
            "--retry-status", "REVIEW_REQUIRED",
        )
    )

    assert rc == 0
    runner = _FakeRunner.instances[0]
    assert Status.NOT_FOUND in runner.retry
    assert Status.REVIEW_REQUIRED in runner.retry
