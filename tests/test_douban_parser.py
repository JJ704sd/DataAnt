from pathlib import Path

import pytest

from app.models import MatchMethod, Status, Task
from app.sites.douban_movie import DoubanMovieAdapter


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


def test_parse_search_empty_returns_empty_list() -> None:
    assert DoubanMovieAdapter.parse_search_html(html("search_empty.html")) == []


def test_parse_search_limits_candidates_to_five() -> None:
    item = '<a href="https://movie.douban.com/subject/{}/">电影</a><span>1994 / 电影</span>'
    assert len(DoubanMovieAdapter.parse_search_html("".join(item.format(i) for i in range(1, 7)))) == 5


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
