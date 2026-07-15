# MiniMax 03：Runner 与 CLI 的可选歧义 fallback

## 操作提示词（可直接复制）

```text
你是本任务的实现工程师。唯一工作目录是绝对路径 D:\DataAnt\.worktrees\browser-bot-demo；所有命令都必须以该目录为工作目录。唯一任务说明是 D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\minimax-03-runner-cli-integration.md。只读取本 spec 和完成本任务必需的现有代码/测试；不得读取 docs/superpowers/plans/2026-07-15-minimax-candidate-matcher.md 或其他总计划。

严格执行 RED → RED verify → GREEN → focused verify → full verify → commit；只改精确文件。测试只用 fake fallback，不调用 MiniMax；不得新增任何 DrissionPage 调用或 Excel 写入，LLM matcher 本身绝不接触二者；不得引入 Playwright、trace、storage_state。不得记录 Key、HTML、cookies、browser-profile、payload 或异常对象。

完成仅回复：
DONE
- changed: <文件列表>
- red: <命令及预期失败摘要>
- green: <命令及通过摘要>
- full_verify: <命令及通过摘要>
- commit: <hash> feat: make MiniMax matching opt in
或：
BLOCKED
- gate: <未满足门禁>
- evidence: <命令与输出摘要>
- changed: <如有>
```

## Base / 前置条件

- 根目录 `D:\DataAnt\.worktrees\browser-bot-demo`；开始时 `git status --short` 无输出。
- MiniMax 01、02 已提交。`MiniMaxMatcher.choose(Task, list[Candidate]) -> MatchDecision | None` 已保证最多 5 候选、最小 payload、10 秒、`max_retries=0`、严格 JSON/index/confidence/title 验证；失败返回 `None`。
- 核心 `choose_match(task, candidates)` 的优先级不可改变：唯一规范化标题为 `RULE_EXACT`；同名且年份唯一为 `RULE_YEAR`；否则返回 `MatchDecision(MatchMethod.NONE, None, ...)`。
- `Runner` 已有 adapter/search/fetch_detail、store/upsert、重试/诊断逻辑。只在确定性结果的 `candidate_index is None` 且候选非空时才允许调用 fallback。
- `Status.REVIEW_REQUIRED`、`MatchMethod.LLM` 已存在。fallback 不可直接调用 DrissionPage 或写 Excel；Runner 原有 adapter/store 行为不属于 LLM 能力，不能扩展。

## Goal

为 Runner 注入一个结构化 `CandidateMatcher` fallback，并为 `run` 子命令增加显式 `--llm-match` 开关。默认核心路径不导入 `app.llm_matcher` 或 `openai`。LLM 仅处理规则歧义；关闭、缺配置、超时、非法响应或异常时都保持/降级 `REVIEW_REQUIRED`，不使整批失败、不自动重试。

## 精确文件边界

- Modify: `app/runner.py`
- Modify: `app/main.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_main.py`
- 不得修改 matcher 实现、依赖、README、站点 adapter、浏览器或 Excel store。

## 接口与精确行为

在 `app/runner.py` 定义协议（不得从 `app.llm_matcher` 导入，避免核心耦合）：

```python
class CandidateMatcher(Protocol):
    def choose(self, task: Task, candidates: list[Candidate]) -> MatchDecision | None: ...
```

`Runner.__init__` 在现有参数末尾增加：

```python
fallback_matcher: CandidateMatcher | None = None
```

并保存为 `self.fallback_matcher`。在原 `decision = choose_match(task, candidates)` 后、原 `REVIEW_REQUIRED` 分支前执行：

```python
if decision.candidate_index is None and self.fallback_matcher is not None:
    try:
        fallback = self.fallback_matcher.choose(task, candidates)
    except Exception:
        self.logger.warning("task_id=%s optional matcher returned no decision", task.task_id)
    else:
        if fallback is not None:
            decision = fallback
```

边界：

