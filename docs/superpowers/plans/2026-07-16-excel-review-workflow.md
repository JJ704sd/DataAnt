# Excel 候选项人工复核流程实施计划

> **面向智能体执行者：** 必须使用 `superpowers:subagent-driven-development`
>（推荐）或 `superpowers:executing-plans`，逐项实施本计划。所有步骤使用
> 复选框（`- [ ]`）跟踪进度。

**目标：** 增加可审计的双工作表人工复核流程和显式、可恢复的
`apply-review` 命令，同时保持现有 12 列电影结果契约和豆瓣真实联网运行
安全门禁不变。

**架构：** `ExcelStore` 继续作为唯一的工作簿持久化边界，原子更新
`movies` 和 `review_queue`。`review_service.py` 完成整批离线验证并生成
不可变操作；`review_runner.py` 只执行已验证操作，在每项完成后记录检查点，
并返回可供未来批次协调器复用的结构化摘要。

**技术栈：** Python 3.11/3.12、`dataclass`、`StrEnum`、openpyxl、
现有 DrissionPage 适配器、argparse、pytest、pytest-cov。

---

## 前提条件和不变量

- 在仓库根目录 `D:\DataAnt` 工作。
- 从提交 `f800337` 或包含
  `docs/superpowers/specs/2026-07-16-excel-review-workflow-design.md`
  的后续提交开始。
- 保留不相关的未跟踪的 `.planning/` 和 `browser_bot_demo.egg-info/`。
- 实施本计划时不得运行真实豆瓣联网命令。
- 所有离线命令必须保持零网络访问。
- 后续任何真实 `apply-review` 调用都必须包含 `--live-approved`、
  `--max-queries N`（`1 <= N <= 10`）、`--headed`，并设置
  `--min-interval 5` 或更大值。
- 遇到验证码、限流、登录安全检查、`sec.douban.com`、`BLOCKED` 或
  `SITE_PROTECTION_CHALLENGE` 时立即停止。
- 不得增加自动登录、站点保护挑战求解、无人值守重试调度或豆瓣批次自动串联。
- `browser-profile/`、`outputs/`、`artifacts/`、日志、HTML、截图、工作簿、
  Cookie 和会话均不得进入 Git。

## 文件清单

**创建**

- `app/review_service.py`：纯粹的复核行验证和不可变执行
计划构建。
- `app/review_runner.py`：执行经过验证的操作、记录检查点、强制执行
节流，并返回结构化恢复信息。
- `tests/test_review_service.py`：纯粹的决策和 URL 验证。
- `tests/test_review_runner.py`：执行、停止、重试和幂等行为。

**修改**

- `app/models.py`：复核枚举、快照、操作和摘要。
- `app/excel_store.py`：第二个工作表架构，复核快照upsert，待处理
行读取和双表原子更新。
- `app/runner.py`：将不明确的候选快照排入队列。
- `app/main.py`：`apply-review` 解析器、预检、联网门禁和退出映射。
- `scripts/verify_core.py`：继续显式验证 `movies` 工作表。
- `tests/test_models.py`：枚举和不可变模型契约。
- `tests/test_excel_store.py`：两表持久性和原子性。
- `tests/test_runner.py`：复核队列集成。
- `tests/test_main.py`：解析器、预浏览器拒绝和退出代码。
- `tests/test_verify_core.py`：验证器与第二张表的兼容性。
- `tests/test_project_config.py`：离线 CI 和跟踪产物约束。
- `README.md`：复核人员流程和受控命令。

## 固定公共契约

在整个实现过程中一致使用这些名称：

```python
class ReviewDecisionType(StrEnum):
    CANDIDATE = "CANDIDATE"
    MANUAL_URL = "MANUAL_URL"
    SKIP = "SKIP"


class ReviewApplyStatus(StrEnum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    title: str
    year: str | None
    kind: str | None
    detail_url: str


@dataclass(frozen=True, slots=True)
class ReviewAction:
    review_id: str
    task: Task
    decision_type: ReviewDecisionType
    detail_url: str | None
    review_note: str


@dataclass(frozen=True, slots=True)
class ReviewPlan:
    actions: tuple[ReviewAction, ...]
    live_query_count: int


@dataclass(frozen=True, slots=True)
class ReviewRunSummary:
    processed: int = 0
    skipped: int = 0
    retryable: int = 0
    stopped: bool = False
    stop_status: Status | None = None
```

`MatchMethod` 恰好获得一个值：

```python
HUMAN_REVIEW = "HUMAN_REVIEW"
```

`review_queue` 使用下面构造的确切列顺序：

```python
REVIEW_COLUMNS = [
    "review_id", "task_id", "query", "query_year", "candidate_count",
    *[
        field
        for number in range(1, 6)
        for field in (
            f"candidate_{number}_title",
            f"candidate_{number}_year",
            f"candidate_{number}_kind",
            f"candidate_{number}_url",
        )
    ],
    "created_at",
    "decision_type", "selected_candidate", "manual_detail_url", "review_note",
    "apply_status", "applied_url", "applied_at", "apply_error",
]
```

### 任务 1：添加不可变的复核领域模型

**文件：**

- 修改：`app/models.py`
- 修改：`tests/test_models.py`

- [ ] **步骤 1：编写失败的模型测试**

附加到 `tests/test_models.py`：

```python
from dataclasses import FrozenInstanceError

import pytest

from app.models import (
    CandidateSnapshot,
    MatchMethod,
    ReviewAction,
    ReviewApplyStatus,
    ReviewDecisionType,
    ReviewPlan,
    ReviewRunSummary,
    Status,
    Task,
)


def test_review_enums_and_human_match_method_are_stable() -> None:
    assert [item.value for item in ReviewDecisionType] == [
        "CANDIDATE", "MANUAL_URL", "SKIP"
    ]
    assert [item.value for item in ReviewApplyStatus] == [
        "PENDING", "APPLIED", "SKIPPED", "FAILED", "SUPERSEDED"
    ]
    assert MatchMethod.HUMAN_REVIEW.value == "HUMAN_REVIEW"


def test_review_plan_is_immutable_and_counts_live_actions() -> None:
    task = Task("task-1", "英雄", "2002")
    action = ReviewAction(
        review_id="review-1",
        task=task,
        decision_type=ReviewDecisionType.CANDIDATE,
        detail_url="https://movie.douban.com/subject/1/",
        review_note="confirmed",
    )
    plan = ReviewPlan(actions=(action,), live_query_count=1)
    assert plan.actions == (action,)
    with pytest.raises(FrozenInstanceError):
        plan.live_query_count = 2  # type: ignore[misc]


def test_review_run_summary_exposes_recovery_state() -> None:
    summary = ReviewRunSummary(
        processed=1,
        skipped=2,
        retryable=1,
        stopped=True,
        stop_status=Status.PAGE_CHANGED,
    )
    assert summary.retryable == 1
    assert summary.stop_status is Status.PAGE_CHANGED
```

