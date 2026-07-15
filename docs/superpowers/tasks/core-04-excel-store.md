# Core 04：幂等原子 Excel Store 执行 Spec

## 操作提示词（可直接复制）

```text
你是本仓库的实现代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。

只读取本 spec：D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\core-04-excel-store.md，以及本 spec 明确列出的必要现有代码 app/models.py 和 pyproject.toml。不得读取总计划 docs/superpowers/plans/2026-07-15-browser-bot-core-demo.md。

严格按本 spec 的 TDD 顺序执行：先写测试并验证 RED，再写最小实现，运行目标测试和全套测试，最后提交。只允许创建或修改 app/excel_store.py 与 tests/test_excel_store.py；不得改动任何其他文件。不得安装依赖。所有 PowerShell 命令先 Set-Location 到绝对 worktree。不得发起任何真实豆瓣或其他外网流量。

验证成功后只提交允许文件，commit message 必须为：feat: add atomic idempotent Excel output

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
- Core 01–02 已完成；`app/models.py` 提供 `MovieResult`、`Status` 等固定类型。
- `pyproject.toml` 已声明 `openpyxl>=3.1,<4`；现有环境可运行 pytest。本任务不得安装或升级依赖。
- 所有测试只使用 pytest 的 `tmp_path`，不得读写真实输出目录。

## Goal

实现固定 12 列的 `.xlsx` Store：按稳定 `task_id` 幂等 upsert，重启后可读取状态索引，每条写入通过同目录临时文件加 `os.replace()` 原子替换；目标文件被占用时抛出面向操作者的自定义错误并保留临时文件。

## Files（仅允许本任务）

- Create：`app/excel_store.py`
- Create：`tests/test_excel_store.py`

不得修改模型、依赖配置或其他文件。

## Fixed contracts

现有模型契约：

```python
class Status(StrEnum):
    SUCCESS = "SUCCESS"
    NOT_FOUND = "NOT_FOUND"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PAGE_CHANGED = "PAGE_CHANGED"
    BLOCKED = "BLOCKED"
    OUTPUT_LOCKED = "OUTPUT_LOCKED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


class MatchMethod(StrEnum):
    RULE_EXACT = "RULE_EXACT"
    RULE_YEAR = "RULE_YEAR"
    LLM = "LLM"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class MovieResult:
    task_id: str
    query: str
    query_year: str | None
    matched_title: str = ""
    matched_year: str | None = None
    director: str = ""
    rating: float | None = None
    detail_url: str = ""
    match_method: MatchMethod = MatchMethod.NONE
    status: Status = Status.UNEXPECTED_ERROR
    error_message: str = ""
    collected_at: str = ""
```

公开接口固定为：

```python
COLUMNS: list[str]

class OutputLockedError(OSError): ...

class ExcelStore:
    def __init__(self, path: Path) -> None: ...
    def status_by_task_id(self) -> dict[str, Status]: ...
    def upsert(self, result: MovieResult) -> None: ...
```

列顺序必须精确为：

```python
[
    "task_id", "query", "query_year", "matched_title", "matched_year", "director",
    "rating", "detail_url", "match_method", "status", "error_message", "collected_at",
]
```

固定行为：新文件工作表名为 `movies`；枚举写入其字符串值；`None` 保持空单元格；同一 `task_id` 替换原行而不追加；已有文件表头不符时抛 `ValueError`；保存到 `<name>.xlsx.tmp` 后调用 `os.replace(temp, target)`；`PermissionError` 转成 `OutputLockedError`，原目标不变且临时文件保留。

## TDD implementation

- [ ] **Step 1 — RED：创建完整测试**

创建 `tests/test_excel_store.py`：

```python
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

import app.excel_store as excel_store_module
from app.excel_store import COLUMNS, ExcelStore, OutputLockedError
from app.models import MatchMethod, MovieResult, Status


def success(task_id: str, title: str, rating: float | None = 9.0) -> MovieResult:
    return MovieResult(
        task_id=task_id,
        query=title,
        query_year="1994",
        matched_title=title,
        matched_year="1994",
        director="Director One / Director Two",
        rating=rating,
        detail_url="https://movie.douban.com/subject/1/",
        match_method=MatchMethod.RULE_EXACT,
        status=Status.SUCCESS,
        collected_at="2026-07-15T12:00:00+08:00",
    )


def test_upsert_creates_exact_schema_and_serializes_values(tmp_path: Path) -> None:
    path = tmp_path / "result.xlsx"
    ExcelStore(path).upsert(success("a", "Movie", rating=None))
    workbook = load_workbook(path)
    assert workbook.active.title == "movies"
    rows = list(workbook.active.values)
    assert list(rows[0]) == COLUMNS
    assert rows[1][0] == "a"
    assert rows[1][6] is None
    assert rows[1][8] == "RULE_EXACT"
    assert rows[1][9] == "SUCCESS"


