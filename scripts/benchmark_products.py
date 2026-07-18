"""Offline benchmark for the local product output pipeline.

Measures how long it takes :class:`ProductOutputBundle` to commit a
fixed-size bundle of products, plus the peak memory the commit
consumes, so we can track the impact of the parallel writer work
introduced in Task 3. The benchmark is fully offline:

- It uses the :func:`tests.helpers_product_performance.fixture_collection`
  helper to build a deterministic 1/5/10-product collection without
  touching the live web-scraping.dev host.
- It uses a :class:`TemporaryDirectory` so the benchmark never writes
  a workbook or HTML page inside the repository.
- It only parses the local HTML fixtures under ``tests/fixtures/``,
  using at most 2 parser workers in parallel with a 2-slot pending
  snapshot queue, so the parser side mirrors the live architecture
  without ever calling ``tab.get()`` or touching the network.

The :func:`run_benchmark` helper returns a JSON-serialisable report
with the worker ceilings, the maximum observed queue depth, optimized
and serial-baseline entries per (count, iteration) sample, and median
comparison fields. The CLI form prints the report as a single JSON
document on stdout and exits 0.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue
from statistics import median
from typing import Iterable

from app.product_excel import ProductExcel
from app.product_gallery import render_gallery
from app.product_json import product_payload, render_product_json
from app.product_models import ProductListing
from app.product_output_bundle import ProductOutputBundle
from app.sites.web_scraping_dev import WebScrapingDevAdapter
from tests.helpers_product_performance import fixture_collection

#: Worker ceilings for the parallel writer / parser side. The writer
#: pool is the same size as :class:`ProductOutputBundle` uses; the
#: parser pool mirrors the bounded local snapshot parser described in
#: the design document and never exceeds 2.
WRITER_WORKERS: int = 3
PARSER_WORKERS: int = 2
MAX_QUEUE_DEPTH: int = 2

#: Default benchmark scales — the same 1/5/10 ladder the rest of the
#: project uses.
DEFAULT_COUNTS: tuple[int, ...] = (1, 5, 10)
DEFAULT_ITERATIONS: int = 5

#: Local fixture HTML used to drive the detached parser side without
#: touching the live host.
_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
_FIXTURE_PAGES: tuple[str, ...] = (
    "wsd_products_page_1.html",
    "wsd_products_page_2.html",
)
_FIXTURE_DETAILS: tuple[str, ...] = (
    "wsd_product_detail.html",
    "wsd_product_partial.html",
    "wsd_product_live_shape.html",
)


def _parse_one_fixture(
    fixture_name: str,
    fixture_dir: Path,
) -> dict[str, int]:
    """Parse one local fixture with the production web-scraping adapter."""
    html = (fixture_dir / fixture_name).read_text(encoding="utf-8")
    adapter = WebScrapingDevAdapter()
    if fixture_name in _FIXTURE_PAGES:
        page = adapter.parse_products_html(html, adapter.PRODUCTS_URL)
        parsed_records = len(page.listings)
    else:
        page_html = (fixture_dir / _FIXTURE_PAGES[0]).read_text(
            encoding="utf-8"
        )
        page = adapter.parse_products_html(page_html, adapter.PRODUCTS_URL)
        listing = page.listings[0] if page.listings else ProductListing(
            product_id="1",
            product_url="https://web-scraping.dev/product/1",
        )
        record = adapter.parse_detail_html(
            html,
            listing,
            listing.product_url,
        )
        parsed_records = 1 if record.product_id else 0
    return {
        "fixture": fixture_name,
        "bytes": len(html.encode("utf-8")),
        "parsed_records": parsed_records,
    }


def _run_parser_phase(
    fixture_dir: Path,
    *,
    pages: Iterable[str] = _FIXTURE_PAGES,
    details: Iterable[str] = _FIXTURE_DETAILS,
) -> dict[str, object]:
    """Run the bounded parser pool and return observed queue depth.

    The parser pool schedules snapshots through a queue of depth
    :data:`MAX_QUEUE_DEPTH` so the benchmark mirrors the design's
    "最多 2 条 pending snapshot" constraint. A separate submitter
    thread feeds the queue so the consumers see backpressure if the
    pool falls behind.
    """
    pending: "Queue[str | None]" = Queue(maxsize=MAX_QUEUE_DEPTH)
    fixtures: tuple[str, ...] = tuple(pages) + tuple(details)
    if not fixtures:
        return {"queue_depth_peak": 0, "parsed": 0, "parsed_records": 0}

    import threading

    queue_depth_peak = {"value": 0}
    depth_lock = threading.Lock()

    def submitter() -> None:
        for name in fixtures:
            pending.put(name)
            with depth_lock:
                current = pending.qsize()
                if current > queue_depth_peak["value"]:
                    queue_depth_peak["value"] = current
        # Send a sentinel per worker so the consumers can drain.
        for _ in range(PARSER_WORKERS):
            pending.put(None)

    def consumer() -> int:
        parsed_records = 0
        while True:
            try:
                item = pending.get(timeout=5.0)
            except Empty:
                break
            if item is None:
                pending.task_done()
                break
            parsed = _parse_one_fixture(item, fixture_dir)
            parsed_records += int(parsed["parsed_records"])
            pending.task_done()
        return parsed_records

    submitter_thread = threading.Thread(target=submitter, daemon=True)
    submitter_thread.start()

    parsed_total = 0
    with ThreadPoolExecutor(
        max_workers=PARSER_WORKERS,
        thread_name_prefix="product-parser",
    ) as executor:
        futures = [executor.submit(consumer) for _ in range(PARSER_WORKERS)]
        for future in futures:
            parsed_total += future.result()
    submitter_thread.join(timeout=5.0)
    return {
        "queue_depth_peak": queue_depth_peak["value"],
        "parsed": parsed_total,
        "parsed_records": parsed_total,
    }


def _output_sizes(directory: Path) -> dict[str, int]:
    return {
        path.name: path.stat().st_size
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def _verify_serial_outputs(collection, directory: Path) -> float:
    started = time.perf_counter()
    expected_ids = [record.product_id for record in collection.records]
    excel_ids = [
        record.product_id
        for record in ProductExcel.read(directory / "products.xlsx")
    ]
    payload = json.loads(
        (directory / "products.json").read_text(encoding="utf-8")
    )
    json_ids = [
        str(item.get("product_id")) for item in payload.get("products", [])
    ]
    if excel_ids != expected_ids or json_ids != expected_ids:
        raise ValueError("baseline artifacts have inconsistent product order")
    for filename in ("products.xlsx", "products.json", "gallery.html"):
        if not (directory / filename).is_file():
            raise ValueError(f"baseline output is missing {filename}")
    return (time.perf_counter() - started) * 1000.0


def _run_baseline_output(collection, target: Path) -> dict[str, object]:
    """Write the three artifacts serially through the pre-bundle APIs."""
    target.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    payload_started = time.perf_counter()
    product_payload(collection)
    payload_build_ms = (time.perf_counter() - payload_started) * 1000.0

    excel_started = time.perf_counter()
    ProductExcel.write(target / "products.xlsx", list(collection.records))
    excel_write_ms = (time.perf_counter() - excel_started) * 1000.0

    json_started = time.perf_counter()
    (target / "products.json").write_text(
        render_product_json(collection),
        encoding="utf-8",
    )
    json_write_ms = (time.perf_counter() - json_started) * 1000.0

    gallery_started = time.perf_counter()
    (target / "gallery.html").write_text(
        render_gallery(collection),
        encoding="utf-8",
    )
    gallery_write_ms = (time.perf_counter() - gallery_started) * 1000.0

    verify_ms = _verify_serial_outputs(collection, target)
    sizes = _output_sizes(target)
    return {
        "records": len(collection.records),
        "payload_build_ms": round(payload_build_ms, 3),
        "json_write_ms": round(json_write_ms, 3),
        "gallery_write_ms": round(gallery_write_ms, 3),
        "excel_write_ms": round(excel_write_ms, 3),
        "verify_ms": round(verify_ms, 3),
        "total_local_ms": round(
            (time.perf_counter() - started) * 1000.0,
            3,
        ),
        "bundle_bytes": sum(sizes.values()),
        "products_json_bytes": sizes.get("products.json", 0),
        "gallery_html_bytes": sizes.get("gallery.html", 0),
        "products_xlsx_bytes": sizes.get("products.xlsx", 0),
    }


def _run_optimized_output(collection, target: Path) -> dict[str, object]:
    """Write through ProductOutputBundle and expose its timing receipt."""
    started = time.perf_counter()
    receipt = ProductOutputBundle(target).write(collection)
    sizes = _output_sizes(target)
    total_local_ms = (time.perf_counter() - started) * 1000.0
    return {
        "records": len(receipt.product_ids),
        "payload_build_ms": round(
            receipt.payload_build_ms,
            3,
        ),
        "json_write_ms": round(
            receipt.json_write_ms,
            3,
        ),
        "gallery_write_ms": round(
            receipt.gallery_write_ms,
            3,
        ),
        "excel_write_ms": round(
            receipt.excel_write_ms,
            3,
        ),
        "verify_ms": round(
            receipt.verify_ms,
            3,
        ),
        "total_local_ms": round(total_local_ms, 3),
        "bundle_bytes": sum(sizes.values()),
        "products_json_bytes": sizes.get("products.json", 0),
        "gallery_html_bytes": sizes.get("gallery.html", 0),
        "products_xlsx_bytes": sizes.get("products.xlsx", 0),
    }


def run_benchmark(
    *,
    counts: tuple[int, ...] = DEFAULT_COUNTS,
    iterations: int = DEFAULT_ITERATIONS,
    output_root: Path | None = None,
) -> dict[str, object]:
    """Run the offline benchmark and return a JSON-serialisable report.

    Parameters
    ----------
    counts:
        Ladder of product counts. Each value must be one of
        ``{1, 5, 10}`` to match :func:`fixture_collection`'s
        fixed sample sizes.
    iterations:
        How many times to repeat each ``count``. Higher values reduce
        noise at the cost of wall-clock time.
    output_root:
        Optional directory to mirror the temporary output under. The
        benchmark never writes the finalised bundle there — it owns
        its own :class:`TemporaryDirectory` so the repository stays
        clean — but the parameter is preserved so callers and tests
        can pass ``tmp_path`` for visibility.
    """
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if not counts:
        raise ValueError("counts must not be empty")
    for count in counts:
        if count not in {1, 5, 10}:
            raise ValueError(
                f"count must be one of 1, 5, or 10, got {count}"
            )

    if output_root is not None:
        # Ensure the parent directory is visible; the benchmark still
        # uses its own TemporaryDirectory so the repo never gains a
        # permanent output artefact.
        Path(output_root).mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, object]] = []
    baseline_runs: list[dict[str, object]] = []
    max_queue_depth = 0
    with tempfile.TemporaryDirectory(prefix="benchmark-products-") as tmp:
        tmp_path = Path(tmp)
        for count in counts:
            for iteration in range(1, iterations + 1):
                parser_phase = _run_parser_phase(_FIXTURE_DIR)
                observed_depth = int(parser_phase.get("queue_depth_peak", 0))
                if observed_depth > max_queue_depth:
                    max_queue_depth = observed_depth

                collection = fixture_collection(count)
                optimized_target = tmp_path / (
                    f"run-{count}-{iteration}-optimized"
                )
                baseline_target = tmp_path / (
                    f"run-{count}-{iteration}-baseline"
                )

                # Re-trace each optimized sample so peak memory is per-run.
                tracemalloc.start()
                try:
                    optimized = _run_optimized_output(
                        collection,
                        optimized_target,
                    )
                    _, optimized_peak_bytes = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()

                # Keep the serial baseline separate so its memory sample does
                # not include the optimized writer's allocations.
                tracemalloc.start()
                try:
                    baseline = _run_baseline_output(
                        collection,
                        baseline_target,
                    )
                    _, baseline_peak_bytes = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()

                common = {
                    "count": count,
                    "iteration": iteration,
                    "parser_queue_depth_peak": observed_depth,
                    "parser_records": int(
                        parser_phase.get("parsed_records", 0)
                    ),
                }
                runs.append(
                    {
                        **common,
                        **optimized,
                        "peak_memory_bytes": optimized_peak_bytes,
                    }
                )
                baseline_runs.append(
                    {
                        **common,
                        **baseline,
                        "peak_memory_bytes": baseline_peak_bytes,
                    }
                )

    optimized_medians: dict[str, float] = {}
    baseline_medians: dict[str, float] = {}
    comparison: dict[str, dict[str, object]] = {}
    for count in dict.fromkeys(counts):
        optimized_median = round(
            float(
                median(
                    float(run["total_local_ms"])
                    for run in runs
                    if run["count"] == count
                )
            ),
            3,
        )
        baseline_median = round(
            float(
                median(
                    float(run["total_local_ms"])
                    for run in baseline_runs
                    if run["count"] == count
                )
            ),
            3,
        )
        speedup_percent = (
            ((baseline_median - optimized_median) / baseline_median) * 100.0
            if baseline_median
            else 0.0
        )
        key = str(count)
        optimized_medians[key] = optimized_median
        baseline_medians[key] = baseline_median
        comparison[key] = {
            "count": count,
            "optimized_median_total_local_ms": optimized_median,
            "baseline_median_total_local_ms": baseline_median,
            "median_speedup_percent": round(speedup_percent, 3),
            "optimized_faster": optimized_median < baseline_median,
        }

    return {
        "writer_workers": WRITER_WORKERS,
        "parser_workers": PARSER_WORKERS,
        "max_queue_depth": max_queue_depth,
        "fixture_dir": str(_FIXTURE_DIR),
        "iterations": iterations,
        "runs": runs,
        "baseline_runs": baseline_runs,
        "optimized_median_total_local_ms": optimized_medians,
        "baseline_median_total_local_ms": baseline_medians,
        "comparison": comparison,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts.benchmark_products",
        description=(
            "Offline benchmark for the local product output pipeline. "
            "Writes a TemporaryDirectory and never touches the live "
            "web-scraping.dev host."
        ),
    )
    parser.add_argument(
        "--counts",
        type=str,
        default=",".join(str(value) for value in DEFAULT_COUNTS),
        help=(
            "Comma-separated product counts. Each value must be one "
            "of 1, 5, or 10."
        ),
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help="How many times to repeat each count (default: 5).",
    )
    args = parser.parse_args(argv)

    try:
        counts = tuple(int(part) for part in args.counts.split(",") if part)
    except ValueError as exc:
        raise SystemExit(f"invalid --counts: {exc}") from exc

    report = run_benchmark(counts=counts, iterations=args.iterations)
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
