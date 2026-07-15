from __future__ import annotations

import argparse
from pathlib import Path

from app.browser_session import BrowserSession
from app.diagnostics import configure_logging
from app.excel_store import ExcelStore, OutputLockedError
from app.input_loader import load_tasks
from app.models import Status
from app.runner import Runner
from app.sites.douban_movie import DoubanMovieAdapter


_ARTIFACTS_DIR = Path("artifacts")
_PROFILE_DEFAULT = "browser-profile/douban"
_MIN_INTERVAL_DEFAULT = 5.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="browser-bot-demo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--input", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument(
        "--headed", action=argparse.BooleanOptionalAction, default=True
    )
    run_parser.add_argument("--retry-status", action="append", default=[])
    run_parser.add_argument(
        "--min-interval", type=float, default=_MIN_INTERVAL_DEFAULT
    )
    run_parser.add_argument("--browser-path", default=None)
    run_parser.add_argument("--profile-dir", default=_PROFILE_DEFAULT)

    return parser


def execute(argv: list[str] | None = None) -> int:
    """Wire the run subcommand end-to-end and map outcomes to exit codes.

    Sequence is fixed: parse args, configure logging, load input, convert
    retry strings to ``Status`` (before any browser work), build the
    Excel store, enter ``BrowserSession`` exactly once, hand the same
    ``tab`` to ``Runner``, then exit the context. ``OutputLockedError``
    is caught explicitly (exit 4); any other exception during the
    browser/runner phase is treated as a global unexpected error (exit 5).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    logger = configure_logging(_ARTIFACTS_DIR)

    try:
        tasks = load_tasks(Path(args.input))
    except ValueError as exc:
        logger.error("Input error: %s", exc)
        return 2

    try:
        retry_statuses = [Status(s) for s in args.retry_status]
    except ValueError as exc:
        logger.error("Invalid retry status: %s", exc)
        return 2

    try:
        store = ExcelStore(Path(args.output))
    except ValueError as exc:
        logger.error("Output config error: %s", exc)
        return 2

    browser_path = Path(args.browser_path) if args.browser_path else None
    profile_dir = Path(args.profile_dir)

    try:
        with BrowserSession(
            args.headed, _ARTIFACTS_DIR, profile_dir, browser_path
        ) as tab:
            summary = Runner(
                DoubanMovieAdapter(),
                store,
                tab,
                args.min_interval,
                retry_statuses,
                logger,
                _ARTIFACTS_DIR,
            ).run(tasks)
    except OutputLockedError as exc:
        logger.error("Output locked: %s", exc)
        return 4
    except Exception as exc:  # noqa: BLE001 — exit code 5 is the catch-all.
        logger.exception("Unexpected error: %s", exc)
        return 5

    if summary.blocked:
        logger.error("Run was blocked by site protection")
        return 3

    return 0


def main() -> int:
    return execute()


if __name__ == "__main__":
    raise SystemExit(main())
