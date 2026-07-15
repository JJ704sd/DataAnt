# MiniMax 02：最小请求与严格本地验证

## 操作提示词（可直接复制）

```text
你是本任务的实现工程师。唯一工作目录是绝对路径 D:\DataAnt\.worktrees\browser-bot-demo；所有命令都必须以该目录为工作目录。唯一任务说明是 D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\minimax-02-client-validation.md。只读取本 spec 和完成本任务必需的现有代码/测试；不得读取 docs/superpowers/plans/2026-07-15-minimax-candidate-matcher.md 或其他总计划。

严格执行 RED → RED verify → GREEN → focused verify → full verify → commit。只修改本 spec 的精确文件。所有测试使用 fake client；不得调用 MiniMax、DrissionPage 或写 Excel；不得打开浏览器；不得引入 Playwright、trace、storage_state。绝不打印或记录 Key、完整 HTML、cookies、browser-profile 或请求异常对象。

完成仅回复：
DONE
- changed: <文件列表>
- red: <命令及预期失败摘要>
- green: <命令及通过摘要>
- full_verify: <命令及通过摘要>
- commit: <hash> feat: add validated MiniMax candidate ranking
或：
BLOCKED
- gate: <未满足门禁>
- evidence: <命令与输出摘要>
- changed: <如有>
```

## Base / 前置条件

- 根目录：`D:\DataAnt\.worktrees\browser-bot-demo`，开始时 `git status --short` 无输出。
- MiniMax 01 已完成；`app/llm_matcher.py` 精确提供 `LlmConfigurationError` 与 `MiniMaxSettings`，配置默认值为 base URL `https://api.minimax.io/v1`、超时 `10.0`、最低置信度 `0.85`。
- 核心代码提供下列不可更名接口：

```python
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

class MatchMethod(StrEnum):
    RULE_EXACT = "RULE_EXACT"
    RULE_YEAR = "RULE_YEAR"
    LLM = "LLM"
    NONE = "NONE"

@dataclass(frozen=True, slots=True)
class MatchDecision:
    method: MatchMethod
    candidate_index: int | None
    reason: str

def normalize_title(value: str) -> str: ...
```

- LLM 只对确定性规则无法唯一决定的歧义候选提供建议。本类不得导航、调用 DrissionPage、抓 HTML、读取 cookies/browser-profile 或写 Excel。

## Goal

实现 `MiniMaxMatcher.choose(task, candidates)`：只发送查询、可选年份以及最多 5 个候选的标题/年份/类型；一次请求、10 秒超时、SDK 自动重试关闭。模型响应必须经过严格本地 JSON 契约、index bounds、`confidence >= 0.85` 与标题关系验证；非法 JSON、超时或任何验证失败均返回 `None`，由上层降级为 `REVIEW_REQUIRED`。

## 精确文件边界

- Modify: `app/llm_matcher.py`
- Modify: `tests/test_llm_matcher.py`
- 不得修改依赖、Runner、CLI、README、浏览器或 Excel 文件。

## 请求与响应契约

请求 payload 必须恰好是：

```json
{
  "query": "用户查询文本",
  "query_year": "可为 null 的四位年份",
  "candidates": [
    {"index": 0, "title": "候选标题", "year": "可为 null", "kind": "可为 null"}
  ]
}
```

约束：

- `candidates` 按原顺序截取前 5 个；不发送 `detail_url`、task_id、HTML、评论、评分、用户数据、cookies、Key、浏览器资料。
- `chat.completions.create` 恰好调用一次，参数为模型名、`temperature=0.1`、`max_completion_tokens=200` 和两条 messages。禁止循环或应用级重试。
- 默认客户端只在构造 `MiniMaxMatcher` 且未注入 fake 时延迟导入：`OpenAI(api_key=..., base_url=..., timeout=10.0, max_retries=0)`。
- 响应必须是一个 JSON object，且 `chosen_index` 必须是 JSON integer（`bool`、字符串、浮点均非法），`confidence` 必须是有限 JSON number（`bool` 非法）且 `0.85 <= confidence <= 1.0`，`reason` 必须是非空 JSON string。
- `0 <= chosen_index < min(len(candidates), 5)`；越界返回 `None`。
- 规范化 query 与被选 title 必须满足任一包含关系；否则返回 `None`。
- 成功返回 `MatchDecision(MatchMethod.LLM, chosen_index, reason[:200])`。
- 空候选直接返回 `None`，且不调用 client。
- JSON/结构/类型/bounds/置信度/标题关系/`TimeoutError` 失败全部返回 `None`，不记录异常或 payload。Task 04 会把任意 SDK 异常边界进一步锁死。

