# MiniMax 04：安全文档、fail-closed 与受控 API 检查

## 操作提示词（可直接复制）

```text
你是本任务的实现工程师。唯一工作目录是绝对路径 D:\DataAnt\.worktrees\browser-bot-demo；所有命令都必须以该目录为工作目录。唯一任务说明是 D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\minimax-04-docs-controlled-check.md。只读取本 spec 和完成本任务必需的现有代码/测试；不得读取 docs/superpowers/plans/2026-07-15-minimax-candidate-matcher.md 或其他总计划。

严格执行文档 RED 门禁 → mock RED → mock GREEN → package/full verify → 受控真实 API 门禁 → commit。只修改“精确文件边界”的 tracked 文件。绝不请求用户在聊天、命令行参数、文件或日志中提供 Key；只检查用户本机当前进程是否已设置 MINIMAX_API_KEY。无 Key 时只跑 mock，创建不含 Key 的 skip 记录并跳过真实 API；不得把缺 Key 当失败。即使有 Key，也必须先取得用户对计费和数据条款的明确确认，并验证模型存在；任一门禁不满足都不得调用 MiniMax。真实 matcher 请求最多一次、10 秒、无自动重试。

不得调用 DrissionPage、不得打开/自动化浏览器、不得写 Excel；不得引入 Playwright、trace、storage_state。不得打印/记录 Key、Authorization、payload/prompt、完整 HTML、cookies、browser-profile 或 SDK 异常对象。

完成仅回复：
DONE
- changed: <tracked 文件列表>
- mock_verify: <命令及通过摘要>
- api_check: <SKIPPED no local key | SKIPPED gate not approved | PASS/REVIEW_REQUIRED，模型/时间/延迟/索引；绝无 Key>
- full_verify: <命令及通过摘要>
- commit: <hash> docs: add safe MiniMax matcher runbook
或：
BLOCKED
- gate: <非 Key 缺失类的阻塞门禁>
- evidence: <不含秘密的摘要>
- changed: <如有>
```

## Base / 前置条件

- 根目录 `D:\DataAnt\.worktrees\browser-bot-demo`；开始时 `git status --short` 无输出。
- MiniMax 01–03 已提交并全绿。`MiniMaxMatcher` 已使用最小 payload、最多 5 候选、10 秒 timeout、`max_retries=0`、一次调用，严格验证 `chosen_index` bounds 与 `confidence >= 0.85`；Runner 只在规则歧义时使用并把 `None` 降级为 `REVIEW_REQUIRED`。
- 本任务不以真实 API 成功作为核心正确性的前提。mock 是必跑门禁；真实 API 是获得授权后的一次受控检查。
- 用户必须在自己本机的当前 PowerShell 进程预先设置 Key。工程师不得请求、读取回显、复制、持久化或记录 Key。

## Goal

补齐安全 runbook；用测试把任意 SDK 异常 fail-closed 为无决策；验证 optional package、全套测试和秘密扫描。只有本机已有 Key且用户明确确认计费与 MiniMax 数据条款后，才验证模型列表并进行恰好一次歧义匹配请求；否则只运行 mock 并记录 `SKIPPED`。

## 精确文件边界

Tracked files：

- Modify: `README.md`
- Modify: `tests/test_llm_matcher.py`
- Modify: `app/llm_matcher.py`

Runtime evidence（Create/overwrite，禁止 `git add`）：

- `artifacts/minimax-api-check.md`

不得修改其他代码、浏览器、Excel 或配置文件。

## 文档与 fail-closed 契约

README 必须明确：

- 安装：`python -m pip install -e ".[dev,llm]"`。
- 仅在当前进程设置 `MINIMAX_API_KEY`、`MINIMAX_BASE_URL`、`MINIMAX_MODEL`；绝不把真实 Key 放入 `.env.example`、源码、Excel、日志、截图、HTML snapshot、browser-profile、命令参数或提交。
- LLM 只在确定性规则歧义时 fallback；默认关闭。
- 最小 payload 是 query、可选 year、最多 5 个候选的 title/year/kind；无 URL、HTML、cookies、用户数据或浏览器资料。
- 一次请求、10 秒、无自动重试。
- 非法 JSON、`chosen_index` 越界/错误类型、`confidence < 0.85`、弱标题关系、超时或 SDK 失败都产生 `REVIEW_REQUIRED`。
- LLM 不调用 DrissionPage、不写 Excel。
- 真实检查会计费并向 MiniMax 发送上述最小文本；必须先由用户确认适用的数据处理/保留/跨境/组织政策条款。

代码边界：`MiniMaxMatcher.choose` 最外层 API/解析/验证边界以 `except Exception: return None` fail closed。不得记录异常对象，因为 SDK 异常可能含请求元数据。`KeyboardInterrupt`/`SystemExit` 不属于 `Exception`，不应吞掉。

## 严格门禁与实施步骤

