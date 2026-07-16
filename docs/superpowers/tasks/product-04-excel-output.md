# 任务 4：实现商品 Excel 合并与原子序列化

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-04-excel-output.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：feat: collect bounded product pages。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格执行本文件中的 RED → verify RED → GREEN → focused verify → full verify → commit 顺序。文件编辑使用 apply_patch。只允许修改文件小节列出的文件；不得安装或升级依赖，不得 amend、reset、force push，不得修改或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

本任务严格离线：不得启动浏览器，不得访问 web-scraping.dev、豆瓣或其他外网，不得传入 --live-approved。

提交前运行 git diff --check，并确认 git diff --name-only 只含本任务允许文件。除非本任务明确说明不需要提交，commit message 必须精确为：feat: add product workbook output

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-04-excel-output
- preflight: <前置提交与初始状态>
- red: <精确命令、退出码、预期失败>
- green: <focused 命令与结果>
- full_verify: <全量命令与结果>
- changed: <逐行文件列表>
- commit: <短 SHA + message；无提交时写 none>
- live: NOT_RUN | SKIPPED_NOT_APPROVED | APPROVED_AND_RUN | STOPPED_ON_PROTECTION
- concerns: <无则写 none>

任何门禁失败都保留现场并报告，不得猜测、伪造绿色结果或扩大范围。
```

## Base / 前置条件

- 仓库根目录：`D:\DataAnt`。
- 批准设计：`docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md`。
- 前置提交：`feat: collect bounded product pages`。
- 本任务提交：`feat: add product workbook output`。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


**文件：**

- 新建：`app/product_excel.py`
- 新建：`tests/test_product_excel.py`

- [ ] **步骤 1：写工作簿失败测试**

创建 `tests/test_product_excel.py`：

```python
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from app.product_excel import PRODUCT_COLUMNS, ProductExcel
from app.product_models import ProductRecord


def test_render_creates_products_sheet_with_exact_columns(tmp_path: Path) -> None:
    path = tmp_path / "products.xlsx"
    ProductExcel.write(path, [ProductRecord.success_fixture("1")])
    workbook = load_workbook(path)
    assert workbook.active.title == "products"
    rows = list(workbook.active.values)
    assert list(rows[0]) == PRODUCT_COLUMNS
    assert rows[1][0] == "1"
    assert rows[1][12] == "SUCCESS"


def test_merge_replaces_product_id_without_duplicate(tmp_path: Path) -> None:
    path = tmp_path / "products.xlsx"
    ProductExcel.write(path, [ProductRecord.success_fixture("1")])
    updated = ProductRecord.success_fixture("1")
    merged = ProductExcel.merge_existing(path, [updated])
    assert [record.product_id for record in merged] == ["1"]


def test_wrong_existing_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "products.xlsx"
    workbook = Workbook()
    workbook.active.append(["wrong"])
    workbook.save(path)
    with pytest.raises(ValueError, match="product workbook schema"):
        ProductExcel.read(path)
```

- [ ] **步骤 2：运行测试确认缺少模块**

```powershell
python -m pytest tests/test_product_excel.py -q
```

预期：缺少 `app.product_excel`。

- [ ] **步骤 3：实现商品工作簿**

创建 `app/product_excel.py`：

- `PRODUCT_COLUMNS` 使用固定 15 列契约。
- `ProductExcel.read(path)` 将工作簿行还原为 `ProductRecord`；
  金额使用 `Decimal(str(value))`。
- `ProductExcel.merge_existing(path, new_records)`：
  读取旧记录，以 `product_id` 为键；旧顺序保留，新 ID 追加，同 ID 替换。
- `ProductExcel.write(path, records)`：
  新建 `products` 工作表，将 enum 写为 `.value`，Decimal 写为 float，
  空值写 `None`。
- 写入调用方提供的暂存路径；目录交换由后续输出包负责。
- 错误 schema 明确抛 `ValueError`。

- [ ] **步骤 4：运行工作簿测试**

```powershell
python -m pytest tests/test_product_excel.py -q
```

预期：全部通过。

- [ ] **步骤 5：提交 Excel 输出**

```powershell
git add app/product_excel.py tests/test_product_excel.py
git commit -m "feat: add product workbook output"
```
