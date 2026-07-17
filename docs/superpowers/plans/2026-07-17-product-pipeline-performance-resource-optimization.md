# 商品采集本地流水线并发、性能与空间优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在不改变真实站点串行访问和商品输出契约的前提下，复用一次规范化 payload，并行生成三种本地输出、控制运行产物空间、增加离线性能基准。

**Architecture:** ProductRunner 的 live 浏览器访问、节流、重试和当前页面诊断保持串行。ProductOutputBundle 在合并出最终 ProductCollection 后建立只读 ProductOutputSnapshot，把同一份 primitive rows 传给 JSON、gallery 和 Excel writer；三个 writer 只在独立 staging 文件上并发执行，所有任务完成后继续走现有原子替换。detached parser 只用于离线 fixture benchmark，不接入 live 默认路径。

**Tech Stack:** Python 3.11、标准库 dataclasses / concurrent.futures / time / tracemalloc / tempfile、现有 ProductCollection、openpyxl、原生 HTML/JavaScript、pytest、PowerShell。

---

## 前提与边界

- 已批准设计：docs/superpowers/specs/2026-07-17-product-pipeline-performance-resource-optimization-design.md
- 当前基线提交：2ce7c70；代码基线为 aa08116。
- 所有命令先执行：

~~~powershell
Set-Location -LiteralPath 'D:\DataAnt'
~~~

- 使用仓库 .venv；本轮不执行 collect-products，不能启动浏览器或访问真实网站。
- 不读取、移动、删除或暂存已有的 .codex-tmp/、.planning/、browser_bot_demo.egg-info/、outputs/、artifacts/、browser-profile/、.worktrees/、.venv/。
- 每个任务只暂存该任务列出的文件，不使用 git add -A。
- 本计划不增加多 tab、多浏览器或多进程 live 抓取，不降低 --min-interval，不扩大 --max-products。

## 文件分工

### 修改文件

- app/product_json.py：创建 ProductOutputSnapshot，提供 compact JSON 和兼容渲染入口。
- app/product_gallery.py：接受 snapshot，避免第二次构造 payload。
- app/product_excel.py：接受共享 primitive rows，返回 ProductWriteReceipt。
- app/product_output_bundle.py：一次创建 snapshot，最多 3 个 writer 并发，维持原子替换和旧 bundle 恢复。
- app/product_runner.py、app/main.py：只增加可选本地指标和日志，不改变 live 行为。
- README.md：补充 benchmark、清理和 live 时间下限说明。

### 新建文件

- tests/helpers_product_performance.py：固定 1/5/10 条商品样本。
- scripts/benchmark_products.py：离线 benchmark 和 JSON 报告。
- scripts/prune_artifacts.py：默认 dry-run 的 artifacts 清理命令。
- tests/test_benchmark_products.py、tests/test_prune_artifacts.py：对应测试。

### 不修改文件

- app/sites/douban_movie.py。
- app/sites/web_scraping_dev.py 的 live URL 白名单、阻断检测、导航和 parser 契约。
- app/browser_session.py、app/product_models.py、pyproject.toml、.github/workflows/core-offline.yml。

---

### Task 0: 锁定离线基线和固定性能样本

**Files:**

- Create: tests/helpers_product_performance.py
- Test: tests/test_product_json.py
- Test: tests/test_product_output_bundle.py

- [ ] Step 1: 创建固定 collection helper

在 tests/helpers_product_performance.py 写入：

~~~python
from __future__ import annotations

from decimal import Decimal

from app.product_models import ProductCollection, ProductRecord