### 1. 文档 RED 门禁

先检查 README 尚未声称或暗示自动启用/无限重试：

```powershell
Select-String -Path README.md -Pattern "Optional MiniMax candidate matching" -SimpleMatch
```

预期：无匹配（exit 0/无输出也可），说明新章节尚未存在。若已存在，逐条对照本 spec 补齐，不得复制 Key。

### 2. 写 README

向 `README.md` 添加以下完整章节：

````markdown
## Optional MiniMax candidate matching

MiniMax is an opt-in fallback only for candidates that deterministic title/year
rules cannot resolve uniquely. Core mode remains functional without an API Key.

Install the optional client with:

```powershell
python -m pip install -e ".[dev,llm]"
```

Set `MINIMAX_API_KEY`, `MINIMAX_BASE_URL`, and `MINIMAX_MODEL` only in the current
process environment, then opt in with `--llm-match`. Never place a real Key in
`.env.example`, source control, Excel, logs, screenshots, HTML snapshots,
browser-profile files, command arguments, or support messages.

The matcher sends only query text, optional year, and up to five candidate titles,
years, and types. It does not send candidate URLs, page HTML, cookies, browser-profile
data, reviews, screenshots, or user data. It makes at most one 10-second request per
ambiguous task and disables automatic retries. It never calls DrissionPage and never
writes Excel.

Local validation is authoritative. Invalid JSON, a non-integer or out-of-range
`chosen_index`, confidence below `0.85`, a weak title relationship, timeout, or SDK
failure produces `REVIEW_REQUIRED` and leaves the core process functional.

Before a controlled real check, the operator must confirm MiniMax billing and the
applicable data-processing, retention, cross-border, and organizational policies.
Without a locally configured Key, run mock verification only and record the real
check as skipped. Never paste or log the Key.
````

### 3. Mock RED：任意 SDK 异常测试

向 `tests/test_llm_matcher.py` 追加：

```python
class RaisingCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        raise RuntimeError("simulated SDK failure with secret request metadata")


def test_sdk_failure_returns_no_decision_without_retry(capsys) -> None:
    completions = RaisingCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    matcher = MiniMaxMatcher(
        MiniMaxSettings("test-key", "https://api.minimax.io/v1", "test-model"),
        client,
    )
    assert matcher.choose(Task("a", "英雄", None), candidates()) is None
    assert completions.calls == 1
    captured = capsys.readouterr()
    assert "secret request metadata" not in captured.out
    assert "secret request metadata" not in captured.err
```

运行：

```powershell
python -m pytest tests/test_llm_matcher.py::test_sdk_failure_returns_no_decision_without_retry -v
```

预期：FAIL，因为 Task 02 的窄异常边界不捕获 `RuntimeError`。

### 4. Mock GREEN：fail closed

在 `MiniMaxMatcher.choose` 的最外层，将窄 `except (...)` 替换为：

```python
        except Exception:
            return None
```

不得增加 log/print/retry。然后运行：

```powershell
python -m pytest tests/test_llm_matcher.py -v
```

预期：全部 PASS，异常调用计数为 1，stdout/stderr 不含模拟秘密。

### 5. Package / full verify 与秘密扫描

```powershell
python -m pip install -e ".[dev,llm]"
python -m pip check
python -m pytest -q
python -c "import sys; import app.main; assert 'openai' not in sys.modules; print('core import is LLM-free')"
$matches = git grep -n -I -E "(sk-[A-Za-z0-9_-]{20,}|MINIMAX_API_KEY=.+|Authorization:[[:space:]]*Bearer|Cookie:)" -- . ':!*.example'
if ($LASTEXITCODE -eq 0) { $matches; throw "Possible secret found" }
git diff --check
```

预期：`pip check` 报 no broken requirements、测试 0 failures、核心 import 不加载 OpenAI、秘密扫描无匹配、diff check 无输出。扫描命令绝不扫描或打印进程环境。

### 6. 创建不含秘密的检查记录

创建/覆盖 `artifacts/minimax-api-check.md`，只允许以下字段：

```markdown
# MiniMax controlled API check
- timestamp:
- billing_confirmed: yes/no
- data_terms_confirmed: yes/no
- local_key_present: yes/no
- model:
- model_verified: yes/no/not-run
- matcher_calls: 0/1
- latency_ms:
- chosen_index:
- validation_outcome: PASS/REVIEW_REQUIRED/SKIPPED
- skip_reason:
```

禁止添加 Key、Key 前后缀、Authorization、endpoint 请求头、payload/prompt、候选文本、HTML、cookies、browser-profile 或异常详情。该文件是 ignored runtime evidence，不得提交。

### 7. 受控真实 API 门禁

严格依次判断：

1. 先完成全部 mock/package/full verify。
2. 只检查本机当前进程是否存在 Key，不输出值：

   ```powershell
   if ([string]::IsNullOrWhiteSpace($env:MINIMAX_API_KEY)) { 'LOCAL_KEY_PRESENT=no' } else { 'LOCAL_KEY_PRESENT=yes' }
   ```