## 严格 TDD 实施步骤

### 1. RED：追加测试

向 `tests/test_llm_matcher.py` 追加以下完整代码：

```python
import json
from types import SimpleNamespace

from app.llm_matcher import MiniMaxMatcher
from app.models import Candidate, MatchMethod, Task


class FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.content, BaseException):
            raise self.content
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def client_with(content):
    completions = FakeCompletions(content)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def candidates(count=2):
    values = [
        Candidate("英雄", "2002", "电影", "https://movie.douban.com/subject/1/"),
        Candidate("英雄", "2022", "电影", "https://movie.douban.com/subject/2/"),
        Candidate("英雄 三", "2023", None, "https://movie.douban.com/subject/3/"),
        Candidate("英雄 四", "2024", "电影", "https://movie.douban.com/subject/4/"),
        Candidate("英雄 五", "2025", "电影", "https://movie.douban.com/subject/5/"),
        Candidate("英雄 六", "2026", "电影", "https://movie.douban.com/subject/6/"),
    ]
    return values[:count]


def matcher_with(content):
    client, calls = client_with(content)
    settings = MiniMaxSettings("test-key", "https://api.minimax.io/v1", "test-model")
    return MiniMaxMatcher(settings, client), calls


def test_valid_high_confidence_choice_is_returned_with_minimal_payload() -> None:
    matcher, calls = matcher_with(
        '{"chosen_index":0,"confidence":0.91,"reason":"year evidence"}'
    )
    decision = matcher.choose(Task("task-secret", "英雄", "2002"), candidates(6))
    assert decision == MatchDecision(MatchMethod.LLM, 0, "year evidence")
    assert len(calls.calls) == 1
    request = calls.calls[0]
    assert request["model"] == "test-model"
    assert request["temperature"] == 0.1
    assert request["max_completion_tokens"] == 200
    payload = json.loads(request["messages"][1]["content"])
    assert set(payload) == {"query", "query_year", "candidates"}
    assert len(payload["candidates"]) == 5
    assert set(payload["candidates"][0]) == {"index", "title", "year", "kind"}
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("task-secret", "detail_url", "Cookie", "browser-profile", "MINIMAX_API_KEY"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "content",
    [
        '{"chosen_index":0,"confidence":0.849,"reason":"low"}',
        '{"chosen_index":5,"confidence":0.99,"reason":"outside sent candidates"}',
        '{"chosen_index":99,"confidence":0.99,"reason":"bad index"}',
        '{"chosen_index":"0","confidence":0.99,"reason":"wrong type"}',
        '{"chosen_index":true,"confidence":0.99,"reason":"bool is not int"}',
        '{"chosen_index":0,"confidence":true,"reason":"bool is not number"}',
        '{"chosen_index":0,"confidence":1.1,"reason":"invalid range"}',
        '{"chosen_index":0,"confidence":0.99,"reason":""}',
        '{"chosen_index":0,"confidence":0.99}',
        "[]",
        "not json",
    ],
)
def test_invalid_response_returns_none(content: str) -> None:
    matcher, _ = matcher_with(content)
    assert matcher.choose(Task("a", "英雄", None), candidates(6)) is None


def test_unrelated_title_returns_none() -> None:
    matcher, _ = matcher_with(
        '{"chosen_index":0,"confidence":0.99,"reason":"invented relation"}'
    )
    unrelated = [Candidate("无间道", "2002", "电影", "https://example.invalid/1")]
    assert matcher.choose(Task("a", "英雄", None), unrelated) is None


def test_timeout_returns_none_without_retry() -> None:
    matcher, calls = matcher_with(TimeoutError("simulated timeout"))
    assert matcher.choose(Task("a", "英雄", None), candidates()) is None
    assert len(calls.calls) == 1


def test_empty_candidates_do_not_call_client() -> None:
    matcher, calls = matcher_with(
        '{"chosen_index":0,"confidence":0.99,"reason":"impossible"}'
    )
    assert matcher.choose(Task("a", "英雄", None), []) is None
    assert calls.calls == []
```