def test_upsert_replaces_same_task_without_duplicate_row(tmp_path: Path) -> None:
    path = tmp_path / "result.xlsx"
    store = ExcelStore(path)
    store.upsert(success("a", "First"))
    store.upsert(success("a", "Updated"))
    rows = list(load_workbook(path).active.values)
    assert len(rows) == 2
    assert rows[1][1] == "Updated"


def test_status_index_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "result.xlsx"
    ExcelStore(path).upsert(success("a", "Movie"))
    assert ExcelStore(path).status_by_task_id() == {"a": Status.SUCCESS}


def test_missing_workbook_has_empty_status_index(tmp_path: Path) -> None:
    assert ExcelStore(tmp_path / "missing.xlsx").status_by_task_id() == {}


def test_existing_wrong_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "wrong.xlsx"
    workbook = Workbook()
    workbook.active.append(["wrong"])
    workbook.save(path)
    with pytest.raises(ValueError, match="12-column contract"):
        ExcelStore(path).status_by_task_id()


def test_permission_error_preserves_target_and_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "result.xlsx"
    ExcelStore(path).upsert(success("a", "Original"))
    original_bytes = path.read_bytes()

    def locked_replace(source: Path, target: Path) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(excel_store_module.os, "replace", locked_replace)
    with pytest.raises(OutputLockedError, match="Close Excel and retry"):
        ExcelStore(path).upsert(success("a", "Updated"))

    assert path.read_bytes() == original_bytes
    assert path.with_suffix(".xlsx.tmp").is_file()
```

- [ ] **Step 2 — verify RED**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest tests/test_excel_store.py -v
```

预期：非零退出，collection 因 `app.excel_store` 不存在而失败。

- [ ] **Step 3 — GREEN：创建完整实现**

创建 `app/excel_store.py`：

```python
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.workbook.workbook import Workbook as WorkbookType

from app.models import MovieResult, Status


COLUMNS = [
    "task_id",
    "query",
    "query_year",
    "matched_title",
    "matched_year",
    "director",
    "rating",
    "detail_url",
    "match_method",
    "status",
    "error_message",
    "collected_at",
]


class OutputLockedError(OSError):
    pass


class ExcelStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _workbook(self) -> WorkbookType:
        if self.path.exists():
            workbook = load_workbook(self.path)
            header = [cell.value for cell in workbook.active[1]]
            if header != COLUMNS:
                raise ValueError(
                    "Existing workbook schema does not match the 12-column contract"
                )
            return workbook
        workbook = Workbook()
        workbook.active.title = "movies"
        workbook.active.append(COLUMNS)
        return workbook

    def status_by_task_id(self) -> dict[str, Status]:
        if not self.path.exists():
            return {}
        workbook = self._workbook()
        return {
            str(row[0]): Status(str(row[9]))
            for row in workbook.active.iter_rows(min_row=2, values_only=True)
        }

    def upsert(self, result: MovieResult) -> None:
        workbook = self._workbook()
        sheet = workbook.active
        row_number = next(
            (
                row[0].row
                for row in sheet.iter_rows(min_row=2)
                if row[0].value == result.task_id
            ),
            sheet.max_row + 1,
        )
        values: dict[str, Any] = asdict(result)
        for column_number, name in enumerate(COLUMNS, start=1):
            value = values[name]
            sheet.cell(
                row=row_number,
                column=column_number,
                value=getattr(value, "value", value),
            )
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            workbook.save(temporary)
            os.replace(temporary, self.path)
        except PermissionError as exc:
            raise OutputLockedError(f"Close Excel and retry: {self.path}") from exc
```

- [ ] **Step 4 — focused verify**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest tests/test_excel_store.py -v
```

预期：6 tests PASS，退出码 0。

- [ ] **Step 5 — full verify**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest -q
```

预期：完整测试套件退出码 0。

- [ ] **Step 6 — commit**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
git status --short
git add -- app/excel_store.py tests/test_excel_store.py
git diff --cached --check
git commit -m "feat: add atomic idempotent Excel output"
```

## Acceptance checklist

- [ ] 仅 `app/excel_store.py` 与 `tests/test_excel_store.py` 被创建或修改。
- [ ] 表头恰好 12 列且顺序固定；新工作表名为 `movies`。
- [ ] 枚举写字符串值，空评分写空单元格而非 0。
- [ ] 同一 `task_id` 重写原行，重启后状态索引仍正确。
- [ ] 每次 upsert 使用同目录临时文件和 `os.replace()`。
- [ ] 文件占用时抛 `OutputLockedError`，目标不变，临时文件保留。
- [ ] 错误表头被明确拒绝。
- [ ] focused tests 与 full suite 均退出 0。
- [ ] 没有真实豆瓣流量或任何外网访问。
- [ ] commit message 精确为 `feat: add atomic idempotent Excel output`。