- [ ] **步骤 2：运行重点测试以验证 RED**

运行：

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_models.py -v
```

预期：收集失败，因为复核类型和 `HUMAN_REVIEW` 不匹配
存在。

- [ ] **步骤 3：实施域类型**

在 `app/models.py` 中，使用锁定的公共添加枚举和冻结dataclass
契约上方。将复核枚举放在 `MatchMethod`、`CandidateSnapshot` 之后
`Candidate` 之后为
，`RunSummary` 之后为计划/汇总类型。

`ReviewAction.detail_url` 是 `None` 仅适用于 `SKIP`。里面不要添加验证
dataclass；验证属于 `review_service.py`。

- [ ] **步骤 4：运行集中且完整的模型测试**

运行：

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_models.py -v
```

预期：所有模型测试均通过。

- [ ] **步骤 5：提交模型契约**

```powershell
git add app/models.py tests/test_models.py
git commit -m "feat: add review workflow models"
```

### 任务 2：使用原子复核队列扩展工作簿

**文件：**

- 修改：`app/excel_store.py`
- 修改：`tests/test_excel_store.py`

- [ ] **步骤 1：编写失败的schema 与快照测试**

附加到 `tests/test_excel_store.py`：

```python
from dataclasses import replace

from app.models import Candidate, ReviewApplyStatus, Task
from app.excel_store import REVIEW_COLUMNS


def ambiguous_candidates() -> list[Candidate]:
    return [
        Candidate("英雄", "2002", "电影", "https://movie.douban.com/subject/1/"),
        Candidate("英雄", "2022", "电影", "https://movie.douban.com/subject/2/"),
    ]


def test_review_upsert_creates_second_sheet_without_changing_movies_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "result.xlsx"
    store = ExcelStore(path)
    store.upsert(success("a", "英雄"))
    review_id = store.upsert_review(
        Task("a", "英雄", None), ambiguous_candidates(), "ambiguous"
    )

    workbook = load_workbook(path)
    assert workbook.sheetnames == ["movies", "review_queue"]
    assert [cell.value for cell in workbook["movies"][1]] == COLUMNS
    assert [cell.value for cell in workbook["review_queue"][1]] == REVIEW_COLUMNS
    row = list(workbook["review_queue"].iter_rows(min_row=2, values_only=True))[0]
    assert row[0] == review_id
    assert row[4] == 2
    assert row[5:9] == (
        "英雄", "2002", "电影", "https://movie.douban.com/subject/1/"
    )
    assert row[REVIEW_COLUMNS.index("apply_status")] == ReviewApplyStatus.PENDING


def test_same_snapshot_preserves_human_fields_and_does_not_duplicate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "result.xlsx"
    store = ExcelStore(path)
    first = store.upsert_review(
        Task("a", "英雄", None), ambiguous_candidates(), "ambiguous"
    )
    workbook = load_workbook(path)
    sheet = workbook["review_queue"]
    sheet.cell(2, REVIEW_COLUMNS.index("decision_type") + 1, "CANDIDATE")
    sheet.cell(2, REVIEW_COLUMNS.index("selected_candidate") + 1, 1)
    workbook.save(path)

    second = ExcelStore(path).upsert_review(
        Task("a", "英雄", None), ambiguous_candidates(), "ambiguous"
    )
    rows = list(load_workbook(path)["review_queue"].iter_rows(min_row=2, values_only=True))
    assert first == second
    assert len(rows) == 1
    assert rows[0][REVIEW_COLUMNS.index("decision_type")] == "CANDIDATE"


def test_changed_snapshot_supersedes_open_row(tmp_path: Path) -> None:
    path = tmp_path / "result.xlsx"
    store = ExcelStore(path)
    first = store.upsert_review(
        Task("a", "英雄", None), ambiguous_candidates(), "ambiguous"
    )
    changed = [Candidate(
        "英雄重制版", "2022", "电影",
        "https://movie.douban.com/subject/3/",
    )]
    second = store.upsert_review(Task("a", "英雄", None), changed, "changed")
    rows = list(load_workbook(path)["review_queue"].iter_rows(min_row=2, values_only=True))
    assert first != second
    assert len(rows) == 2
    status_index = REVIEW_COLUMNS.index("apply_status")
    assert rows[0][status_index] == "SUPERSEDED"
    assert rows[1][status_index] == "PENDING"
```

- [ ] **步骤 2：运行测试以验证 RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_excel_store.py -v
```

预期：`REVIEW_COLUMNS` 和的导入或属性失败
`upsert_review`。

- [ ] **步骤 3：重构保存处理而不更改现有行为**

在`app/excel_store.py`中添加：

```python
import hashlib
import json
from datetime import datetime

from app.models import (
    Candidate,
    ReviewApplyStatus,
    Task,
)

REVIEW_SHEET = "review_queue"
MAX_REVIEW_CANDIDATES = 5
REVIEW_COLUMNS = [
    "review_id", "task_id", "query", "query_year", "candidate_count",
    *[
        field
        for number in range(1, 6)
        for field in (
            f"candidate_{number}_title",
            f"candidate_{number}_year",
            f"candidate_{number}_kind",
            f"candidate_{number}_url",
        )
    ],
    "created_at",
    "decision_type", "selected_candidate", "manual_detail_url", "review_note",
    "apply_status", "applied_url", "applied_at", "apply_error",
]
```

将现有的原子写入提取到：

```python
def _save(self, workbook: WorkbookType) -> None:
    temporary = self.path.with_suffix(self.path.suffix + ".tmp")
    try:
        workbook.save(temporary)
        os.replace(temporary, self.path)
    except PermissionError as exc:
        raise OutputLockedError(f"Close Excel and retry: {self.path}") from exc
