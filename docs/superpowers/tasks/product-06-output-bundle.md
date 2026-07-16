# 任务 6：实现三产物原子输出包

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-06-output-bundle.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：feat: render product json and gallery。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格执行本文件中的 RED → verify RED → GREEN → focused verify → full verify → commit 顺序。文件编辑使用 apply_patch。只允许修改文件小节列出的文件；不得安装或升级依赖，不得 amend、reset、force push，不得修改或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

本任务严格离线：不得启动浏览器，不得访问 web-scraping.dev、豆瓣或其他外网，不得传入 --live-approved。

提交前运行 git diff --check，并确认 git diff --name-only 只含本任务允许文件。除非本任务明确说明不需要提交，commit message 必须精确为：feat: commit product outputs as one bundle

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-06-output-bundle
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
- 前置提交：`feat: render product json and gallery`。
- 本任务提交：`feat: commit product outputs as one bundle`。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


**文件：**

- 新建：`app/product_output_bundle.py`
- 新建：`tests/test_product_output_bundle.py`

- [ ] **步骤 1：写完整输出和回滚失败测试**

创建 `tests/test_product_output_bundle.py`，覆盖：

```python
from pathlib import Path

import pytest

import app.product_output_bundle as bundle_module
from app.excel_store import OutputLockedError
from app.product_models import ProductCollection, ProductRecord
from app.product_output_bundle import ProductOutputBundle


def collection(product_id: str) -> ProductCollection:
    return ProductCollection.from_records(
        [ProductRecord.success_fixture(product_id)],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )


def test_write_creates_exact_three_outputs(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    ProductOutputBundle(target).write(collection("1"))
    assert sorted(path.name for path in target.iterdir()) == [
        "gallery.html",
        "products.json",
        "products.xlsx",
    ]


def test_existing_bundle_is_merged_and_replaced_as_one_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "demo"
    bundle = ProductOutputBundle(target)
    bundle.write(collection("1"))
    bundle.write(collection("2"))
    assert bundle.read_product_ids() == ["1", "2"]


def test_failed_directory_swap_restores_previous_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"
    bundle = ProductOutputBundle(target)
    bundle.write(collection("1"))
    original_json = (target / "products.json").read_bytes()

    real_replace = bundle_module.os.replace
    calls = {"count": 0}

    def fail_second_replace(source: Path, destination: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise PermissionError("locked")
        real_replace(source, destination)

    monkeypatch.setattr(bundle_module.os, "replace", fail_second_replace)
    with pytest.raises(OutputLockedError):
        bundle.write(collection("2"))

    assert (target / "products.json").read_bytes() == original_json
```

- [ ] **步骤 2：运行测试确认缺少输出包**

```powershell
python -m pytest tests/test_product_output_bundle.py -q
```

预期：缺少模块。

- [ ] **步骤 3：实现目录级提交**

创建 `app/product_output_bundle.py`：

1. 验证 `target_dir` 位于调用方允许的 `outputs/` 边界内；CLI 负责传入已解析边界。
2. 如果存在 `products.xlsx`，用 `ProductExcel.read()` 读取旧记录并按 ID 合并。
3. 使用合并后的记录重新构建 `ProductCollection`，确保三个产物一致。
   合并结果超过 10 件时抛
   `ValueError("product bundle cannot exceed 10 products")`，
   避免跨多次运行绕过受控上限。
4. 在目标同级创建唯一暂存目录：
   `.<target-name>.staging-<uuid>`。
5. 在暂存目录写：
   `products.xlsx`、`products.json`、`gallery.html`。
6. 重新读取暂存 Excel 和 JSON，确认商品 ID 顺序一致。
7. 若目标存在，将目标重命名为
   `.<target-name>.backup-<uuid>`。
8. 将暂存目录重命名为目标目录。
9. 成功后用 `shutil.rmtree()` 删除 backup。
10. 第二次重命名失败时，将 backup 重命名回目标，并抛
    `OutputLockedError(f"Close open output files and retry: {self.target_dir}")`。
11. 无论成功失败，清理仍存在的 staging；不得删除已恢复的目标。

增加：

```python
def read_product_ids(self) -> list[str]:
    return [
        record.product_id
        for record in ProductExcel.read(self.target_dir / "products.xlsx")
    ]
```

供测试和后续验证脚本使用。

- [ ] **步骤 4：运行输出包测试**

```powershell
python -m pytest tests/test_product_output_bundle.py -q
```

预期：全部通过。

- [ ] **步骤 5：提交原子输出**

```powershell
git add app/product_output_bundle.py tests/test_product_output_bundle.py
git commit -m "feat: commit product outputs as one bundle"
```