def fixture_collection(count: int) -> ProductCollection:
    if count not in {1, 5, 10}:
        raise ValueError("fixture collection count must be 1, 5, or 10")
    records = [
        ProductRecord(
            product_id=str(index),
            source_site="web-scraping.dev",
            product_url=f"https://web-scraping.dev/product/{index}",
            name=f"Product {index}",
            category="consumables",
            description=f"Description {index}",
            primary_image_url=(
                f"https://web-scraping.dev/assets/products/{index}.webp"
            ),
            current_price=Decimal("9.99"),
            currency="USD",
            brand=f"Brand {index}",
            variant_count=index % 3,
            collected_at="2026-07-16T20:00:00+08:00",
        )
        for index in range(1, count + 1)
    ]
    return ProductCollection.from_records(
        records,
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
~~~

- [ ] Step 2: 运行当前 focused baseline

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_json.py tests/test_product_excel.py tests/test_product_output_bundle.py -q
~~~

Expected: 当前 focused 测试全部通过；不出现浏览器或网络访问。

- [ ] Step 3: 记录优化前本地输出基线

只使用系统临时目录：

~~~powershell
& '.\.venv\Scripts\python.exe' -c "from pathlib import Path; from tempfile import mkdtemp; from time import perf_counter; from app.product_output_bundle import ProductOutputBundle; from tests.helpers_product_performance import fixture_collection; import json; import shutil; d=Path(mkdtemp()); target=d/'demo'; start=perf_counter(); ProductOutputBundle(target).write(fixture_collection(10)); elapsed=(perf_counter()-start)*1000; sizes={p.name:p.stat().st_size for p in target.iterdir()}; print(json.dumps({'elapsed_ms':round(elapsed,3),'sizes':sizes,'total_bytes':sum(sizes.values())}, sort_keys=True)); shutil.rmtree(d)"
~~~

Expected: 输出一行包含 elapsed_ms、sizes、total_bytes 的 JSON；结果只记录在交付回报，不写入仓库。

- [ ] Step 4: 提交基线 helper

~~~powershell
git add tests/helpers_product_performance.py
git commit -m "test: add product performance fixtures"
~~~

Expected: 只提交该 helper。

---

### Task 1: 创建一次性 ProductOutputSnapshot 和紧凑 JSON

**Files:**

- Modify: app/product_json.py
- Modify: app/product_gallery.py
- Test: tests/test_product_json.py
- Test: tests/test_product_gallery.py

- [ ] Step 1: 先写失败测试

在 tests/test_product_json.py 增加：

~~~python
import json

from app.product_json import (
    build_product_output_snapshot,
    render_product_json,
)
from app.product_models import ProductCollection, ProductRecord


def test_snapshot_calls_to_primitive_once_per_record(monkeypatch) -> None:
    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1"), ProductRecord.success_fixture("2")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    calls = {"count": 0}
    original = ProductRecord.to_primitive

    def counted(record):
        calls["count"] += 1
        return original(record)

    monkeypatch.setattr(ProductRecord, "to_primitive", counted)
    snapshot = build_product_output_snapshot(collection)

    assert calls["count"] == 2
    assert snapshot.product_ids == ("1", "2")
    assert json.loads(snapshot.json_text)["products"][1]["product_id"] == "2"


def test_render_product_json_is_compact_without_schema_change() -> None:
    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    rendered = render_product_json(collection)
    payload = json.loads(rendered)

    assert payload["schema_version"] == 1
    assert payload["products"][0]["product_id"] == "1"
    assert "\n  " not in rendered
    assert rendered.endswith("\n")
~~~

在 tests/test_product_gallery.py 增加 snapshot 转发测试：

~~~python
def test_gallery_uses_supplied_snapshot(monkeypatch) -> None:
    from app.product_json import build_product_output_snapshot

    collection = ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    snapshot = build_product_output_snapshot(collection)
    monkeypatch.setattr(
        "app.product_gallery.build_product_output_snapshot",
        lambda _collection: (_ for _ in ()).throw(
            AssertionError("gallery rebuilt payload")
        ),
    )

    page = render_gallery(collection, snapshot=snapshot)

    assert '"product_id": "1"' in page
~~~

- [ ] Step 2: 运行测试确认 RED

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_json.py tests/test_product_gallery.py -q
~~~

Expected: 因 snapshot builder 和 gallery 参数不存在而失败。

- [ ] Step 3: 实现 snapshot 和 compact JSON

在 app/product_json.py 增加：

~~~python
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True, slots=True)
class ProductOutputSnapshot:
    payload: dict[str, object]
    product_rows: tuple[dict[str, object], ...]
    json_text: str
    product_ids: tuple[str, ...]


def build_product_output_snapshot(
    collection: ProductCollection,
) -> ProductOutputSnapshot:
    payload = product_payload(collection)
    raw_products = payload.get("products")
    if not isinstance(raw_products, list):
        raise TypeError("product payload products must be a list")
    rows = tuple(cast(dict[str, object], item) for item in raw_products)
    compact = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ) + "\n"
    return ProductOutputSnapshot(
        payload=payload,
        product_rows=rows,
        json_text=compact,
        product_ids=tuple(str(row["product_id"]) for row in rows),
    )