```

更新 `upsert()` 以调用 `_save(workbook)`。现有测试必须保持通过
添加复核行为之前的
。

也停止依赖 `workbook.active`。添加 `MOVIES_SHEET = "movies"` 并制作
`_workbook()` 明确选择 `workbook[MOVIES_SHEET]`。对于现有的
工作簿，拒绝丢失的 `movies` 工作表。对于新工作簿，将其初始名称命名为
表 `movies`。所有电影读取和写入都必须使用指定的工作表，即使
复核人员保存了 `review_queue` 处于活动状态的 Excel。

- [ ] **步骤 4：添加确定性复核标识和工作表助手**

添加：

```python
def _candidate_payload(candidates: list[Candidate]) -> list[dict[str, str | None]]:
    return [
        {
            "title": item.title,
            "year": item.year,
            "kind": item.kind,
            "detail_url": item.detail_url,
        }
        for item in candidates[:MAX_REVIEW_CANDIDATES]
    ]


def _review_id(task: Task, candidates: list[Candidate]) -> str:
    payload = {
        "task_id": task.task_id,
        "candidates": _candidate_payload(candidates),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]
```

添加私有 `_review_sheet(workbook)`，用于在以下情况下创建工作表和页眉
缺失，并使用 `ValueError` 拒绝错误的现有标头。

添加 `upsert_review(task, candidates, reason) -> str`：

- 拒绝空候选列表；
- 候选项上限为五；
- 计算 `review_id`；
- 为与 `SUPERSEDED` 相同的任务标记其他 `PENDING` 或 `FAILED` 行；
- 保留现有的相同行，包括人类字段；
- 附加一个包含候选字段的新行，ISO8601 `created_at`，
`apply_status=PENDING`，以及空决策/应用字段；
- 调用 `_save()` 一次；
- 返回 `review_id`。

`reason` 被调用方契约接受，但不存储在第一个中
架构版本；不要添加未记录的列。

- [ ] **步骤 5：添加读取和双表更新 API**

添加这些持久性 API：

```python
def review_rows(self) -> list[dict[str, object]]:
    workbook = self._workbook()
    if REVIEW_SHEET not in workbook.sheetnames:
        return []
    sheet = workbook[REVIEW_SHEET]
    header = [cell.value for cell in sheet[1]]
    if header != REVIEW_COLUMNS:
        raise ValueError("review_queue schema does not match the contract")
    return [
        {
            **dict(zip(REVIEW_COLUMNS, values, strict=True)),
            "_row_number": row_number,
        }
        for row_number, values in enumerate(
            sheet.iter_rows(min_row=2, values_only=True),
            start=2,
        )
    ]

def movie_status_by_task_id(self) -> dict[str, Status]:
    return self.status_by_task_id()

def apply_review_result(
    self,
    *,
    review_id: str,
    result: MovieResult | None,
    apply_status: ReviewApplyStatus,
    applied_url: str,
    apply_error: str,
) -> None:
    workbook = self._workbook()
    if REVIEW_SHEET not in workbook.sheetnames:
        raise ValueError("review_queue worksheet is required")
    sheet = workbook[REVIEW_SHEET]
    review_id_column = REVIEW_COLUMNS.index("review_id") + 1
    matches = [
        row_number
        for row_number in range(2, sheet.max_row + 1)
        if sheet.cell(row_number, review_id_column).value == review_id
    ]
    if len(matches) != 1:
        raise ValueError(f"review_id must identify one row: {review_id}")
    if result is not None:
        self._upsert_movie_in_workbook(workbook, result)
    row_number = matches[0]
    updates = {
        "apply_status": apply_status.value,
        "applied_url": applied_url,
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "apply_error": apply_error[:200],
    }
    for name, value in updates.items():
        sheet.cell(row_number, REVIEW_COLUMNS.index(name) + 1, value)
    self._save(workbook)
```

`review_rows()` 将每个数据行作为字典和私有返回
`"_row_number"` 仅用于验证消息的整数。

`apply_review_result()` 必须：

- 加载工作簿一次；
- 准确找到一个复核行；
- 拒绝丢失或重复的 `review_id`；
- 如果 `result` 不是 `None`，则将其upsert到同一工作簿内的 `movies` 中
对象；
- 更新 `apply_status`、`applied_url`、`applied_at` 和有界
`apply_error[:200]`;
- 两张表都更改后调用一次 `_save()`。

提取私有 `_upsert_movie_in_workbook(workbook, result)` 所以 `upsert()` 和
`apply_review_result()` 共享相同的序列号。

- [ ] **步骤 6：添加双表原子性和幂等性测试**

附加测试证明：

```python
def test_apply_review_result_updates_both_sheets_in_one_save(tmp_path: Path) -> None:
    path = tmp_path / "result.xlsx"
    store = ExcelStore(path)
    store.upsert(MovieResult.from_task(Task("a", "英雄", None)).stamped())
    review_id = store.upsert_review(
        Task("a", "英雄", None), ambiguous_candidates(), "ambiguous"
    )
    result = success("a", "英雄")
    result = replace(result, match_method=MatchMethod.HUMAN_REVIEW)
    store.apply_review_result(
        review_id=review_id,
        result=result,
        apply_status=ReviewApplyStatus.APPLIED,
        applied_url=result.detail_url,
        apply_error="",
    )
    workbook = load_workbook(path)
    assert workbook["movies"]["I2"].value == "HUMAN_REVIEW"
    status_col = REVIEW_COLUMNS.index("apply_status") + 1
    assert workbook["review_queue"].cell(2, status_col).value == "APPLIED"
```

还猴子补丁 `os.replace` 并证明锁保留了原始字节
用于配对更新。

- [ ] **步骤 7：运行重点测试**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_excel_store.py -v
```

预期：所有 Excel 测试均通过。

- [ ] **步骤 8：提交工作簿支持**

```powershell
git add app/excel_store.py tests/test_excel_store.py
git commit -m "feat: add atomic Excel review queue"
```

### 任务 3：构建整批离线复核验证

**文件：**

- 创建：`app/review_service.py`
- 创建：`tests/test_review_service.py`

