# Core 03：确定性候选匹配执行 Spec

## 操作提示词（可直接复制）

```text
你是本仓库的实现代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。

只读取本 spec：D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\core-03-deterministic-matcher.md，以及本 spec 明确列出的必要现有代码 app/models.py。不得读取总计划 docs/superpowers/plans/2026-07-15-browser-bot-core-demo.md。

严格按本 spec 的 TDD 顺序执行：先写测试并验证 RED，再写最小实现，运行目标测试和全套测试，最后提交。只允许创建或修改 app/matcher.py 与 tests/test_matcher.py；不得改动任何其他文件。不得安装依赖。所有 PowerShell 命令先 Set-Location 到绝对 worktree。不得发起任何真实豆瓣或其他外网流量。

验证成功后只提交允许文件，commit message 必须为：feat: add deterministic movie matching

完成时回报：
DONE
- changed: <逐行列出文件>
- red: <命令与预期失败摘要>
- verify: <命令与通过摘要>
- commit: <短 SHA 和 message>

无法完成时回报：
BLOCKED
- step: <阻塞步骤>
- evidence: <命令、错误原文和已检查内容>
- changed: <已经改动的文件；没有则写 none>

不得用猜测绕过失败，不得真实访问豆瓣。
```

## Base / prerequisites

- Repo root：`D:\DataAnt\.worktrees\browser-bot-demo`。
- Core 01–02 已完成；`app/models.py` 已定义下述固定类型。
- Python 3.11 或 3.12、pytest 已在现有 `.venv` 中可用；本任务不安装依赖。
- 本任务是纯函数逻辑，不启动浏览器、不读取 fixture、不访问网络。

## Goal

实现可复现、无副作用的电影候选匹配：标题先做 Unicode NFKC、大小写和空白标准化；唯一同名候选用标题规则，多名同名候选仅在输入年份唯一命中时用年份规则，其余情况明确返回无法确定。

## Files（仅允许本任务）

- Create：`app/matcher.py`
- Create：`tests/test_matcher.py`

不得修改 `app/models.py`、`pyproject.toml` 或任何其他文件。

## Fixed contracts

现有 `app/models.py` 中参与本任务的契约如下；名称、字段顺序和枚举值不可改变：

```python
from dataclasses import dataclass
from enum import StrEnum


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
```

公开接口固定为：

```python
def normalize_title(value: str) -> str: ...
def choose_match(task: Task, candidates: list[Candidate]) -> MatchDecision: ...
```

行为顺序固定为：

1. `normalize_title()` 执行 Unicode NFKC、`casefold()`、去除首尾空白、把任意连续空白合并为一个 ASCII 空格；中文和字母数字保留。
2. 标准化标题完全相等且只有一个候选：`RULE_EXACT`，返回该候选原列表索引。
3. 有多个标准化标题完全相等，且 `task.query_year` 非空并只与其中一个候选年份相等：`RULE_YEAR`。
4. 空候选、无精确标题、同名但无年份、年份无命中或年份仍多重命中：`NONE` 和 `candidate_index=None`。
5. 不按评分、列表位置或模糊相似度猜测；不调用 LLM。

## TDD implementation

- [ ] **Step 1 — RED：创建完整测试**

创建 `tests/test_matcher.py`：

```python
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
```

- [ ] **Step 2 — verify RED**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest tests/test_matcher.py -v
```

预期：命令非零退出，collection 因 `app.matcher` 不存在而失败。若测试意外通过，先确认工作区中是否已有同名实现；不得跳过 RED 证据。

- [ ] **Step 3 — GREEN：创建最小实现**

创建 `app/matcher.py`：

```python
from __future__ import annotations

import re
import unicodedata

from app.models import Candidate, MatchDecision, MatchMethod, Task


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"\s+", " ", normalized)


def choose_match(task: Task, candidates: list[Candidate]) -> MatchDecision:
    query = normalize_title(task.query)
    exact = [
        index
        for index, item in enumerate(candidates)
        if normalize_title(item.title) == query
    ]
    if len(exact) == 1:
        return MatchDecision(MatchMethod.RULE_EXACT, exact[0], "unique normalized title")
    if len(exact) > 1 and task.query_year:
        year_matches = [
            index for index in exact if candidates[index].year == task.query_year
        ]
        if len(year_matches) == 1:
            return MatchDecision(MatchMethod.RULE_YEAR, year_matches[0], "title and year")
    return MatchDecision(MatchMethod.NONE, None, "no unique deterministic match")
```

- [ ] **Step 4 — focused verify**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest tests/test_matcher.py -v
```

预期：全部 matcher tests PASS，退出码 0。

- [ ] **Step 5 — full verify**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest -q
```

预期：完整测试套件退出码 0；本任务不得为了修复无关失败而修改允许列表之外的文件。

- [ ] **Step 6 — commit**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
git status --short
git add -- app/matcher.py tests/test_matcher.py
git diff --cached --check
git commit -m "feat: add deterministic movie matching"
```

提交前确认暂存区只有上述两个文件。

## Acceptance checklist

- [ ] 仅 `app/matcher.py` 与 `tests/test_matcher.py` 被创建或修改。
- [ ] NFKC、大小写、中英文、首尾空白和连续空白均有测试。
- [ ] 唯一精确匹配返回 `RULE_EXACT` 和原候选索引。
- [ ] 同名候选仅由唯一年份命中返回 `RULE_YEAR`。
- [ ] 所有歧义/无匹配情况返回 `NONE`，没有默认第一项或评分猜测。
- [ ] focused tests 与 full suite 均退出 0。
- [ ] 没有浏览器启动、真实豆瓣流量或外网访问。
- [ ] commit message 精确为 `feat: add deterministic movie matching`。
