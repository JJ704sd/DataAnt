from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.product_models import (
    ProductListing,
    ProductStatus,
)
from app.site_errors import BlockedError, NetworkError
from app.sites.web_scraping_dev import WebScrapingDevAdapter


FIXTURES = Path(__file__).parent / "fixtures"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Pure URL contract
# --------------------------------------------------------------------------- #


def test_canonical_product_url_accepts_only_numeric_product_paths() -> None:
    adapter = WebScrapingDevAdapter()
    assert adapter.canonical_product_url("/product/1?ref=list#top") == (
        "https://web-scraping.dev/product/1"
    )
    with pytest.raises(ValueError, match="product URL"):
        adapter.canonical_product_url("https://example.com/product/1")
    with pytest.raises(ValueError, match="product URL"):
        adapter.canonical_product_url("/robots-disallowed")


def test_canonical_products_url_accepts_only_allowed_pagination() -> None:
    adapter = WebScrapingDevAdapter()
    assert adapter.canonical_products_url("/products?page=2") == (
        "https://web-scraping.dev/products?page=2"
    )
    assert adapter.canonical_products_url(
        "https://web-scraping.dev/products?category=consumables&page=3&sort=price"
    ) == "https://web-scraping.dev/products?category=consumables&page=3&sort=price"
    with pytest.raises(ValueError, match="products URL"):
        adapter.canonical_products_url("/robots-disallowed")
    with pytest.raises(ValueError, match="products URL"):
        adapter.canonical_products_url("/products?page=2&q=forbidden")


# --------------------------------------------------------------------------- #
# List page parser
# --------------------------------------------------------------------------- #


def test_parse_product_page_preserves_order_and_next_page() -> None:
    page = WebScrapingDevAdapter.parse_products_html(
        html("wsd_products_page_1.html"),
        "https://web-scraping.dev/products",
    )
    assert [item.product_id for item in page.listings] == ["1", "2"]
    assert [item.product_url for item in page.listings] == [
        "https://web-scraping.dev/product/1",
        "https://web-scraping.dev/product/2",
    ]
    assert page.listings[0].category == "consumables"
    assert page.next_url == "https://web-scraping.dev/products?page=2"


def test_parse_product_page_without_next_link_returns_none() -> None:
    page = WebScrapingDevAdapter.parse_products_html(
        html("wsd_products_page_2.html"),
        "https://web-scraping.dev/products?page=2",
    )
    assert [item.product_id for item in page.listings] == ["2", "3"]
    assert page.next_url is None


# --------------------------------------------------------------------------- #
# Detail page parser
# --------------------------------------------------------------------------- #


def test_parse_detail_extracts_required_and_optional_fields() -> None:
    listing = ProductListing(
        "1", "https://web-scraping.dev/product/1", "consumables"
    )
    record = WebScrapingDevAdapter.parse_detail_html(
        html("wsd_product_detail.html"),
        listing,
        listing.product_url,
    )
    assert record.status is ProductStatus.SUCCESS
    assert record.name == "Box of Chocolate Candy"
    assert record.current_price == Decimal("9.99")
    assert record.original_price == Decimal("12.99")
    assert record.primary_image_url.endswith("/assets/products/1.webp")
    assert record.brand == "ChocoDelight"
    assert record.variant_count == 2
    assert record.description == (
        "Chocolate assortment with orange and cherry fillings."
    )
    assert record.category == "consumables"


def test_missing_optional_fields_returns_partial() -> None:
    listing = ProductListing(
        "4", "https://web-scraping.dev/product/4", "consumables"
    )
    record = WebScrapingDevAdapter.parse_detail_html(
        html("wsd_product_partial.html"),
        listing,
        listing.product_url,
    )
    assert record.status is ProductStatus.PARTIAL
    assert "image" in record.error_message
    assert "brand" in record.error_message


@pytest.mark.parametrize(
    "body",
    [
        "<main><span class='price'>$9.99</span></main>",
        "<main><h3>Product</h3></main>",
        "<main><h3>Product</h3><span class='price'>not-money</span></main>",
    ],
)
def test_missing_required_detail_contract_is_page_changed(body: str) -> None:
    listing = ProductListing(
        "8", "https://web-scraping.dev/product/8", ""
    )
    record = WebScrapingDevAdapter.parse_detail_html(
        body, listing, listing.product_url
    )
    assert record.status is ProductStatus.PAGE_CHANGED


# --------------------------------------------------------------------------- #
# Blocked-page detection
# --------------------------------------------------------------------------- #


def test_blocked_page_is_detected_before_parsing() -> None:
    assert WebScrapingDevAdapter.is_blocked(
        html("wsd_product_blocked.html"), 200, "https://web-scraping.dev/blocked"
    )
    assert WebScrapingDevAdapter.is_blocked(
        "", 429, "https://web-scraping.dev/products"
    )
    assert not WebScrapingDevAdapter.is_blocked(
        html("wsd_product_detail.html"), 200, "https://web-scraping.dev/product/1"
    )


# --------------------------------------------------------------------------- #
# Browser access (fake tab) tests
# --------------------------------------------------------------------------- #


class NavigationFailureTab:
    """A tab whose navigation always returns a falsy value (offline / no network)."""

    html = ""
    url = "data:text/html,offline"

    def get(self, url: str, retry: int, timeout: int) -> bool:
        return False


class LoadedTab:
    """A tab that reports the given body and final URL after a successful get()."""

    def __init__(self, body: str, final_url: str) -> None:
        self.html = body
        self.url = final_url
        self._get_attempts = 0

    def get(self, url: str, retry: int, timeout: int) -> bool:
        self._get_attempts += 1
        return True


def test_fetch_products_rejects_external_redirect() -> None:
    tab = LoadedTab(
        html("wsd_products_page_1.html"),
        final_url="https://example.com/products",
    )
    with pytest.raises(BlockedError, match="outside"):
        WebScrapingDevAdapter().fetch_products_page(
            tab, WebScrapingDevAdapter.PRODUCTS_URL
        )


def test_fetch_product_navigation_failure_is_network_error() -> None:
    with pytest.raises(NetworkError, match="navigation failed"):
        WebScrapingDevAdapter().fetch_product(
            NavigationFailureTab(),
            ProductListing("1", "https://web-scraping.dev/product/1", ""),
        )


def test_fetch_products_navigation_failure_is_network_error() -> None:
    with pytest.raises(NetworkError, match="navigation failed"):
        WebScrapingDevAdapter().fetch_products_page(
            NavigationFailureTab(), WebScrapingDevAdapter.PRODUCTS_URL
        )


def test_fetch_products_success_returns_parsed_page() -> None:
    tab = LoadedTab(
        html("wsd_products_page_1.html"),
        final_url="https://web-scraping.dev/products",
    )
    page = WebScrapingDevAdapter().fetch_products_page(
        tab, WebScrapingDevAdapter.PRODUCTS_URL
    )
    assert [item.product_id for item in page.listings] == ["1", "2"]
    assert page.next_url == "https://web-scraping.dev/products?page=2"
    assert tab._get_attempts == 1


def test_fetch_product_success_returns_parsed_record() -> None:
    tab = LoadedTab(
        html("wsd_product_detail.html"),
        final_url="https://web-scraping.dev/product/1",
    )
    listing = ProductListing(
        "1", "https://web-scraping.dev/product/1", "consumables"
    )
    record = WebScrapingDevAdapter().fetch_product(tab, listing)
    assert record.status is ProductStatus.SUCCESS
    assert record.name == "Box of Chocolate Candy"
    assert tab._get_attempts == 1
