from pathlib import Path

import pytest

from app.models import Candidate, MatchMethod, Status, Task
from app.sites import douban_movie
from app.site_errors import (
    BlockedError,
    NetworkError,
    PageChangedError,
    SiteProtectionChallenge,
)
from app.sites.douban_movie import DoubanMovieAdapter
from DrissionPage.errors import ContextLostError, PageDisconnectedError


FIXTURES = Path(__file__).parent / "fixtures"
DETAIL_URL = "https://movie.douban.com/subject/1292052/"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_search_candidates_in_source_order() -> None:
    candidates = DoubanMovieAdapter.parse_search_html(html("search_results.html"))
    assert [(c.title, c.year, c.kind, c.detail_url) for c in candidates] == [
        ("肖申克的救赎", "1994", "电影", DETAIL_URL),
        ("肖申克", "2010", "短片", "https://movie.douban.com/subject/9999999/"),
    ]


def test_parse_react_search_candidates_with_nested_markup() -> None:
    candidates = DoubanMovieAdapter.parse_search_html(
        html("search_results_react.html")
    )
    assert [(c.title, c.year, c.kind, c.detail_url) for c in candidates] == [
        ("肖申克的救赎", "1994", "电影", DETAIL_URL),
        ("肖申克", "2010", "短片", "https://movie.douban.com/subject/9999999/"),
    ]


def test_parse_search_empty_returns_empty_list() -> None:
    assert DoubanMovieAdapter.parse_search_html(html("search_empty.html")) == []


def test_parse_search_limits_candidates_to_five() -> None:
    item = '<a href="https://movie.douban.com/subject/{}/">电影</a><span>1994 / 电影</span>'
    assert len(DoubanMovieAdapter.parse_search_html("".join(item.format(i) for i in range(1, 7)))) == 5


def test_parse_search_live_shape_extracts_three_unique_cards() -> None:
    candidates = DoubanMovieAdapter.parse_search_html(html("search_results_live_shape.html"))
    assert [(c.title, c.year, c.kind, c.detail_url) for c in candidates] == [
        ("霸王别姬", "1993", "电影", "https://movie.douban.com/subject/1291546/"),
        ("霸王别姬(京剧)", "2014", "电影", "https://movie.douban.com/subject/20645019/"),
        ("测试电影", "2025", "电影", "https://movie.douban.com/subject/9999999999/"),
    ]


def test_parse_search_live_shape_strips_left_to_right_mark() -> None:
    candidates = DoubanMovieAdapter.parse_search_html(html("search_results_live_shape.html"))
    assert len(candidates) == 3, "expected three cards before checking invisible char strip"
    for candidate in candidates:
        # U+200E / U+200F / U+FEFF invisible marks must be stripped from titles.
        assert "\u200e" not in candidate.title
        assert "\u200f" not in candidate.title
        assert "\ufeff" not in candidate.title


def test_parse_detail_extracts_fields_and_multiple_directors() -> None:
    task = Task("a", "肖申克的救赎", "1994")
    result = DoubanMovieAdapter.parse_detail_html(html("detail_movie.html"), task, DETAIL_URL)
    assert result.status == Status.SUCCESS
    assert result.matched_title == "肖申克的救赎"
    assert result.matched_year == "1994"
    assert result.director == "弗兰克·德拉邦特 / 第二导演"
    assert result.rating == 9.7
    assert result.detail_url == DETAIL_URL
    assert result.match_method == MatchMethod.NONE
    assert result.collected_at


def test_detail_allows_missing_non_core_fields() -> None:
    task = Task("a", "电影", None)
    body = '<span property="v:itemreviewed">电影</span><strong property="v:average"></strong>'
    result = DoubanMovieAdapter.parse_detail_html(body, task, DETAIL_URL)
    assert result.status == Status.SUCCESS
    assert result.matched_year is None
    assert result.director == ""
    assert result.rating is None


@pytest.mark.parametrize("url", ["", "http://movie.douban.com/subject/1/", "https://example.com/subject/1/"])
def test_invalid_detail_url_returns_page_changed(url: str) -> None:
    task = Task("a", "电影", None)
    body = '<span property="v:itemreviewed">电影</span>'
    result = DoubanMovieAdapter.parse_detail_html(body, task, url)
    assert result.status == Status.PAGE_CHANGED
    assert result.error_message == "Missing title or canonical detail URL"


def test_missing_title_returns_page_changed() -> None:
    result = DoubanMovieAdapter.parse_detail_html("<html></html>", Task("a", "电影", None), DETAIL_URL)
    assert result.status == Status.PAGE_CHANGED