- [ ] **步骤 1：编写失败的正常路径测试**

使用生成字典的助手创建 `tests/test_review_service.py`
匹配 `ExcelStore.review_rows()`，然后添加：

```python
from app.models import ReviewDecisionType, Status
from app.review_service import ReviewValidationError, build_review_plan


def test_candidate_manual_and_skip_rows_build_immutable_plan() -> None:
    rows = [
        review_row("r1", "t1", decision_type="CANDIDATE", selected_candidate=2),
        review_row(
            "r2", "t2", decision_type="MANUAL_URL",
            manual_detail_url="https://movie.douban.com/subject/42",
        ),
        review_row("r3", "t3", decision_type="SKIP"),
    ]
    plan = build_review_plan(
        rows,
        {"t1": Status.REVIEW_REQUIRED, "t2": Status.REVIEW_REQUIRED,
         "t3": Status.REVIEW_REQUIRED},
        max_queries=2,
    )
    assert plan.live_query_count == 2
    assert [action.decision_type for action in plan.actions] == [
        ReviewDecisionType.CANDIDATE,
        ReviewDecisionType.MANUAL_URL,
        ReviewDecisionType.SKIP,
    ]
    assert plan.actions[0].detail_url.endswith("/2/")
    assert plan.actions[1].detail_url == \
        "https://movie.douban.com/subject/42/"
    assert plan.actions[2].detail_url is None
```

- [ ] **步骤 2：添加失败拒绝矩阵**

参数化拒绝测试：

- 空白且未知的 `decision_type`；
- 候选选择空白、非整数、零、负数或大于
`candidate_count`;
- `CANDIDATE` 带有手动 URL；
- `MANUAL_URL` 与候选选择；
- `SKIP` 带有任一选择字段；
- 使用 HTTP 的手动 URL、错误的主机、凭据、端口、查询、片段或
非主题路径；
- `movies` 中缺少任务；
- `REVIEW_REQUIRED`、`PAGE_CHANGED`、`NETWORK_ERROR` 以外的任务状态，或
`UNEXPECTED_ERROR`;
- 一项任务重复待决决策；
- 两个不同任务重复使用的一个手动 URL；
- 比 `max_queries` 更多的真人表演；
- `review_note` 长度超过 500 个字符。

添加一项聚合测试：

```python
def test_any_invalid_row_rejects_entire_batch_with_all_row_errors() -> None:
    with pytest.raises(ReviewValidationError) as exc_info:
        build_review_plan(
            [
                review_row("bad-1", "t1", decision_type=""),
                review_row("bad-2", "missing", decision_type="SKIP"),
            ],
            {"t1": Status.REVIEW_REQUIRED},
            max_queries=1,
        )
    message = str(exc_info.value)
    assert "bad-1" in message
    assert "bad-2" in message
    assert len(exc_info.value.errors) == 2
```

- [ ] **步骤 3：运行测试以验证 RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_review_service.py -v
```

预期：收集失败，因为 `app.review_service` 不存在。

- [ ] **步骤 4：实施规范 URL 验证**

创建 `app/review_service.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from app.models import (
    ReviewAction,
    ReviewApplyStatus,
    ReviewDecisionType,
    ReviewPlan,
    Status,
    Task,
)

_RETRYABLE_MOVIE_STATUSES = frozenset({
    Status.REVIEW_REQUIRED,
    Status.PAGE_CHANGED,
    Status.NETWORK_ERROR,
    Status.UNEXPECTED_ERROR,
})
_TERMINAL_REVIEW_STATUSES = frozenset({
    ReviewApplyStatus.APPLIED,
    ReviewApplyStatus.SKIPPED,
    ReviewApplyStatus.SUPERSEDED,
})


class ReviewValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("\n".join(errors))


def normalize_manual_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname != "movie.douban.com":
        raise ValueError("manual URL must use https://movie.douban.com")
    if parsed.username or parsed.password or parsed.port:
        raise ValueError("manual URL must not contain credentials or a port")
    if parsed.query or parsed.fragment:
        raise ValueError("manual URL must not contain query or fragment")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] != "subject" or not parts[1].isdigit():
        raise ValueError("manual URL path must be /subject/<digits>/")
    return urlunparse(("https", "movie.douban.com", f"/subject/{parts[1]}/", "", "", ""))