def render_product_json(
    collection: ProductCollection,
    *,
    snapshot: ProductOutputSnapshot | None = None,
) -> str:
    return (snapshot or build_product_output_snapshot(collection)).json_text
~~~

保留 product_payload(collection) 的 schema 和直接调用方式。不要修改 ProductCollection 或 ProductRecord 的可变性。

- [ ] Step 4: 修改 gallery 接口但保持兼容

将 render_gallery 改为：

~~~python
def render_gallery(
    collection: ProductCollection,
    *,
    snapshot: ProductOutputSnapshot | None = None,
) -> str:
    output_snapshot = snapshot or build_product_output_snapshot(collection)
    payload = output_snapshot.payload
    # 继续使用现有模板、escaping、占位符和内嵌 JSON。
~~~

移除 gallery 内部第二次直接调用 product_payload(collection)；render_gallery(collection) 仍必须可用。

- [ ] Step 5: 运行 focused tests确认 GREEN

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_json.py tests/test_product_gallery.py -q
~~~

Expected: JSON 可解析、schema 不变，gallery 的 escaping、自包含和质量摘要测试全部通过。

- [ ] Step 6: 提交

~~~powershell
git add app/product_json.py app/product_gallery.py tests/test_product_json.py tests/test_product_gallery.py
git commit -m "perf: reuse product output payload"
~~~

---

### Task 2: Excel 复用 primitive rows 并返回 receipt

**Files:**

- Modify: app/product_excel.py
- Test: tests/test_product_excel.py
- Test: tests/test_product_output_bundle.py

- [ ] Step 1: 先写失败测试

在 tests/test_product_excel.py 增加：

~~~python
from app.product_excel import ProductWriteReceipt


def test_write_accepts_shared_rows_and_returns_receipt(tmp_path) -> None:
    path = tmp_path / "products.xlsx"
    record = ProductRecord.success_fixture("1")

    receipt = ProductExcel.write(
        path,
        [record],
        primitive_rows=(record.to_primitive(),),
    )

    assert isinstance(receipt, ProductWriteReceipt)
    assert receipt.product_ids == ("1",)
    assert receipt.row_count == 1
    assert receipt.bytes_written == path.stat().st_size


def test_write_rejects_shared_row_length_mismatch(tmp_path) -> None:
    path = tmp_path / "products.xlsx"
    with pytest.raises(ValueError, match="primitive rows"):
        ProductExcel.write(
            path,
            [ProductRecord.success_fixture("1")],
            primitive_rows=(),
        )
~~~

- [ ] Step 2: 运行测试确认 RED

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_excel.py -q
~~~

Expected: 因 receipt 和 primitive_rows 参数不存在而失败。

- [ ] Step 3: 实现 receipt 和共享 rows 写入

在 app/product_excel.py 增加：

~~~python
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductWriteReceipt:
    product_ids: tuple[str, ...]
    row_count: int
    bytes_written: int
~~~

将 write 签名改为：

~~~python
@classmethod
def write(
    cls,
    path: Path,
    records: list[ProductRecord],
    *,
    primitive_rows: Sequence[Mapping[str, object]] | None = None,
) -> ProductWriteReceipt:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = (
        tuple(record.to_primitive() for record in records)
        if primitive_rows is None
        else tuple(primitive_rows)
    )
    if len(rows) != len(records):
        raise ValueError("primitive rows must match records")

    workbook, sheet = cls._workbook_for(path)
    for row in rows:
        sheet.append([row[column] for column in PRODUCT_COLUMNS])
    workbook.save(path)
    return ProductWriteReceipt(
        product_ids=tuple(record.product_id for record in records),
        row_count=len(records),
        bytes_written=path.stat().st_size,
    )
~~~

保留 ProductExcel.write(path, records) 兼容；只在传入 shared rows 时跳过第二次 primitive 转换。

- [ ] Step 4: 运行测试确认 GREEN

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_excel.py -q
~~~

