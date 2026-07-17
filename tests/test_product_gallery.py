from dataclasses import replace

from app.product_json import build_product_output_snapshot
from app.product_gallery import render_gallery
from app.product_models import (
    ProductCollection,
    ProductListing,
    ProductRecord,
    ProductStatus,
)


def gallery() -> str:
    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    return render_gallery(collection)


def quality_gallery() -> str:
    partial_a = replace(
        ProductRecord.success_fixture(
            "2",
            status=ProductStatus.PARTIAL,
            error_message="missing optional fields: category",
        ),
        category="",
        description="Partial product A",
        primary_image_url="https://web-scraping.dev/assets/products/2.webp",
        brand="Brand A",
    )
    partial_b = replace(
        ProductRecord.success_fixture(
            "3",
            status=ProductStatus.PARTIAL,
            error_message="missing optional fields: category",
        ),
        category="   ",
        description="Partial product B",
        primary_image_url="https://web-scraping.dev/assets/products/3.webp",
        brand="Brand B",
    )
    failed = ProductRecord.failure(
        ProductListing(
            "4",
            "https://web-scraping.dev/product/4",
            "",
        ),
        ProductStatus.PAGE_CHANGED,
        "Missing required detail fields: name",
    )
    collection = ProductCollection.from_records(
        [
            ProductRecord.success_fixture("1"),
            partial_a,
            partial_b,
            failed,
        ],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    return render_gallery(collection)


def test_gallery_is_self_contained_and_has_required_controls() -> None:
    page = gallery()
    assert '<input id="search"' in page
    assert '<select id="category-filter"' in page
    assert '<select id="status-filter"' in page
    assert '<select id="price-sort"' in page
    assert 'id="product-grid"' in page
    assert 'id="evidence-panel"' in page
    assert "function renderProducts()" in page
    assert "function selectProduct(productId)" in page


def test_gallery_embeds_data_without_external_script_or_font_dependencies() -> None:
    page = gallery()

    for forbidden in (
        "<script src=",
        "@import url(",
        "@font-face",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
    ):
        assert forbidden not in page
    assert '"product_id":"1"' in page


def test_gallery_escapes_product_content_before_embedding() -> None:
    dangerous = ProductRecord.success_fixture("1")
    dangerous = replace(
        dangerous,
        name="</script><script>alert(1)</script>",
    )
    collection = ProductCollection.from_records(
        [dangerous],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    page = render_gallery(collection)
    assert "</script><script>alert(1)</script>" not in page
    assert "\\u003c/script\\u003e" in page


def test_gallery_renders_quality_summary_and_missing_field_aggregation() -> None:
    page = quality_gallery()

    assert 'id="summary-quality"' in page
    assert 'id="summary-completeness">1 / 4<' in page
    assert 'id="summary-missing-fields">Missing category: 2<' in page
    assert 'id="summary-context">Showing 4 of 4 records<' in page


def test_gallery_exposes_partial_reason_and_uncategorized_contract() -> None:
    page = quality_gallery()

    for fragment in (
        "function missingFieldsFor(product)",
        "function categoryValue(product)",
        "function categoryLabel(product)",
        'var UNCATEGORIZED_VALUE = "__UNCATEGORIZED__";',
        "Uncategorized",
        "Missing fields",
        "Original reason",
        "Data quality",
        'aria-live="polite"',
        'aria-label="Status: ',
        ".product-card:focus-visible",
    ):
        assert fragment in page
    assert "missing optional fields: category" in page


def test_gallery_formats_timestamps_without_character_breaking() -> None:
    page = quality_gallery()

    assert (
        'id="summary-generated">2026-07-16 20:00:00 (+08:00)<'
        in page
    )
    assert "function formatTimestamp(value)" in page
    assert "word-break: normal" in page
    assert "overflow-wrap: normal" in page


def test_gallery_recomputes_summary_for_visible_snapshot() -> None:
    page = quality_gallery()

    assert "function summarizeQuality(items)" in page
    assert "renderSummary(filtered);" in page
    assert "Showing \" + current.total + \" of \" + products.length" in page
    assert "categoryValue(product) !== state.category" in page
    assert "formatTimestamp(product.collected_at)" in page


def test_gallery_preserves_placeholder_like_product_values() -> None:
    dangerous = replace(
        ProductRecord.success_fixture("1"),
        name="__TOTAL__",
    )
    collection = ProductCollection.from_records(
        [dangerous],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )

    page = render_gallery(collection)

    assert '"name":"__TOTAL__"' in page


def test_gallery_validates_source_links_before_creating_evidence_href() -> None:
    dangerous = replace(
        ProductRecord.success_fixture("1"),
        product_url="javascript:alert(1)",
    )
    collection = ProductCollection.from_records(
        [dangerous],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )

    page = render_gallery(collection)

    assert '"product_url":"javascript:alert(1)"' in page
    assert "function safeSourceUrl(value)" in page
    assert "var safeLink = safeSourceUrl(value);" in page


def test_gallery_falls_back_when_a_failed_record_has_no_reason() -> None:
    failed = ProductRecord.failure(
        ProductListing(
            "5",
            "https://web-scraping.dev/product/5",
            "",
        ),
        ProductStatus.PAGE_CHANGED,
        "",
    )
    collection = ProductCollection.from_records(
        [failed],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )

    page = render_gallery(collection)

    assert '"error_message":""' in page
    assert 'return error || "Failure reason unavailable";' in page


def test_gallery_keeps_failure_aware_quality_summary_copy() -> None:
    page = quality_gallery()

    assert 'if (!summary.total) return "No records";' in page
    assert '"Fields complete for evaluated records"' in page
    assert '"Not evaluated"' in page


def test_gallery_preserves_timestamp_words_in_evidence_rows() -> None:
    page = quality_gallery()

    assert ".evidence-panel .row .val.timestamp" in page


def test_gallery_uses_supplied_snapshot(monkeypatch) -> None:
    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    snapshot = build_product_output_snapshot(collection)
    monkeypatch.setattr(
        "app.product_gallery.build_product_output_snapshot",
        lambda _collection: (_ for _ in ()).throw(
            AssertionError("gallery rebuilt payload")
        ),
    )

    page = render_gallery(collection, snapshot=snapshot)

    assert '"product_id":"1"' in page


def test_gallery_embeds_supplied_snapshot_without_reserializing_with_spaces() -> None:
    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    snapshot = build_product_output_snapshot(collection)

    page = render_gallery(collection, snapshot=snapshot)
    embedded = page.split(
        '<script id="product-data" type="application/json">', 1
    )[1].split("</script>", 1)[0]

    expected = snapshot.json_text.rstrip("\n")
    expected = expected.replace("<", "\\u003c")
    expected = expected.replace(">", "\\u003e")
    expected = expected.replace("&", "\\u0026")
    assert embedded == expected
