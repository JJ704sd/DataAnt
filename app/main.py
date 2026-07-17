from __future__ import annotations

import argparse
import time
from pathlib import Path

from app.browser_session import BrowserSession
from app.diagnostics import configure_logging
from app.excel_store import ExcelStore, OutputLockedError
from app.input_loader import load_tasks
from app.models import Status
from app.product_output_bundle import ProductOutputBundle
from app.product_runner import ProductRunMetrics, ProductRunner
from app.runner import Runner
from app.sites.douban_movie import DoubanMovieAdapter
from app.sites.web_scraping_dev import WebScrapingDevAdapter


_ARTIFACTS_DIR = Path("artifacts")
_PROFILE_DEFAULT = "browser-profile/douban"
_MIN_INTERVAL_DEFAULT = 5.0

_LIVE_MIN_INTERVAL = 5.0
_LIVE_MAX_QUERIES = 10


_PRODUCT_PROFILE_DEFAULT = "browser-profile/web-scraping-dev"
_PRODUCT_MIN_INTERVAL_DEFAULT = 2.0
_PRODUCT_LIVE_MIN_INTERVAL = 2.0
_PRODUCT_LIVE_MAX = 10


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
    run_parser.add_argument("--live-approved", action="store_true")
    run_parser.add_argument("--max-queries", type=int, default=None)

    products_parser = subparsers.add_parser("collect-products")
    products_parser.add_argument("--site", required=True)
    products_parser.add_argument("--output-dir", required=True)
    products_parser.add_argument(
        "--headed", action=argparse.BooleanOptionalAction, default=True
    )
    products_parser.add_argument(
        "--min-interval", type=float, default=_PRODUCT_MIN_INTERVAL_DEFAULT
    )
    products_parser.add_argument("--browser-path", default=None)
    products_parser.add_argument(
        "--profile-dir", default=_PRODUCT_PROFILE_DEFAULT
    )
    products_parser.add_argument("--live-approved", action="store_true")
    products_parser.add_argument("--max-products", type=int, default=None)

    return parser


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


def _validate_product_live_run(
    args: argparse.Namespace, logger
) -> bool:
    """Validate the controlled web-scraping.dev live-run gate.

    Runs in this fixed order so failures always short-circuit before
    any ``BrowserSession`` is created, the adapter is instantiated, the
    runner is constructed, or the output bundle is opened:

    1. ``--live-approved`` must be present.
    2. ``--max-products`` must be an integer in ``[1, 10]``.
    3. The browser must run headed.
    4. ``--min-interval`` must be at least 2 seconds.
    5. ``--site`` must be the approved ``web-scraping.dev`` identifier.
    6. The output directory must resolve inside the repository
       ``outputs/`` root.
    7. The profile directory must resolve inside the repository
       ``browser-profile/`` root.
    """
    if not args.live_approved:
        logger.error("Live run requires --live-approved")
        return False
    if (
        args.max_products is None
        or not 1 <= args.max_products <= _PRODUCT_LIVE_MAX
    ):
        logger.error(
            "--max-products must be between 1 and %s", _PRODUCT_LIVE_MAX
        )
        return False
    if not args.headed:
        logger.error("Live run requires headed browser mode")
        return False
    if args.min_interval < _PRODUCT_LIVE_MIN_INTERVAL:
        logger.error(
            "Live run requires --min-interval >= %.1f",
            _PRODUCT_LIVE_MIN_INTERVAL,
        )
        return False
    if args.site != "web-scraping.dev":
        logger.error("Unsupported site: %s", args.site)
        return False
    repo_root = Path(__file__).resolve().parent.parent
    output_path = Path(args.output_dir).resolve()
    profile_path = Path(args.profile_dir).resolve()
    outputs_root = (repo_root / "outputs").resolve()
    profiles_root = (repo_root / "browser-profile").resolve()
    if not output_path.is_relative_to(outputs_root):
        logger.error(
            "Output dir must live inside %s", outputs_root
        )
        return False
    if not profile_path.is_relative_to(profiles_root):
        logger.error(
            "Profile dir must live inside %s", profiles_root
        )
        return False
    return True


