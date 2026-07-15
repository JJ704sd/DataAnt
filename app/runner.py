from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.diagnostics import capture_failure, redact
from app.matcher import choose_match
from app.models import MovieResult, RunSummary, Status, Task
from app.sites.douban_movie import BlockedError, NetworkError, PageChangedError

DEFAULT_RETRY: frozenset[Status] = frozenset(
    {Status.NETWORK_ERROR, Status.OUTPUT_LOCKED, Status.UNEXPECTED_ERROR}
)

# Backoff sleeps between network attempts: attempt 1 immediate, attempt 2
# after 2s, attempt 3 after 5s. Three attempts total.
_NETWORK_BACKOFF_SECONDS: tuple[float, ...] = (0.0, 2.0, 5.0)
_NETWORK_ERROR_MESSAGE_MAX = 200

# Failure statuses that warrant a diagnostic capture. Success and ordinary
# business-end statuses (NOT_FOUND, REVIEW_REQUIRED) intentionally stay out.
_CAPTURE_STATUSES: frozenset[Status] = frozenset(
    {
        Status.NETWORK_ERROR,
        Status.PAGE_CHANGED,
        Status.BLOCKED,
        Status.UNEXPECTED_ERROR,
    }
)


class Runner:
    def __init__(
        self,
        adapter,
        store,
        tab: Any,
        min_interval_seconds: float = 5,
        retry_statuses=None,
        logger: logging.Logger | None = None,
        artifacts_dir: Path | None = None,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.tab = tab
        self.min_interval_seconds = float(min_interval_seconds)
        self.retry_statuses: frozenset[Status] = DEFAULT_RETRY | frozenset(
            retry_statuses or set()
        )
        self.logger = logger
        self.artifacts_dir = artifacts_dir

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
            self._persist(result)
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
            candidates = self._network_operation(
                lambda: self.adapter.search(self.tab, task)
            )
        except BlockedError as exc:
            return (
                _result_with(task, status=Status.BLOCKED, error_message=str(exc)),
                True,
            )
        except PageChangedError as exc:
            return (
                _result_with(task, status=Status.PAGE_CHANGED, error_message=str(exc)),
                False,
            )
        except NetworkError as exc:
            return (
                _result_with(
                    task,
                    status=Status.NETWORK_ERROR,
                    error_message=str(exc)[:_NETWORK_ERROR_MESSAGE_MAX],
                ),
                False,
            )
        except Exception as exc:
            return (
                _result_with(
                    task,
                    status=Status.UNEXPECTED_ERROR,
                    error_message=type(exc).__name__,
                ),
                False,
            )

        if not candidates:
            return (
                _result_with(
                    task, status=Status.NOT_FOUND, error_message="No candidates"
                ),
                False,
            )

        decision = choose_match(task, candidates)
        if decision.candidate_index is None:
            return (
                _result_with(
                    task,
                    status=Status.REVIEW_REQUIRED,
                    error_message=decision.reason,
                ),
                False,
            )

        candidate = candidates[decision.candidate_index]
        try:
            detail = self._network_operation(
                lambda: self.adapter.fetch_detail(self.tab, task, candidate)
            )
        except BlockedError as exc:
            return (
                _result_with(task, status=Status.BLOCKED, error_message=str(exc)),
                True,
            )
        except PageChangedError as exc:
            return (
                _result_with(task, status=Status.PAGE_CHANGED, error_message=str(exc)),
                False,
            )
        except NetworkError as exc:
            return (
                _result_with(
                    task,
                    status=Status.NETWORK_ERROR,
                    error_message=str(exc)[:_NETWORK_ERROR_MESSAGE_MAX],
                ),
                False,
            )
        except Exception as exc:
            return (
                _result_with(
                    task,
                    status=Status.UNEXPECTED_ERROR,
                    error_message=type(exc).__name__,
                ),
                False,
            )

        merged = replace(detail, match_method=decision.method)
        return merged, False

    def _network_operation(self, operation):
        """Run a network-touching operation with 2/5-second exponential backoff.

        Tries up to three times. Only ``NetworkError`` triggers a retry;
        any other exception propagates immediately. The final ``NetworkError``
        is re-raised when all attempts fail.
        """
        last_error: NetworkError | None = None
        for backoff in _NETWORK_BACKOFF_SECONDS:
            if backoff > 0:
                time.sleep(backoff)
            try:
                return operation()
            except NetworkError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def _persist(self, result: MovieResult) -> None:
        """Upsert the result, log it, and capture diagnostics on failure.

        ``OutputLockedError`` raised by ``store.upsert`` propagates as-is so
        the CLI can return exit code 4. Capture is skipped when
        ``artifacts_dir`` is ``None`` or the tab lacks screenshot
        capability, and any diagnostics exception is swallowed so the
        persisted business result is never overridden.
        """
        # OutputLockedError must propagate to the CLI; do not catch it.
        self.store.upsert(result)

        if self.logger is not None:
            self.logger.info(
                "task_id=%s status=%s",
                redact(result.task_id),
                result.status.value,
            )

        if result.status in _CAPTURE_STATUSES:
            if self.artifacts_dir is not None and hasattr(
                self.tab, "get_screenshot"
            ):
                try:
                    capture_failure(self.tab, self.artifacts_dir, result.task_id)
                except Exception:
                    # Diagnostics must never override the business result.
                    pass


def _result_with(task: Task, *, status: Status, error_message: str) -> MovieResult:
    base = MovieResult.from_task(task)
    return replace(base, status=status, error_message=error_message).stamped()
