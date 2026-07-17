from __future__ import annotations

import logging
from pathlib import Path
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
from app.site_errors import (
    BlockedError,
    NetworkError,
    PageChangedError,
    SiteProtectionChallenge,
)


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


def test_network_error_is_not_swallowed_and_writes_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("app.runner.time.sleep", lambda seconds: sleeps.append(seconds))

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
    # Three attempts on task "a" with the 2/5-second backoff between them.
    assert sleeps == [pytest.approx(2.0), pytest.approx(5.0)]


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


# --------------------------------------------------------------------------- #
# Diagnostics: redaction (app.diagnostics.redact)
# --------------------------------------------------------------------------- #


def test_redact_replaces_uppercase_minimax_api_key_value() -> None:
    from app.diagnostics import redact

    text = "Authorization header: MINIMAX_API_KEY=sk-secret-abc-123"
    redacted = redact(text)

    assert "sk-secret-abc-123" not in redacted
    # The label is preserved so the log line still reads naturally.
    assert "MINIMAX_API_KEY=" in redacted
    assert "***" in redacted


def test_redact_replaces_lowercase_minimax_api_key_value() -> None:
    from app.diagnostics import redact

    text = "config minimax_api_key=sk-lower-456"
    redacted = redact(text)

    assert "sk-lower-456" not in redacted


def test_redact_replaces_mixed_case_minimax_api_key_value() -> None:
    from app.diagnostics import redact

    text = "MiniMax_API_KEY=sk-mixed-789"
    redacted = redact(text)

    assert "sk-mixed-789" not in redacted


def test_redact_replaces_cookie_value() -> None:
    from app.diagnostics import redact

    text = "Request had Cookie: dbcl2=abc123456; bid=xyz987"
    redacted = redact(text)

    # The literal cookie values are scrubbed.
    assert "abc123456" not in redacted
    assert "xyz987" not in redacted
    # The header label is preserved so the line still reads naturally.
    assert "Cookie:" in redacted


def test_redact_preserves_non_sensitive_text() -> None:
    from app.diagnostics import redact

    text = "Movie lookup succeeded for 英雄 (2002) with no errors"
    assert redact(text) == text


# --------------------------------------------------------------------------- #
# Diagnostics: configure_logging
# --------------------------------------------------------------------------- #


def test_configure_logging_creates_browser_bot_logger_with_timestamped_file(
    tmp_path: Path,
) -> None:
    from app.diagnostics import configure_logging

    artifacts_dir = tmp_path / "artifacts"

    logger = configure_logging(artifacts_dir)

    assert logger.name == "browser_bot"
    assert logger.level <= logging.INFO
    assert artifacts_dir.is_dir()
    log_files = list(artifacts_dir.glob("run-*.log"))
    assert len(log_files) == 1
    assert log_files[0].name.endswith(".log")
    # Has both console and file handlers attached.
    assert len(logger.handlers) >= 2


def test_configure_logging_does_not_duplicate_handlers(tmp_path: Path) -> None:
    from app.diagnostics import configure_logging

    artifacts_dir = tmp_path / "artifacts"
    logger1 = configure_logging(artifacts_dir)
    handlers_after_first = len(logger1.handlers)

    logger2 = configure_logging(artifacts_dir)

    # Same logger instance, no duplicated handlers.
    assert logger2 is logger1
    assert len(logger2.handlers) == handlers_after_first
    # Two timestamped files (one per call) so prior runs are not overwritten.
    log_files = list(artifacts_dir.glob("run-*.log"))
    assert len(log_files) == 2


# --------------------------------------------------------------------------- #
# Diagnostics: capture_failure
# --------------------------------------------------------------------------- #


class FakeTab:
    """A minimal DrissionPage `tab` stand-in: `.html` and `.get_screenshot()`."""

    def __init__(self, html: str = "no secrets here") -> None:
        self.html = html
        self.screenshot_calls: list[dict[str, Any]] = []

    def get_screenshot(
        self, path: Any = None, name: Any = None, full_page: Any = False
    ) -> str:
        if path is not None and name is not None:
            output = Path(str(path)) / str(name)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"\x89PNG placeholder")
            self.screenshot_calls.append(
                {"path": str(path), "name": str(name), "full_page": full_page}
            )
            return str(output)
        return ""


def test_capture_failure_invokes_screenshot_and_writes_redacted_html(
    tmp_path: Path,
) -> None:
    from app.diagnostics import capture_failure

    tab = FakeTab(
        html=(
            "<html><body>"
            "Token: MINIMAX_API_KEY=sk-real-secret-99 "
            "Cookie: dbcl2=session-cookie-99"
            "</body></html>"
        )
    )
    artifacts_dir = tmp_path / "artifacts"

    capture_failure(tab, artifacts_dir, "task-redact")

    # Screenshot is called once with full_page=True.
    assert len(tab.screenshot_calls) == 1
    call = tab.screenshot_calls[0]
    assert call["name"] == "task-redact.png"
    assert call["full_page"] is True
    assert Path(call["path"]) == artifacts_dir

    # HTML on disk contains no secrets and is within the size cap.
    html_file = artifacts_dir / "task-redact.html"
    assert html_file.exists()
    content = html_file.read_text(encoding="utf-8")
    assert "sk-real-secret-99" not in content
    assert "session-cookie-99" not in content
    assert len(content) <= 200_000


