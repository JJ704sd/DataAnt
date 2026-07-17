"""Bounded product collection runner.

Drives a single ``web-scraping.dev`` session through:

- ordered, deduplicated product discovery across paginated list pages;
- per-product detail fetching with bounded 2/5s backoff on transient
  network failures;
- minimum interval pacing between every list and detail visit;
- terminal status mapping for blocked / page-changed / network /
  unexpected errors; and
- batch stop on the first blocked signal (either at discovery or
  during detail fetching).

Discovery starts at ``adapter.PRODUCTS_URL``; detail fetches stop once
``max_products`` records have been collected, or earlier when a
blocked signal aborts the batch.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.diagnostics import capture_failure
from app.product_models import (
    ProductCollection,
    ProductListing,
    ProductRecord,
    ProductStatus,
)
from app.site_errors import (
    BlockedError,
    NetworkError,
    PageChangedError,
)


# Backoff between network attempts: 0s before the first attempt, 2s
# before the second, 5s before the third. Three attempts total.
_NETWORK_BACKOFF_SECONDS: tuple[float, ...] = (0.0, 2.0, 5.0)

# Hard cap on the recorded error message so an oversized upstream
# exception string never bloats the workbook or HTML evidence.
_NETWORK_ERROR_MESSAGE_MAX = 200

# Failure statuses that warrant diagnostic capture. SUCCESS and
# PARTIAL are deliberately excluded; PARTIAL is the expected outcome
# of a valid page that is missing some optional fields, and SUCCESS
# is the desired terminal status.
_CAPTURE_STATUSES: frozenset[ProductStatus] = frozenset(
    {
        ProductStatus.NETWORK_ERROR,
        ProductStatus.PAGE_CHANGED,
        ProductStatus.BLOCKED,
        ProductStatus.UNEXPECTED_ERROR,
    }
)


class ProductRunner:
    def __init__(
        self,
        adapter: Any,
        tab: Any,
        *,
        max_products: int,
        min_interval_seconds: float,
        logger: logging.Logger | None = None,
        artifacts_dir: Path | None = None,
    ) -> None:
        if max_products <= 0:
            raise ValueError(
                f"max_products must be positive, got {max_products}"
            )
        if min_interval_seconds < 0:
            raise ValueError(
                f"min_interval_seconds must be non-negative, got "
                f"{min_interval_seconds}"
            )
        self.adapter = adapter
        self.tab = tab
        self.max_products = max_products
        self.min_interval_seconds = float(min_interval_seconds)
        self.logger = logger
        self.artifacts_dir = artifacts_dir

    # -- Public API ---------------------------------------------------- #

    def run(self) -> ProductCollection:
        """Discover, fetch, stop safely, and return one immutable collection."""
        listings, discovery_blocked = self._discover()
        records: list[ProductRecord] = []
        detail_blocked = False
        for listing in listings:
            if len(records) >= self.max_products:
                break
            record, stop = self._fetch(listing)
            records.append(record)
            if stop:
                detail_blocked = True
                break
        return ProductCollection.from_records(
            records,
            generated_at=datetime.now()
            .astimezone()
            .isoformat(timespec="seconds"),
            blocked=discovery_blocked or detail_blocked,
        )

    # -- Discovery ------------------------------------------------------ #

    def _discover(self) -> tuple[list[ProductListing], bool]:
        """Return ordered unique listings and whether discovery was blocked.

        Iterates ``adapter.PRODUCTS_URL`` and follows ``next_url`` while
        the count is below ``max_products``. The discovery loop is
        stable across pages: a product seen on an earlier page is never
        re-queued, so the returned order matches the order of first
        appearance.

        A ``BlockedError`` on any list page sets the blocked flag and
        stops the loop, preserving any listings already collected.
        ``PageChangedError``, ``NetworkError`` and any other exception
        also stop the loop but do not set the blocked flag; the runner
        then proceeds to fetch details for whatever was discovered.
        """
        seen: dict[str, ProductListing] = {}
        blocked = False
        url: str | None = self.adapter.PRODUCTS_URL
        while url:
            if len(seen) >= self.max_products:
                break
            try:
                page = self._paced(
                    lambda: self.adapter.fetch_products_page(self.tab, url)
                )
            except BlockedError as exc:
                blocked = True
                if self.logger is not None:
                    self.logger.warning(
                        "stage=discover status=BLOCKED url=%s",
                        url,
                    )
                break
            except PageChangedError as exc:
                if self.logger is not None:
                    self.logger.warning(
                        "stage=discover status=PAGE_CHANGED url=%s",
                        url,
                    )
                break
            except NetworkError as exc:
                if self.logger is not None:
                    self.logger.warning(
                        "stage=discover status=NETWORK_ERROR url=%s",
                        url,
                    )
                break
            except Exception as exc:  # pragma: no cover - defensive
                if self.logger is not None:
                    self.logger.warning(
                        "stage=discover status=UNEXPECTED_ERROR "
                        "url=%s error=%s",
                        url,
                        type(exc).__name__,
                    )
                break
            for listing in page.listings:
                if listing.product_id in seen:
                    continue
                seen[listing.product_id] = listing
                if len(seen) >= self.max_products:
                    break
            url = page.next_url
        return list(seen.values()), blocked

    # -- Detail fetching ----------------------------------------------- #

    def _fetch(
        self, listing: ProductListing
    ) -> tuple[ProductRecord, bool]:
        """Return one terminal record and whether the batch must stop.

        A ``BlockedError`` from the detail adapter produces a
        ``BLOCKED`` record and signals the runner to stop the batch.
        ``PageChangedError`` and ``NetworkError`` (after the bounded
        retry has exhausted) produce terminal records and let the
        runner continue with the remaining listings. Any other
        exception is captured as ``UNEXPECTED_ERROR`` with only the
        exception class name in the message.
        """
        try:
            record = self._paced(
                lambda: self.adapter.fetch_product(self.tab, listing)
            )
        except BlockedError as exc:
            return self._on_blocked(listing, exc)
        except PageChangedError as exc:
            return self._on_page_changed(listing, exc)
        except NetworkError as exc:
            return self._on_network_error(listing, exc)
        except Exception as exc:
            return self._on_unexpected(listing, exc)
        if self.logger is not None:
            self.logger.info(
                "product=%s stage=fetch status=%s",
                listing.product_id,
                record.status.value,
            )
        return record, False

    def _on_blocked(
        self, listing: ProductListing, exc: BlockedError
    ) -> tuple[ProductRecord, bool]:
        record = ProductRecord.failure(
            listing,
            ProductStatus.BLOCKED,
            str(exc)[:_NETWORK_ERROR_MESSAGE_MAX],
        )
        if self.logger is not None:
            self.logger.warning(
                "product=%s stage=fetch status=BLOCKED stop=batch",
                listing.product_id,
            )
        self._capture(listing)
        return record, True

    def _on_page_changed(
        self, listing: ProductListing, exc: PageChangedError
    ) -> tuple[ProductRecord, bool]:
        record = ProductRecord.failure(
            listing,
            ProductStatus.PAGE_CHANGED,
            str(exc)[:_NETWORK_ERROR_MESSAGE_MAX],
        )
        if self.logger is not None:
            self.logger.info(
                "product=%s stage=fetch status=PAGE_CHANGED",
                listing.product_id,
            )
        self._capture(listing)
        return record, False

    def _on_network_error(
        self, listing: ProductListing, exc: NetworkError
    ) -> tuple[ProductRecord, bool]:
        record = ProductRecord.failure(
            listing,
            ProductStatus.NETWORK_ERROR,
            str(exc)[:_NETWORK_ERROR_MESSAGE_MAX],
        )
        if self.logger is not None:
            self.logger.info(
                "product=%s stage=fetch status=NETWORK_ERROR",
                listing.product_id,
            )
        self._capture(listing)
        return record, False

    def _on_unexpected(
        self, listing: ProductListing, exc: Exception
    ) -> tuple[ProductRecord, bool]:
        record = ProductRecord.failure(
            listing,
            ProductStatus.UNEXPECTED_ERROR,
            type(exc).__name__,
        )
        if self.logger is not None:
            self.logger.warning(
                "product=%s stage=fetch status=UNEXPECTED_ERROR "
                "error=%s",
                listing.product_id,
                type(exc).__name__,
            )
        self._capture(listing)
        return record, False

    def _capture(self, listing: ProductListing) -> None:
        """Capture diagnostic artifacts for a single failed product.

        Mirrors the movie runner's policy: skip when ``artifacts_dir``
        is missing or the tab cannot produce a screenshot, and swallow
        any exception so diagnostics never break the business flow.
        """
        if self.artifacts_dir is None:
            return
        if not hasattr(self.tab, "get_screenshot"):
            return
        try:
            capture_failure(
                self.tab,
                self.artifacts_dir,
                f"product-{listing.product_id}",
            )
        except Exception:
            # Diagnostics must never override the business result.
            pass

    # -- Network / pacing primitives ---------------------------------- #

    def _network_operation(self, operation: Callable[[], Any]) -> Any:
        """Run a network-touching operation with 2/5s exponential backoff.

        Tries up to three times. Only :class:`NetworkError` triggers a
        retry; any other exception propagates immediately. The final
        :class:`NetworkError` is re-raised when all attempts fail.
        """
        last_error: NetworkError | None = None
        for backoff in _NETWORK_BACKOFF_SECONDS:
            if backoff > 0:
                time.sleep(backoff)
            try:
                return operation()
            except NetworkError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _paced(self, operation: Callable[[], Any]) -> Any:
        """Execute one network operation and enforce the minimum interval.

        Pacing starts when this method is entered; after the operation
        returns (or raises), the runner sleeps the difference between
        the elapsed wall time and ``min_interval_seconds`` so that
        back-to-back visits never go faster than the configured pace.
        """
        started = time.monotonic()
        try:
            return self._network_operation(operation)
        finally:
            elapsed = time.monotonic() - started
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)
