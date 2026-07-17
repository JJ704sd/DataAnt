"""Adapter for the public web-scraping.dev product demo.

Scope:

- Build and validate the allowed ``/products`` pagination URLs and
  ``/product/<id>`` canonical product URLs.
- Parse the rendered product list and product detail HTML using
  :class:`html.parser.HTMLParser` so the same code works against the
  minimal sanitised fixtures and the live page.
- Detect blocked / login / challenge responses and external redirects
  before parsing, surfacing the existing site-error hierarchy instead of
  a custom exception.
- Drive DrissionPage ``tab`` navigation with the same one-shot retry
  policy for transient CDP context loss that the Douban adapter uses.

This module is pure (no I/O, no CLI) and the only allowed outbound
URLs are the ones whitelisted by :data:`BASE_URL`.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from DrissionPage.errors import ContextLostError, PageDisconnectedError

from app.product_models import (
    ProductListing,
    ProductPage,
    ProductRecord,
    ProductStatus,
)
from app.site_errors import BlockedError, NetworkError


# --------------------------------------------------------------------------- #
# URL whitelisting
# --------------------------------------------------------------------------- #


BASE_URL = "https://web-scraping.dev"
PRODUCTS_URL = "https://web-scraping.dev/products"

# Matches the path component /product/<digits> with an optional trailing
# slash; any other product URL is rejected by ``canonical_product_url``.
_PRODUCT_PATH = re.compile(r"^/product/(\d+)/?$")
_PRODUCTS_PATH = "/products"

# Pagination parameters we are willing to forward. Anything else
# (search, sort variants, custom trackers, etc.) is dropped.
_ALLOWED_PRODUCTS_PARAMS = frozenset({"page", "category", "sort"})

# Login / challenge / blocked markers. These are the only stable substrings
# the practice site returns when it forces a 429, an interstitial, or a
# proof-of-work challenge. We keep them narrow on purpose so a real
# product description can never accidentally trip them.
BLOCK_TEXT: tuple[str, ...] = (
    "Access blocked",
    "Too many requests",
    "Please retry later",
    "Please login",
    "Antibot Challenge",
)

# A handful of well-known paths the practice site uses for login,
# challenge, and the ``/robots-disallowed`` training route. Any redirect
# to one of these must be treated as ``BlockedError`` rather than a
# successful navigation.
LOGIN_PATH = "/login"
CHALLENGE_PATH = "/antibot-challenge"
ROBOTS_DISALLOWED_PATH = "/robots-disallowed"
_ALLOWED_HOST = "web-scraping.dev"

# Transient DrissionPage errors raised when the browser's CDP target for
# the current tab is gone or the underlying connection dropped. They
# share the Douban adapter's policy: one immediate retry, then escalate
# to ``NetworkError`` so the runner's bounded 2/5s backoff can absorb
# them without the business ``UNEXPECTED_ERROR`` bucket recording a
# phantom exception.
_TRANSIENT_CONTEXT_ERRORS: tuple[type[BaseException], ...] = (
    ContextLostError,
    PageDisconnectedError,
)


def _rebuild(
    scheme: str,
    netloc: str,
    path: str,
    query_pairs: list[tuple[str, str]],
    fragment: str = "",
) -> str:
    return urlunsplit((scheme, netloc, path, urlencode(query_pairs), fragment))


def _validate_https_url(url: str, *, label: str) -> urlsplit:
    """Parse and validate ``url`` belongs to the allowed site over HTTPS.

    Returns the parsed :class:`urlsplit` when the URL is acceptable,
    otherwise raises :class:`ValueError` with a stable ``label``-prefixed
    message so the caller can match on the string "product URL" or
    "products URL".
    """
    if not url:
        raise ValueError(f"empty {label}")
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError(f"{label} must use https: {url!r}")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} must not contain credentials: {url!r}")
    if parsed.hostname != _ALLOWED_HOST:
        raise ValueError(f"{label} is outside the allowed site: {url!r}")
    return parsed


# --------------------------------------------------------------------------- #
# Public adapter
# --------------------------------------------------------------------------- #


class WebScrapingDevAdapter:
    BASE_URL = BASE_URL
    PRODUCTS_URL = PRODUCTS_URL

    # -- URL whitelisting ------------------------------------------------ #

    @staticmethod
    def canonical_product_url(url: str) -> str:
        """Return the canonical ``https://web-scraping.dev/product/<id>`` URL.

        Accepts an absolute URL, a same-site absolute path such as
        ``/product/1``, or a fully qualified URL with extra query
        parameters / fragments. Anything else (off-site host, missing
        product id, the ``/robots-disallowed`` path, http:// scheme,
        embedded credentials) raises :class:`ValueError` whose message
        contains the literal ``"product URL"``.
        """
        if not url:
            raise ValueError("empty product URL")
        joined = urljoin(BASE_URL + "/", url)
        parsed = _validate_https_url(joined, label="product URL")
        match = _PRODUCT_PATH.match(parsed.path)
        if match is None:
            raise ValueError(f"not a canonical product URL: {url!r}")
        return _rebuild(
            parsed.scheme,
            parsed.netloc,
            f"/product/{match.group(1)}",
            [],
            "",
        )

    @staticmethod
    def canonical_products_url(url: str) -> str:
        """Return the canonical ``/products`` pagination URL.

        Only the whitelisted query parameters ``page``, ``category`` and
        ``sort`` survive; everything else (search, trackers, etc.) is
        rejected as a ``ValueError`` whose message contains the literal
        ``"products URL"``. Unknown parameters in the same URL raise
        immediately; the surviving parameters keep their original
        order in the output so the URL we re-emit is byte-for-byte
        the same as the well-formed input.
        """
        if not url:
            raise ValueError("empty products URL")
        joined = urljoin(BASE_URL + "/", url)
        parsed = _validate_https_url(joined, label="products URL")
        if parsed.path != _PRODUCTS_PATH:
            raise ValueError(
                f"not a canonical products URL: {url!r}"
            )
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        rejected = [
            key for key, _ in pairs if key not in _ALLOWED_PRODUCTS_PARAMS
        ]
        if rejected:
            raise ValueError(
                f"products URL has disallowed params {rejected!r}: {url!r}"
            )
        return _rebuild(
            parsed.scheme,
            parsed.netloc,
            _PRODUCTS_PATH,
            pairs,
            "",
        )

    # -- Blocked / login / challenge detection -------------------------- #

    @staticmethod
    def is_blocked(
        html: str, status_code: int | None, url: str = ""
    ) -> bool:
        """Return True when the response should stop the batch.

        Triggers: HTTP 429, well-known blocked text, redirect to the
        login / antibot-challenge / robots-disallowed paths, redirect to
        any host other than ``web-scraping.dev``.
        """
        if status_code == 429:
            return True
        if html and any(marker in html for marker in BLOCK_TEXT):
            return True
        if not url:
            return False
        try:
            parsed = urlsplit(url)
        except ValueError:
            return True
        if parsed.hostname and parsed.hostname != _ALLOWED_HOST:
            return True
        path = parsed.path or ""
        if path in {LOGIN_PATH, CHALLENGE_PATH, ROBOTS_DISALLOWED_PATH}:
            return True
        return False

    # -- List page parsing ----------------------------------------------- #

    @classmethod
    def parse_products_html(
        cls,
        html: str,
        page_url: str,
    ) -> ProductPage:
        """Parse ordered product listings and the canonical next-page URL."""
        parser = _ProductsListParser()
        parser.feed(html)
        listings: list[ProductListing] = []
        seen: set[str] = set()
        for card in parser.cards:
            href = card.get("href")
            if not href:
                continue
            try:
                canonical = cls.canonical_product_url(href)
            except ValueError:
                # Skip off-site, malformed, or non-product links the page
                # may have stuffed inside a product card.
                continue
            product_id = canonical.rsplit("/", 1)[-1]
            if product_id in seen:
                continue
            seen.add(product_id)
            listings.append(
                ProductListing(
                    product_id=product_id,
                    product_url=canonical,
                    category=card.get("category", ""),
                )
            )
        next_url: str | None = None
        next_href = parser.next_href
        if next_href:
            try:
                next_url = cls.canonical_products_url(next_href)
            except ValueError:
                next_url = None
        return ProductPage(tuple(listings), next_url)

    # -- Detail page parsing -------------------------------------------- #

    @classmethod
    def parse_detail_html(
        cls,
        html: str,
        listing: ProductListing,
        final_url: str,
    ) -> ProductRecord:
        """Parse one terminal SUCCESS, PARTIAL, or PAGE_CHANGED record."""
        # Canonicalise ``final_url`` so the record's ``product_url`` is
        # always the same stable form, regardless of what the browser
        # ended up at. A non-canonical final URL is a strong signal that
        # the page contract has changed (off-site redirect, login wall).
        try:
            canonical_final = cls.canonical_product_url(final_url)
        except ValueError:
            return ProductRecord.failure(
                listing,
                ProductStatus.PAGE_CHANGED,
                "Final URL is not a canonical product URL",
            )
        parser = _ProductDetailParser()
        parser.feed(html)
        missing_required: list[str] = []
        if not parser.name:
            missing_required.append("name")
        if parser.price is None:
            missing_required.append("current_price")
        if missing_required:
            return ProductRecord(
                product_id=listing.product_id,
                source_site="web-scraping.dev",
                product_url=canonical_final,
                category=listing.category,
                status=ProductStatus.PAGE_CHANGED,
                error_message=(
                    "Missing required detail fields: "
                    + ", ".join(missing_required)
                ),
            ).stamped()
        # All required fields present. Optional fields can be partial.
        missing_optional: list[str] = []
        category = parser.category or listing.category
        if not category:
            missing_optional.append("category")
        if not parser.description:
            missing_optional.append("description")
        if not parser.image_url:
            missing_optional.append("image")
        if not parser.brand:
            missing_optional.append("brand")
        if missing_optional:
            status = ProductStatus.PARTIAL
            error_message = (
                "missing optional fields: " + ", ".join(missing_optional)
            )
        else:
            status = ProductStatus.SUCCESS
            error_message = ""
        return ProductRecord(
            product_id=listing.product_id,
            source_site="web-scraping.dev",
            product_url=canonical_final,
            name=parser.name or "",
            category=category,
            description=parser.description or "",
            primary_image_url=parser.image_url or "",
            current_price=parser.price,
            original_price=parser.price_original,
            currency="USD",
            brand=parser.brand or "",
            variant_count=parser.variant_count,
            status=status,
            error_message=error_message,
        ).stamped()

    # -- Browser access -------------------------------------------------- #

    def fetch_products_page(self, tab: Any, url: str) -> ProductPage:
        """Navigate once, enforce the site boundary, and parse the list."""
        canonical = self.canonical_products_url(url)
        try:
            return self._fetch_products_once(tab, canonical)
        except _TRANSIENT_CONTEXT_ERRORS:
            try:
                return self._fetch_products_once(tab, canonical)
            except _TRANSIENT_CONTEXT_ERRORS as exc2:
                raise NetworkError(
                    f"context lost: {type(exc2).__name__}"
                ) from exc2

    def _fetch_products_once(self, tab: Any, url: str) -> ProductPage:
        if not tab.get(url, retry=0, timeout=20):
            raise NetworkError("web-scraping.dev navigation failed")
        final_url = getattr(tab, "url", url) or url
        if self.is_blocked(getattr(tab, "html", "") or "", None, final_url):
            raise BlockedError(
                "web-scraping.dev redirected the list page outside "
                "the allowed site"
            )
        return self.parse_products_html(
            getattr(tab, "html", "") or "", final_url
        )

    def fetch_product(
        self,
        tab: Any,
        listing: ProductListing,
    ) -> ProductRecord:
        """Navigate once, enforce the site boundary, and parse the detail."""
        try:
            return self._fetch_detail_once(tab, listing)
        except _TRANSIENT_CONTEXT_ERRORS:
            try:
                return self._fetch_detail_once(tab, listing)
            except _TRANSIENT_CONTEXT_ERRORS as exc2:
                raise NetworkError(
                    f"context lost: {type(exc2).__name__}"
                ) from exc2

    def _fetch_detail_once(
        self, tab: Any, listing: ProductListing
    ) -> ProductRecord:
        url = listing.product_url
        if not tab.get(url, retry=0, timeout=20):
            raise NetworkError("web-scraping.dev navigation failed")
        final_url = getattr(tab, "url", url) or url
        if self.is_blocked(getattr(tab, "html", "") or "", None, final_url):
            raise BlockedError(
                "web-scraping.dev redirected the detail page outside "
                "the allowed site"
            )
        return self.parse_detail_html(
            getattr(tab, "html", "") or "",
            listing,
            final_url,
        )


# --------------------------------------------------------------------------- #
# Money parsing
# --------------------------------------------------------------------------- #


def _parse_money(text: str) -> Decimal | None:
    """Parse a USD-style money string.

    Accepts the four shapes the practice site has used: ``"9.99"``,
    ``"$9.99"``, ``"from $12.99"`` and ``"from 12.99"``. Returns
    ``None`` on any other input so the caller can surface the page as
    ``PAGE_CHANGED`` rather than guessing the price.
    """
    if not text:
        return None
    cleaned = text.replace("$", "").replace("from", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


# --------------------------------------------------------------------------- #
# HTML parser: product list page
# --------------------------------------------------------------------------- #


class _ProductsListParser(HTMLParser):
    """Collect ``div.product`` cards, the ``rel=next`` link, and category.

    A card is matched on the ``product`` class of its outer ``<div>``;
    any anchor with a non-empty ``href`` and any inner ``<h3>`` text is
    captured. The list category, when present as the first
    ``<a class="category">`` anchor outside a card, is propagated onto
    every card so the runner can pass it through to the listing.
    """

    _CARD_CLASS = "product"
    _CATEGORY_CLASS = "category"
    _NEXT_REL = "next"

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # Output
        self._cards: list[dict[str, str]] = []
        self._next_href: str | None = None
        self._category_text: str = ""
        # State
        self._div_stack: list[set[str]] = []
        self._current: dict[str, str] | None = None
        self._current_depth: int | None = None
        self._h3_buffer: list[str] = []
        self._capturing_h3 = False
        # Category-anchor text capture. We start the buffer when the
        # <a class="category"> opens and flush on its </a>.
        self._capturing_category = False
        self._category_buffer: list[str] = []

    @property
    def cards(self) -> list[dict[str, str]]:
        return self._cards

    @property
    def next_href(self) -> str | None:
        return self._next_href

    # -- Parser callbacks ---------------------------------------------- #

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr_map = {name: (value or "") for name, value in attrs}
        classes = (attr_map.get("class") or "").split()
        if tag == "div":
            class_set = set(classes)
            self._div_stack.append(class_set)
            if (
                self._current is None
                and self._CARD_CLASS in class_set
            ):
                self._current = {
                    "href": "",
                    "title": "",
                    "category": self._category_text,
                }
                self._current_depth = len(self._div_stack) - 1
            return
        if tag == "a":
            href = (attr_map.get("href") or "").strip()
            if not href:
                return
            rel = (attr_map.get("rel") or "").lower()
            if self._NEXT_REL in rel.split():
                self._next_href = href
                return
            if self._CATEGORY_CLASS in classes and not self._category_text:
                self._capturing_category = True
                self._category_buffer = []
                return
            if self._current is not None and not self._current["href"]:
                self._current["href"] = href
            return
        if tag == "h3" and self._current is not None:
            self._capturing_h3 = True
            self._h3_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capturing_category:
            text = "".join(self._category_buffer).strip()
            if text:
                self._category_text = " ".join(text.split())
            self._capturing_category = False
            self._category_buffer = []
            return
        if tag == "h3" and self._capturing_h3:
            self._capturing_h3 = False
            if self._current is not None:
                title = "".join(self._h3_buffer).strip()
                if title:
                    self._current["title"] = " ".join(title.split())
            return
        if tag == "div":
            if not self._div_stack:
                return
            self._div_stack.pop()
            if (
                self._current is not None
                and self._current_depth is not None
                and len(self._div_stack) == self._current_depth
            ):
                self._cards.append(self._current)
                self._current = None
                self._current_depth = None

    def handle_data(self, data: str) -> None:
        if self._capturing_category:
            self._category_buffer.append(data)
            return
        if self._capturing_h3 and self._current is not None:
            self._h3_buffer.append(data)


# --------------------------------------------------------------------------- #
# HTML parser: product detail page
# --------------------------------------------------------------------------- #


class _ProductDetailParser(HTMLParser):
    """Collect the well-known detail page fields.

    Captures:

    - first top-level ``<h3>`` (product name);
    - first ``<span class="price">`` and ``<span class="price-original">``;
    - first ``<img>`` inside ``<section class="gallery">``;
    - the paragraph that follows the first ``<h4>Description</h4>``;
    - anchors inside the ``<section>`` whose first ``<h3>`` says
      "Variants";
    - key/value rows in the first ``<table class="features">``;
    - the category anchor text from inside ``<nav>``.
    """

    _GALLERY_CLASS = "gallery"
    _FEATURES_CLASS = "features"
    _PRICE_CLASS = "price"
    _PRICE_ORIGINAL_CLASS = "price-original"
    _DESCRIPTION_HEADING = "Description"
    _VARIANTS_HEADING = "Variants"

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # Output
        self.name: str = ""
        self.price: Decimal | None = None
        self.price_original: Decimal | None = None
        self.image_url: str = ""
        self.description: str = ""
        self.category: str = ""
        self.brand: str = ""
        self.variant_count: int = 0
        # State
        self._in_nav: bool = False
        self._nav_anchor_buffer: list[str] | None = None
        # Main h3 outside any <section> is the product name. Inside a
        # <section>, the h3 is a section heading (e.g. "Variants").
        self._name_h3_buffer: list[str] | None = None
        self._section_stack: list[dict[str, Any]] = []
        # Span capture
        self._span_class: str | None = None
        self._span_buffer: list[str] | None = None
        # Description paragraph capture
        self._desc_p_buffer: list[str] | None = None
        # Features table
        self._in_features_table: bool = False
        self._features_table_depth: int = 0
        self._feature_cell_target: str | None = None
        self._feature_cell_buffer: list[str] | None = None
        self._feature_key: str = ""

    # -- Parser callbacks ---------------------------------------------- #

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr_map = {name: (value or "") for name, value in attrs}
        classes = (attr_map.get("class") or "").split()
        class_set = set(classes)
        if tag == "section":
            self._section_stack.append(
                {
                    "classes": class_set,
                    "h3": "",
                    "h4": "",
                    "h3_buf": None,
                    "h4_buf": None,
                }
            )
            return
        if tag == "nav":
            self._in_nav = True
            return
        if tag == "a":
            if self._in_nav and self._nav_anchor_buffer is None:
                self._nav_anchor_buffer = []
                return
            if (
                self._section_stack
                and self._section_stack[-1].get("h3") == self._VARIANTS_HEADING
            ):
                self.variant_count += 1
            return
        if tag == "h3":
            if self._section_stack:
                self._section_stack[-1]["h3_buf"] = []
            elif self._name_h3_buffer is None and not self.name:
                self._name_h3_buffer = []
            return
        if tag == "h4" and self._section_stack:
            self._section_stack[-1]["h4_buf"] = []
            return
        if tag == "p" and self._section_stack:
            top = self._section_stack[-1]
            if (
                top.get("h4") == self._DESCRIPTION_HEADING
                and self._desc_p_buffer is None
                and not self.description
            ):
                self._desc_p_buffer = []
            return
        if tag == "img":
            if (
                not self.image_url
                and self._section_stack
                and self._GALLERY_CLASS in self._section_stack[-1]["classes"]
            ):
                self.image_url = (attr_map.get("src") or "").strip()
            return
        if tag == "span":
            if (
                self._PRICE_CLASS in class_set
                and self._PRICE_ORIGINAL_CLASS not in class_set
                and self.price is None
                and self._span_class is None
            ):
                self._span_class = self._PRICE_CLASS
                self._span_buffer = []
                return
            if (
                self._PRICE_ORIGINAL_CLASS in class_set
                and self.price_original is None
                and self._span_class is None
            ):
                self._span_class = self._PRICE_ORIGINAL_CLASS
                self._span_buffer = []
            return
        if tag == "table":
            if self._FEATURES_CLASS in class_set and not self._in_features_table:
                self._in_features_table = True
                self._features_table_depth = 1
            elif self._in_features_table:
                self._features_table_depth += 1
            return
        if self._in_features_table and tag == "tr":
            self._feature_key = ""
            self._feature_cell_target = None
            self._feature_cell_buffer = None
            return
        if self._in_features_table and tag in {"th", "td"}:
            self._feature_cell_target = tag
            self._feature_cell_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._section_stack:
            self._section_stack.pop()
            return
        if tag == "nav":
            self._in_nav = False
            return
        if tag == "a" and self._nav_anchor_buffer is not None:
            text = "".join(self._nav_anchor_buffer).strip()
            if text and not self.category:
                self.category = " ".join(text.split())
            self._nav_anchor_buffer = None
            return
        if tag == "h3":
            if self._section_stack and self._section_stack[-1]["h3_buf"] is not None:
                buf = self._section_stack[-1]["h3_buf"]
                text = "".join(buf).strip()
                if text:
                    self._section_stack[-1]["h3"] = " ".join(text.split())
                self._section_stack[-1]["h3_buf"] = None
            elif self._name_h3_buffer is not None:
                text = "".join(self._name_h3_buffer).strip()
                if text:
                    self.name = " ".join(text.split())
                self._name_h3_buffer = None
            return
        if tag == "h4" and self._section_stack and self._section_stack[-1]["h4_buf"] is not None:
            buf = self._section_stack[-1]["h4_buf"]
            text = "".join(buf).strip()
            if text:
                self._section_stack[-1]["h4"] = " ".join(text.split())
            self._section_stack[-1]["h4_buf"] = None
            return
        if tag == "p" and self._desc_p_buffer is not None:
            text = "".join(self._desc_p_buffer).strip()
            if text:
                self.description = " ".join(text.split())
            self._desc_p_buffer = None
            return
        if tag == "span" and self._span_class is not None and self._span_buffer is not None:
            text = "".join(self._span_buffer).strip()
            money = _parse_money(text)
            if self._span_class == self._PRICE_CLASS and money is not None:
                self.price = money
            elif (
                self._span_class == self._PRICE_ORIGINAL_CLASS
                and money is not None
            ):
                self.price_original = money
            self._span_class = None
            self._span_buffer = None
            return
        if tag == "table" and self._in_features_table:
            if self._features_table_depth <= 1:
                self._in_features_table = False
                self._features_table_depth = 0
            else:
                self._features_table_depth -= 1
            return
        if (
            tag in {"th", "td"}
            and self._in_features_table
            and self._feature_cell_target is not None
            and self._feature_cell_buffer is not None
        ):
            text = "".join(self._feature_cell_buffer).strip()
            if self._feature_cell_target == "th":
                self._feature_key = text.lower()
            elif self._feature_cell_target == "td" and self._feature_key:
                if self._feature_key == "brand":
                    self.brand = text
                self._feature_key = ""
            self._feature_cell_target = None
            self._feature_cell_buffer = None

    def handle_data(self, data: str) -> None:
        if self._name_h3_buffer is not None:
            self._name_h3_buffer.append(data)
            return
        if self._span_buffer is not None:
            self._span_buffer.append(data)
            return
        if self._nav_anchor_buffer is not None:
            self._nav_anchor_buffer.append(data)
            return
        if self._desc_p_buffer is not None:
            self._desc_p_buffer.append(data)
            return
        if self._section_stack:
            top = self._section_stack[-1]
            if top["h3_buf"] is not None:
                top["h3_buf"].append(data)
            elif top["h4_buf"] is not None:
                top["h4_buf"].append(data)
            return
        if (
            self._in_features_table
            and self._feature_cell_target is not None
            and self._feature_cell_buffer is not None
        ):
            self._feature_cell_buffer.append(data)