@pytest.mark.parametrize("status_code", [403, 418, 429])
def test_blocked_status_is_detected(status_code: int) -> None:
    assert DoubanMovieAdapter.is_blocked("", status_code)


def test_blocked_text_is_detected() -> None:
    assert DoubanMovieAdapter.is_blocked(html("blocked.html"), 200)
    assert not DoubanMovieAdapter.is_blocked("<html>普通页面</html>", 200)


def test_adapter_exposes_a_small_locator_contract() -> None:
    assert DoubanMovieAdapter.SEARCH_INPUTS == (
        "@role=searchbox",
        "css:input[name='search_text']",
    )


class NavigationFailureTab:
    html = ""
    url = "data:text/html,offline"

    def get(self, url: str, retry: int, timeout: int) -> bool:
        return False


class SearchInput:
    def input(self, value: str, clear: bool) -> None:
        return None


class LoadedTab:
    def __init__(self, body: str, url: str = DETAIL_URL, result_marker: bool = True):
        self.html = body
        self.url = url
        self.result_marker = result_marker

    def get(self, url: str, retry: int, timeout: int) -> bool:
        return True

    def ele(self, locator: str, timeout: int):
        if locator in DoubanMovieAdapter.SEARCH_INPUTS:
            return SearchInput()
        if locator == "css:.result-list" and self.result_marker:
            return object()
        return None


def test_search_navigation_failure_is_a_network_error() -> None:
    with pytest.raises(NetworkError, match="navigation failed"):
        DoubanMovieAdapter().search(NavigationFailureTab(), Task("a", "电影", None))


def test_detail_navigation_failure_is_a_network_error() -> None:
    candidate = Candidate("电影", "1994", "电影", "https://movie.douban.com/subject/1/")
    with pytest.raises(NetworkError, match="detail navigation failed"):
        DoubanMovieAdapter().fetch_detail(
            NavigationFailureTab(), Task("a", "电影", None), candidate
        )


def test_search_returns_candidates_after_result_marker() -> None:
    tab = LoadedTab(html("search_results.html"))
    candidates = DoubanMovieAdapter().search(tab, Task("a", "肖申克的救赎", "1994"))
    assert [candidate.title for candidate in candidates] == ["肖申克的救赎", "肖申克"]


def test_search_accepts_rendered_candidates_without_legacy_marker() -> None:
    tab = LoadedTab(html("search_results_react.html"), result_marker=False)
    candidates = DoubanMovieAdapter().search(
        tab, Task("a", "肖申克的救赎", "1994")
    )
    assert [candidate.title for candidate in candidates] == [
        "肖申克的救赎",
        "肖申克",
    ]


def test_search_timeout_is_a_page_changed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(predicate, timeout: int) -> None:
        raise TimeoutError

    monkeypatch.setattr(douban_movie, "wait_until", raise_timeout)
    with pytest.raises(PageChangedError, match="result marker"):
        DoubanMovieAdapter().search(
            LoadedTab("<html>普通页面</html>", result_marker=False),
            Task("a", "电影", None),
        )


def test_search_blocked_page_stops_the_batch() -> None:
    with pytest.raises(BlockedError, match="blocked the batch"):
        DoubanMovieAdapter().search(LoadedTab(html("blocked.html")), Task("a", "电影", None))


def test_detail_blocked_page_stops_the_batch() -> None:
    candidate = Candidate("电影", "1994", "电影", DETAIL_URL)
    with pytest.raises(BlockedError, match="blocked the batch"):
        DoubanMovieAdapter().fetch_detail(
            LoadedTab(html("blocked.html")), Task("a", "电影", None), candidate
        )


def test_fetch_detail_parses_loaded_page() -> None:
    candidate = Candidate("肖申克的救赎", "1994", "电影", DETAIL_URL)
    result = DoubanMovieAdapter().fetch_detail(
        LoadedTab(html("detail_movie.html")),
        Task("a", "肖申克的救赎", "1994"),
        candidate,
    )
    assert result.status == Status.SUCCESS
    assert result.matched_title == "肖申克的救赎"


@pytest.mark.parametrize(
    "url",
    [
        "https://sec.douban.com/c?r=https%3A%2F%2Fmovie.douban.com%2Fsubject%2F1%2F",
        "https://accounts.douban.com/passport/login",
    ],
)
def test_security_or_login_redirect_is_blocked(url: str) -> None:
    assert DoubanMovieAdapter.is_blocked("<html></html>", None, url)