```

不要在此处执行 DNS、HTTP 或浏览器工作。

- [ ] **步骤 5：实施整体计划构建**

实施：

```python
def build_review_plan(
    rows: list[dict[str, object]],
    movie_statuses: dict[str, Status],
    *,
    max_queries: int,
) -> ReviewPlan:
    errors: list[str] = []
    actions: list[ReviewAction] = []
    active_task_ids: set[str] = set()
    live_urls: dict[str, str] = {}

    for row in rows:
        review_id = str(row.get("review_id") or "")
        row_number = int(row.get("_row_number") or 0)
        prefix = f"row {row_number} review_id={review_id or '<blank>'}: "
        try:
            apply_status = ReviewApplyStatus(
                str(row.get("apply_status") or ReviewApplyStatus.PENDING)
            )
        except ValueError:
            errors.append(prefix + "invalid apply_status")
            continue
        if apply_status in _TERMINAL_REVIEW_STATUSES:
            continue

        task_id = str(row.get("task_id") or "")
        query = str(row.get("query") or "")
        raw_year = row.get("query_year")
        query_year = str(raw_year) if raw_year not in (None, "") else None
        if not review_id or not task_id or not query:
            errors.append(prefix + "review_id, task_id, and query are required")
            continue
        if task_id in active_task_ids:
            errors.append(prefix + f"duplicate active decision for task_id={task_id}")
            continue
        active_task_ids.add(task_id)
        if movie_statuses.get(task_id) not in _RETRYABLE_MOVIE_STATUSES:
            errors.append(prefix + "movies row is missing or not review-eligible")
            continue

        try:
            decision = ReviewDecisionType(str(row.get("decision_type") or ""))
        except ValueError:
            errors.append(prefix + "decision_type must be CANDIDATE, MANUAL_URL, or SKIP")
            continue
        selected = row.get("selected_candidate")
        manual = str(row.get("manual_detail_url") or "").strip()
        note = str(row.get("review_note") or "")
        if len(note) > 500:
            errors.append(prefix + "review_note must be at most 500 characters")
            continue

        detail_url: str | None
        if decision is ReviewDecisionType.CANDIDATE:
            if manual:
                errors.append(prefix + "CANDIDATE must not set manual_detail_url")
                continue
            try:
                selected_number = int(selected)
                candidate_count = int(row.get("candidate_count") or 0)
            except (TypeError, ValueError):
                errors.append(prefix + "selected_candidate must be an integer")
                continue
            if str(selected_number) != str(selected).strip() or not (
                1 <= selected_number <= candidate_count <= 5
            ):
                errors.append(prefix + "selected_candidate is outside the snapshot")
                continue
            detail_url = str(
                row.get(f"candidate_{selected_number}_url") or ""
            ).strip()
            try:
                detail_url = normalize_manual_url(detail_url)
            except ValueError as exc:
                errors.append(prefix + f"captured candidate URL is invalid: {exc}")
                continue
        elif decision is ReviewDecisionType.MANUAL_URL:
            if selected not in (None, ""):
                errors.append(prefix + "MANUAL_URL must not set selected_candidate")
                continue
            try:
                detail_url = normalize_manual_url(manual)
            except ValueError as exc:
                errors.append(prefix + str(exc))
                continue
        else:
            if selected not in (None, "") or manual:
                errors.append(prefix + "SKIP must not set a candidate or manual URL")
                continue
            detail_url = None

        if detail_url is not None:
            prior_task = live_urls.get(detail_url)
            if prior_task is not None and prior_task != task_id:
                errors.append(prefix + "selected URL is reused by another task")
                continue
            live_urls[detail_url] = task_id
        actions.append(ReviewAction(
            review_id=review_id,
            task=Task(task_id, query, query_year),
            decision_type=decision,
            detail_url=detail_url,
            review_note=note,
        ))

    live_query_count = sum(
        action.decision_type is not ReviewDecisionType.SKIP
        for action in actions
    )
    if live_query_count > max_queries:
        errors.append(
            f"live decision count {live_query_count} exceeds max_queries={max_queries}"
        )
    if errors:
        raise ReviewValidationError(errors)
    return ReviewPlan(tuple(actions), live_query_count)
```

规则：

- 忽略 `apply_status` 为 `APPLIED`、`SKIPPED` 或 `SUPERSEDED` 的行；
- 验证剩余的每一行并收集所有错误；
- 每个错误前缀中包含 `"_row_number"` 和 `review_id`；
- 使用 `CANDIDATE` 的编号快照中的候选 URL；
- 标准化 `MANUAL_URL` 的手册 URL；
- 将 `detail_url=None` 设置为 `SKIP`；
- 拒绝重复的活动任务 ID；
- 拒绝不同任务 ID 使用的标准化实时 URL；
- 计算 `CANDIDATE` 和 `MANUAL_URL`，但不计算 `SKIP`；
- 拒绝超过 `max_queries` 的计数；
- 在 `ReviewPlan.actions` 中保留工作簿行顺序；
- 验证所有行后提高一个 `ReviewValidationError(errors)` ；
- 返回不可变的操作元组。

- [ ] **步骤 6：运行重点测试**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_review_service.py -v
```

预期：所有验证测试均通过，无需文件系统或网络访问。

- [ ] **步骤 7：提交验证**

```powershell
git add app/review_service.py tests/test_review_service.py
git commit -m "feat: validate Excel review batches"
```

### 任务 4：在正常运行期间将不明确的候选项入队

**文件：**

- 修改：`app/runner.py`
- 修改：`tests/test_runner.py`

- [ ] **步骤 1：扩展假存储并编写失败的测试**

添加到 `FakeStore`：

```python
self.review_upserts: list[tuple[Task, list[Candidate], str]] = []

def upsert_review(
    self, task: Task, candidates: list[Candidate], reason: str
) -> str:
    self.review_upserts.append((task, list(candidates), reason))
    return f"review-{task.task_id}"
```

添加测试：

```python
def test_ambiguous_match_writes_bounded_candidate_snapshot() -> None:
    candidates = [
        Candidate(f"英雄 {i}", str(2000 + i), "电影",
                  f"https://movie.douban.com/subject/{i}/")
        for i in range(1, 7)
    ]
    store = FakeStore()
    runner = make_runner(FakeAdapter({"a": candidates}), store)
    runner.run([task("a", year=None)])
    assert len(store.review_upserts) == 1
    queued_task, queued, reason = store.review_upserts[0]
    assert queued_task.task_id == "a"
    assert len(queued) == 5
    assert reason == "no unique deterministic match"


def test_not_found_and_deterministic_success_do_not_write_review_rows() -> None:
    missing_store = FakeStore()
    make_runner(FakeAdapter(), missing_store).run([task("missing")])
    assert missing_store.review_upserts == []

    exact_task = task("exact", query="英雄", year="2002")
    exact_candidate = candidate("英雄", "2002")
    exact_adapter = FakeAdapter({"exact": [exact_candidate]})
    exact_adapter.detail_results["exact"] = successful_detail(exact_task)
    exact_store = FakeStore()
    make_runner(exact_adapter, exact_store).run([exact_task])
    assert exact_store.review_upserts == []
```

- [ ] **步骤 2：验证 RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest `
  tests/test_runner.py::test_ambiguous_match_writes_bounded_candidate_snapshot -v
```

预期：失败，因为 `Runner` 未调用 `upsert_review`。

- [ ] **步骤 3：添加队列写入**

在 `Runner._process` 中，在返回 `REVIEW_REQUIRED` 之前立即调用：

```python
self.store.upsert_review(task, candidates[:5], decision.reason)
```

如果复核持久性引发 `OutputLockedError`，则允许其传播
现有的输出锁定路径。不要将其捕获为 `UNEXPECTED_ERROR`。不
队列 `NOT_FOUND` 或确定性匹配。

- [ ] **步骤 4：运行器和 Excel 测试**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest `
  tests/test_runner.py tests/test_excel_store.py -v
```

预期：所有测试均通过。

- [ ] **步骤 5：提交正常运行集成**

```powershell
git add app/runner.py tests/test_runner.py
git commit -m "feat: queue ambiguous movie candidates"
```

