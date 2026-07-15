import pytest

from app.matcher import choose_match, normalize_title
from app.models import Candidate, MatchMethod, Task


def candidate(title: str, year: str | None) -> Candidate:
    return Candidate(title, year, "电影", "https://movie.douban.com/subject/1/")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Ａ  Movie  ", "a movie"),
        ("英雄", "英雄"),
        ("The\tMOVIE\nPart  2", "the movie part 2"),
    ],
)
def test_normalize_title_handles_nfkc_case_and_whitespace(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


def test_unique_exact_title_is_selected() -> None:
    task = Task("1", "英雄", None)
    decision = choose_match(task, [candidate("英雄", "2002"), candidate("英雄本色", "1986")])
    assert decision == decision.__class__(MatchMethod.RULE_EXACT, 0, "unique normalized title")


def test_normalized_title_equality_is_used() -> None:
    task = Task("1", "Ａ Movie", None)
    decision = choose_match(task, [candidate("a   movie", "2002")])
    assert decision.method == MatchMethod.RULE_EXACT
    assert decision.candidate_index == 0


def test_year_breaks_an_exact_title_tie() -> None:
    task = Task("1", "英雄", "2002")
    decision = choose_match(task, [candidate("英雄", "2002"), candidate("英雄", "2022")])
    assert decision.method == MatchMethod.RULE_YEAR
    assert decision.candidate_index == 0
    assert decision.reason == "title and year"


@pytest.mark.parametrize(
    ("task", "candidates"),
    [
        (Task("1", "英雄", None), []),
        (Task("1", "英雄", None), [candidate("英雄本色", "1986")]),
        (Task("1", "英雄", None), [candidate("英雄", "2002"), candidate("英雄", "2022")]),
        (Task("1", "英雄", "1999"), [candidate("英雄", "2002"), candidate("英雄", "2022")]),
        (Task("1", "英雄", "2002"), [candidate("英雄", "2002"), candidate("英雄", "2002")]),
    ],
)
def test_non_unique_or_non_exact_cases_are_not_guessed(
    task: Task, candidates: list[Candidate]
) -> None:
    decision = choose_match(task, candidates)
    assert decision.method == MatchMethod.NONE
    assert decision.candidate_index is None
    assert decision.reason == "no unique deterministic match"
