from __future__ import annotations

from typing import Any

import pytest

from app.models import (
    Candidate,
    MatchDecision,
    MatchMethod,
    MovieResult,
    RunSummary,
    Status,
    Task,
)
from app.runner import DEFAULT_RETRY, Runner
from app.sites.douban_movie import BlockedError, NetworkError, PageChangedError


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


class FakeStore:
    def __init__(self, statuses: dict[str, Status] | None = None) -> None:
        self.statuses: dict[str, Status] = dict(statuses or {})
        self.upserts: list[MovieResult] = []

    def status_by_task_id(self) -> dict[str, Status]:
        return dict(self.statuses)

    def upsert(self, result: MovieResult) -> None:
        self.upserts.append(result)
        self.statuses[result.task_id] = result.status


class FakeAdapter:
    def __init__(self, search_results: dict[str, list[Candidate]] | None = None) -> None:
        self.search_results: dict[str, list[Candidate]] = dict(search_results or {})
        self.detail_results: dict[str, MovieResult] = {}
        self.search_calls: list[tuple[Any, Task]] = []
        self.detail_calls: list[tuple[Any, Task, Candidate]] = []

    def search(self, tab: Any, task: Task) -> list[Candidate]:
        self.search_calls.append((tab, task))
        if task.task_id in self.search_results:
            payload = self.search_results[task.task_id]
            if isinstance(payload, Exception):
                raise payload
            return payload
        return []

    def fetch_detail(self, tab: Any, task: Task, candidate: Candidate) -> MovieResult:
        self.detail_calls.append((tab, task, candidate))
        if task.task_id in self.detail_results:
            payload = self.detail_results[task.task_id]
            if isinstance(payload, Exception):
                raise payload
            return payload
        raise AssertionError(f"fetch_detail unexpectedly called for {task.task_id}")


def task(task_id: str, query: str = "英雄", year: str | None = None) -> Task:
    return Task(task_id=task_id, query=query, query_year=year)


def candidate(title: str = "英雄", year: str = "2002") -> Candidate:
    return Candidate(title, year, "电影", f"https://movie.douban.com/subject/1/")


def successful_detail(task: Task, method: MatchMethod = MatchMethod.NONE) -> MovieResult:
    return MovieResult(
        task_id=task.task_id,
        query=task.query,
        query_year=task.query_year,
        matched_title="英雄",
        matched_year="2002",
        director="Director",
        rating=9.1,
        detail_url="https://movie.douban.com/subject/1/",
        match_method=method,
        status=Status.SUCCESS,
        collected_at="2026-07-15T12:00:00+08:00",
    )


def make_runner(
    adapter: FakeAdapter,
    store: FakeStore,
    tab: Any = None,
    **kwargs: Any,
) -> Runner:
    """Construct a Runner with no pacing by default; pacing tests pass
    `min_interval_seconds` explicitly."""
    kwargs.setdefault("min_interval_seconds", 0)
    return Runner(adapter=adapter, store=store, tab=tab or object(), **kwargs)


# --------------------------------------------------------------------------- #
# Skipping, NOT_FOUND, REVIEW_REQUIRED
# --------------------------------------------------------------------------- #


def test_success_status_is_skipped_and_not_looked_up() -> None:
    store = FakeStore({"done": Status.SUCCESS})
    adapter = FakeAdapter()
    runner = make_runner(adapter, store)

    summary = runner.run([task("done")])

    assert summary == RunSummary(processed=0, skipped=1, blocked=False)
    assert adapter.search_calls == []
    assert store.upserts == []


def test_no_candidates_writes_not_found_with_specific_message() -> None:
    store = FakeStore()
    adapter = FakeAdapter()
    runner = make_runner(adapter, store)

    summary = runner.run([task("a")])

    assert summary == RunSummary(processed=1, skipped=0, blocked=False)
    assert len(store.upserts) == 1
    result = store.upserts[0]
    assert result.status is Status.NOT_FOUND
    assert result.error_message == "No candidates"


def test_multiple_candidates_without_year_writes_review_required() -> None:
    store = FakeStore()
    adapter = FakeAdapter(
        search_results={
            "a": [candidate("英雄", "2002"), candidate("英雄", "2022")],
        }
    )
    runner = make_runner(adapter, store)

    summary = runner.run([task("a", year=None)])

    assert summary == RunSummary(processed=1, skipped=0, blocked=False)
    assert len(store.upserts) == 1
    result = store.upserts[0]
    assert result.status is Status.REVIEW_REQUIRED
    assert result.error_message == MatchDecision(
        MatchMethod.NONE, None, "no unique deterministic match"
    ).reason
    assert adapter.detail_calls == []


