from __future__ import annotations

import re
from dataclasses import replace
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

from DrissionPage.common import wait_until
from DrissionPage.errors import ContextLostError, PageDisconnectedError

from app.models import Candidate, MatchMethod, MovieResult, Status, Task

# Transient DrissionPage errors raised when the browser's CDP target for the
# current tab is gone or the underlying connection dropped. They are mapped
# to ``NetworkError`` so the runner's bounded 2/5s backoff retry can absorb
# them instead of the business ``UNEXPECTED_ERROR`` bucket, but we still
# re-attach the tab once ourselves first: most of these resolve themselves
# on the next ``tab.get`` call without waiting for a backoff sleep.
_TRANSIENT_CONTEXT_ERRORS: tuple[type[BaseException], ...] = (
    ContextLostError,
    PageDisconnectedError,
)


DETAIL_URL = re.compile(r"^https://movie\.douban\.com/subject/\d+/$")
BLOCK_TEXT = (
    "访问频率过高", "异常请求", "验证码", "error code: 01004", "Please login",
)
BLOCK_HOSTS = {"sec.douban.com"}
LOGIN_PATH = "/passport/login"
_SUBJECT_LINK = re.compile(
    r'<a\b[^>]*href=["\'](https://movie\.douban\.com/subject/\d+/)["\'][^>]*>'
    r'(.*?)</a>(.*?)(?=<a\b[^>]*href=["\']https://movie\.douban\.com/subject/\d+/|$)',
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")
_YEAR_AND_KIND = re.compile(r"\b((?:19|20)\d{2})\b\s*/\s*([^<\n]+)")
_TRAILING_YEAR = re.compile(r"[(\uff08](\d{4})[)\uff09]\s*$")
_INVISIBLE_MARKS = ("\u200e", "\u200f", "\ufeff")
_MAX_CANDIDATES = 5


def _text(fragment: str) -> str:
    return " ".join(unescape(_TAG.sub(" ", fragment)).split())


def _strip_invisible(text: str) -> str:
    cleaned = text
    for mark in _INVISIBLE_MARKS:
        cleaned = cleaned.replace(mark, "")
    return cleaned.strip()


class _ItemRootCardParser(HTMLParser):
    """Parse the rendered React search result DOM: <div class="item-root"> cards
    where the same subject URL is repeated on a.cover-link and a.title-text.
    We prefer a.title-text for the visible title and strip trailing U+200E /
    U+200F / U+FEFF marks before extracting the year from " (YYYY)".
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._cards: list[dict[str, str | None]] = []
        self._div_stack: list[str] = []
        self._current: dict[str, str | None] | None = None
        self._card_entry_depth: int | None = None
        self._capture_href: str | None = None
        self._capture_text: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: (value or "") for name, value in attrs}
        classes = (attr_map.get("class") or "").split()
        if tag == "div":
            if self._current is None and "item-root" in classes:
                self._current = {"title": None, "href": None}
                self._card_entry_depth = len(self._div_stack)
            self._div_stack.append(" ".join(classes))
            return
        if self._current is None:
            return
        if tag == "a":
            href = attr_map.get("href") or ""
            if DETAIL_URL.match(href):
                self._capture_href = href
                self._capture_text = "title-text" in classes

    def handle_data(self, data: str) -> None:
        if self._current is None or self._capture_href is None or not self._capture_text:
            return
        self._current["title"] = data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_href is not None:
            if self._current is not None and self._current["href"] is None:
                self._current["href"] = self._capture_href
            self._capture_href = None
            self._capture_text = False
            return
        if tag != "div":
            return
        if not self._div_stack:
            return
        self._div_stack.pop()
        if (
            self._current is not None
            and self._card_entry_depth is not None
            and len(self._div_stack) == self._card_entry_depth
        ):
            self._cards.append(self._current)
            self._current = None
            self._card_entry_depth = None

    @property
    def cards(self) -> list[dict[str, str | None]]:
        return self._cards


def _parse_item_root_cards(html: str) -> list[Candidate]:
    parser = _ItemRootCardParser()
    parser.feed(html)
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for card in parser.cards:
        href = card.get("href")
        raw_title = card.get("title")
        if not href or not raw_title:
            continue
        if href in seen:
            continue
        title = _strip_invisible(raw_title)
        if not title:
            continue
        year_match = _TRAILING_YEAR.search(title)
        if year_match is None:
            continue
        title = title[: year_match.start()].strip()
        year = year_match.group(1)
        if not title:
            continue
        seen.add(href)
        candidates.append(Candidate(title, year, "电影", href))
        if len(candidates) == _MAX_CANDIDATES:
            break
    return candidates


def _parse_legacy_subject_links(html: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for url, anchor_html, trailing_html in _SUBJECT_LINK.findall(html):
        title = _text(anchor_html)
        metadata = _text(trailing_html)
        match = _YEAR_AND_KIND.search(metadata)
        if not title or match is None:
            continue
        candidates.append(
            Candidate(title, match.group(1), match.group(2).strip(), url)
        )
        if len(candidates) == _MAX_CANDIDATES:
            break
    return candidates


class BlockedError(RuntimeError):
    pass


class PageChangedError(RuntimeError):
    pass


class NetworkError(RuntimeError):
    pass


class SiteProtectionChallenge(RuntimeError):
    """Raised when Douban's JavaScript proof-of-work challenge is detected.

    Douban serves a SHA-512 nonce-mining challenge (typically under
    ``sec.douban.com``) when site protection decides the current request
    pattern is suspect. The browser can solve it automatically in 1-3
    seconds, but per the project's live-run rules we never automate that
    bypass: we stop the batch and surface the status so the operator can
    decide whether to wait for the IP frequency window to expire and
    retry. This is distinct from ``BlockedError`` because a challenge is
    transient and a blocked page is not.
    """


class DoubanMovieAdapter:
    SEARCH_INPUTS = (
        "@role=searchbox",
        "css:input[name='search_text']",
    )
    EMPTY_RESULT_TEXT = ("没有找到", "暂无搜索结果")
    # The Douban JS proof-of-work challenge form posts to ``/c`` and uses
    # three hidden inputs named ``cha`` (challenge string), ``sol`` (solved
    # nonce placeholder) and ``red`` (post-challenge redirect target). We
    # only need the first two to recognise the page: any real movie page
    # that ships these inputs is serving the challenge, not content.
    _CHALLENGE_MARKERS: tuple[str, ...] = (
        'name="sec"',
        'name="cha"',
        'name="sol"',
    )

    @staticmethod
    def is_challenge_pending(html: str) -> bool:
        return all(marker in html for marker in DoubanMovieAdapter._CHALLENGE_MARKERS)

    @staticmethod
    def is_blocked(html: str, status_code: int | None, url: str = "") -> bool:
        parsed = urlparse(url)
        redirected_to_login = (
            parsed.hostname == "accounts.douban.com"
            and parsed.path.rstrip("/") == LOGIN_PATH
        )
        return (
            status_code in {403, 418, 429}
            or parsed.hostname in BLOCK_HOSTS
            or redirected_to_login
            or any(marker in html for marker in BLOCK_TEXT)
        )

    @staticmethod
    def parse_search_html(html: str) -> list[Candidate]:
        rendered = _parse_item_root_cards(html)
        if rendered:
            return rendered
        return _parse_legacy_subject_links(html)

    @staticmethod
    def parse_detail_html(html: str, task: Task, url: str) -> MovieResult:
        title = re.search(r'property="v:itemreviewed"[^>]*>([^<]+)', html)
        year = re.search(r'class="year"[^>]*>\((\d{4})\)', html)
        directors = re.findall(r'rel="v:directedBy"[^>]*>([^<]+)', html)
        rating = re.search(r'property="v:average"[^>]*>([^<]*)', html)
        if title is None or DETAIL_URL.fullmatch(url) is None:
            return replace(
                MovieResult.from_task(task),
                status=Status.PAGE_CHANGED,
                error_message="Missing title or canonical detail URL",
            ).stamped()
        rating_value = float(rating.group(1)) if rating and rating.group(1).strip() else None
        return replace(
            MovieResult.from_task(task),
            matched_title=title.group(1).strip(),
            matched_year=year.group(1) if year else None,
            director=" / ".join(name.strip() for name in directors),
            rating=rating_value,
            detail_url=url,
            match_method=MatchMethod.NONE,
            status=Status.SUCCESS,
        ).stamped()

    def _search_input(self, tab):
        for locator in self.SEARCH_INPUTS:
            element = tab.ele(locator, timeout=1)
            if element:
                return element
        raise PageChangedError("Search input was not found")

    @classmethod
    def _search_is_ready(cls, html: str) -> bool:
        return bool(cls.parse_search_html(html)) or any(
            marker in html for marker in cls.EMPTY_RESULT_TEXT
        )

    def search(self, tab, task: Task) -> list[Candidate]:
        try:
            return self._search_once(tab, task)
        except _TRANSIENT_CONTEXT_ERRORS:
            # The CDP target went away between tasks; re-attach the same tab
            # by retrying the whole search step once. If the second attempt
            # also fails with a transient error, escalate to NetworkError so
            # the runner's 2/5s backoff can take over without the business
            # ``UNEXPECTED_ERROR`` bucket recording a phantom exception.
            try:
                return self._search_once(tab, task)
            except _TRANSIENT_CONTEXT_ERRORS as exc2:
                raise NetworkError(
                    f"context lost: {type(exc2).__name__}"
                ) from exc2

    def _search_once(self, tab, task: Task) -> list[Candidate]:
        if not tab.get("https://movie.douban.com/", retry=0, timeout=20):
            raise NetworkError("Douban navigation failed")
        self._check_site_protection(tab.html, tab.url)
        if self.is_blocked(tab.html, None, tab.url):
            raise BlockedError("Douban blocked the batch")
        self._search_input(tab).input(f"{task.query}\n", clear=True)
        try:
            wait_until(lambda: self._search_is_ready(tab.html), timeout=10)
        except TimeoutError as exc:
            raise PageChangedError("Search result marker was not found") from exc
        page_html = tab.html
        self._check_site_protection(page_html, tab.url)
        if self.is_blocked(page_html, None, tab.url):
            raise BlockedError("Douban blocked the batch")
        return self.parse_search_html(page_html)

    def fetch_detail(self, tab, task: Task, candidate: Candidate) -> MovieResult:
        try:
            return self._fetch_detail_once(tab, task, candidate)
        except _TRANSIENT_CONTEXT_ERRORS:
            try:
                return self._fetch_detail_once(tab, task, candidate)
            except _TRANSIENT_CONTEXT_ERRORS as exc2:
                raise NetworkError(
                    f"context lost: {type(exc2).__name__}"
                ) from exc2

    def _fetch_detail_once(self, tab, task: Task, candidate: Candidate) -> MovieResult:
        if not tab.get(candidate.detail_url, retry=0, timeout=20):
            raise NetworkError("Douban detail navigation failed")
        page_html = tab.html
        self._check_site_protection(page_html, tab.url)
        if self.is_blocked(page_html, None, tab.url):
            raise BlockedError("Douban blocked the batch")
        return self.parse_detail_html(page_html, task, tab.url)

    @classmethod
    def _check_site_protection(cls, html: str, url: str) -> None:
        if cls.is_challenge_pending(html):
            raise SiteProtectionChallenge(
                f"Douban served a JS proof-of-work challenge (url={url}); "
                "stop the batch and wait for the IP frequency window to expire."
            )
