"""Offline tests for the bounded product runner.

The runner is driven by a fake adapter that records every list-page
and detail-page call, returns canned :class:`ProductPage` /
:class:`ProductRecord` values, or raises the existing site errors.
This keeps the suite fully offline and removes the need to spin up a
real browser.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.product_models import (
    ProductListing,
    ProductPage,
    ProductRecord,
    ProductStatus,
)
from app.product_runner import ProductRunner
from app.site_errors import BlockedError, NetworkError, PageChangedError
from app.sites.web_scraping_dev import WebScrapingDevAdapter


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


def _default_record(product_id: str) -> ProductRecord:
    return ProductRecord(
        product_id=product_id,
        source_site="web-scraping.dev",
        product_url=f"https://web-scraping.dev/product/{product_id}",
        name=f"Product {product_id}",
        current_price=Decimal("9.99"),
        currency="USD",
        status=ProductStatus.SUCCESS,
        collected_at="2026-07-16T20:00:00+08:00",
    )


class FakeAdapter:
    """In-memory adapter double for the product runner.

    - ``pages`` maps list-page URL to a :class:`ProductPage` or an
      :class:`BaseException` to raise.
    - ``products`` maps ``product_id`` to a :class:`ProductRecord` to
      return or an :class:`BaseException` to raise on the detail call.
    - ``single_page`` builds a one-page adapter for tests that do not
      need pagination.
    """

    PRODUCTS_URL = WebScrapingDevAdapter.PRODUCTS_URL

    def __init__(
        self,
        pages: dict[str, ProductPage | BaseException] | None = None,
        products: dict[str, ProductRecord | BaseException] | None = None,
    ) -> None:
        self.pages: dict[str, ProductPage | BaseException] = dict(pages or {})
        self.products: dict[str, ProductRecord | BaseException] = dict(
            products or {}
        )
        self.list_calls: list[str] = []
        self.product_calls: list[str] = []

    @classmethod
    def single_page(cls, *product_ids: str) -> "FakeAdapter":
        listings = tuple(
            ProductListing(
                product_id=pid,
                product_url=f"https://web-scraping.dev/product/{pid}",
            )
            for pid in product_ids
        )
        products = {pid: _default_record(pid) for pid in product_ids}
        return cls(
            pages={cls.PRODUCTS_URL: ProductPage(listings, None)},
            products=products,
        )

    def fetch_products_page(self, tab, url: str) -> ProductPage:
        self.list_calls.append(url)
        if url in self.pages:
            payload = self.pages[url]
            if isinstance(payload, BaseException):
                raise payload
            return payload
        raise NetworkError(f"unexpected list URL {url!r}")

    def fetch_product(
        self, tab, listing: ProductListing
    ) -> ProductRecord:
        self.product_calls.append(listing.product_id)
        if listing.product_id in self.products:
            payload = self.products[listing.product_id]
            if isinstance(payload, BaseException):
                raise payload
            return payload
        return _default_record(listing.product_id)


# --------------------------------------------------------------------------- #
# Step 1: pagination, deduplication, and limit
# --------------------------------------------------------------------------- #


def test_runner_crosses_pages_deduplicates_and_honors_limit() -> None:
    adapter = FakeAdapter(
        pages={
            "https://web-scraping.dev/products": ProductPage(
                (
                    ProductListing("1", "https://web-scraping.dev/product/1"),
                    ProductListing("2", "https://web-scraping.dev/product/2"),
                ),
                "https://web-scraping.dev/products?page=2",
            ),
            "https://web-scraping.dev/products?page=2": ProductPage(
                (
                    ProductListing("2", "https://web-scraping.dev/product/2"),
                    ProductListing("3", "https://web-scraping.dev/product/3"),
                ),
                None,
            ),
        },
        products={
            "1": _default_record("1"),
            "2": _default_record("2"),
            "3": _default_record("3"),
        },
    )

    collection = ProductRunner(
        adapter, object(), max_products=3, min_interval_seconds=0
    ).run()

    assert [r.product_id for r in collection.records] == ["1", "2", "3"]
    assert adapter.product_calls == ["1", "2", "3"]


def test_blocked_detail_stops_remaining_products() -> None:
    adapter = FakeAdapter.single_page("1", "2", "3")
    adapter.products["1"] = _default_record("1")
    adapter.products["2"] = BlockedError("429 rate limited")

    collection = ProductRunner(
        adapter, object(), max_products=3, min_interval_seconds=0
    ).run()

    assert [r.product_id for r in collection.records] == ["1", "2"]
    assert collection.records[1].status is ProductStatus.BLOCKED
    assert collection.summary.blocked is True
    assert adapter.product_calls == ["1", "2"]


# --------------------------------------------------------------------------- #
# Step 4: pacing and bounded network retry
# --------------------------------------------------------------------------- #


def test_two_list_visits_and_three_detail_visits_each_throttled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "app.product_runner.time.sleep",
        lambda seconds: sleeps.append(float(seconds)),
    )
    # Freeze the clock: every monotonic() call returns 0 so the
    # pacing logic always sleeps the full min_interval budget.
    monkeypatch.setattr(
        "app.product_runner.time.monotonic", lambda: 0.0
    )

    adapter = FakeAdapter(
        pages={
            WebScrapingDevAdapter.PRODUCTS_URL: ProductPage(
                (
                    ProductListing("1", "https://web-scraping.dev/product/1"),
                    ProductListing("2", "https://web-scraping.dev/product/2"),
                ),
                "https://web-scraping.dev/products?page=2",
            ),
            "https://web-scraping.dev/products?page=2": ProductPage(
                (ProductListing("3", "https://web-scraping.dev/product/3"),),
                None,
            ),
        },
        products={
            "1": _default_record("1"),
            "2": _default_record("2"),
            "3": _default_record("3"),
        },
    )

    collection = ProductRunner(
        adapter,
        object(),
        max_products=3,
        min_interval_seconds=1.0,
    ).run()

    assert len(collection.records) == 3
    # Two list-page visits + three detail-page visits = 5 paced calls.
    # With the clock frozen, each pacing call must sleep the full 1.0s.
    assert sleeps == [pytest.approx(1.0)] * 5
    assert adapter.list_calls == [
        "https://web-scraping.dev/products",
        "https://web-scraping.dev/products?page=2",
    ]
    assert adapter.product_calls == ["1", "2", "3"]


def test_first_network_error_then_success_only_waits_two_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "app.product_runner.time.sleep",
        lambda seconds: sleeps.append(float(seconds)),
    )
    monkeypatch.setattr(
        "app.product_runner.time.monotonic", lambda: 0.0
    )

    adapter = FakeAdapter.single_page("1")
    detail_attempts = {"count": 0}
    original_fetch_product = adapter.fetch_product

    def fetch_product(tab, listing):
        detail_attempts["count"] += 1
        if detail_attempts["count"] == 1:
            raise NetworkError("first attempt transient")
        return original_fetch_product(tab, listing)

    adapter.fetch_product = fetch_product  # type: ignore[method-assign]

    collection = ProductRunner(
        adapter, object(), max_products=1, min_interval_seconds=0
    ).run()

    assert [r.product_id for r in collection.records] == ["1"]
    assert collection.records[0].status is ProductStatus.SUCCESS
    # The pacing interval is 0 so no pacing sleep is recorded; the only
    # backoff sleeps that actually fire are between attempts. After the
    # first failure the runner must wait 2 seconds before the retry.
    assert sleeps == [pytest.approx(2.0)]


def test_three_network_failures_emit_two_and_five_second_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "app.product_runner.time.sleep",
        lambda seconds: sleeps.append(float(seconds)),
    )
    monkeypatch.setattr(
        "app.product_runner.time.monotonic", lambda: 0.0
    )

    adapter = FakeAdapter.single_page("1")

    def fetch_product(tab, listing):
        raise NetworkError(f"transient for {listing.product_id}")

    adapter.fetch_product = fetch_product  # type: ignore[method-assign]

    collection = ProductRunner(
        adapter, object(), max_products=1, min_interval_seconds=0
    ).run()

    assert [r.product_id for r in collection.records] == ["1"]
    assert collection.records[0].status is ProductStatus.NETWORK_ERROR
    # Three attempts: no sleep before the first, then 2s and 5s before
    # the second and third. The pacing interval is 0 so the only
    # recorded sleeps are the backoff sleeps.
    assert sleeps == [pytest.approx(2.0), pytest.approx(5.0)]


def test_page_changed_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "app.product_runner.time.sleep",
        lambda seconds: sleeps.append(float(seconds)),
    )
    monkeypatch.setattr(
        "app.product_runner.time.monotonic", lambda: 0.0
    )

    adapter = FakeAdapter.single_page("1")
    detail_attempts = {"count": 0}

    def fetch_product(tab, listing):
        detail_attempts["count"] += 1
        raise PageChangedError("name missing")

    adapter.fetch_product = fetch_product  # type: ignore[method-assign]

    collection = ProductRunner(
        adapter, object(), max_products=1, min_interval_seconds=0
    ).run()

    assert detail_attempts["count"] == 1
    assert collection.records[0].status is ProductStatus.PAGE_CHANGED
    # PageChangedError is not a network error; no retry backoff fires.
    # The pacing interval is 0 so no pacing sleep either.
    assert sleeps == []


def test_unclassified_exception_message_contains_only_class_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "app.product_runner.time.sleep",
        lambda seconds: sleeps.append(float(seconds)),
    )
    monkeypatch.setattr(
        "app.product_runner.time.monotonic", lambda: 0.0
    )

    adapter = FakeAdapter.single_page("1")

    class _ProbeError(RuntimeError):
        pass

    def fetch_product(tab, listing):
        raise _ProbeError("internal stack details should not leak")

    adapter.fetch_product = fetch_product  # type: ignore[method-assign]

    collection = ProductRunner(
        adapter, object(), max_products=1, min_interval_seconds=0
    ).run()

    record = collection.records[0]
    assert record.status is ProductStatus.UNEXPECTED_ERROR
    assert record.error_message == "_ProbeError"
    # Unknown exceptions must not trigger retry backoff. The pacing
    # interval is 0 so no sleep is recorded.
    assert sleeps == []


def test_max_products_one_does_not_visit_second_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "app.product_runner.time.sleep",
        lambda seconds: sleeps.append(float(seconds)),
    )
    monkeypatch.setattr(
        "app.product_runner.time.monotonic", lambda: 0.0
    )

    adapter = FakeAdapter.single_page("1", "2")

    collection = ProductRunner(
        adapter, object(), max_products=1, min_interval_seconds=0
    ).run()

    assert [r.product_id for r in collection.records] == ["1"]
    assert adapter.product_calls == ["1"]