def test_capture_failure_truncates_html_to_200000_chars(tmp_path: Path) -> None:
    from app.diagnostics import capture_failure

    long_html = "x" * 250_000
    tab = FakeTab(html=long_html)
    artifacts_dir = tmp_path / "artifacts"

    capture_failure(tab, artifacts_dir, "task-trunc")

    html_file = artifacts_dir / "task-trunc.html"
    content = html_file.read_text(encoding="utf-8")
    assert len(content) == 200_000


# --------------------------------------------------------------------------- #
# Runner + diagnostics: capture only on failure statuses
# --------------------------------------------------------------------------- #


def test_success_status_does_not_trigger_screenshot_or_html_capture(
    tmp_path: Path,
) -> None:
    tab = FakeTab(html="anything")
    success_task = task("a")
    adapter = FakeAdapter(search_results={"a": [candidate("英雄", "2002")]})
    adapter.detail_results["a"] = successful_detail(
        success_task, method=MatchMethod.NONE
    )
    store = FakeStore()
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=tmp_path)

    runner.run([success_task])

    assert tab.screenshot_calls == []
    assert not (tmp_path / "a.html").exists()
    assert not (tmp_path / "a.png").exists()
    assert store.upserts[0].status is Status.SUCCESS


def test_network_error_status_triggers_capture_with_redacted_html(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Avoid the 2/5-second real-time backoff in this test.
    monkeypatch.setattr("app.runner.time.sleep", lambda seconds: None)

    secret_html = "MINIMAX_API_KEY=sk-net-secret-1"
    tab = FakeTab(html=secret_html)
    store = FakeStore()
    adapter = FakeAdapter(search_results={"a": NetworkError("transient")})
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=tmp_path)

    runner.run([task("a")])

    assert len(tab.screenshot_calls) == 1
    html_file = tmp_path / "a.html"
    assert html_file.exists()
    assert "sk-net-secret-1" not in html_file.read_text(encoding="utf-8")
    assert store.upserts[0].status is Status.NETWORK_ERROR


def test_page_changed_status_triggers_capture(tmp_path: Path) -> None:
    tab = FakeTab(html="layout shifted")
    store = FakeStore()
    adapter = FakeAdapter(search_results={"a": PageChangedError("layout shifted")})
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=tmp_path)

    runner.run([task("a")])

    assert len(tab.screenshot_calls) == 1
    assert (tmp_path / "a.html").exists()
    assert store.upserts[0].status is Status.PAGE_CHANGED


def test_blocked_status_triggers_capture(tmp_path: Path) -> None:
    tab = FakeTab(html="captcha")
    store = FakeStore()
    adapter = FakeAdapter(search_results={"a": BlockedError("captcha")})
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=tmp_path)

    runner.run([task("a")])

    assert len(tab.screenshot_calls) == 1
    assert (tmp_path / "a.html").exists()
    assert store.upserts[0].status is Status.BLOCKED


def test_site_protection_challenge_stops_the_batch_after_writing_current_task() -> None:
    store = FakeStore()
    adapter = FakeAdapter(
        search_results={
            "a": SiteProtectionChallenge("proof-of-work challenge pending"),
            "b": [],
        }
    )
    runner = make_runner(adapter, store)

    summary = runner.run([task("a"), task("b")])

    assert summary == RunSummary(processed=1, skipped=0, blocked=True)
    assert [result.task_id for result in store.upserts] == ["a"]
    # The challenge must be surfaced as its own status, never collapsed
    # into BLOCKED or UNEXPECTED_ERROR.
    assert store.upserts[0].status is Status.SITE_PROTECTION_CHALLENGE
    assert "proof-of-work challenge" in (store.upserts[0].error_message or "")
    # Adapter.search must not have been called for "b".
    assert [called[1].task_id for called in adapter.search_calls] == ["a"]


def test_site_protection_challenge_status_triggers_capture(tmp_path: Path) -> None:
    tab = FakeTab(html="challenge pending")
    store = FakeStore()
    adapter = FakeAdapter(
        search_results={"a": SiteProtectionChallenge("proof-of-work challenge pending")}
    )
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=tmp_path)

    runner.run([task("a")])

    assert len(tab.screenshot_calls) == 1
    assert (tmp_path / "a.html").exists()
    assert store.upserts[0].status is Status.SITE_PROTECTION_CHALLENGE


