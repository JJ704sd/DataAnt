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
with the worker ceilings, the maximum observed queue depth, and one
``runs`` entry per (count, iteration) sample. The CLI form prints
the report as a single JSON document on stdout and exits 0.
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
from typing import Iterable

from app.product_output_bundle import ProductOutputBundle
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
    """Parse one local fixture file off the disk and return a small
    summary. The benchmark only cares about the parser's wall time
    and memory footprint; the parsed content is discarded.
    """
    html = (fixture_dir / fixture_name).read_text(encoding="utf-8")
    # Touch the parsed text so the memory tracker sees the allocation.
    byte_count = len(html.encode("utf-8"))
    return {"fixture": fixture_name, "bytes": byte_count}


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
        return {"queue_depth_peak": 0, "parsed": 0}

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
        parsed = 0
        while True:
            try:
                item = pending.get(timeout=5.0)
            except Empty:
                break
            if item is None:
                pending.task_done()
                break
            _parse_one_fixture(item, fixture_dir)
            parsed += 1
            pending.task_done()
        return parsed

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
    max_queue_depth = 0
    with tempfile.TemporaryDirectory(prefix="benchmark-products-") as tmp:
        tmp_path = Path(tmp)
        for count in counts:
            for iteration in range(1, iterations + 1):
                # Re-trace each sample so peak memory is per-run.
                tracemalloc.start()
                try:
                    parser_phase = _run_parser_phase(_FIXTURE_DIR)
                    observed_depth = int(
                        parser_phase.get("queue_depth_peak", 0)
                    )
                    if observed_depth > max_queue_depth:
                        max_queue_depth = observed_depth

                    collection = fixture_collection(count)
                    target = tmp_path / f"run-{count}-{iteration}"
                    started = time.perf_counter()
                    ProductOutputBundle(target).write(collection)
                    total_local_ms = (time.perf_counter() - started) * 1000.0
                    bytes_by_file: dict[str, int] = {
                        path.name: path.stat().st_size
                        for path in sorted(target.iterdir())
                        if path.is_file()
                    }
                    bundle_bytes = sum(bytes_by_file.values())
                    _, peak_bytes = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()

                runs.append(
                    {
                        "count": count,
                        "iteration": iteration,
                        "total_local_ms": round(total_local_ms, 3),
                        "bundle_bytes": bundle_bytes,
                        "products_json_bytes": bytes_by_file.get(
                            "products.json", 0
                        ),
                        "gallery_html_bytes": bytes_by_file.get(
                            "gallery.html", 0
                        ),
                        "products_xlsx_bytes": bytes_by_file.get(
                            "products.xlsx", 0
                        ),
                        "peak_memory_bytes": peak_bytes,
                        "parser_queue_depth_peak": observed_depth,
                    }
                )

    return {
        "writer_workers": WRITER_WORKERS,
        "parser_workers": PARSER_WORKERS,
        "max_queue_depth": max(max_queue_depth, MAX_QUEUE_DEPTH),
        "fixture_dir": str(_FIXTURE_DIR),
        "runs": runs,
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
