"""Offline tests for the local product pipeline benchmark.

The benchmark only uses Task 0 fixture collections, fixture HTML
files under ``tests/fixtures/``, and a :class:`TemporaryDirectory` for
output. It must never instantiate :class:`BrowserSession` or touch the
live web-scraping.dev host.
"""

from __future__ import annotations

from scripts.benchmark_products import (
    _FIXTURE_DIR,
    _parse_one_fixture,
    run_benchmark,
)


def test_benchmark_parser_uses_product_adapter_on_fixture() -> None:
    parsed = _parse_one_fixture(
        "wsd_products_page_1.html",
        _FIXTURE_DIR,
    )

    assert parsed["parsed_records"] > 0


def test_benchmark_report_contains_limits_and_sizes(tmp_path) -> None:
    report = run_benchmark(counts=(1,), iterations=1, output_root=tmp_path)

    assert report["writer_workers"] == 3
    assert report["parser_workers"] == 2
    assert report["max_queue_depth"] <= 2
    assert report["iterations"] == 1
    assert report["runs"]
    assert report["baseline_runs"]
    assert report["runs"][0]["parser_records"] > 0
    assert report["baseline_runs"][0]["parser_records"] > 0
    assert report["runs"][0]["bundle_bytes"] > 0
    assert report["runs"][0]["products_json_bytes"] > 0
    assert report["runs"][0]["gallery_html_bytes"] > 0
    assert report["runs"][0]["products_xlsx_bytes"] > 0
    for run in (report["runs"][0], report["baseline_runs"][0]):
        assert run["records"] == 1
        for field in (
            "payload_build_ms",
            "json_write_ms",
            "gallery_write_ms",
            "excel_write_ms",
            "verify_ms",
        ):
            assert run[field] >= 0
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
    assert report["optimized_median_total_local_ms"]
    assert report["baseline_median_total_local_ms"]
    assert report["comparison"]


def test_benchmark_comparison_is_grouped_by_product_count() -> None:
    report = run_benchmark(counts=(1, 5, 10), iterations=1, output_root=None)

    assert set(report["comparison"]) == {"1", "5", "10"}
    for count in (1, 5, 10):
        comparison = report["comparison"][str(count)]
        assert comparison["count"] == count
        assert comparison["optimized_median_total_local_ms"] >= 0
        assert comparison["baseline_median_total_local_ms"] >= 0


def test_benchmark_rejects_unknown_count() -> None:
    import pytest

    with pytest.raises(ValueError, match="count"):
        run_benchmark(counts=(7,), iterations=1, output_root=None)


def test_benchmark_rejects_empty_count_ladder() -> None:
    import pytest

    with pytest.raises(ValueError, match="counts"):
        run_benchmark(counts=(), iterations=1, output_root=None)