3. 若输出 `no`：记录 `local_key_present: no`、`matcher_calls: 0`、`validation_outcome: SKIPPED`、`skip_reason: no local process Key; mock verification passed`，停止真实检查。不得请求 Key，任务仍可 DONE。
4. 若有 Key，要求用户只回答两项确认，不要求/展示 Key：
   - “我确认这一次模型列表查询和最多一次 matcher 请求可能产生计费。”
   - “我确认最小候选文本发送给 MiniMax 符合适用的数据处理、保留、跨境及组织政策。”
5. 任一未明确确认：记录 0 次与 `SKIPPED`，停止；不得自行假设授权。
6. 确认 `MINIMAX_MODEL` 非空；通过官方 `GET /v1/models` 验证该精确模型 id 存在。HTTP client timeout 10 秒且禁止重试；验证失败就记录 0 次与 `SKIPPED`，不得进行 matcher 请求。
7. 只有全部门禁通过，才运行下一节脚本；matcher 请求恰好最多一次。

### 8. 一次受控 matcher 检查

以下脚本不打印 Key/payload/候选/异常；`MiniMaxMatcher` 自身为 10 秒、`max_retries=0`。模型列表查询不是 matcher 请求，也不得重试。运行前不要开启 shell tracing。

```powershell
@'
import json
import os
import time
import urllib.request
from datetime import datetime

from app.llm_matcher import MiniMaxMatcher, MiniMaxSettings
from app.models import Candidate, Task

settings = MiniMaxSettings.from_env()
request = urllib.request.Request(
    f"{settings.base_url}/models",
    headers={"Authorization": f"Bearer {settings.api_key}"},
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        models = json.load(response)
except Exception:
    raise SystemExit("MODEL_CHECK_FAILED; matcher was not called")

ids = {item.get("id") for item in models.get("data", []) if isinstance(item, dict)}
if settings.model not in ids:
    raise SystemExit("MODEL_NOT_FOUND; matcher was not called")

task = Task("controlled-check", "英雄", None)
candidates = [
    Candidate("英雄", "2002", "电影", "https://movie.douban.com/subject/1/"),
    Candidate("英雄", "2022", "电影", "https://movie.douban.com/subject/2/"),
]
started = time.monotonic()
decision = MiniMaxMatcher(settings).choose(task, candidates)
latency_ms = round((time.monotonic() - started) * 1000)
print({
    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    "model": settings.model,
    "latency_ms": latency_ms,
    "chosen_index": None if decision is None else decision.candidate_index,
    "validation_outcome": "REVIEW_REQUIRED" if decision is None else "PASS",
    "matcher_calls": 1,
})
'@ | python -
```

把允许字段人工抄入 runtime record。输出 `PASS` 或 `REVIEW_REQUIRED` 都是安全的合格结果；禁止因超时/非法响应再次调用。`MODEL_CHECK_FAILED`/`MODEL_NOT_FOUND` 意味着 matcher 0 次并记录 `SKIPPED`。

### 9. 最终验证

```powershell
python -m pytest --cov=app --cov-report=term-missing -v
python -m pip check
python -c "import sys; import app.main; assert 'openai' not in sys.modules"
git diff --check
git status --short
```

预期：0 failures、依赖健康、核心 import 独立。status 只允许三个 tracked 精确文件以及 ignored 的 runtime record（通常不会显示）；若显示其他文件则停止并清理本任务产生的越界内容，不得删除他人内容。

### 10. Commit

```powershell
git add README.md tests/test_llm_matcher.py app/llm_matcher.py
git commit -m "docs: add safe MiniMax matcher runbook"
```

不得 `git add artifacts/minimax-api-check.md`。

## Acceptance checklist

- [ ] README 写明 opt-in、仅歧义 fallback、最多 5 候选、最小 payload。
- [ ] README 写明 10 秒、一次、无自动重试、`confidence >= 0.85`。
- [ ] 非法/越界/低置信度/超时/SDK 异常都安全降级 REVIEW_REQUIRED。
- [ ] broad exception 测试证明一次调用且无异常文本泄漏。
- [ ] 无本机 Key 时只跑 mock、记录 SKIPPED、绝不请求 Key。
- [ ] 有 Key 时已明确确认计费与数据条款并先验证模型；否则 0 matcher calls。
- [ ] 真实 matcher 最多一次；失败不重试。
- [ ] 记录不含 Key、Authorization、payload、HTML、cookies、browser-profile。
- [ ] LLM 不调用 DrissionPage、不写 Excel。
- [ ] 没有 Playwright、trace、storage_state 残留。
- [ ] runtime evidence 未提交；tracked 修改仅三个精确文件。
- [ ] 最终验证通过并提交指定 message。