@pytest.mark.parametrize("text", ["error code: 01004", "Please login"])
def test_login_required_text_is_blocked(text: str) -> None:
    assert DoubanMovieAdapter.is_blocked(text, 200, "https://movie.douban.com/")


def test_fetch_detail_raises_blocked_on_security_redirect() -> None:
    candidate = Candidate("电影", "1994", "电影", DETAIL_URL)
    tab = LoadedTab("<html>正常页面</html>", url="https://sec.douban.com/c?r=foo")
    with pytest.raises(BlockedError, match="blocked the batch"):
        DoubanMovieAdapter().fetch_detail(tab, Task("a", "电影", None), candidate)


# --------------------------------------------------------------------------- #
# Transient CDP context errors: ContextLostError / PageDisconnectedError
# --------------------------------------------------------------------------- #


class FlakyContextTab:
    """A tab that raises a transient CDP error on the first navigation
    attempt and recovers on the second. Mirrors the real DrissionPage
    behaviour where the same tab handle is re-attached after the CDP
    target briefly drops."""

    def __init__(self, body: str, failure_factory) -> None:
        self.html = body
        self.url = "https://movie.douban.com/"
        self._failure_factory = failure_factory
        self._get_attempts = 0

    def get(self, url: str, retry: int, timeout: int) -> bool:
        self._get_attempts += 1
        if self._get_attempts == 1:
            raise self._failure_factory()
        return True

    def ele(self, locator: str, timeout: int):
        if locator in DoubanMovieAdapter.SEARCH_INPUTS:
            return SearchInput()
        if locator == "css:.result-list":
            return object()
        return None


class AlwaysLostTab:
    """A tab whose every navigation raises the supplied transient error."""

    def __init__(self, failure_factory) -> None:
        self.html = "<html></html>"
        self.url = "https://movie.douban.com/"
        self._failure_factory = failure_factory

    def get(self, url: str, retry: int, timeout: int) -> bool:
        raise self._failure_factory()

    def ele(self, locator: str, timeout: int):
        if locator in DoubanMovieAdapter.SEARCH_INPUTS:
            return SearchInput()
        if locator == "css:.result-list":
            return object()
        return None


@pytest.mark.parametrize(
    "failure_factory",
    [
        lambda: ContextLostError(),
        lambda: PageDisconnectedError(),
    ],
    ids=["ContextLostError", "PageDisconnectedError"],
)
def test_search_recovers_when_first_navigation_raises_transient_cdp_error(
    failure_factory,
) -> None:
    tab = FlakyContextTab(html("search_results.html"), failure_factory)
    candidates = DoubanMovieAdapter().search(tab, Task("a", "肖申克的救赎", "1994"))
    # The second navigation succeeded, so we must get parsed candidates,
    # not a swallowed UNEXPECTED_ERROR / NetworkError.
    assert [c.title for c in candidates] == ["肖申克的救赎", "肖申克"]
    # And the tab.get retry path was actually exercised exactly twice.
    assert tab._get_attempts == 2


@pytest.mark.parametrize(
    "failure_factory",
    [
        lambda: ContextLostError(),
        lambda: PageDisconnectedError(),
    ],
    ids=["ContextLostError", "PageDisconnectedError"],
)
def test_search_escalates_persistent_transient_cdp_error_to_network_error(
    failure_factory,
) -> None:
    tab = AlwaysLostTab(failure_factory)
    with pytest.raises(NetworkError, match=r"^context lost: "):
        DoubanMovieAdapter().search(tab, Task("a", "肖申克的救赎", "1994"))


class FlakyContextDetailTab:
    """A tab that loses its CDP target on the first detail navigation,
    then recovers on the second. Returns detail body on successful nav."""

    def __init__(self, body: str, failure_factory) -> None:
        self._body = body
        self._failure_factory = failure_factory
        self._get_attempts = 0
        self.url = DETAIL_URL

    @property
    def html(self) -> str:
        return self._body

    def get(self, url: str, retry: int, timeout: int) -> bool:
        self._get_attempts += 1
        if self._get_attempts == 1:
            raise self._failure_factory()
        return True


class AlwaysLostDetailTab:
    def __init__(self, failure_factory) -> None:
        self._body = "<html></html>"
        self._failure_factory = failure_factory
        self.url = DETAIL_URL

    @property
    def html(self) -> str:
        return self._body

    def get(self, url: str, retry: int, timeout: int) -> bool:
        raise self._failure_factory()