- 无候选时直接 `NOT_FOUND`，不调用 fallback。
- 确定性规则已选中时不调用 fallback。
- fallback 返回 `None` 或抛任意异常时沿用原 NONE decision，写 `REVIEW_REQUIRED`。
- 日志只写 task_id 与固定文本；不得写异常对象、Key、HTML、cookies、browser-profile、候选或 prompt。
- fallback 成功后仍由 Runner 按原流程用被选 candidate 调用 adapter 并由 store 持久化；fallback 自身不持有 page/store。
- 不给 fallback 增加 retry；单个歧义任务最多调用一次 `choose`。
- Runner 必须信任的是 matcher 的“有决策/无决策”接口，而不是原始模型文本：matcher 只处理最多 5 个候选的最小 payload，并在非法 JSON、`chosen_index` 类型/bounds 错误、`confidence < 0.85`、弱标题关系或 10 秒超时时返回 `None`；Runner 对所有这些情况统一写 `REVIEW_REQUIRED`。

CLI：

```python
run.add_argument("--llm-match", action="store_true")
```

在 `execute()` 中、构造 Runner 前：

```python
fallback = None
if args.llm_match:
    from app.llm_matcher import MiniMaxMatcher, MiniMaxSettings

    fallback = MiniMaxMatcher(MiniMaxSettings.from_env())
```

然后以关键字 `fallback_matcher=fallback` 传给 Runner。未启用时不读取 `MINIMAX_*`，不导入 `app.llm_matcher`/`openai`。启用但缺 Key/模型时沿用 CLI 的配置错误路径（退出 2），错误不得含变量值。

## 严格 TDD 实施步骤

### 1. RED：Runner 测试

向 `tests/test_runner.py` 追加（复用文件已有 `FakeAdapter`、`FakeStore`，并补充模型 imports）：

```python
from app.models import MatchDecision, MatchMethod


class RecordingFallback:
    def __init__(self, decision=None, error=None):
        self.decision = decision
        self.error = error
        self.calls = []

    def choose(self, task, candidates):
        self.calls.append((task, list(candidates)))
        if self.error is not None:
            raise self.error
        return self.decision


def test_runner_uses_fallback_once_only_after_rule_ambiguity() -> None:
    class Ambiguous(FakeAdapter):
        def search(self, page, task):
            return [
                Candidate(task.query, "2002", "电影", "https://movie.douban.com/subject/1/"),
                Candidate(task.query, "2022", "电影", "https://movie.douban.com/subject/2/"),
            ]

    fallback = RecordingFallback(MatchDecision(MatchMethod.LLM, 1, "selected"))
    store = FakeStore()
    Runner(Ambiguous(), store, object(), 0, fallback_matcher=fallback).run(
        [Task("a", "英雄", None)]
    )
    assert len(fallback.calls) == 1
    assert store.results[0].match_method == MatchMethod.LLM
    assert store.results[0].detail_url.endswith("/2/")


def test_runner_does_not_use_fallback_for_deterministic_match() -> None:
    fallback = RecordingFallback(MatchDecision(MatchMethod.LLM, 0, "unused"))
    store = FakeStore()
    Runner(FakeAdapter(), store, object(), 0, fallback_matcher=fallback).run(
        [Task("a", "英雄", "2002")]
    )
    assert fallback.calls == []
    assert store.results[0].match_method == MatchMethod.RULE_EXACT


def test_runner_fallback_none_degrades_to_review_required() -> None:
    class Ambiguous(FakeAdapter):
        def search(self, page, task):
            return [
                Candidate(task.query, "2002", "电影", "https://movie.douban.com/subject/1/"),
                Candidate(task.query, "2022", "电影", "https://movie.douban.com/subject/2/"),
            ]

    store = FakeStore()
    Runner(Ambiguous(), store, object(), 0, fallback_matcher=RecordingFallback()).run(
        [Task("a", "英雄", None)]
    )
    assert store.results[0].status == Status.REVIEW_REQUIRED


def test_runner_fallback_exception_degrades_without_batch_failure() -> None:
    class Ambiguous(FakeAdapter):
        def search(self, page, task):
            return [
                Candidate(task.query, "2002", "电影", "https://movie.douban.com/subject/1/"),
                Candidate(task.query, "2022", "电影", "https://movie.douban.com/subject/2/"),
            ]

    store = FakeStore()
    summary = Runner(
        Ambiguous(), store, object(), 0,
        fallback_matcher=RecordingFallback(error=TimeoutError("secret metadata")),
    ).run([Task("a", "英雄", None)])
    assert summary.processed == 1
    assert summary.blocked is False
    assert store.results[0].status == Status.REVIEW_REQUIRED
```

