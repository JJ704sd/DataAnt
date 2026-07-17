from dataclasses import replace

from app.product_gallery import render_gallery
from app.product_models import ProductCollection, ProductRecord


def gallery() -> str:
    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
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
    assert '<script src=' not in page
    assert '@import url(' not in page
    assert 'fetch(' not in page
    assert '"product_id": "1"' in page


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
