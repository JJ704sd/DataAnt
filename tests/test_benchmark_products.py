"""Offline tests for the local product pipeline benchmark.

The benchmark only uses Task 0 fixture collections, fixture HTML
files under ``tests/fixtures/``, and a :class:`TemporaryDirectory` for
output. It must never instantiate :class:`BrowserSession` or touch the
live web-scraping.dev host.
"""

from __future__ import annotations

from scripts.benchmark_products import run_benchmark


def test_benchmark_report_contains_limits_and_sizes(tmp_path) -> None:
    report = run_benchmark(counts=(1,), iterations=1, output_root=tmp_path)

    assert report["writer_workers"] == 3
    assert report["parser_workers"] == 2
    assert report["max_queue_depth"] <= 2
    assert report["runs"]
    assert report["runs"][0]["bundle_bytes"] > 0
    assert report["runs"][0]["products_json_bytes"] > 0
    assert report["runs"][0]["gallery_html_bytes"] > 0
    assert report["runs"][0]["products_xlsx_bytes"] > 0
    # run_benchmark must not leave any writer output behind in
    # ``output_root``: it owns its own TemporaryDirectory.
    assert not list(tmp_path.glob("*.xlsx"))
    assert not list(tmp_path.glob("*.html"))
    assert not list(tmp_path.glob("*.json"))


def test_benchmark_default_scales_match_plan() -> None:
    report = run_benchmark(counts=(1, 5, 10), iterations=1, output_root=None)

    counts = [run["count"] for run in report["runs"]]
    assert counts == [1, 5, 10]
    assert all("peak_memory_bytes" in run for run in report["runs"])
    assert all("total_local_ms" in run for run in report["runs"])


def test_benchmark_rejects_unknown_count() -> None:
    import pytest

    with pytest.raises(ValueError, match="count"):
        run_benchmark(counts=(7,), iterations=1, output_root=None)
