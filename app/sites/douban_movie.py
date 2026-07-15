from __future__ import annotations

import re
from dataclasses import replace
from html import unescape

from DrissionPage.common import wait_until

from app.models import Candidate, MatchMethod, MovieResult, Status, Task


DETAIL_URL = re.compile(r"^https://movie\.douban\.com/subject/\d+/$")
BLOCK_TEXT = ("访问频率过高", "异常请求", "验证码")
_SUBJECT_LINK = re.compile(
    r'<a\b[^>]*href=["\'](https://movie\.douban\.com/subject/\d+/)["\'][^>]*>'
    r'(.*?)</a>(.*?)(?=<a\b[^>]*href=["\']https://movie\.douban\.com/subject/\d+/|$)',
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")
_YEAR_AND_KIND = re.compile(r"\b((?:19|20)\d{2})\b\s*/\s*([^<\n]+)")


def _text(fragment: str) -> str:
    return " ".join(unescape(_TAG.sub(" ", fragment)).split())


class BlockedError(RuntimeError):
    pass


class PageChangedError(RuntimeError):
    pass


class NetworkError(RuntimeError):
    pass


class DoubanMovieAdapter:
    SEARCH_INPUTS = (
        "@role=searchbox",
        "css:input[name='search_text']",
    )
    EMPTY_RESULT_TEXT = ("没有找到", "暂无搜索结果")

    @staticmethod
    def is_blocked(html: str, status_code: int | None) -> bool:
        return status_code in {403, 418, 429} or any(marker in html for marker in BLOCK_TEXT)

    @staticmethod
    def parse_search_html(html: str) -> list[Candidate]:
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
            if len(candidates) == 5:
                break
        return candidates

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
        if not tab.get("https://movie.douban.com/", retry=0, timeout=20):
            raise NetworkError("Douban navigation failed")
        if self.is_blocked(tab.html, None):
            raise BlockedError("Douban blocked the batch")
        self._search_input(tab).input(f"{task.query}\n", clear=True)
        try:
            wait_until(lambda: self._search_is_ready(tab.html), timeout=10)
        except TimeoutError as exc:
            raise PageChangedError("Search result marker was not found") from exc
        page_html = tab.html
        if self.is_blocked(page_html, None):
            raise BlockedError("Douban blocked the batch")
        return self.parse_search_html(page_html)

    def fetch_detail(self, tab, task: Task, candidate: Candidate) -> MovieResult:
        if not tab.get(candidate.detail_url, retry=0, timeout=20):
            raise NetworkError("Douban detail navigation failed")
        page_html = tab.html
        if self.is_blocked(page_html, None):
            raise BlockedError("Douban blocked the batch")
        return self.parse_detail_html(page_html, task, tab.url)
