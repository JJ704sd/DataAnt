from __future__ import annotations

import re
import unicodedata

from app.models import Candidate, MatchDecision, MatchMethod, Task

_PRIMARY_TITLE_BOUNDARIES = frozenset("/·:：-—(（[【")


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"\s+", " ", normalized)


def _has_primary_title_prefix(candidate: str, query: str) -> bool:
    if not candidate.startswith(query) or len(candidate) == len(query):
        return False
    boundary = candidate[len(query)]
    return boundary.isspace() or boundary in _PRIMARY_TITLE_BOUNDARIES


def choose_match(task: Task, candidates: list[Candidate]) -> MatchDecision:
    query = normalize_title(task.query)
    exact = [
        index
        for index, item in enumerate(candidates)
        if normalize_title(item.title) == query
    ]
    if len(exact) == 1:
        return MatchDecision(MatchMethod.RULE_EXACT, exact[0], "unique normalized title")
    if len(exact) > 1 and task.query_year:
        year_matches = [
            index for index in exact if candidates[index].year == task.query_year
        ]
        if len(year_matches) == 1:
            return MatchDecision(MatchMethod.RULE_YEAR, year_matches[0], "title and year")
    if task.query_year:
        primary_year_matches = [
            index
            for index, item in enumerate(candidates)
            if item.year == task.query_year
            and _has_primary_title_prefix(normalize_title(item.title), query)
        ]
        if len(primary_year_matches) == 1:
            return MatchDecision(
                MatchMethod.RULE_YEAR,
                primary_year_matches[0],
                "primary title and year",
            )
    return MatchDecision(MatchMethod.NONE, None, "no unique deterministic match")