def test_site_protection_challenge_during_fetch_detail_stops_batch() -> None:
    store = FakeStore()
    adapter = FakeAdapter(search_results={"a": [candidate("英雄", "2002")]})
    adapter.detail_results = {
        "a": SiteProtectionChallenge("proof-of-work challenge pending"),
    }
    runner = make_runner(adapter, store)

    summary = runner.run([task("a"), task("b")])

    assert summary == RunSummary(processed=1, skipped=0, blocked=True)
    assert [r.task_id for r in store.upserts] == ["a"]
    # Status must be the challenge-specific one even when the challenge is
    # raised on the detail navigation, not just on the search navigation.
    assert store.upserts[0].status is Status.SITE_PROTECTION_CHALLENGE


def test_unexpected_error_status_triggers_capture(tmp_path: Path) -> None:
    tab = FakeTab(html="boom")
    store = FakeStore()
    adapter = FakeAdapter(
        search_results={"a": ValueError("internal stack details")}
    )
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=tmp_path)

    runner.run([task("a")])

    assert len(tab.screenshot_calls) == 1
    assert (tmp_path / "a.html").exists()
    result = store.upserts[0]
    assert result.status is Status.UNEXPECTED_ERROR
    # Exception message is not written to the workbook; only the type name is.
    assert result.error_message == "ValueError"
    assert "internal stack details" not in result.error_message


def test_runner_without_artifacts_dir_skips_capture_silently() -> None:
    tab = FakeTab(html="secret")
    store = FakeStore()
    adapter = FakeAdapter(search_results={"a": NetworkError("transient")})
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=None)

    summary = runner.run([task("a")])

    assert summary.processed == 1
    assert tab.screenshot_calls == []
    # Business status is still recorded.
    assert store.upserts[0].status is Status.NETWORK_ERROR


# --------------------------------------------------------------------------- #
# Runner: network retry with 2/5-second backoff
# --------------------------------------------------------------------------- #


def test_network_operation_retries_three_times_with_2_and_5_second_sleeps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("app.runner.time.sleep", lambda seconds: sleeps.append(seconds))

    tab = FakeTab()
    store = FakeStore()
    adapter = FakeAdapter(search_results={"a": NetworkError("transient")})
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=tmp_path)

    summary = runner.run([task("a")])

    assert summary.processed == 1
    # 3 attempts on the search call, with the 2/5-second backoff between them.
    assert len(adapter.search_calls) == 3
    assert sleeps == [pytest.approx(2.0), pytest.approx(5.0)]
    assert store.upserts[0].status is Status.NETWORK_ERROR
    assert store.upserts[0].error_message == "transient"


def test_network_operation_stops_after_success_on_second_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("app.runner.time.sleep", lambda seconds: sleeps.append(seconds))

    call_count = {"n": 0}

    def flaky_search(tab: Any, task: Task) -> list[Candidate]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise NetworkError("first attempt fails")
        return []

    tab = FakeTab()
    store = FakeStore()
    adapter = FakeAdapter()
    adapter.search = flaky_search  # type: ignore[method-assign]
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=tmp_path)

    runner.run([task("a")])

    # First attempt fails, second succeeds — no third attempt, no second sleep.
    assert call_count["n"] == 2
    assert sleeps == [pytest.approx(2.0)]
    # Empty result becomes NOT_FOUND, not NETWORK_ERROR.
    assert store.upserts[0].status is Status.NOT_FOUND


# --------------------------------------------------------------------------- #
# Runner: OutputLockedError is re-raised from store.upsert
# --------------------------------------------------------------------------- #


def test_output_locked_error_is_re_raised_from_run(tmp_path: Path) -> None:
    from app.excel_store import OutputLockedError

    tab = FakeTab()

    class LockedStore(FakeStore):
        def upsert(self, result: MovieResult) -> None:
            raise OutputLockedError("Close Excel and retry")

    store = LockedStore()
    adapter = FakeAdapter()
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=tmp_path)

    with pytest.raises(OutputLockedError, match="Close Excel and retry"):
        runner.run([task("a")])


# --------------------------------------------------------------------------- #
# Runner: UNEXPECTED_ERROR with type name only
# --------------------------------------------------------------------------- #


def test_unclassified_exception_writes_unexpected_error_with_type_name_only(
    tmp_path: Path,
) -> None:
    tab = FakeTab()
    store = FakeStore()
    adapter = FakeAdapter(
        search_results={"a": ValueError("stack frames with secrets")}
    )
    runner = make_runner(adapter, store, tab=tab, artifacts_dir=tmp_path)

    summary = runner.run([task("a")])

    assert summary.processed == 1
    result = store.upserts[0]
    assert result.status is Status.UNEXPECTED_ERROR
    assert result.error_message == "ValueError"
    assert "stack frames with secrets" not in result.error_message
