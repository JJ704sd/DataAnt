from __future__ import annotations

import re
from dataclasses import replace

from DrissionPage.common import wait_until

from app.models import Candidate, MatchMethod, MovieResult, Status, Task


DETAIL_URL = re.compile(r"^https://movie\.douban\.com/subject/\d+/$")
BLOCK_TEXT = ("访问频率过高", "异常请求", "验证码")


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

    @staticmethod
    def is_blocked(html: str, status_code: int | None) -> bool:
        return status_code in {403, 418, 429} or any(marker in html for marker in BLOCK_TEXT)

    @staticmethod
    def parse_search_html(html: str) -> list[Candidate]:
        links = re.findall(
            r'<a[^>]+href="(https://movie\.douban\.com/subject/\d+/)"[^>]*>([^<]+)</a>\s*<span>(\d{4})\s*/\s*([^<]+)</span>',
            html,
        )
        return [
            Candidate(title.strip(), year, kind.strip(), url)
            for url, title, year, kind in links[:5]
        ]

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

    def search(self, tab, task: Task) -> list[Candidate]:
        if not tab.get("https://movie.douban.com/", retry=0, timeout=20):
            raise NetworkError("Douban navigation failed")
        if self.is_blocked(tab.html, None):
            raise BlockedError("Douban blocked the batch")
        self._search_input(tab).input(f"{task.query}\n", clear=True)
        try:
            wait_until(
                lambda: bool(tab.ele("css:.result-list", timeout=0))
                or "没有找到" in tab.html,
                timeout=10,
            )
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
