from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app import main
from app.excel_store import OutputLockedError
from app.input_loader import InputError
from app.main import build_parser, execute
from app.models import RunSummary, Status, Task
from app.product_models import ProductCollection, ProductRecord, ProductStatus


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
    _FakeProductRunner.instances.clear()
    _FakeProductOutputBundle.instances.clear()
    _FakeProductOutputBundle.raise_on_write = None
    _FakeProductOutputBundle.blocked_flag = False

    monkeypatch.setattr(main, "load_tasks", lambda p: [Task("t1", "英雄", None)])
    monkeypatch.setattr(main, "ExcelStore", _FakeStore)
    monkeypatch.setattr(main, "BrowserSession", _FakeBrowserSession)
    monkeypatch.setattr(main, "DoubanMovieAdapter", _FakeAdapter)
    monkeypatch.setattr(main, "Runner", _FakeRunner)
    monkeypatch.setattr(main, "WebScrapingDevAdapter", _FakeProductAdapter)
    monkeypatch.setattr(main, "ProductRunner", _FakeProductRunner)
    monkeypatch.setattr(main, "ProductOutputBundle", _FakeProductOutputBundle)
    monkeypatch.setattr(
        main, "configure_logging", lambda p: logging.getLogger("browser_bot")
    )

    csv = tmp_path / "in.csv"
    csv.write_text("query\n英雄\n", encoding="utf-8")
    out = tmp_path / "out.xlsx"

    return {
        "csv": csv,
        "out": out,
        "out_dir": "outputs/demo",
        "profile_dir": "browser-profile/web-scraping-dev",
    }


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


# --------------------------------------------------------------------------- #
# Test doubles for collect-products
# --------------------------------------------------------------------------- #


class _FakeProductAdapter:
    """Empty stand-in for WebScrapingDevAdapter — never invoked in unit tests."""


class _FakeProductRunner:
    """Records every construction call and returns a configurable collection.

    Mirrors the production ``ProductRunner`` keyword-only signature so the
    CLI passes arguments the same way. ``next_collection`` controls the
    return value of ``run()`` so individual tests can flip the
    ``blocked`` flag without re-instantiating the fake.
    """

    instances: list = []
    next_collection_blocked: bool = False

    def __init__(
        self,
        adapter: object,
        tab: object,
        *,
        max_products: int,
        min_interval_seconds: float,
        logger: logging.Logger,
        artifacts_dir: Path,
    ) -> None:
        self.adapter = adapter
        self.tab = tab
        self.max_products = max_products
        self.min_interval_seconds = min_interval_seconds
        self.logger = logger
        self.artifacts_dir = artifacts_dir
        _FakeProductRunner.instances.append(self)

    def run(self) -> ProductCollection:  # type: ignore[override]
        record = ProductRecord.success_fixture(
            "1", status=ProductStatus.SUCCESS
        )
        return ProductCollection.from_records(
            [record],
            generated_at="2026-07-16T20:00:00+08:00",
            blocked=_FakeProductRunner.next_collection_blocked,
        )


class _FakeProductOutputBundle:
    """Records construction and ``write`` calls; lets a test force a raise.

    ``raise_on_write`` is read once per ``write`` call so a test can wire
    an exception that fires when the CLI calls ``bundle.write(...)``.
    ``blocked_flag`` is exposed for tests that want to assert the
    run-level blocked signal is propagated.
    """

    instances: list = []
    raise_on_write: BaseException | None = None
    blocked_flag: bool = False

    def __init__(self, target_dir: Path) -> None:
        self.target_dir = target_dir
        self.write_calls: int = 0
        _FakeProductOutputBundle.instances.append(self)

    def write(self, collection: ProductCollection) -> None:  # type: ignore[override]
        self.write_calls += 1
        if _FakeProductOutputBundle.raise_on_write is not None:
            raise _FakeProductOutputBundle.raise_on_write


def products_live_args(
    stub_dependencies: dict, *extra: str
) -> list[str]:
    return [
        "collect-products",
        "--site", "web-scraping.dev",
        "--output-dir", stub_dependencies["out_dir"],
        "--live-approved",
        "--max-products", "3",
        "--profile-dir", stub_dependencies["profile_dir"],
        *extra,
    ]


# --------------------------------------------------------------------------- #
# collect-products parser contract
# --------------------------------------------------------------------------- #


def test_collect_products_parser_has_safe_defaults() -> None:
    args = build_parser().parse_args(
        [
            "collect-products",
            "--site", "web-scraping.dev",
            "--output-dir", "outputs/demo",
        ]
    )
    assert args.site == "web-scraping.dev"
    assert args.output_dir == "outputs/demo"
    assert args.headed is True
    assert args.min_interval == 2.0
    assert args.profile_dir == "browser-profile/web-scraping-dev"
    assert args.live_approved is False
    assert args.max_products is None


# --------------------------------------------------------------------------- #
# collect-products pre-browser authorization gate
# --------------------------------------------------------------------------- #