同时把 import 区补全为从 `app.llm_matcher` 导入 `MiniMaxMatcher, MiniMaxSettings`，并从 `app.models` 导入 `Candidate, MatchDecision, MatchMethod, Task`；不得保留重复 import。

### 2. RED verify

```powershell
python -m pytest tests/test_llm_matcher.py -v
```

预期：因 `MiniMaxMatcher` 尚不存在而失败。

### 3. GREEN：实现 matcher

保留 Task 01 的设置代码，在 `app/llm_matcher.py` 增加 `json`、`math` 和模型/规范化 imports，并追加：

```python
import json
import math

from app.matcher import normalize_title
from app.models import Candidate, MatchDecision, MatchMethod, Task


class MiniMaxMatcher:
    def __init__(self, settings: MiniMaxSettings, client=None) -> None:
        self.settings = settings
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise LlmConfigurationError(
                    'Install the optional dependency with pip install -e ".[llm]"'
                ) from exc
            client = OpenAI(
                api_key=settings.api_key,
                base_url=settings.base_url,
                timeout=settings.timeout_seconds,
                max_retries=0,
            )
        self.client = client

    def choose(
        self, task: Task, candidates: list[Candidate]
    ) -> MatchDecision | None:
        offered = candidates[:5]
        if not offered:
            return None
        payload = {
            "query": task.query,
            "query_year": task.query_year,
            "candidates": [
                {
                    "index": index,
                    "title": item.title,
                    "year": item.year,
                    "kind": item.kind,
                }
                for index, item in enumerate(offered)
            ],
        }
        try:
            response = self.client.chat.completions.create(
                model=self.settings.model,
                temperature=0.1,
                max_completion_tokens=200,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Return only one JSON object with chosen_index, confidence, "
                            "and reason. Choose only an offered index; do not invent evidence."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
            )
            data = json.loads(response.choices[0].message.content)
            if not isinstance(data, dict):
                return None
            index = data.get("chosen_index")
            confidence = data.get("confidence")
            reason = data.get("reason")
            if isinstance(index, bool) or not isinstance(index, int):
                return None
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                return None
            if not math.isfinite(float(confidence)):
                return None
            if not isinstance(reason, str) or not reason.strip():
                return None
            if not 0 <= index < len(offered):
                return None
            if not self.settings.min_confidence <= float(confidence) <= 1.0:
                return None
            query = normalize_title(task.query)
            title = normalize_title(offered[index].title)
            if query not in title and title not in query:
                return None
            return MatchDecision(MatchMethod.LLM, index, reason.strip()[:200])
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, TimeoutError):
            return None
```

不得记录异常对象、messages 或 payload。不得添加 retry loop。

### 4. Focused verify

```powershell
python -m pytest tests/test_llm_matcher.py -v
```

预期：全部通过；fake 的调用计数证明每次最多一次且没有网络请求。

### 5. Full verify

```powershell
python -m pytest -q
python -c "import sys; import app.main; assert 'openai' not in sys.modules; print('core import is LLM-free')"
git diff --check
git diff --name-only
```

预期：0 failures；打印 `core import is LLM-free`；只修改两个精确文件。

### 6. Commit

```powershell
git add app/llm_matcher.py tests/test_llm_matcher.py
git commit -m "feat: add validated MiniMax candidate ranking"
```

## Acceptance checklist

- [ ] payload 只有 query/query_year/最多 5 个候选的 index/title/year/kind。
- [ ] 不发送 URL、Key、HTML、cookies、browser-profile 或用户数据。
- [ ] 10 秒、`max_retries=0`，每次 `choose` 最多一请求。
- [ ] `chosen_index` 严格 JSON integer 且 bounds 正确。
- [ ] `confidence` 有限且 `>= 0.85`、`<= 1.0`。
- [ ] 非法 JSON、错误类型、越界、低置信度、弱标题关系、超时都返回 `None`。
- [ ] 成功只返回建议性 `MatchDecision`；不调用 DrissionPage、不写 Excel。
- [ ] 没有 Playwright、trace、storage_state 残留。
- [ ] focused/full verify 通过并提交指定 message。