def _execute_douban(args: argparse.Namespace, logger) -> int:
    """Run the existing Douban flow; preserved behavior contract."""
    try:
        tasks = load_tasks(Path(args.input))
    except ValueError as exc:
        logger.error("Input error: %s", exc)
        return 2

    if not _validate_live_run(args, len(tasks), logger):
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


def _execute_products(args: argparse.Namespace, logger) -> int:
    """Run the controlled product collection flow.

    The live-run gate runs first, before any ``BrowserSession``,
    adapter, runner, or output bundle is created. On success, one
    browser session drives one product runner and one output bundle.
    Exit codes: 0 success, 2 validation failure, 3 blocked run, 4
    output lock, 5 unclassified exception.
    """
    if not _validate_product_live_run(args, logger):
        return 2

    browser_path = Path(args.browser_path) if args.browser_path else None
    profile_dir = Path(args.profile_dir)
    output_dir = Path(args.output_dir)
    metrics = ProductRunMetrics()

    try:
        with BrowserSession(
            args.headed, _ARTIFACTS_DIR, profile_dir, browser_path
        ) as tab:
            adapter = WebScrapingDevAdapter()
            runner = ProductRunner(
                adapter,
                tab,
                max_products=args.max_products,
                min_interval_seconds=args.min_interval,
                logger=logger,
                artifacts_dir=_ARTIFACTS_DIR,
                metrics=metrics,
            )
            collection = runner.run()
    except OutputLockedError as exc:
        logger.error("Output locked: %s", exc)
        return 4
    except Exception as exc:  # noqa: BLE001 — exit code 5 is the catch-all.
        logger.exception("Unexpected error: %s", exc)
        return 5

    try:
        bundle_started = time.perf_counter()
        ProductOutputBundle(output_dir).write(collection)
        local_output_ms = (time.perf_counter() - bundle_started) * 1000.0
    except OutputLockedError as exc:
        logger.error("Output locked: %s", exc)
        return 4
    except Exception as exc:  # noqa: BLE001 — exit code 5 is the catch-all.
        logger.exception("Unexpected error: %s", exc)
        return 5

    # Read back the three file sizes locally so the metric log stays
    # strictly numeric. No HTML, cookie, header, profile path, or
    # API key value is ever read or logged here.
    bytes_by_file: dict[str, int] = {}
    if output_dir.is_dir():
        for artifact in sorted(output_dir.iterdir()):
            if artifact.is_file():
                bytes_by_file[artifact.name] = artifact.stat().st_size
    bundle_bytes = sum(bytes_by_file.values())
    writer_count = len(bytes_by_file)
    record_count = collection.summary.total
    logger.info(
        "stage=metrics paced_operations=%s network_retry_count=%s "
        "detail_records=%s discovery_ms=%.3f detail_ms=%.3f",
        metrics.paced_operations,
        metrics.network_retry_count,
        metrics.detail_records,
        metrics.discovery_seconds * 1000.0,
        metrics.detail_seconds * 1000.0,
    )
    logger.info(
        "stage=bundle local_output_ms=%.3f writers=%s records=%s "
        "bundle_bytes=%s",
        local_output_ms,
        writer_count,
        record_count,
        bundle_bytes,
    )

    if collection.summary.blocked:
        logger.error("Run was blocked by site protection")
        return 3

    return 0


def execute(argv: list[str] | None = None) -> int:
    """Parse CLI args, configure logging, then dispatch by subcommand.

    The Douban and product flows each own their own pre-browser
    authorization gate, output lifecycle, and exit-code mapping. This
    dispatcher only chooses the right one.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    logger = configure_logging(_ARTIFACTS_DIR)

    if args.command == "run":
        return _execute_douban(args, logger)
    if args.command == "collect-products":
        return _execute_products(args, logger)
    raise AssertionError(f"unsupported command: {args.command}")


def main() -> int:
    return execute()


if __name__ == "__main__":
    raise SystemExit(main())