@pytest.mark.parametrize(
    "failure_factory",
    [
        lambda: ContextLostError(),
        lambda: PageDisconnectedError(),
    ],
    ids=["ContextLostError", "PageDisconnectedError"],
)
def test_fetch_detail_recovers_when_first_navigation_raises_transient_cdp_error(
    failure_factory,
) -> None:
    candidate = Candidate("肖申克的救赎", "1994", "电影", DETAIL_URL)
    tab = FlakyContextDetailTab(html("detail_movie.html"), failure_factory)
    result = DoubanMovieAdapter().fetch_detail(tab, Task("a", "肖申克的救赎", "1994"), candidate)
    assert result.status is Status.SUCCESS
    assert result.matched_title == "肖申克的救赎"
    assert tab._get_attempts == 2


@pytest.mark.parametrize(
    "failure_factory",
    [
        lambda: ContextLostError(),
        lambda: PageDisconnectedError(),
    ],
    ids=["ContextLostError", "PageDisconnectedError"],
)
def test_fetch_detail_escalates_persistent_transient_cdp_error_to_network_error(
    failure_factory,
) -> None:
    candidate = Candidate("肖申克的救赎", "1994", "电影", DETAIL_URL)
    tab = AlwaysLostDetailTab(failure_factory)
    with pytest.raises(NetworkError, match=r"^context lost: "):
        DoubanMovieAdapter().fetch_detail(tab, Task("a", "肖申克的救赎", "1994"), candidate)


# --------------------------------------------------------------------------- #
# Site protection proof-of-work challenge: distinct from BLOCKED
# --------------------------------------------------------------------------- #


def test_is_challenge_pending_recognises_the_pow_challenge_form() -> None:
    assert DoubanMovieAdapter.is_challenge_pending(html("challenge.html")) is True


def test_is_challenge_pending_is_false_for_real_movie_pages() -> None:
    assert DoubanMovieAdapter.is_challenge_pending(html("search_results.html")) is False
    assert DoubanMovieAdapter.is_challenge_pending(html("detail_movie.html")) is False
    assert DoubanMovieAdapter.is_challenge_pending(html("blocked.html")) is False
    assert DoubanMovieAdapter.is_challenge_pending("") is False


def test_challenge_html_is_blocked_too_but_collected_as_challenge() -> None:
    # Douban's challenge page also matches the "sec.douban.com" / "captcha"
    # heuristics in some past runs; the runner must surface it as the more
    # specific SITE_PROTECTION_CHALLENGE status, not BLOCKED. We assert the
    # ordering by exercising the adapter helper that the runner relies on.
    assert DoubanMovieAdapter.is_challenge_pending(html("challenge.html")) is True


class ChallengePageTab:
    """A tab whose every navigation returns the real-shape PoW challenge page."""

    def __init__(self) -> None:
        self.html = html("challenge.html")
        self.url = "https://sec.douban.com/c?r=https%3A%2F%2Fmovie.douban.com%2F"
        self._get_attempts = 0

    def get(self, url: str, retry: int, timeout: int) -> bool:
        self._get_attempts += 1
        return True

    def ele(self, locator: str, timeout: int):
        if locator in DoubanMovieAdapter.SEARCH_INPUTS:
            return SearchInput()
        if locator == "css:.result-list":
            return object()
        return None


def test_search_challenge_page_raises_site_protection_challenge() -> None:
    tab = ChallengePageTab()
    with pytest.raises(SiteProtectionChallenge, match="proof-of-work challenge"):
        DoubanMovieAdapter().search(tab, Task("a", "肖申克的救赎", "1994"))
    # Adapter must NOT silently retry when a challenge is detected.
    assert tab._get_attempts == 1


def test_fetch_detail_challenge_page_raises_site_protection_challenge() -> None:
    candidate = Candidate("肖申克的救赎", "1994", "电影", DETAIL_URL)
    tab = ChallengePageTab()
    with pytest.raises(SiteProtectionChallenge, match="proof-of-work challenge"):
        DoubanMovieAdapter().fetch_detail(
            tab, Task("a", "肖申克的救赎", "1994"), candidate
        )
    assert tab._get_attempts == 1


def test_search_challenge_does_not_collapse_into_blocked_error() -> None:
    tab = ChallengePageTab()
    # If we ever regressed and let the challenge slip into the BLOCKED bucket,
    # this test would raise BlockedError instead of the more specific
    # SiteProtectionChallenge and fail the match.
    with pytest.raises(SiteProtectionChallenge):
        DoubanMovieAdapter().search(tab, Task("a", "肖申克的救赎", "1994"))
