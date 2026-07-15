from __future__ import annotations

import re
import unicodedata

from app.models import Candidate, MatchDecision, MatchMethod, Task


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"\s+", " ", normalized)


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
    return MatchDecision(MatchMethod.NONE, None, "no unique deterministic match")
