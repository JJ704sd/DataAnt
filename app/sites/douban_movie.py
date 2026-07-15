from __future__ import annotations

import re
from dataclasses import replace

from app.models import Candidate, MatchMethod, MovieResult, Status, Task


DETAIL_URL = re.compile(r"^https://movie\.douban\.com/subject/\d+/$")
BLOCK_TEXT = ("访问频率过高", "异常请求", "验证码")


class DoubanMovieAdapter:
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