### 任务 5：执行经过验证的检查点复核计划

**文件：**

- 创建：`app/review_runner.py`
- 创建：`tests/test_review_runner.py`

- [ ] **步骤 1：编写失败成功、跳过和幂等测试**

为适配器和商店创建假货。假商店记录
`apply_review_result` 来电。添加：

```python
def test_candidate_action_fetches_detail_and_checkpoints_human_match() -> None:
    action = live_action("r1", "t1", "https://movie.douban.com/subject/1/")
    adapter = FakeReviewAdapter(successful_detail(action.task))
    store = FakeReviewStore()
    summary = ReviewRunner(adapter, store, object(), 0).run(
        ReviewPlan((action,), live_query_count=1)
    )
    assert summary == ReviewRunSummary(processed=1)
    saved = store.calls[0]
    assert saved["result"].match_method is MatchMethod.HUMAN_REVIEW
    assert saved["apply_status"] is ReviewApplyStatus.APPLIED


def test_skip_action_never_calls_adapter() -> None:
    action = skip_action("r1", "t1")
    adapter = FakeReviewAdapter()
    store = FakeReviewStore()
    summary = ReviewRunner(adapter, store, object(), 0).run(
        ReviewPlan((action,), live_query_count=0)
    )
    assert adapter.calls == []
    assert summary == ReviewRunSummary(processed=0, skipped=1)
    assert store.calls[0]["apply_status"] is ReviewApplyStatus.SKIPPED
```

- [ ] **步骤 2：写入失败错误并停止测试**

覆盖：

- `NetworkError` 变为 `NETWORK_ERROR`、`FAILED`，可重试计数为 1，并且
下一步动作继续；
- `PageChangedError` 变为 `PAGE_CHANGED`、`FAILED`，可重试计数 1；
- `BlockedError` 变为 `BLOCKED`，检查当前操作，然后停止；
- `SiteProtectionChallenge` 变为其独特状态并停止；
- 意外的适配器错误变为 `UNEXPECTED_ERROR`，而不会泄漏异常
文字；
- `NetworkError`使用现有的三次尝试0/2/5秒有界重试；
- 节流仅在相邻实时动作之间休眠，而不是在 `SKIP` 之后或之后
最终真人版；
- 每个已完成的操作在下一个操作开始之前都会调用一次存储。

- [ ] **步骤 3：验证 RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_review_runner.py -v
```

预期：收集失败，因为 `app.review_runner` 不存在。

- [ ] **步骤 4：实施复核运行器**

使用以下内容创建 `app/review_runner.py`：

```python
from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from app.models import (
    Candidate,
    MatchMethod,
    MovieResult,
    ReviewApplyStatus,
    ReviewDecisionType,
    ReviewPlan,
    ReviewRunSummary,
    Status,
)
from app.sites.douban_movie import (
    BlockedError,
    NetworkError,
    PageChangedError,
    SiteProtectionChallenge,
)

_NETWORK_BACKOFF_SECONDS = (0.0, 2.0, 5.0)