def test_collect_products_requires_live_approved(
    stub_dependencies: dict,
) -> None:
    rc = execute(
        [
            "collect-products",
            "--site", "web-scraping.dev",
            "--output-dir", stub_dependencies["out_dir"],
            "--max-products", "3",
            "--profile-dir", stub_dependencies["profile_dir"],
        ]
    )
    assert rc == 2
    assert _FakeBrowserSession.instances == []
    assert _FakeProductRunner.instances == []


@pytest.mark.parametrize("value", ["0", "11"])
def test_collect_products_rejects_max_products_outside_one_to_ten(
    stub_dependencies: dict, value: str
) -> None:
    rc = execute(
        products_live_args(stub_dependencies, "--max-products", value)
    )
    assert rc == 2
    assert _FakeBrowserSession.instances == []
    assert _FakeProductRunner.instances == []


def test_collect_products_rejects_missing_max_products(
    stub_dependencies: dict,
) -> None:
    arguments = [
        "collect-products",
        "--site", "web-scraping.dev",
        "--output-dir", stub_dependencies["out_dir"],
        "--live-approved",
        "--profile-dir", stub_dependencies["profile_dir"],
    ]
    assert execute(arguments) == 2
    assert _FakeBrowserSession.instances == []
    assert _FakeProductRunner.instances == []


def test_collect_products_rejects_headless_mode(
    stub_dependencies: dict,
) -> None:
    rc = execute(products_live_args(stub_dependencies, "--no-headed"))
    assert rc == 2
    assert _FakeBrowserSession.instances == []
    assert _FakeProductRunner.instances == []


def test_collect_products_rejects_min_interval_below_two(
    stub_dependencies: dict,
) -> None:
    rc = execute(products_live_args(stub_dependencies, "--min-interval", "1.99"))
    assert rc == 2
    assert _FakeBrowserSession.instances == []
    assert _FakeProductRunner.instances == []


def test_collect_products_rejects_unknown_site(
    stub_dependencies: dict,
) -> None:
    rc = execute(
        [
            "collect-products",
            "--site", "other.example",
            "--output-dir", stub_dependencies["out_dir"],
            "--live-approved",
            "--max-products", "3",
            "--profile-dir", stub_dependencies["profile_dir"],
        ]
    )
    assert rc == 2
    assert _FakeBrowserSession.instances == []
    assert _FakeProductRunner.instances == []


def test_collect_products_rejects_output_dir_outside_repo_outputs(
    stub_dependencies: dict, tmp_path: Path,
) -> None:
    outside = tmp_path / "escape"
    rc = execute(products_live_args(stub_dependencies, "--output-dir", str(outside)))
    assert rc == 2
    assert _FakeBrowserSession.instances == []
    assert _FakeProductRunner.instances == []


def test_collect_products_rejects_profile_dir_outside_repo_browser_profile(
    stub_dependencies: dict, tmp_path: Path,
) -> None:
    outside = tmp_path / "escape-profile"
    rc = execute(products_live_args(stub_dependencies, "--profile-dir", str(outside)))
    assert rc == 2
    assert _FakeBrowserSession.instances == []
    assert _FakeProductRunner.instances == []


# --------------------------------------------------------------------------- #
# collect-products exit code mapping
# --------------------------------------------------------------------------- #


def test_collect_products_constructs_one_browser_and_one_runner(
    stub_dependencies: dict,
) -> None:
    rc = execute(products_live_args(stub_dependencies))

    assert rc == 0
    assert len(_FakeBrowserSession.instances) == 1
    assert len(_FakeProductRunner.instances) == 1
    runner = _FakeProductRunner.instances[0]
    session = _FakeBrowserSession.instances[0]
    assert runner.tab is session._tab
    assert runner.max_products == 3
    assert runner.min_interval_seconds == 2.0
    assert session.profile_dir == Path("browser-profile/web-scraping-dev")
    assert len(_FakeProductOutputBundle.instances) == 1
    bundle = _FakeProductOutputBundle.instances[0]
    assert bundle.write_calls == 1
    assert bundle.target_dir == Path("outputs/demo")


def test_collect_products_returns_3_when_collection_blocked(
    stub_dependencies: dict,
) -> None:
    _FakeProductRunner.next_collection_blocked = True

    rc = execute(products_live_args(stub_dependencies))

    assert rc == 3
    assert _FakeProductOutputBundle.instances[0].write_calls == 1


def test_collect_products_returns_4_for_output_locked_error(
    stub_dependencies: dict,
) -> None:
    _FakeProductOutputBundle.raise_on_write = OutputLockedError("locked")

    rc = execute(products_live_args(stub_dependencies))

    assert rc == 4


def test_collect_products_returns_5_for_unexpected_browser_error(
    stub_dependencies: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BoomSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> object:
            raise RuntimeError("product browser boom")

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

    monkeypatch.setattr(main, "BrowserSession", _BoomSession)

    rc = execute(products_live_args(stub_dependencies))

    assert rc == 5


def test_collect_products_returns_5_for_unexpected_runner_error(
    stub_dependencies: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BoomRunner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def run(self) -> ProductCollection:
            raise RuntimeError("product runner boom")

    monkeypatch.setattr(main, "ProductRunner", _BoomRunner)

    rc = execute(products_live_args(stub_dependencies))

    assert rc == 5
    assert _FakeProductOutputBundle.instances == []
