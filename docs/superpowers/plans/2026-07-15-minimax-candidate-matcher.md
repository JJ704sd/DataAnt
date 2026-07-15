# MiniMax Candidate Matcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in MiniMax text matcher that ranks ambiguous movie candidates without controlling the browser or becoming a core runtime dependency.

**Architecture:** A small `CandidateMatcher` protocol lets the runner ask an optional fallback after deterministic rules return no unique match. The MiniMax implementation sends only minimal candidate metadata through the OpenAI-compatible endpoint, validates JSON and confidence locally, and returns `None` on every unsafe or invalid response so the runner writes `REVIEW_REQUIRED`.

**Tech Stack:** Existing core Demo, OpenAI Python SDK as optional extra, MiniMax OpenAI-compatible API, pytest mocks, environment variables.

---

## Prerequisites and boundaries

- Complete and verify `2026-07-15-browser-bot-core-demo.md` first.
- Do not pass complete HTML, cookies, storage state, API keys, user data, reviews, or page screenshots to MiniMax.
- LLM output is advisory. It never calls Playwright and never writes directly to Excel.
- The accepted model is configured with `MINIMAX_MODEL`; do not assume the model name remains available forever. Confirm through MiniMax's official models endpoint before a real integration run.
- Official references: `https://platform.minimax.io/docs/api-reference/text-openai-api` and `https://platform.minimax.io/docs/faq/about-apis`.

## First-principles derivation

The only unresolved core uncertainty is: “several observed candidates remain plausible after exact title and year rules.” From that fact:

- LLM input is limited to the evidence needed for that decision: query, optional year, and at most five candidate titles/years/types.
- LLM output is only a proposed candidate index plus confidence and reason; it cannot navigate, extract fields, persist rows, or override a block.
- Local validation is authoritative. Invalid JSON, an unknown index, confidence below the threshold, weak title relation, timeout, missing Key, or SDK failure all produce the same safe outcome: no decision.
- Because the core Demo already has `REVIEW_REQUIRED`, LLM availability is never a liveness dependency.
- A single call is the cost ceiling per ambiguous task. Repeating a probabilistic call does not create new evidence.
- The Key provides capability, not justification. MiniMax is enabled only when measured ambiguous cases warrant it.

### Task 1: Add optional dependency and validated settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Create: `app/llm_matcher.py`
- Create: `tests/test_llm_matcher.py`

- [ ] **Step 1: Add a failing settings test**

Create `tests/test_llm_matcher.py`:

```python
import pytest

from app.llm_matcher import LlmConfigurationError, MiniMaxSettings


def test_settings_require_key_only_when_llm_is_enabled(monkeypatch) -> None:
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with pytest.raises(LlmConfigurationError):
        MiniMaxSettings.from_env()


def test_settings_use_official_default_base_url(monkeypatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_MODEL", "test-model")
    settings = MiniMaxSettings.from_env()
    assert settings.base_url == "https://api.minimax.io/v1"
    assert settings.model == "test-model"
```

- [ ] **Step 2: Run the test to verify failure**

```powershell
python -m pytest tests/test_llm_matcher.py -v
```

Expected: FAIL because `app.llm_matcher` does not exist.

- [ ] **Step 3: Add optional dependency and environment template**

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = ["pytest>=8,<9", "pytest-cov>=5,<7"]
llm = ["openai>=1,<3"]
```

Replace `.env.example` with names only:

```dotenv
MINIMAX_API_KEY=
MINIMAX_BASE_URL=https://api.minimax.io/v1
MINIMAX_MODEL=MiniMax-M2.7
```

- [ ] **Step 4: Implement settings without importing OpenAI at module import time**

Create `app/llm_matcher.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


class LlmConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MiniMaxSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 10.0
    min_confidence: float = 0.85

    @classmethod
    def from_env(cls) -> "MiniMaxSettings":
        key = os.environ.get("MINIMAX_API_KEY", "").strip()
        model = os.environ.get("MINIMAX_MODEL", "").strip()
        if not key:
            raise LlmConfigurationError("MINIMAX_API_KEY is required when --llm-match is enabled")
        if not model:
            raise LlmConfigurationError("MINIMAX_MODEL is required when --llm-match is enabled")
        return cls(key, os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/v1").rstrip("/"), model)
```

Run:

```powershell
python -m pytest tests/test_llm_matcher.py -v
```

Expected: 2 tests PASS without installing the `llm` extra.

- [ ] **Step 5: Commit settings and optional packaging**

```powershell
git add pyproject.toml .env.example app/llm_matcher.py tests/test_llm_matcher.py
git commit -m "feat: add optional MiniMax settings"
```

### Task 2: Implement minimal-payload request and strict response validation

**Files:**
- Modify: `app/llm_matcher.py`
- Modify: `tests/test_llm_matcher.py`

- [ ] **Step 1: Write failing tests for valid, low-confidence, and invalid responses**

Append to `tests/test_llm_matcher.py`:

```python
from types import SimpleNamespace

from app.llm_matcher import MiniMaxMatcher
from app.models import Candidate, MatchMethod, Task


class FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.last_messages = None

    def create(self, **kwargs):
        self.last_messages = kwargs["messages"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


def client_with(content):
    completions = FakeCompletions(content)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def candidates():
    return [
        Candidate("英雄", "2002", "电影", "https://movie.douban.com/subject/1/"),
        Candidate("英雄", "2022", "电影", "https://movie.douban.com/subject/2/"),
    ]


def test_valid_high_confidence_choice_is_returned() -> None:
    client, calls = client_with('{"chosen_index":0,"confidence":0.91,"reason":"year"}')
    matcher = MiniMaxMatcher(MiniMaxSettings("key", "https://api.minimax.io/v1", "model"), client)
    decision = matcher.choose(Task("a", "英雄", "2002"), candidates())
    assert decision is not None
    assert decision.method == MatchMethod.LLM
    assert decision.candidate_index == 0
    assert "Cookie" not in str(calls.last_messages)


@pytest.mark.parametrize("content", [
    '{"chosen_index":0,"confidence":0.5,"reason":"weak"}',
    '{"chosen_index":99,"confidence":0.99,"reason":"bad index"}',
    'not json',
])
def test_unsafe_response_returns_none(content: str) -> None:
    client, _ = client_with(content)
    matcher = MiniMaxMatcher(MiniMaxSettings("key", "https://api.minimax.io/v1", "model"), client)
    assert matcher.choose(Task("a", "英雄", None), candidates()) is None
```

- [ ] **Step 2: Run tests to verify failure**

```powershell
python -m pytest tests/test_llm_matcher.py -v
```

Expected: FAIL because `MiniMaxMatcher` does not exist.

- [ ] **Step 3: Implement prompt construction and local validation**

Append to `app/llm_matcher.py`:

```python
import json

from app.matcher import normalize_title
from app.models import Candidate, MatchDecision, MatchMethod, Task


class MiniMaxMatcher:
    def __init__(self, settings: MiniMaxSettings, client=None) -> None:
        self.settings = settings
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise LlmConfigurationError('Install the optional dependency with pip install -e ".[llm]"') from exc
            client = OpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=settings.timeout_seconds)
        self.client = client

    def choose(self, task: Task, candidates: list[Candidate]) -> MatchDecision | None:
        payload = {
            "query": task.query,
            "query_year": task.query_year,
            "candidates": [
                {"index": i, "title": item.title, "year": item.year, "kind": item.kind}
                for i, item in enumerate(candidates[:5])
            ],
        }
        try:
            response = self.client.chat.completions.create(
                model=self.settings.model,
                temperature=0.1,
                max_completion_tokens=200,
                messages=[
                    {"role": "system", "content": "Return only JSON with chosen_index, confidence, and reason. Do not invent candidates."},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            )
            data = json.loads(response.choices[0].message.content)
            index = int(data["chosen_index"])
            confidence = float(data["confidence"])
            if not 0 <= index < min(len(candidates), 5) or confidence < self.settings.min_confidence:
                return None
            query = normalize_title(task.query)
            title = normalize_title(candidates[index].title)
            if query not in title and title not in query:
                return None
            return MatchDecision(MatchMethod.LLM, index, str(data.get("reason", "LLM candidate ranking"))[:200])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, TimeoutError):
            return None
```

- [ ] **Step 4: Run unit tests without a real API call**

```powershell
python -m pytest tests/test_llm_matcher.py -v
python -m pytest -q
```

Expected: all matcher tests PASS; no network request occurs.

- [ ] **Step 5: Commit the matcher**

```powershell
git add app/llm_matcher.py tests/test_llm_matcher.py
git commit -m "feat: add validated MiniMax candidate ranking"
```

### Task 3: Integrate the optional fallback into Runner and CLI

**Files:**
- Modify: `app/runner.py`
- Modify: `app/main.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write a failing runner fallback test**

Append to `tests/test_runner.py`:

```python
from app.models import MatchDecision, MatchMethod


class ChoosingFallback:
    def choose(self, task, candidates):
        return MatchDecision(MatchMethod.LLM, 1, "selected by test fallback")


def test_runner_uses_optional_fallback_only_after_rule_ambiguity() -> None:
    class Ambiguous(FakeAdapter):
        def search(self, page, task):
            return [
                Candidate(task.query, "2002", "电影", "https://movie.douban.com/subject/1/"),
                Candidate(task.query, "2022", "电影", "https://movie.douban.com/subject/2/"),
            ]
    store = FakeStore()
    Runner(Ambiguous(), store, object(), 0, fallback_matcher=ChoosingFallback()).run([Task("a", "英雄", None)])
    assert store.results[0].match_method == MatchMethod.LLM
    assert store.results[0].detail_url.endswith("/2/")
```

- [ ] **Step 2: Run test to verify failure**

```powershell
python -m pytest tests/test_runner.py::test_runner_uses_optional_fallback_only_after_rule_ambiguity -v
```

Expected: FAIL because `Runner` does not accept `fallback_matcher`.

- [ ] **Step 3: Add fallback without changing deterministic priority**

Add `fallback_matcher=None` to `Runner.__init__`. Immediately after `choose_match`, add:

```python
if decision.candidate_index is None and self.fallback_matcher is not None:
    fallback = self.fallback_matcher.choose(task, candidates)
    if fallback is not None:
        decision = fallback
```

Keep the existing `REVIEW_REQUIRED` branch when the fallback returns `None` or throws. Catch fallback exceptions, log a redacted warning, and continue to `REVIEW_REQUIRED`; do not mark a batch-level failure.

- [ ] **Step 4: Add `--llm-match` wiring and verify core mode does not import OpenAI**

Add to `build_parser()`:

```python
run.add_argument("--llm-match", action="store_true")
```

In `execute()`, create a fallback only when enabled:

```python
fallback = None
if args.llm_match:
    from app.llm_matcher import MiniMaxMatcher, MiniMaxSettings
    fallback = MiniMaxMatcher(MiniMaxSettings.from_env())
```

Pass `fallback_matcher=fallback` to `Runner`.

Run:

```powershell
python -m pytest tests/test_runner.py tests/test_main.py -v
python -c "import sys; import app.main; assert 'openai' not in sys.modules; print('core import is LLM-free')"
```

Expected: tests PASS and the command prints `core import is LLM-free`.

- [ ] **Step 5: Commit integration**

```powershell
git add app/runner.py app/main.py tests/test_runner.py tests/test_main.py
git commit -m "feat: make MiniMax matching opt in"
```

### Task 4: Document, mock-verify, and perform one controlled API check

**Files:**
- Modify: `README.md`
- Modify: `tests/test_llm_matcher.py`

- [ ] **Step 1: Document local-only Key setup and data boundary**

Add to README:

```markdown
## Optional MiniMax candidate matching

Install with `python -m pip install -e ".[dev,llm]"`. Set `MINIMAX_API_KEY`,
`MINIMAX_BASE_URL`, and `MINIMAX_MODEL` in the current process environment. Never
place a real Key in `.env.example`, source control, Excel, logs, screenshots, or traces.

The matcher sends only query text, optional year, and up to five candidate titles,
years, and types. It does not send page HTML, cookies, storage state, or user data.
Any timeout, invalid JSON, out-of-range index, confidence below 0.85, or weak title
relationship becomes REVIEW_REQUIRED.
```

- [ ] **Step 2: Add an exact fail-closed exception test and implementation**

Append to `tests/test_llm_matcher.py`:

```python
class RaisingCompletions:
    def create(self, **kwargs):
        raise RuntimeError("simulated SDK failure with no request metadata")


def test_sdk_failure_returns_no_decision() -> None:
    client = SimpleNamespace(chat=SimpleNamespace(completions=RaisingCompletions()))
    matcher = MiniMaxMatcher(MiniMaxSettings("key", "https://api.minimax.io/v1", "model"), client)
    assert matcher.choose(Task("a", "英雄", None), candidates()) is None
```

At the API boundary in `MiniMaxMatcher.choose`, replace the narrow final exception tuple with a fail-closed boundary:

```python
        except Exception:
            return None
```

The method must not log the exception object because SDK exceptions can contain request metadata. Runner logs only that fallback returned no decision and writes `REVIEW_REQUIRED`.

Run:

```powershell
python -m pytest tests/test_llm_matcher.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Verify optional package health and secret scan**

```powershell
python -m pip install -e ".[dev,llm]"
python -m pip check
python -m pytest -q
$matches = git grep -n -I -E "(sk-[A-Za-z0-9_-]{20,}|MINIMAX_API_KEY=.+)" -- . ':!*.example'
if ($LASTEXITCODE -eq 0) { $matches; throw "Possible secret found" }
```

Expected: no broken requirements, 0 test failures, and no real secret match.

- [ ] **Step 4: Perform one explicitly approved MiniMax call**

Set the Key only in the current PowerShell process and run a one-query ambiguous fixture/integration command. Before calling, query `GET https://api.minimax.io/v1/models` or use the official SDK endpoint to verify `MINIMAX_MODEL` exists. Do not print the Key or environment.

Expected: one valid response is locally validated, or the item becomes `REVIEW_REQUIRED`; either outcome leaves the core process functional. Record model, timestamp, latency, chosen index, and validation outcome, but not prompt contents or credentials.

- [ ] **Step 5: Commit documentation and final tests**

```powershell
git add README.md tests/test_llm_matcher.py app/llm_matcher.py
git commit -m "docs: add safe MiniMax matcher runbook"
```

Final verification:

```powershell
python -m pytest --cov=app --cov-report=term-missing -v
python -m pip check
python -c "import sys; import app.main; assert 'openai' not in sys.modules"
```

Expected: 0 failures, no broken requirements, and core import remains independent of the OpenAI SDK.
