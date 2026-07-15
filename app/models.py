from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class Status(StrEnum):
    SUCCESS = "SUCCESS"
    NOT_FOUND = "NOT_FOUND"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PAGE_CHANGED = "PAGE_CHANGED"
    BLOCKED = "BLOCKED"
    OUTPUT_LOCKED = "OUTPUT_LOCKED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


class MatchMethod(StrEnum):
    RULE_EXACT = "RULE_EXACT"
    RULE_YEAR = "RULE_YEAR"
    LLM = "LLM"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    query: str
    query_year: str | None


@dataclass(frozen=True, slots=True)
class Candidate:
    title: str
    year: str | None
    kind: str | None
    detail_url: str


@dataclass(frozen=True, slots=True)
class MatchDecision:
    method: MatchMethod
    candidate_index: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class MovieResult:
    task_id: str
    query: str
    query_year: str | None
    matched_title: str = ""
    matched_year: str | None = None
    director: str = ""
    rating: float | None = None
    detail_url: str = ""
    match_method: MatchMethod = MatchMethod.NONE
    status: Status = Status.UNEXPECTED_ERROR
    error_message: str = ""
    collected_at: str = ""

    @classmethod
    def from_task(cls, task: Task) -> MovieResult:
        return cls(
            task_id=task.task_id,
            query=task.query,
            query_year=task.query_year,
        )

    def stamped(self) -> MovieResult:
        collected_at = datetime.now().astimezone().isoformat(timespec="seconds")
        return replace(self, collected_at=collected_at)


@dataclass(frozen=True, slots=True)
class RunSummary:
    processed: int = 0
    skipped: int = 0
    blocked: bool = False