Expected: workbook 仍只有 products sheet，列顺序严格等于 PRODUCT_COLUMNS，现有 read/merge 测试通过。

- [ ] Step 5: 测试 bundle 转发同一份 rows

在 tests/test_product_output_bundle.py monkeypatch ProductExcel.write，记录收到的 primitive_rows，再执行一次 ProductOutputBundle(target).write(collection("1"))：

~~~python
def test_bundle_passes_shared_rows_to_excel(tmp_path, monkeypatch) -> None:
    received = []
    original = bundle_module.ProductExcel.write

    def capture(path, records, *, primitive_rows=None):
        received.append(tuple(primitive_rows or ()))
        return original(path, records, primitive_rows=primitive_rows)

    monkeypatch.setattr(bundle_module.ProductExcel, "write", capture)
    bundle_module.ProductOutputBundle(tmp_path / "demo").write(collection("1"))

    assert len(received) == 1
    assert received[0][0]["product_id"] == "1"
~~~

- [ ] Step 6: 运行 focused tests并提交

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_excel.py tests/test_product_output_bundle.py -q
git add app/product_excel.py tests/test_product_excel.py tests/test_product_output_bundle.py
git commit -m "perf: reuse primitive rows for product Excel"
~~~

Expected: focused tests全部通过；只提交列出的文件。

---

### Task 3: 并行生成三产物并保留原子回退

**Files:**

- Modify: app/product_output_bundle.py
- Modify: app/product_gallery.py
- Test: tests/test_product_output_bundle.py

- [ ] Step 1: 先写 writer 异常回退测试

