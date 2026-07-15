from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from app.matcher import choose_match
from app.models import MovieResult, RunSummary, Status, Task
from app.sites.douban_movie import BlockedError, NetworkError, PageChangedError

DEFAULT_RETRY: frozenset[Status] = frozenset(
    {Status.NETWORK_ERROR, Status.OUTPUT_LOCKED, Status.UNEXPECTED_ERROR}
)


class Runner:
    def __init__(
        self,
        adapter,
        store,
        tab: Any,
        min_interval_seconds: float = 5,
        retry_statuses=None,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.tab = tab
        self.min_interval_seconds = float(min_interval_seconds)
        self.retry_statuses: frozenset[Status] = DEFAULT_RETRY | frozenset(
            retry_statuses or set()
        )

    def run(self, tasks: list[Task]) -> RunSummary:
        existing = self.store.status_by_task_id()
        processed = 0
        skipped = 0
        blocked = False

        for task in tasks:
            prior = existing.get(task.task_id)
            if prior is not None and prior not in self.retry_statuses:
                skipped += 1
                continue

            started = time.monotonic()
            result, was_blocked = self._process(task)
            self.store.upsert(result)
            finished = time.monotonic()

            elapsed = finished - started
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)

            processed += 1
            if was_blocked:
                blocked = True
                break

        return RunSummary(processed=processed, skipped=skipped, blocked=blocked)

    def _process(self, task: Task) -> tuple[MovieResult, bool]:
        try:
            candidates = self.adapter.search(self.tab, task)
        except BlockedError as exc:
            return (
                _result_with(task, status=Status.BLOCKED, error_message=str(exc)),
                True,
            )
        except PageChangedError as exc:
            return _result_with(task, status=Status.PAGE_CHANGED, error_message=str(exc)), False
        except NetworkError as exc:
            return _result_with(task, status=Status.NETWORK_ERROR, error_message=str(exc)), False

        if not candidates:
            return _result_with(task, status=Status.NOT_FOUND, error_message="No candidates"), False

        decision = choose_match(task, candidates)
        if decision.candidate_index is None:
            return _result_with(
                task,
                status=Status.REVIEW_REQUIRED,
                error_message=decision.reason,
            ), False

        candidate = candidates[decision.candidate_index]
        detail = self.adapter.fetch_detail(self.tab, task, candidate)
        merged = replace(detail, match_method=decision.method)
        return merged, False


def _result_with(task: Task, *, status: Status, error_message: str) -> MovieResult:
    base = MovieResult.from_task(task)
    return replace(base, status=status, error_message=error_message).stamped()