class ReviewRunner:
    def __init__(
        self, adapter, store, tab: Any, min_interval_seconds: float = 5
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.tab = tab
        self.min_interval_seconds = float(min_interval_seconds)

    def run(self, plan: ReviewPlan) -> ReviewRunSummary:
        processed = skipped = retryable = 0
        live_indexes = [
            index
            for index, action in enumerate(plan.actions)
            if action.decision_type is not ReviewDecisionType.SKIP
        ]
        final_live_index = live_indexes[-1] if live_indexes else None
        for index, action in enumerate(plan.actions):
            if action.decision_type is ReviewDecisionType.SKIP:
                self.store.apply_review_result(
                    review_id=action.review_id,
                    result=None,
                    apply_status=ReviewApplyStatus.SKIPPED,
                    applied_url="",
                    apply_error="",
                )
                skipped += 1
                continue

            started = time.monotonic()
            result, stop = self._fetch(action)
            apply_status = (
                ReviewApplyStatus.APPLIED
                if result.status is Status.SUCCESS
                else ReviewApplyStatus.FAILED
            )
            self.store.apply_review_result(
                review_id=action.review_id,
                result=result,
                apply_status=apply_status,
                applied_url=action.detail_url or "",
                apply_error=result.error_message,
            )
            processed += 1
            if result.status in {
                Status.NETWORK_ERROR,
                Status.PAGE_CHANGED,
                Status.UNEXPECTED_ERROR,
            }:
                retryable += 1
            elapsed = time.monotonic() - started
            if (
                not stop
                and index != final_live_index
                and elapsed < self.min_interval_seconds
            ):
                time.sleep(self.min_interval_seconds - elapsed)
            if stop:
                return ReviewRunSummary(
                    processed, skipped, retryable, True, result.status
                )
        return ReviewRunSummary(processed, skipped, retryable)
```

用相同的三次尝试实现 `_network_operation(operation)`
0/2/5 秒退避为 `Runner`；只有 `NetworkError` 是可重试的。实施
`_fetch(action)` 通过从所选 URL 创建 `Candidate` 并调用：

```python
self._network_operation(
    lambda: self.adapter.fetch_detail(self.tab, action.task, candidate)
)
```

转换成功结果：

```python
replace(result, match_method=MatchMethod.HUMAN_REVIEW)
```

将适配器异常映射到与正常情况完全相同的标记 `MovieResult` 值
运行器确实如此。将网络错误文本限制为 200 个字符和意外错误
文本仅用于异常类型名称。`BlockedError` 和
`SiteProtectionChallenge` 设置 `stop=True`。

不要重试 `PageChangedError`、阻止、站点保护挑战或
意外异常。该运行器每执行一次选定的细节操作
操作，仅针对瞬态 `NetworkError` 进行有界重试。

- [ ] **步骤 5：运行重点测试**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_review_runner.py -v
```

预期：所有复核运行器测试均通过。

- [ ] **步骤 6：提交执行支持**

```powershell
git add app/review_runner.py tests/test_review_runner.py
git commit -m "feat: apply validated review actions"
```

### 任务 6：添加显式 `apply-review` CLI

**文件：**

- 修改：`app/main.py`
- 修改：`tests/test_main.py`

- [ ] **步骤 1：编写失败的解析器测试**

添加：

```python
def test_apply_review_parser_exposes_controlled_arguments() -> None:
    args = build_parser().parse_args([
        "apply-review",
        "--workbook", "out.xlsx",
        "--live-approved",
        "--max-queries", "3",
    ])
    assert args.command == "apply-review"
    assert args.workbook == "out.xlsx"
    assert args.headed is True
    assert args.min_interval == 5.0
    assert args.profile_dir == "browser-profile/douban"
```

断言 `apply-review` 不公开 `--retry-status`。

- [ ] **步骤 2：编写失败的预检顺序测试**

猴子补丁 `ExcelStore.review_rows`、`movie_status_by_task_id`、
`build_review_plan` 和 `BrowserSession`。证明：

- 无效工作簿或 `ReviewValidationError` 返回 2；
- 记录每个无效行；
- 浏览器构建计数保持为零；
- 工作簿字节不变；
- 具有两个实际操作且 `--max-queries 1` 返回 2 的计划；
- 缺少批准、无头模式、间隔低于 5、最大超出 1..10
浏览器构建前返回2；
- 仅包含 `SKIP` 的计划仍需要显式实时授权，
因为 `apply-review` 是一个联网命令，并且不得批准
根据计划内容推断。

- [ ] **步骤 3：编写失败的退出映射测试**

使用假的 `ReviewRunner` 来证明：

- 普通汇总返回0；
- `stop_status=BLOCKED` 返回 3；
- `stop_status=SITE_PROTECTION_CHALLENGE` 返回 3；
- `OutputLockedError` 返回 4；
- 意外的浏览器故障返回 5。

- [ ] **步骤 4：验证 RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_main.py -v
```

预期：失败，因为 `apply-review` 未知。

- [ ] **步骤 5：重构共享联网参数和验证**

在 `build_parser()` 中，创建一个助手，添加：

```python
--headed / --no-headed
--min-interval
--browser-path
--profile-dir
--live-approved
--max-queries
```

将其用于 `run` 和 `apply-review`。保留 `--input`、`--output` 和
`--retry-status` 仅适用于 `run`；仅添加所需的 `--workbook`
`apply-review`。

重构 `_validate_live_run` 以接受 `live_query_count` 而不是 CSV 任务
计数，同时保留所有现有的运行测试和消息。

- [ ] **步骤 6：实施命令调度和离线优先预检**

将当前没有语义变化的 `run` 主体移动到
`_execute_run(args, logger)`。让`execute()`解析一次，配置日志记录
一次，并显式调度：

```python
if args.command == "run":
    return _execute_run(args, logger)
if args.command == "apply-review":
    return _execute_apply_review(args, logger)
raise AssertionError(f"unhandled command: {args.command}")
```

apply 函数必须按以下顺序执行：

```python
workbook_path = Path(args.workbook)
if not workbook_path.is_file():
    logger.error("Review workbook is required: %s", workbook_path)
    return 2
store = ExcelStore(workbook_path)
rows = store.review_rows()
statuses = store.movie_status_by_task_id()
plan = build_review_plan(rows, statuses, max_queries=10)
if not _validate_live_run(args, plan.live_query_count, logger):
    return 2
browser_path = Path(args.browser_path) if args.browser_path else None
with BrowserSession(
    args.headed,
    _ARTIFACTS_DIR,
    Path(args.profile_dir),
    browser_path,
) as tab:
    summary = ReviewRunner(
        DoubanMovieAdapter(), store, tab, args.min_interval
    ).run(plan)
```

在浏览器构建之前捕获 `ValueError` 和 `ReviewValidationError` 并
返回 2。将 `OutputLockedError` 捕获为 4，并将意外的浏览器/全局错误捕获为
5. 当 `summary.stop_status` 为 `BLOCKED` 时返回 3 或
`SITE_PROTECTION_CHALLENGE`。

重要订购细节：因为 `max_queries` 本身必须被验证为
1. .10，解析工作簿，安全临时上限为 10，验证 CLI
参数，则当 `plan.live_query_count > args.max_queries` 时拒绝。不
将 `0` 传递给 `build_review_plan` 以获取缺失值。最终实现
因此
应该是：

```python
plan = build_review_plan(rows, statuses, max_queries=10)
if not _validate_live_run(args, plan.live_query_count, logger):
    return 2
```

- [ ] **步骤 7：运行重点 CLI 测试**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_main.py -v
```

预期：所有主要测试均通过，并且没有启动真正的浏览器。

- [ ] **步骤 8：手动验证帮助文本**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m app.main apply-review --help
```

预期：退出 0；输出包含 `--workbook`、`--live-approved`、
`--max-queries`、`--headed`、`--min-interval`，并且不包含
`--retry-status`。

- [ ] **步骤 9：提交 CLI 连接**

```powershell
git add app/main.py tests/test_main.py
git commit -m "feat: add controlled apply-review command"
```

### 任务 7：保留发布验证和文档操作

**文件：**

- 修改：`scripts/verify_core.py`
- 修改：`tests/test_verify_core.py`
- 修改：`tests/test_project_config.py`
- 修改：`README.md`

- [ ] **步骤 1：编写失败的验证器兼容性测试**

附加到 `tests/test_verify_core.py`：

```python
def test_workbook_verifier_uses_movies_sheet_when_review_queue_exists(
    tmp_path: Path,
) -> None:
    path = tmp_path / "controlled.xlsx"
    workbook = Workbook()
    movies = workbook.active
    movies.title = "movies"
    movies.append(EXPECTED_COLUMNS)
    movies.append(valid_row("task-1"))
    review = workbook.create_sheet("review_queue")
    review.append(["review-only"])
    workbook.active = 1
    workbook.save(path)
    assert verify_controlled_workbook(path) == {
        "data_rows": 1, "unique_ids": 1
    }
```

该测试故意使 `review_queue` 处于活动状态，证明验证者确实
不依赖于 `workbook.active`。

- [ ] **步骤 2：验证 RED**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest `
  tests/test_verify_core.py::test_workbook_verifier_uses_movies_sheet_when_review_queue_exists -v
```

预期：失败，因为验证者读取活动工作表。

- [ ] **步骤 3：明确选择 `movies`**

更改：

```python
rows = list(workbook.active.values)
```

至：

```python
if "movies" not in workbook.sheetnames:
    raise WorkbookContractError("movies worksheet is required")
rows = list(workbook["movies"].values)
```

保留现有的 12 列、行计数、状态、ID 和时间戳检查。

- [ ] **步骤 4：加强离线CI配置测试**

在 `tests/test_project_config.py` 中，断言：

- `.github/workflows/core-offline.yml` 不包含 `apply-review`；
- 不包含 `--live-approved`；
- 跟踪运行时扫描仍然只允许低于 `outputs/` 的 `.gitkeep`，
`artifacts/` 和 `browser-profile/`；
- `README.md` 示例永远不会忽略真实 `apply-review` 的联网门禁
命令。

- [ ] **步骤 5：更新自述文件**

添加简洁的“Excel 人工复核”部分，其中包含：

1. 正常的`run`创建`review_queue`以产生歧义；
2. 仅 `decision_type`、`selected_candidate`、`manual_detail_url` 和
`review_note` 可编辑；
3. 合法决策组合；
4. 规范手工 URL示例；
5. 精确控制命令：

```powershell
python -m app.main apply-review `
  --workbook .\outputs\douban_movies.xlsx `
  --live-approved `
  --max-queries 5 `
  --headed `
  --min-interval 5 `
  --profile-dir .\browser-profile\douban
```

6. 整批预检拒绝并退出代码2；
7. `SKIP`、检查点、恢复和已应用的行为；
8. 阻止/挑战的停止行为；
9. “应用前关闭Excel”；
10. 运行时产物永远不会进入 Git。

请勿描述无人值守调度或审批重用。

- [ ] **步骤 6：运行重点验证**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest `
  tests/test_verify_core.py tests/test_project_config.py -v
```

预期：所有测试均通过。

- [ ] **步骤 7：提交验证和文档**

```powershell
git add scripts/verify_core.py tests/test_verify_core.py `
  tests/test_project_config.py README.md
git commit -m "docs: add Excel review operations"
```

### 任务 8：完成离线发布验证

**文件：**

- 没有计划的源更改；仅修复由任务 1-7 直接引起的故障。

- [ ] **步骤 1：运行完整套件**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest -q
```

预期：所有测试通过；计数大于 164 测试基线。

- [ ] **步骤 2：运行覆盖范围和可移植门禁**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pytest `
  --cov=app `
  --cov-report=term-missing `
  --cov-report=json:artifacts/coverage.json -v
if ($LASTEXITCODE -ne 0) { throw 'coverage run failed' }
& '.\.venv\Scripts\python.exe' -m scripts.verify_core `
  --coverage-json artifacts/coverage.json
if ($LASTEXITCODE -ne 0) { throw 'verify_core failed' }
```

预期：退出 0；现有的三个必修模块保持在 80% 或以上。

- [ ] **步骤 3：运行包和本地浏览器检查**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m pip check
if ($LASTEXITCODE -ne 0) { throw 'pip check failed' }
& '.\.venv\Scripts\python.exe' -m scripts.browser_smoke
if ($LASTEXITCODE -ne 0) { throw 'browser smoke failed' }
```

预期：依赖关系完整；本地 `data:` 冒烟测试退出 0 且不
访问豆瓣。

- [ ] **步骤 4：无需浏览器运行 CLI 拒绝检查**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
& '.\.venv\Scripts\python.exe' -m app.main apply-review `
  --workbook .\outputs\missing.xlsx `
  --max-queries 1 `
  --headed `
  --min-interval 5
if ($LASTEXITCODE -ne 2) {
    throw "expected exit 2, got $LASTEXITCODE"
}
```

预期：退出码 2；无需创建浏览器/配置文件，也无需访问网络。

- [ ] **步骤 5：运行密钥和跟踪产物扫描**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
$SecretPattern = '(sk-[A-Za-z0-9_-]{20,}|MINIMAX_API_KEY\s*=\s*["'']?[A-Za-z0-9_-]{16,}|Cookie:\s*[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
$SecretMatches = git grep -n -I -E $SecretPattern -- .
$SecretExit = $LASTEXITCODE
if ($SecretExit -eq 0) { $SecretMatches; throw 'Possible tracked secret found' }
if ($SecretExit -gt 1) { throw "git grep failed with exit $SecretExit" }

$TrackedRuntime = @(git ls-files -- outputs artifacts browser-profile)
$Unexpected = @(
  $TrackedRuntime |
    Where-Object { $_ -notmatch '^(outputs|artifacts|browser-profile)/\.gitkeep$' }
)
if ($Unexpected.Count -gt 0) {
  $Unexpected
  throw 'Tracked runtime artifacts found'
}
```

预期：无密钥匹配；只允许 `.gitkeep` 运行时条目。

- [ ] **步骤 6：检查范围和空白**

```powershell
Set-Location -LiteralPath 'D:\DataAnt'
git diff --check
git status --short
git log --oneline -10
```

预期：`git diff --check` 是干净的。`.planning/` 和
`browser_bot_demo.egg-info/` 可能保持不相关且未被追踪；不要暂存或
删除它们。

- [ ] **步骤 7：记录实施交接**

报告：

- 最终测试计数；
- 覆盖率门禁结果；
- CLI 帮助/拒绝证据；
- 变更文件；
- 创建的提交；
- 确认没有发生真实豆瓣或 MiniMax 请求；
- 遗留问题（如有）。

在操作员单独运行有效的验证之前，不要声明实时复核成功
1–10 行工作簿，并取得明确授权。

## 计划自我复核清单

- 每个设计验收标准都对应于任务 2-8。
- `movies` 恰好保留 12 列。
- `review_queue` 有一个声明的列顺序。
- 验证发生在浏览器构建之前和工作簿突变之前。
- `SKIP` 不执行网络操作。
- 手动URL无法逃脱规范的豆瓣主题路径。
- 成对的电影/复核更新使用一个原子工作簿保存。
- 完成的行被幂等地跳过；更改的快照将被取代。
- `ReviewPlan` 和 `ReviewRunSummary` 提供未来的批量/恢复接缝。
- 豆瓣审批是每次调用的，不能持久或计划。
- MiniMax、第二站点支持和无人值守实时批次仍然超出范围。
- 没有计划步骤需要真正的网络访问。