~~~python
def test_writer_failure_leaves_existing_bundle_and_cleans_siblings(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "demo"
    bundle = ProductOutputBundle(target)
    bundle.write(collection("1"))
    original_json = (target / "products.json").read_bytes()

    def fail_gallery(*args, **kwargs):
        raise RuntimeError("gallery writer failed")

    monkeypatch.setattr(bundle_module, "render_gallery", fail_gallery)
    with pytest.raises(RuntimeError, match="gallery writer failed"):
        bundle.write(collection("2"))

    assert (target / "products.json").read_bytes() == original_json
    assert not list(target.parent.glob(f".{target.name}.staging-*"))
    assert not list(target.parent.glob(f".{target.name}.backup-*"))
~~~

增加 writer active counter 测试，使用 threading.Lock 保护计数，断言最大值不超过 3；不要测试真实 tab 或网络。

- [ ] Step 2: 运行 bundle tests确认 RED

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_output_bundle.py -q
~~~

Expected: 新增并发/失败测试在实现前失败；已有 directory swap 恢复测试继续通过。

- [ ] Step 3: 增加 BundleWriteReceipt 和文本写入 helper

在 app/product_output_bundle.py 增加：

~~~python
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from app.product_json import (
    ProductOutputSnapshot,
    build_product_output_snapshot,
)
from app.product_excel import ProductWriteReceipt


@dataclass(frozen=True, slots=True)
class BundleWriteReceipt:
    product_ids: tuple[str, ...]
    excel: ProductWriteReceipt
    bytes_by_file: dict[str, int]


def _write_text(path: Path, content: str) -> int:
    path.write_text(content, encoding="utf-8")
    return path.stat().st_size
~~~

- [ ] Step 4: 改造 write 和 _write_three

在合并 collection 后只调用一次：

~~~python
snapshot = build_product_output_snapshot(merged_collection)
staging_dir.mkdir(parents=True)
receipt = self._write_three(
    merged_collection,
    staging_dir,
    snapshot=snapshot,
)
self._verify_consistent(snapshot, receipt, staging_dir)
~~~

用最多 3 个 worker 写三个不同文件。gallery 的渲染必须在 future 内部执行：

~~~python
def _render_and_write_gallery(
    collection: ProductCollection,
    directory: Path,
    snapshot: ProductOutputSnapshot,
) -> int:
    return _write_text(
        directory / "gallery.html",
        render_gallery(collection, snapshot=snapshot),
    )


@staticmethod
def _write_three(
    collection: ProductCollection,
    directory: Path,
    *,
    snapshot: ProductOutputSnapshot,
) -> BundleWriteReceipt:
    with ThreadPoolExecutor(
        max_workers=3,
        thread_name_prefix="product-output",
    ) as executor:
        excel_future = executor.submit(
            ProductExcel.write,
            directory / "products.xlsx",
            list(collection.records),
            primitive_rows=snapshot.product_rows,
        )
        json_future = executor.submit(
            _write_text,
            directory / "products.json",
            snapshot.json_text,
        )
        gallery_future = executor.submit(
            _render_and_write_gallery,
            collection,
            directory,
            snapshot,
        )
        excel_receipt = excel_future.result()
        json_bytes = json_future.result()
        gallery_bytes = gallery_future.result()
    return BundleWriteReceipt(
        product_ids=snapshot.product_ids,
        excel=excel_receipt,
        bytes_by_file={
            "products.xlsx": excel_receipt.bytes_written,
            "products.json": json_bytes,
            "gallery.html": gallery_bytes,
        },
    )
~~~

future 抛出的异常必须回到主线程；finally 继续删除本轮 staging，旧 bundle 恢复逻辑保持不变。

- [ ] Step 5: 使用 receipt 做轻量一致性确认

保留 products.json 的落盘读取，但不再对刚写出的 Excel 立即调用 openpyxl 反读：

~~~python
@staticmethod
def _verify_consistent(
    snapshot: ProductOutputSnapshot,
    receipt: BundleWriteReceipt,
    directory: Path,
) -> None:
    expected_ids = list(snapshot.product_ids)
    if list(receipt.excel.product_ids) != expected_ids:
        raise ValueError("staging Excel IDs do not match snapshot")
    payload = json.loads(
        (directory / "products.json").read_text(encoding="utf-8")
    )
    json_ids = [
        str(item.get("product_id"))
        for item in payload.get("products", [])
    ]
    if json_ids != expected_ids:
        raise ValueError("staging JSON IDs do not match snapshot")
    for filename in ("products.xlsx", "products.json", "gallery.html"):
        if not (directory / filename).is_file():
            raise ValueError(f"staging output is missing {filename}")
~~~

完整的跨产物校验继续由 scripts.verify_products 执行，不删除其 Excel schema 和唯一 ID 检查。

- [ ] Step 6: 运行 focused suite并提交

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_output_bundle.py tests/test_product_excel.py tests/test_product_json.py tests/test_product_gallery.py -q
git add app/product_output_bundle.py app/product_gallery.py tests/test_product_output_bundle.py
git commit -m "perf: parallelize local product outputs"
~~~

Expected: focused suite全部通过；writer 失败时旧 bundle 字节不变且 sibling 不残留。

---

### Task 4: 陈旧 bundle sibling 与 artifacts 清理工具

**Files:**

- Modify: app/product_output_bundle.py
- Create: scripts/prune_artifacts.py
- Create: tests/test_prune_artifacts.py
- Test: tests/test_product_output_bundle.py

- [ ] Step 1: 先写清理失败测试

陈旧 sibling 测试必须只匹配当前 target 生成的命名：

~~~python
def test_cleanup_stale_siblings_only_removes_generated_old_dirs(tmp_path):
    target = tmp_path / "demo"
    stale = target.with_name(".demo.staging-old")
    fresh = target.with_name(".demo.backup-fresh")
    unrelated = target.with_name(".demo-not-generated")
    stale.mkdir()
    fresh.mkdir()
    unrelated.mkdir()
    old = time.time() - 48 * 60 * 60
    os.utime(stale, (old, old))

    ProductOutputBundle(target).cleanup_stale_siblings(
        max_age_seconds=24 * 60 * 60,
    )

    assert not stale.exists()
    assert fresh.exists()
    assert unrelated.exists()
~~~

在 tests/test_prune_artifacts.py 测试 dry-run、不删除新文件、apply 删除过期文件和 root 越界拒绝：

~~~python
def test_prune_files_dry_run_does_not_delete_old_file(tmp_path):
    old_file = tmp_path / "old.log"
    old_file.write_text("old", encoding="utf-8")
    result = prune_files(tmp_path, older_than_days=1, apply=False)
    assert result == (old_file,)
    assert old_file.exists()


def test_prune_files_apply_deletes_only_old_files(tmp_path):
    old_file = tmp_path / "old.log"
    new_file = tmp_path / "new.log"
    old_file.write_text("old", encoding="utf-8")
    new_file.write_text("new", encoding="utf-8")
    old = time.time() - 2 * 24 * 60 * 60
    os.utime(old_file, (old, old))

    result = prune_files(tmp_path, older_than_days=1, apply=True)

    assert result == (old_file,)
    assert not old_file.exists()
    assert new_file.exists()


def test_prune_command_rejects_root_outside_repository_artifacts(tmp_path):
    with pytest.raises(ValueError, match="artifacts"):
        validate_artifacts_root(tmp_path)
~~~

- [ ] Step 2: 运行清理测试确认 RED

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_prune_artifacts.py tests/test_product_output_bundle.py -q
~~~

Expected: 因清理 API 尚不存在而失败。

- [ ] Step 3: 实现 sibling 清理

在 ProductOutputBundle 增加：

~~~python
def cleanup_stale_siblings(
    self,
    *,
    max_age_seconds: float,
) -> tuple[Path, ...]:
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    prefix = f".{self.target_dir.name}."
    now = time.time()
    removed = []
    for candidate in self.target_dir.parent.iterdir():
        if not candidate.is_dir() or not candidate.name.startswith(prefix):
            continue
        if ".staging-" not in candidate.name and ".backup-" not in candidate.name:
            continue
        if now - candidate.stat().st_mtime > max_age_seconds:
            shutil.rmtree(candidate)
            removed.append(candidate)
    return tuple(removed)
~~~

在 write() 创建本轮 staging 之前调用 24 小时阈值；保留本轮 finally 即时清理。

- [ ] Step 4: 实现 scripts.prune_artifacts

提供以下函数和 CLI：

~~~python
def validate_artifacts_root(root: Path) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    allowed = (repo_root / "artifacts").resolve()
    resolved = root.resolve()
    if resolved != allowed:
        raise ValueError(f"root must resolve to {allowed}")
    return resolved


def prune_files(
    root: Path,
    *,
    older_than_days: int,
    apply: bool,
) -> tuple[Path, ...]:
    if older_than_days <= 0:
        raise ValueError("older_than_days must be positive")
    root = root.resolve()
    cutoff = time.time() - older_than_days * 24 * 60 * 60
    candidates = tuple(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != ".gitkeep"
        and path.stat().st_mtime < cutoff
    )
    if apply:
        for path in candidates:
            path.unlink()
    return candidates
~~~

CLI 解析 --root、--older-than-days、--apply；进入 prune_files 前先调用 validate_artifacts_root，默认输出 DRY-RUN，只有 --apply 输出 DELETE 并执行删除。越界 root 必须在扫描前拒绝。这样 prune_files 可以用 tmp_path 做纯函数测试，而 CLI 仍有仓库 root 安全门。

- [ ] Step 5: 运行测试确认 GREEN并提交

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_prune_artifacts.py tests/test_product_output_bundle.py -q
git add app/product_output_bundle.py scripts/prune_artifacts.py tests/test_prune_artifacts.py tests/test_product_output_bundle.py
git commit -m "chore: add bounded runtime artifact cleanup"
~~~

Expected: 测试只操作 tmp_path；真实 D:\DataAnt\artifacts 不被删除。

---

### Task 5: 增加本地 metrics 和离线 benchmark

**Files:**

- Modify: app/product_runner.py
- Modify: app/main.py
- Create: scripts/benchmark_products.py
- Create: tests/test_benchmark_products.py
- Test: tests/test_product_runner.py
- Test: tests/test_main.py

- [ ] Step 1: 先写 metrics 和 benchmark 报告测试

在 tests/test_product_runner.py 增加：

~~~python
def test_runner_metrics_count_paced_operations_and_records():
    adapter = FakeAdapter.single_page("1")
    metrics = ProductRunMetrics()

    collection = ProductRunner(
        adapter,
        object(),
        max_products=1,
        min_interval_seconds=0,
        metrics=metrics,
    ).run()

    assert collection.summary.total == 1
    assert metrics.paced_operations == 2
    assert metrics.network_retry_count == 0
    assert metrics.detail_records == 1
~~~

在 tests/test_benchmark_products.py 断言：

~~~python
def test_benchmark_report_contains_limits_and_sizes(tmp_path):
    report = run_benchmark(counts=(1,), iterations=1, output_root=tmp_path)

    assert report["writer_workers"] == 3
    assert report["parser_workers"] == 2
    assert report["max_queue_depth"] <= 2
    assert report["runs"]
    assert report["runs"][0]["bundle_bytes"] > 0
    assert not list(tmp_path.glob("*.xlsx"))
    assert not list(tmp_path.glob("*.html"))
~~~

- [ ] Step 2: 运行测试确认 RED

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_runner.py tests/test_benchmark_products.py -q
~~~

Expected: metrics API 和 run_benchmark 尚不存在的测试失败；现有 runner 测试不能因为没有传 metrics 而失败。

- [ ] Step 3: 实现可选 ProductRunMetrics

在 app/product_runner.py 增加：

~~~python
@dataclass(slots=True)
class ProductRunMetrics:
    paced_operations: int = 0
    network_retry_count: int = 0
    detail_records: int = 0
    discovery_seconds: float = 0.0
    detail_seconds: float = 0.0
~~~

给 ProductRunner.__init__ 增加 metrics: ProductRunMetrics | None = None，默认 None。每次进入 _paced() 递增 paced_operations；每次 _network_operation() 捕获一次可重试 NetworkError 递增 network_retry_count；每次 detail 产生终态 record 递增 detail_records。用 time.perf_counter() 包住现有 discovery 和 detail loop，填写秒数字段。不得改变现有 backoff、sleep、状态映射和诊断调用。

- [ ] Step 4: 在商品 CLI 输出指标日志

在 app/main.py 的商品执行路径创建 metrics，传给 runner；在 ProductOutputBundle.write() 前后计时并记录 local_output_ms、writer 数量、记录数和 bundle bytes。receipt 必须提供 bytes_by_file，日志不得包含 HTML、Cookie、请求头、profile 路径或 API Key。

- [ ] Step 5: 实现离线 benchmark

scripts/benchmark_products.py 的 run_benchmark 使用 Task 0 fixture、TemporaryDirectory、time.perf_counter 和 tracemalloc。报告至少包含：

~~~python
{
    "writer_workers": 3,
    "parser_workers": 2,
    "max_queue_depth": 2,
    "runs": [
        {
            "count": 10,
            "iteration": 1,
            "total_local_ms": 0.0,
            "bundle_bytes": 0,
            "products_json_bytes": 0,
            "gallery_html_bytes": 0,
            "products_xlsx_bytes": 0,
            "peak_memory_bytes": 0,
        }
    ],
}
~~~

默认规模为 (1, 5, 10)，默认迭代 5 次；parser worker 只解析 tests/fixtures 下的本地 HTML，最多 2 条 pending snapshot。benchmark 不实例化 BrowserSession、不调用 tab.get()、不访问网络。CLI：

~~~powershell
& '.\.venv\Scripts\python.exe' -m scripts.benchmark_products --counts 1,5,10 --iterations 5
~~~

- [ ] Step 6: 运行 metrics、benchmark 和 runner tests确认 GREEN

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_runner.py tests/test_main.py tests/test_benchmark_products.py -q
& '.\.venv\Scripts\python.exe' -m scripts.benchmark_products --counts 1,5,10 --iterations 5
~~~

Expected: pytest 全部通过；benchmark stdout 为合法 JSON，包含三种规模、耗时、字节数、峰值内存和 worker 上限；不新增仓库运行产物。

- [ ] Step 7: 提交

~~~powershell
git add app/product_runner.py app/main.py scripts/benchmark_products.py tests/test_product_runner.py tests/test_main.py tests/test_benchmark_products.py
git commit -m "perf: add offline product pipeline benchmark"
~~~

---

### Task 6: 更新 README

**Files:**

- Modify: README.md
- Test: tests/test_project_config.py（只有新增静态契约时才修改）

- [ ] Step 1: 增加 README 静态断言

若现有配置测试已覆盖 README，则在 tests/test_project_config.py 增加：

~~~python
from pathlib import Path

def test_readme_documents_product_performance_controls():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "scripts.benchmark_products" in text
    assert "scripts.prune_artifacts" in text
    assert "--live-approved" in text
    assert "--min-interval 2" in text
    assert "多 tab" in text or "多浏览器" in text
~~~

- [ ] Step 2: 更新商品章节

说明 live 访问仍是单 tab 串行；本地最多 3 个 writer；JSON 紧凑但 schema 不变；benchmark 只用 fixture；清理命令默认 dry-run；.venv 和 .worktrees 不会被清理；网络等待不是本地优化指标。加入：

~~~powershell
& '.\.venv\Scripts\python.exe' -m scripts.benchmark_products --counts 1,5,10 --iterations 5
& '.\.venv\Scripts\python.exe' -m scripts.prune_artifacts --root .\artifacts --older-than-days 7
~~~

- [ ] Step 3: 运行 README 检查并提交

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_project_config.py -q
git diff --check
git add README.md tests/test_project_config.py
git commit -m "docs: document product performance controls"
~~~

Expected: 静态配置测试通过；README 不包含缺少 live 授权、max-products、headed 或 min-interval 的真实运行示例。若测试文件没有改动，只暂存 README。

---

### Task 7: 全量离线验收与交付

**Files:**

- Verify: Tasks 0–6 的所有修改文件
- No runtime artifacts committed

- [ ] Step 1: 运行 focused product suite

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_product_json.py tests/test_product_gallery.py tests/test_product_excel.py tests/test_product_output_bundle.py tests/test_product_runner.py tests/test_benchmark_products.py tests/test_prune_artifacts.py -q
~~~

Expected: 全部通过；不启动浏览器，不访问目标网站。

- [ ] Step 2: 运行全量离线检查

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' -m pip check
git diff --check
~~~

Expected：pytest 退出码 0；pip check 输出 No broken requirements found；git diff --check 无输出；无浏览器和外部网络访问。

- [ ] Step 3: 运行 bundle verifier 和 benchmark

~~~powershell
& '.\.venv\Scripts\python.exe' -m scripts.benchmark_products --counts 10 --iterations 5
if (Test-Path -LiteralPath 'D:\DataAnt\outputs\web-scraping-dev-demo') {
    & '.\.venv\Scripts\python.exe' -m scripts.verify_products --output-dir 'D:\DataAnt\outputs\web-scraping-dev-demo'
}
~~~

Expected: benchmark 输出合法 JSON；已有 bundle 时 verifier 输出五项计数并退出码 0；没有 bundle 时不启动 live run。

- [ ] Step 4: 对比 baseline 与优化版

在同一 .venv、同一机器、同一 fixture 和同一迭代参数下记录：

- total_local_ms 中位数目标降低至少 15%；未达到时不得宣称性能提升，必须报告实际数字。
- products_json_bytes 不得大于 baseline。
- bundle_bytes 不得比 baseline 增加超过 5%。
- max_queue_depth <= 2，writer worker 数为 3。
- live 访问次数、串行顺序、阻断停止和 --min-interval 约束无变化。

- [ ] Step 5: 扫描最终变更范围

~~~powershell
git status --short
git diff --name-only HEAD~6..HEAD
git diff --check HEAD~6..HEAD
~~~

Expected：变更只落在允许的 app、scripts、tests 和 README；不出现 outputs、artifacts、browser-profile、.venv、.worktrees 或新的运行产物；diff check 无输出。若任务提交数不是 6，使用实际首个任务提交到 HEAD 的范围重新执行同等检查。

- [ ] Step 6: 交付报告

报告必须包含：每个 focused RED/GREEN 命令和实际结果；full pytest、pip check、diff check；benchmark baseline/优化版中位耗时、峰值内存、队列深度和字节数；修改文件和 commit SHA；live run 记录为 SKIPPED_NOT_APPROVED；既有未跟踪目录未被处理。没有实际 benchmark 数字时不得使用“应该”“预计”替代。

## 计划自检

- payload 复用和 compact JSON：Task 1。
- primitive rows 和 Excel receipt：Task 2。
- 三 writer 并发、顺序、异常回退和原子 bundle：Task 3。
- staging/backup 与 artifacts 空间控制：Task 4。
- metrics、离线 parser benchmark 和本地阶段指标：Task 5。
- README、full offline verification 和 bundle verifier：Tasks 6–7。
- 真实 live 串行、阻断立即停止、现有 schema 和未跟踪目录边界贯穿全部任务。
- 每个代码改动都有对应测试、命令和预期结果；没有未指定文件的开放式实现步骤。