若 `FakeAdapter` 的唯一候选行为不同，允许只调整测试夹具使其产生唯一 exact；不得弱化断言。

### 2. RED verify

```powershell
python -m pytest tests/test_runner.py::test_runner_uses_fallback_once_only_after_rule_ambiguity -v
```

预期：失败，原因是 `Runner` 不接受 `fallback_matcher`。

### 3. GREEN：Runner 最小实现

在 `app/runner.py` 从 `typing` 导入 `Protocol`，从 `app.models` 导入 `Candidate`、`MatchDecision`，加入上述协议、构造参数和 fallback 块。必须把 fallback 块放在 `choose_match` 之后且在 `candidate_index is None` 判断之前。不要捕获或改变 adapter/store 原有异常语义。

运行：

```powershell
python -m pytest tests/test_runner.py -v
```

预期：Runner 测试全部通过。

### 4. RED：CLI 测试

向 `tests/test_main.py` 追加；如现有测试已有同名 import，合并 import：

```python
import sys

from app.main import build_parser


def test_llm_match_flag_is_explicit_and_defaults_off() -> None:
    parser = build_parser()
    base = ["run", "--input", "in.csv", "--output", "out.xlsx"]
    assert parser.parse_args(base).llm_match is False
    assert parser.parse_args([*base, "--llm-match"]).llm_match is True


def test_core_main_import_does_not_load_openai() -> None:
    assert "openai" not in sys.modules
```

```powershell
python -m pytest tests/test_main.py::test_llm_match_flag_is_explicit_and_defaults_off -v
```

预期：失败，因为 parser 没有 `llm_match`。

### 5. GREEN：CLI 最小实现

按“接口与精确行为”增加 flag、延迟 import、fallback 构造与 Runner 关键字参数。`LlmConfigurationError` 是 `ValueError`，因此应由现有参数/配置错误分支处理；不得在日志写 Key。

### 6. Focused verify

```powershell
python -m pytest tests/test_runner.py tests/test_main.py -v
python -c "import sys; import app.main; assert 'openai' not in sys.modules; assert 'app.llm_matcher' not in sys.modules; print('core mode is LLM-free')"
```

预期：全部通过并打印 `core mode is LLM-free`。不得执行真实 CLI run，因为它会打开浏览器。

### 7. Full verify

```powershell
python -m pytest -q
git diff --check
git diff --name-only
```

预期：0 failures；只出现四个精确文件；测试未调用 MiniMax、DrissionPage 或写 Excel。

### 8. Commit

```powershell
git add app/runner.py app/main.py tests/test_runner.py tests/test_main.py
git commit -m "feat: make MiniMax matching opt in"
```

## Acceptance checklist

- [ ] LLM 只在候选非空且确定性规则歧义时调用一次。
- [ ] 规则唯一匹配保持优先，no candidates 保持 NOT_FOUND。
- [ ] fallback `None`、非法/超时造成的 `None` 或异常均为 REVIEW_REQUIRED。
- [ ] fallback 异常不造成 batch failure，不记录异常对象。
- [ ] `--llm-match` 默认关闭；核心 import 不加载 llm/OpenAI。
- [ ] 启用才读取 Key/模型；配置错误不泄漏值。
- [ ] LLM 不调用 DrissionPage、不写 Excel、不接收 page/store。
- [ ] 没有 HTML、cookies、browser-profile、Key 泄漏。
- [ ] 没有 Playwright、trace、storage_state 残留。
- [ ] focused/full verify 通过并提交指定 message。
