# 任务 8：增加跨产物验证、覆盖率门禁和离线 CI 保护

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-08-verification-ci.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：feat: add controlled product collection command。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格执行本文件中的 RED → verify RED → GREEN → focused verify → full verify → commit 顺序。文件编辑使用 apply_patch。只允许修改文件小节列出的文件；不得安装或升级依赖，不得 amend、reset、force push，不得修改或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

本任务严格离线：不得启动浏览器，不得访问 web-scraping.dev、豆瓣或其他外网，不得传入 --live-approved。

提交前运行 git diff --check，并确认 git diff --name-only 只含本任务允许文件。除非本任务明确说明不需要提交，commit message 必须精确为：test: verify offline product output contract

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-08-verification-ci
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
- 前置提交：`feat: add controlled product collection command`。
- 本任务提交：`test: verify offline product output contract`。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


**文件：**

- 新建：`scripts/verify_products.py`
- 新建：`tests/test_verify_products.py`
- 修改：`scripts/verify_core.py:10-14`
- 修改：`tests/test_verify_core.py`
- 修改：`tests/test_project_config.py:45-94`
- 修改：`.github/workflows/core-offline.yml`

- [x] **步骤 1：写三产物一致性失败测试**

创建 `tests/test_verify_products.py`，使用测试输出包生成基线，然后验证：

```python
def test_verify_bundle_accepts_matching_outputs(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    ProductOutputBundle(target).write(collection("1"))
    assert verify_product_bundle(target) == {
        "products": 1,
        "unique_ids": 1,
        "success": 1,
        "partial": 0,
        "failed": 0,
    }


def test_verify_bundle_rejects_json_id_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    ProductOutputBundle(target).write(collection("1"))
    payload = json.loads((target / "products.json").read_text(encoding="utf-8"))
    payload["products"][0]["product_id"] = "other"
    (target / "products.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    with pytest.raises(ProductBundleContractError, match="product ids"):
        verify_product_bundle(target)
```

另测：

- 缺任一产物；
- Excel 列错误；
- JSON `schema_version != 1`；
- 重复 ID；
- 超过 10 个商品；
- `collected_at` 缺失；
- HTML 不含对应嵌入 ID；
- HTML 含 `<script src=`、`fetch(` 或外部字体。

- [x] **步骤 2：实现 `scripts/verify_products.py`**

公开：

```python
class ProductBundleContractError(AssertionError):
    pass


def verify_product_bundle(output_dir: Path) -> dict[str, int]:
    """Validate the three-file product bundle and return status counts."""
```

验证：

- 三个文件存在；
- Excel 1 到 10 行、ID 唯一、15 列匹配；
- JSON 版本、来源、摘要和 ID 顺序匹配 Excel；
- HTML 包含安全嵌入数据和必要控件；
- HTML 无外部脚本、字体、`fetch(`、XHR 或 WebSocket；
- 返回状态计数摘要。

CLI：

```powershell
python -m scripts.verify_products --output-dir .\outputs\web-scraping-dev-demo
```

- [x] **步骤 3：扩展覆盖率门禁**

在 `scripts/verify_core.py`：

```python
REQUIRED_COVERAGE = {
    "app/input_loader.py": 80.0,
    "app/matcher.py": 80.0,
    "app/sites/douban_movie.py": 80.0,
    "app/sites/web_scraping_dev.py": 80.0,
    "app/product_runner.py": 80.0,
}
```

更新 `tests/test_verify_core.py` 的平台路径、通过和失败用例。

- [x] **步骤 4：强化 CI 静态保护**

更新 `tests/test_project_config.py`：

- CI job body 不得包含 `web-scraping.dev`；
- 不得包含 `collect-products`；
- 不得包含 `--max-products`；
- 不得上传 `products.xlsx`、`products.json` 或 `gallery.html`。

更新 `.github/workflows/core-offline.yml` 顶部注释，明确第二站点也禁止真实访问。
工作流执行步骤仍只有安装、pytest、覆盖率门禁、diff 检查和 tracked 文件扫描。

- [x] **步骤 5：运行验证测试**

```powershell
python -m pytest tests/test_verify_products.py tests/test_verify_core.py tests/test_project_config.py -q
```

预期：全部通过。

- [x] **步骤 6：提交验证门禁**

```powershell
git add scripts/verify_products.py scripts/verify_core.py tests/test_verify_products.py tests/test_verify_core.py tests/test_project_config.py .github/workflows/core-offline.yml
git commit -m "test: verify offline product output contract"
```