# --------------------------------------------------------------------------- #
# Default vs explicit retry sets
# --------------------------------------------------------------------------- #


def test_default_retry_re_runs_only_transient_statuses() -> None:
    store = FakeStore(
        {
            "skip_success": Status.SUCCESS,
            "skip_blocked": Status.BLOCKED,
            "skip_changed": Status.PAGE_CHANGED,
            "skip_review": Status.REVIEW_REQUIRED,
            "skip_missing": Status.NOT_FOUND,
            "retry_net": Status.NETWORK_ERROR,
            "retry_lock": Status.OUTPUT_LOCKED,
            "retry_unexp": Status.UNEXPECTED_ERROR,
        }
    )
    adapter = FakeAdapter()
    runner = make_runner(adapter, store)

    summary = runner.run(
        [
            task("skip_success"),
            task("skip_blocked"),
            task("skip_changed"),
            task("skip_review"),
            task("skip_missing"),
            task("retry_net"),
            task("retry_lock"),
            task("retry_unexp"),
        ]
    )

    assert summary == RunSummary(processed=3, skipped=5, blocked=False)
    processed_ids = {result.task_id for result in store.upserts}
    assert processed_ids == {"retry_net", "retry_lock", "retry_unexp"}
    for result in store.upserts:
        assert result.status is Status.NOT_FOUND
        assert result.error_message == "No candidates"


def test_explicit_retry_statuses_only_add_to_default_set() -> None:
    store = FakeStore(
        {
            "extra_changed": Status.PAGE_CHANGED,  # not in DEFAULT_RETRY
            "skip_success": Status.SUCCESS,
            "retry_net": Status.NETWORK_ERROR,
        }
    )
    adapter = FakeAdapter()
    runner = make_runner(
        adapter,
        store,
        retry_statuses={Status.PAGE_CHANGED},
    )

    summary = runner.run(
        [task("extra_changed"), task("skip_success"), task("retry_net")]
    )

    assert summary == RunSummary(processed=2, skipped=1, blocked=False)
    processed_ids = {result.task_id for result in store.upserts}
    assert processed_ids == {"extra_changed", "retry_net"}


def test_default_retry_set_is_exactly_three_transient_statuses() -> None:
    assert DEFAULT_RETRY == frozenset(
        {Status.NETWORK_ERROR, Status.OUTPUT_LOCKED, Status.UNEXPECTED_ERROR}
    )


# --------------------------------------------------------------------------- #
# Adapter exceptions
# --------------------------------------------------------------------------- #


def test_blocked_error_stops_the_batch_after_writing_current_task() -> None:
    store = FakeStore()
    adapter = FakeAdapter(
        search_results={
            "a": BlockedError("captcha"),
            "b": [],
        }
    )
    runner = make_runner(adapter, store)

    summary = runner.run([task("a"), task("b")])

    assert summary == RunSummary(processed=1, skipped=0, blocked=True)
    assert [result.task_id for result in store.upserts] == ["a"]
    assert store.upserts[0].status is Status.BLOCKED
    assert store.upserts[0].error_message == "captcha"
    # Adapter.search must not have been called for "b".
    assert [called[1].task_id for called in adapter.search_calls] == ["a"]


def test_page_changed_error_writes_status_and_continues_batch() -> None:
    store = FakeStore()
    adapter = FakeAdapter(
        search_results={
            "a": PageChangedError("layout shifted"),
            "b": [],
        }
    )
    runner = make_runner(adapter, store)

    summary = runner.run([task("a"), task("b")])

    assert summary == RunSummary(processed=2, skipped=0, blocked=False)
    assert [(r.task_id, r.status) for r in store.upserts] == [
        ("a", Status.PAGE_CHANGED),
        ("b", Status.NOT_FOUND),
    ]
    assert store.upserts[0].error_message == "layout shifted"


def test_network_error_is_not_swallowed_and_writes_status() -> None:
    store = FakeStore()
    adapter = FakeAdapter(
        search_results={"a": NetworkError("transient"), "b": []}
    )
    runner = make_runner(adapter, store)

    summary = runner.run([task("a"), task("b")])

    assert summary == RunSummary(processed=2, skipped=0, blocked=False)
    assert [r.status for r in store.upserts] == [
        Status.NETWORK_ERROR,
        Status.NOT_FOUND,
    ]
    assert store.upserts[0].error_message == "transient"


# --------------------------------------------------------------------------- #
# Detail fetching with injected tab
# --------------------------------------------------------------------------- #


def test_unique_match_fetches_detail_and_replaces_match_method() -> None:
    tab = object()
    detail_task = task("a")
    adapter = FakeAdapter(search_results={"a": [candidate("英雄", "2002")]})
    adapter.detail_results["a"] = successful_detail(detail_task, method=MatchMethod.NONE)
    store = FakeStore()
    runner = make_runner(adapter, store, tab=tab)

    summary = runner.run([detail_task])

    assert summary == RunSummary(processed=1, skipped=0, blocked=False)
    assert len(adapter.detail_calls) == 1
    call_tab, called_task, called_candidate = adapter.detail_calls[0]
    assert call_tab is tab
    assert called_task is detail_task
    assert called_candidate.title == "英雄"
    result = store.upserts[0]
    # match_method on the persisted result is the decision method, not the detail's.
    assert result.match_method is MatchMethod.RULE_EXACT
    assert result.status is Status.SUCCESS
    # Detail parser's collected_at is preserved.
    assert result.collected_at == "2026-07-15T12:00:00+08:00"


def test_unique_match_with_year_decision_keeps_rule_year_method() -> None:
    detail_task = task("a", year="2002")
    adapter = FakeAdapter(
        search_results={
            "a": [candidate("英雄", "2002"), candidate("英雄", "2022")],
        }
    )
    adapter.detail_results["a"] = successful_detail(detail_task, method=MatchMethod.NONE)
    store = FakeStore()
    runner = make_runner(adapter, store)

    summary = runner.run([detail_task])

    assert summary == RunSummary(processed=1, skipped=0, blocked=False)
    result = store.upserts[0]
    assert result.match_method is MatchMethod.RULE_YEAR
    assert result.status is Status.SUCCESS


# --------------------------------------------------------------------------- #
# Minimum interval pacing
# --------------------------------------------------------------------------- #


def test_min_interval_is_enforced_only_for_processed_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("app.runner.time.sleep", lambda seconds: sleeps.append(seconds))

    # Per-task pacing: each task is measured from its start; if the run
    # finishes faster than min_interval_seconds, the runner sleeps the diff.
    # Two processed tasks, each finishing instantly, both must sleep the
    # full budget. The skipped task in the middle must not contribute.
    monotonic_values = iter([100.0, 100.0, 102.0, 102.0])
    monkeypatch.setattr("app.runner.time.monotonic", lambda: next(monotonic_values))

    store = FakeStore(
        {
            "skip": Status.SUCCESS,  # skipped — no sleep
            "a": Status.NETWORK_ERROR,  # retried — sleep 5
            "b": Status.NETWORK_ERROR,  # retried — sleep 5
        }
    )
    adapter = FakeAdapter()
    runner = Runner(
        adapter=adapter,
        store=store,
        tab=object(),
        min_interval_seconds=5,
    )

    summary = runner.run([task("skip"), task("a"), task("b")])

    assert summary == RunSummary(processed=2, skipped=1, blocked=False)
    # Skipped tasks must not contribute to the sleep budget; each processed
    # task sleeps the full min_interval because it does no work.
    assert sleeps == [pytest.approx(5.0), pytest.approx(5.0)]


def test_min_interval_uses_frozen_clock_when_task_is_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("app.runner.time.sleep", lambda seconds: sleeps.append(seconds))

    # Task "a" starts at 0, finishes at 0 (no work elapsed). Task "b" starts
    # at 0, finishes at 0. With min_interval=5, both should sleep the full 5s.
    monotonic_values = iter([0.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr("app.runner.time.monotonic", lambda: next(monotonic_values))

    store = FakeStore({"a": Status.NETWORK_ERROR, "b": Status.NETWORK_ERROR})
    adapter = FakeAdapter()
    runner = Runner(
        adapter=adapter,
        store=store,
        tab=object(),
        min_interval_seconds=5,
    )

    runner.run([task("a"), task("b")])

    assert sleeps == [pytest.approx(5.0), pytest.approx(5.0)]


# --------------------------------------------------------------------------- #
# Stamping / upsert behavior
# --------------------------------------------------------------------------- #


def test_not_found_result_is_stamped_before_upsert() -> None:
    store = FakeStore()
    adapter = FakeAdapter()
    runner = make_runner(adapter, store)

    runner.run([task("a")])

    result = store.upserts[0]
    # NOT_FOUND path always stamps (no collected_at from detail parser).
    assert result.collected_at != ""
    assert result.status is Status.NOT_FOUND


def test_upsert_updates_existing_task_id() -> None:
    store = FakeStore({"a": Status.NETWORK_ERROR})
    adapter = FakeAdapter()
    runner = make_runner(adapter, store)

    runner.run([task("a")])

    # Single record persisted; status index reflects the new outcome.
    assert [result.task_id for result in store.upserts] == ["a"]
    assert store.status_by_task_id()["a"] is Status.NOT_FOUND
