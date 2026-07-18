# Product Output Pipeline Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the product output path into immutable snapshot, artifact writer, verifier, and atomic directory transaction components without changing CLI behavior or the three output contracts.

**Architecture:** Keep `ProductOutputBundle.write()` as the public façade. It acquires a target transaction lock, merges existing records, builds one immutable snapshot, writes three staging artifacts through a bounded writer component, verifies their IDs, and atomically commits or restores the previous directory.

**Tech Stack:** Python 3.11/3.12, dataclasses, `MappingProxyType`, `ThreadPoolExecutor`, pathlib, openpyxl, pytest.

---

## Preconditions and file map

Execute this plan in an isolated worktree created with `using-git-worktrees`. Do not run either live command. Every command below is offline and must use the worktree virtual environment.

**Create:**

- `app/product_output_snapshot.py` — canonical payload construction and recursive immutable snapshot.
- `app/product_artifact_writers.py` — fixed three-thread local artifact generation and writer receipts.
- `app/product_bundle_verifier.py` — staging artifact/ID consistency checks.
- `app/product_bundle_transaction.py` — target locking, staging lifecycle, atomic swap, rollback, and stale sibling cleanup.
- `tests/test_product_output_snapshot.py` — immutable snapshot and compatibility coverage.
- `tests/test_product_artifact_writers.py` — concurrency, receipt, and failure coverage.
- `tests/test_product_bundle_verifier.py` — staging consistency coverage.
- `tests/test_product_bundle_transaction.py` — locking, cleanup, swap, and rollback coverage.

**Modify:**

- `app/product_json.py` — retain JSON façade and compatibility re-exports.
- `app/product_gallery.py` — import snapshot types from their new owner.
- `app/product_output_bundle.py` — reduce to orchestration façade and stable public receipt.
- `app/product_excel.py` — fix workbook factory typing and remove dead row conversion.
- `app/main.py` — consume the required receipt fields directly.
- `scripts/benchmark_products.py` — consume the required receipt timing directly.
- `tests/test_product_json.py` — retain JSON contract checks through the compatibility façade.
- `tests/test_product_output_bundle.py` — keep façade integration and merge/limit coverage.
- `tests/test_product_excel.py` — lock workbook behavior during cleanup.
- `tests/test_main.py` — use a complete typed bundle receipt and assert strict receipt handling.

## Task 1: Extract and freeze the product output snapshot

**Files:**

- Create: `app/product_output_snapshot.py`
- Create: `tests/test_product_output_snapshot.py`
- Modify: `app/product_json.py`
- Modify: `app/product_gallery.py`
- Test: `tests/test_product_json.py`
- Test: `tests/test_product_gallery.py`

- [ ] **Step 1: Write failing ownership and immutability tests**

Create `tests/test_product_output_snapshot.py`:

```python
import json

import pytest

from app.product_models import ProductCollection, ProductRecord
from app.product_output_snapshot import build_product_output_snapshot


def collection() -> ProductCollection:
    return ProductCollection.from_records(
        [ProductRecord.success_fixture("1"), ProductRecord.success_fixture("2")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )


def test_snapshot_payload_and_rows_are_recursively_read_only() -> None:
    snapshot = build_product_output_snapshot(collection())

    with pytest.raises(TypeError):
        snapshot.payload["schema_version"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.product_rows[0]["product_id"] = "changed"  # type: ignore[index]
    products = snapshot.payload["products"]
    assert isinstance(products, tuple)
    assert snapshot.product_ids == ("1", "2")


def test_snapshot_serializes_before_freezing() -> None:
    snapshot = build_product_output_snapshot(collection())
    payload = json.loads(snapshot.json_text)

    assert payload["schema_version"] == 1
    assert [item["product_id"] for item in payload["products"]] == ["1", "2"]
```

Append this compatibility test to `tests/test_product_json.py`:

```python
def test_product_json_reexports_snapshot_api() -> None:
    from app import product_json, product_output_snapshot

    assert (
        product_json.ProductOutputSnapshot
        is product_output_snapshot.ProductOutputSnapshot
    )
    assert (
        product_json.build_product_output_snapshot
        is product_output_snapshot.build_product_output_snapshot
    )
    assert product_json.product_payload is product_output_snapshot.product_payload
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_product_output_snapshot.py tests/test_product_json.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.product_output_snapshot'`.

- [ ] **Step 3: Implement the immutable snapshot owner**

Create `app/product_output_snapshot.py`:

```python
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from app.product_models import ProductCollection


def product_payload(collection: ProductCollection) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_site": "web-scraping.dev",
        "generated_at": collection.generated_at,
        "summary": {
            "total": collection.summary.total,
            "success": collection.summary.success,
            "partial": collection.summary.partial,
            "failed": collection.summary.failed,
        },
        "products": [record.to_primitive() for record in collection.records],
    }


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ProductOutputSnapshot:
    payload: Mapping[str, object]
    product_rows: tuple[Mapping[str, object], ...]
    json_text: str
    product_ids: tuple[str, ...]


def build_product_output_snapshot(
    collection: ProductCollection,
) -> ProductOutputSnapshot:
    mutable_payload = product_payload(collection)
    raw_products = mutable_payload.get("products")
    if not isinstance(raw_products, list):
        raise TypeError("product payload products must be a list")
    json_text = json.dumps(
        mutable_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ) + "\n"
    frozen_payload = cast(Mapping[str, object], _freeze(mutable_payload))
    frozen_products = frozen_payload.get("products")
    if not isinstance(frozen_products, tuple):
        raise TypeError("frozen product payload products must be a tuple")
    rows = cast(tuple[Mapping[str, object], ...], frozen_products)
    return ProductOutputSnapshot(
        payload=frozen_payload,
        product_rows=rows,
        json_text=json_text,
        product_ids=tuple(str(row["product_id"]) for row in rows),
    )


__all__ = [
    "ProductOutputSnapshot",
    "build_product_output_snapshot",
    "product_payload",
]
```

Replace `app/product_json.py` with:

```python
from __future__ import annotations

from app.product_models import ProductCollection
from app.product_output_snapshot import (
    ProductOutputSnapshot,
    build_product_output_snapshot,
    product_payload,
)


def render_product_json(
    collection: ProductCollection,
    *,
    snapshot: ProductOutputSnapshot | None = None,
) -> str:
    return (snapshot or build_product_output_snapshot(collection)).json_text


__all__ = [
    "ProductOutputSnapshot",
    "build_product_output_snapshot",
    "product_payload",
    "render_product_json",
]
```

Change the snapshot import in `app/product_gallery.py` to:

```python
from app.product_output_snapshot import (
    ProductOutputSnapshot,
    build_product_output_snapshot,
)
```

- [ ] **Step 4: Run snapshot, JSON, and gallery tests and verify GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_product_output_snapshot.py tests/test_product_json.py tests/test_product_gallery.py -q
```

Expected: all selected tests pass with no warnings.

- [ ] **Step 5: Commit the snapshot extraction**

```powershell
git add app/product_output_snapshot.py app/product_json.py app/product_gallery.py tests/test_product_output_snapshot.py tests/test_product_json.py
git commit -m "refactor: extract immutable product output snapshot"
```

## Task 2: Extract bounded artifact writers

**Files:**

- Create: `app/product_artifact_writers.py`
- Create: `tests/test_product_artifact_writers.py`
- Integration target: `app/product_output_bundle.py`

- [ ] **Step 1: Write failing writer receipt and shutdown tests**

Create `tests/test_product_artifact_writers.py`:

```python
from pathlib import Path

import pytest

import app.product_artifact_writers as writer_module
from app.product_artifact_writers import ProductArtifactWriters
from app.product_models import ProductCollection, ProductRecord
from app.product_output_snapshot import build_product_output_snapshot


def collection() -> ProductCollection:
    return ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )


def test_writers_create_exact_artifacts_and_complete_receipt(tmp_path: Path) -> None:
    value = collection()
    snapshot = build_product_output_snapshot(value)

    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)

    assert sorted(receipt.bytes_by_file) == [
        "gallery.html",
        "products.json",
        "products.xlsx",
    ]
    assert receipt.product_ids == ("1",)
    assert receipt.excel.product_ids == ("1",)
    assert receipt.json_write_ms >= 0
    assert receipt.gallery_write_ms >= 0
    assert receipt.excel_write_ms >= 0


def test_writer_failure_is_propagated_and_executor_cancels_pending_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutdown_calls: list[tuple[bool, bool]] = []
    real_executor = writer_module.ThreadPoolExecutor

    class RecordingExecutor(real_executor):
        def shutdown(
            self, wait: bool = True, *, cancel_futures: bool = False
        ) -> None:
            shutdown_calls.append((wait, cancel_futures))
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(writer_module, "ThreadPoolExecutor", RecordingExecutor)
    monkeypatch.setattr(
        writer_module,
        "render_gallery",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("gallery failed")),
    )
    value = collection()

    with pytest.raises(RuntimeError, match="gallery failed"):
        ProductArtifactWriters.write(
            value,
            tmp_path,
            snapshot=build_product_output_snapshot(value),
        )

    assert shutdown_calls == [(True, True)]


def test_writer_pool_is_bounded_to_three_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_counts: list[int] = []
    real_executor = writer_module.ThreadPoolExecutor

    class RecordingExecutor(real_executor):
        def __init__(self, max_workers: int, **kwargs: object) -> None:
            worker_counts.append(max_workers)
            super().__init__(max_workers=max_workers, **kwargs)

    monkeypatch.setattr(writer_module, "ThreadPoolExecutor", RecordingExecutor)
    value = collection()
    ProductArtifactWriters.write(
        value,
        tmp_path,
        snapshot=build_product_output_snapshot(value),
    )

    assert worker_counts == [3]
```

- [ ] **Step 2: Run the writer tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_product_artifact_writers.py -q
```

Expected: collection fails because `app.product_artifact_writers` does not exist.

- [ ] **Step 3: Implement the fixed three-writer component**

Create `app/product_artifact_writers.py`:

```python
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from app.product_excel import ProductExcel, ProductWriteReceipt
from app.product_gallery import render_gallery
from app.product_models import ProductCollection
from app.product_output_snapshot import ProductOutputSnapshot


_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class ArtifactWriteReceipt:
    product_ids: tuple[str, ...]
    excel: ProductWriteReceipt
    bytes_by_file: dict[str, int]
    json_write_ms: float
    gallery_write_ms: float
    excel_write_ms: float


def _write_text(path: Path, content: str) -> int:
    path.write_text(content, encoding="utf-8")
    return path.stat().st_size


def _render_and_write_gallery(
    collection: ProductCollection,
    directory: Path,
    snapshot: ProductOutputSnapshot,
) -> int:
    return _write_text(
        directory / "gallery.html",
        render_gallery(collection, snapshot=snapshot),
    )


def _timed_call(
    function: Callable[..., _T], *args: object, **kwargs: object
) -> tuple[_T, float]:
    started = time.perf_counter()
    result = function(*args, **kwargs)
    return result, (time.perf_counter() - started) * 1000.0


class ProductArtifactWriters:
    @staticmethod
    def write(
        collection: ProductCollection,
        directory: Path,
        *,
        snapshot: ProductOutputSnapshot,
    ) -> ArtifactWriteReceipt:
        executor = ThreadPoolExecutor(
            max_workers=3,
            thread_name_prefix="product-output",
        )
        try:
            excel_future = executor.submit(
                _timed_call,
                ProductExcel.write,
                directory / "products.xlsx",
                list(collection.records),
                primitive_rows=snapshot.product_rows,
            )
            json_future = executor.submit(
                _timed_call,
                _write_text,
                directory / "products.json",
                snapshot.json_text,
            )
            gallery_future = executor.submit(
                _timed_call,
                _render_and_write_gallery,
                collection,
                directory,
                snapshot,
            )
            excel_receipt, excel_ms = excel_future.result()
            json_bytes, json_ms = json_future.result()
            gallery_bytes, gallery_ms = gallery_future.result()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        return ArtifactWriteReceipt(
            product_ids=snapshot.product_ids,
            excel=excel_receipt,
            bytes_by_file={
                "products.xlsx": excel_receipt.bytes_written,
                "products.json": json_bytes,
                "gallery.html": gallery_bytes,
            },
            json_write_ms=json_ms,
            gallery_write_ms=gallery_ms,
            excel_write_ms=excel_ms,
        )


__all__ = ["ArtifactWriteReceipt", "ProductArtifactWriters"]
```

- [ ] **Step 4: Run writer and existing output tests and verify GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_product_artifact_writers.py tests/test_product_excel.py tests/test_product_gallery.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the writer component**

```powershell
git add app/product_artifact_writers.py tests/test_product_artifact_writers.py
git commit -m "refactor: extract product artifact writers"
```

## Task 3: Extract staging bundle verification

**Files:**

- Create: `app/product_bundle_verifier.py`
- Create: `tests/test_product_bundle_verifier.py`

- [ ] **Step 1: Write failing ID and missing-file verification tests**

Create `tests/test_product_bundle_verifier.py`:

```python
from dataclasses import replace
from pathlib import Path

import pytest

from app.product_artifact_writers import ProductArtifactWriters
from app.product_bundle_verifier import ProductBundleVerifier
from app.product_models import ProductCollection, ProductRecord
from app.product_output_snapshot import build_product_output_snapshot


def collection() -> ProductCollection:
    return ProductCollection.from_records(
        [ProductRecord.success_fixture("1")],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )


def test_verifier_accepts_three_consistent_artifacts(tmp_path: Path) -> None:
    value = collection()
    snapshot = build_product_output_snapshot(value)
    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)

    elapsed_ms = ProductBundleVerifier.verify(snapshot, receipt, tmp_path)

    assert elapsed_ms >= 0


def test_verifier_rejects_json_id_drift(tmp_path: Path) -> None:
    value = collection()
    snapshot = build_product_output_snapshot(value)
    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)
    (tmp_path / "products.json").write_text(
        '{"products":[{"product_id":"2"}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="JSON IDs"):
        ProductBundleVerifier.verify(snapshot, receipt, tmp_path)


def test_verifier_rejects_excel_id_drift(tmp_path: Path) -> None:
    value = collection()
    snapshot = build_product_output_snapshot(value)
    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)
    drifted_excel = replace(receipt.excel, product_ids=("2",))
    drifted_receipt = replace(receipt, excel=drifted_excel)

    with pytest.raises(ValueError, match="Excel IDs"):
        ProductBundleVerifier.verify(snapshot, drifted_receipt, tmp_path)


@pytest.mark.parametrize(
    "product_ids",
    [[], ["1", "1"], ["2", "1"]],
)
def test_verifier_rejects_missing_duplicate_or_reordered_json_ids(
    tmp_path: Path, product_ids: list[str]
) -> None:
    import json

    value = collection()
    snapshot = build_product_output_snapshot(value)
    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)
    payload = {
        "products": [{"product_id": product_id} for product_id in product_ids]
    }
    (tmp_path / "products.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="JSON IDs"):
        ProductBundleVerifier.verify(snapshot, receipt, tmp_path)


def test_verifier_rejects_missing_gallery(tmp_path: Path) -> None:
    value = collection()
    snapshot = build_product_output_snapshot(value)
    receipt = ProductArtifactWriters.write(value, tmp_path, snapshot=snapshot)
    (tmp_path / "gallery.html").unlink()

    with pytest.raises(ValueError, match="gallery.html"):
        ProductBundleVerifier.verify(snapshot, receipt, tmp_path)
```

- [ ] **Step 2: Run verifier tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_product_bundle_verifier.py -q
```

Expected: collection fails because `app.product_bundle_verifier` does not exist.

- [ ] **Step 3: Implement the verifier**

Create `app/product_bundle_verifier.py`:

```python
from __future__ import annotations

import json
import time
from pathlib import Path

from app.product_artifact_writers import ArtifactWriteReceipt
from app.product_output_snapshot import ProductOutputSnapshot


class ProductBundleVerifier:
    @staticmethod
    def verify(
        snapshot: ProductOutputSnapshot,
        receipt: ArtifactWriteReceipt,
        directory: Path,
    ) -> float:
        started = time.perf_counter()
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
        return (time.perf_counter() - started) * 1000.0


__all__ = ["ProductBundleVerifier"]
```

- [ ] **Step 4: Run verifier tests and verify GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_product_bundle_verifier.py -q
```

Expected: all verifier tests pass.

- [ ] **Step 5: Commit the verifier**

```powershell
git add app/product_bundle_verifier.py tests/test_product_bundle_verifier.py
git commit -m "refactor: extract product bundle verifier"
```

## Task 4: Extract atomic directory transaction

**Files:**

- Create: `app/product_bundle_transaction.py`
- Create: `tests/test_product_bundle_transaction.py`
- Integration target: `app/product_output_bundle.py`

- [ ] **Step 1: Write failing transaction rollback and cleanup tests**

Create `tests/test_product_bundle_transaction.py`:

```python
import os
import time
from pathlib import Path

import pytest

import app.product_bundle_transaction as transaction_module
from app.excel_store import OutputLockedError
from app.product_bundle_transaction import ProductBundleTransaction


def test_commit_replaces_target_and_removes_backup(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    transaction = ProductBundleTransaction(target)

    with transaction.staging_directory() as staging:
        (staging / "new.txt").write_text("new", encoding="utf-8")
        transaction.commit(staging)

    assert not (target / "old.txt").exists()
    assert (target / "new.txt").read_text(encoding="utf-8") == "new"
    assert not list(tmp_path.glob(".demo.backup-*"))


def test_second_replace_failure_restores_previous_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    transaction = ProductBundleTransaction(target)
    real_replace = transaction_module.os.replace
    calls = {"count": 0}

    def fail_second(source: Path, destination: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise PermissionError("locked")
        real_replace(source, destination)

    monkeypatch.setattr(transaction_module.os, "replace", fail_second)
    with pytest.raises(OutputLockedError):
        with transaction.staging_directory() as staging:
            (staging / "new.txt").write_text("new", encoding="utf-8")
            transaction.commit(staging)

    assert (target / "old.txt").read_text(encoding="utf-8") == "old"


def test_restore_failure_reports_that_previous_bundle_was_not_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    transaction = ProductBundleTransaction(target)
    real_replace = transaction_module.os.replace
    calls = {"count": 0}

    def fail_commit_and_restore(source: Path, destination: Path) -> None:
        calls["count"] += 1
        if calls["count"] >= 2:
            raise PermissionError("locked")
        real_replace(source, destination)

    monkeypatch.setattr(
        transaction_module.os,
        "replace",
        fail_commit_and_restore,
    )
    with pytest.raises(OutputLockedError, match="could not be restored"):
        with transaction.staging_directory() as staging:
            (staging / "new.txt").write_text("new", encoding="utf-8")
            transaction.commit(staging)


def test_cleanup_only_removes_old_generated_siblings(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    stale = tmp_path / ".demo.staging-old"
    fresh = tmp_path / ".demo.backup-fresh"
    unrelated = tmp_path / ".demo-not-generated"
    for path in (stale, fresh, unrelated):
        path.mkdir()
    old = time.time() - 48 * 60 * 60
    os.utime(stale, (old, old))

    removed = ProductBundleTransaction(target).cleanup_stale_siblings(
        max_age_seconds=24 * 60 * 60
    )

    assert removed == (stale,)
    assert not stale.exists()
    assert fresh.exists()
    assert unrelated.exists()
```

- [ ] **Step 2: Run transaction tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_product_bundle_transaction.py -q
```

Expected: collection fails because `app.product_bundle_transaction` does not exist.

- [ ] **Step 3: Move the existing lock and transaction behavior behind one component**

Create `app/product_bundle_transaction.py` with the existing platform lock helpers moved unchanged and this public component:

```python
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - exercised by Linux CI.
    import fcntl

from app.excel_store import OutputLockedError


BUNDLE_LOCK_TIMEOUT_SECONDS: float = 30.0
_BUNDLE_LOCKS: dict[str, threading.RLock] = {}
_BUNDLE_LOCKS_GUARD = threading.Lock()


def _lock_for_target(target_dir: Path) -> threading.RLock:
    key = str(target_dir.resolve())
    with _BUNDLE_LOCKS_GUARD:
        lock = _BUNDLE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _BUNDLE_LOCKS[key] = lock
        return lock


def _acquire_file_lock(handle) -> None:
    if os.name == "nt":
        deadline = time.monotonic() + BUNDLE_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise OutputLockedError(
                        "Timed out waiting for the product output lock"
                    ) from exc
                time.sleep(0.05)
    else:  # pragma: no cover - exercised by Linux CI.
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_file_lock(handle) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover - exercised by Linux CI.
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ProductBundleTransaction:
    def __init__(self, target_dir: Path) -> None:
        self.target_dir = Path(target_dir)
        self.target_dir.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def locked(self):
        with _lock_for_target(self.target_dir):
            lock_path = self.target_dir.with_name(f".{self.target_dir.name}.lock")
            with lock_path.open("a+b") as handle:
                if os.name == "nt":
                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == 0:
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                _acquire_file_lock(handle)
                try:
                    yield self
                finally:
                    had_active_exception = sys.exc_info()[0] is not None
                    try:
                        _release_file_lock(handle)
                    except OSError:
                        if not had_active_exception:
                            raise

    @contextmanager
    def staging_directory(self):
        staging = self._sibling_path("staging")
        staging.mkdir(parents=True)
        try:
            yield staging
        finally:
            if staging.exists():
                had_active_exception = sys.exc_info()[0] is not None
                try:
                    shutil.rmtree(staging)
                except OSError:
                    if not had_active_exception:
                        raise

    def cleanup_stale_siblings(
        self, *, max_age_seconds: float
    ) -> tuple[Path, ...]:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        generated_name = re.compile(
            rf"\.{re.escape(self.target_dir.name)}\."
            rf"(?:staging|backup)-[0-9a-f]{{32}}"
        )
        now = time.time()
        removed: list[Path] = []
        for candidate in self.target_dir.parent.iterdir():
            if (
                candidate.is_symlink()
                or not candidate.is_dir()
                or generated_name.fullmatch(candidate.name) is None
            ):
                continue
            if now - candidate.stat().st_mtime > max_age_seconds:
                shutil.rmtree(candidate)
                removed.append(candidate)
        return tuple(removed)

    def commit(self, staging: Path) -> None:
        backup: Path | None = None
        try:
            if self.target_dir.exists():
                backup = self._sibling_path("backup")
                os.replace(self.target_dir, backup)
            os.replace(staging, self.target_dir)
        except OSError as exc:
            if backup is not None and backup.exists() and not self.target_dir.exists():
                try:
                    os.replace(backup, self.target_dir)
                except OSError as restore_exc:
                    raise OutputLockedError(
                        "Close open output files and retry; previous bundle "
                        f"could not be restored: {self.target_dir}"
                    ) from restore_exc
            raise OutputLockedError(
                f"Close open output files and retry: {self.target_dir}"
            ) from exc
        if backup is not None and backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError:
                # The second rename is the commit point. Leave a locked
                # backup for a later stale-sibling cleanup rather than
                # reporting an ambiguous failure after commit.
                pass

    def _sibling_path(self, role: str) -> Path:
        return self.target_dir.with_name(
            f".{self.target_dir.name}.{role}-{uuid.uuid4().hex}"
        )


__all__ = [
    "BUNDLE_LOCK_TIMEOUT_SECONDS",
    "ProductBundleTransaction",
]
```

- [ ] **Step 4: Add the existing bounded Windows lock test to the new owner**

Append to `tests/test_product_bundle_transaction.py`:

```python
@pytest.mark.skipif(os.name != "nt", reason="Windows lock semantics only")
def test_windows_lock_acquisition_has_a_bounded_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = (tmp_path / "demo.lock").open("a+b")
    try:
        monkeypatch.setattr(
            transaction_module,
            "BUNDLE_LOCK_TIMEOUT_SECONDS",
            0.0,
        )
        monkeypatch.setattr(
            transaction_module.msvcrt,
            "locking",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("locked")),
        )
        with pytest.raises(OutputLockedError):
            transaction_module._acquire_file_lock(handle)
    finally:
        handle.close()


def test_staging_cleanup_does_not_mask_active_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transaction = ProductBundleTransaction(tmp_path / "demo")
    monkeypatch.setattr(
        transaction_module.shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    with pytest.raises(RuntimeError, match="writer failed"):
        with transaction.staging_directory():
            raise RuntimeError("writer failed")


def test_lock_release_does_not_mask_active_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transaction = ProductBundleTransaction(tmp_path / "demo")
    monkeypatch.setattr(
        transaction_module,
        "_release_file_lock",
        lambda handle: (_ for _ in ()).throw(OSError("unlock failed")),
    )

    with pytest.raises(RuntimeError, match="writer failed"):
        with transaction.locked():
            raise RuntimeError("writer failed")


def test_cleanup_rejects_non_positive_threshold(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_age_seconds"):
        ProductBundleTransaction(tmp_path / "demo").cleanup_stale_siblings(
            max_age_seconds=0
        )


def test_different_targets_have_independent_process_locks(tmp_path: Path) -> None:
    first = transaction_module._lock_for_target(tmp_path / "first")
    second = transaction_module._lock_for_target(tmp_path / "second")

    assert first is not second
```

- [ ] **Step 5: Run transaction tests and verify GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_product_bundle_transaction.py -q
```

Expected: all transaction tests pass; the Windows-only case runs on Windows and is skipped on Linux.

- [ ] **Step 6: Commit the transaction component**

```powershell
git add app/product_bundle_transaction.py tests/test_product_bundle_transaction.py
git commit -m "refactor: extract product bundle transaction"
```

## Task 5: Rebuild `ProductOutputBundle` as a façade

**Files:**

- Modify: `app/product_output_bundle.py`
- Modify: `tests/test_product_output_bundle.py`
- Test: `tests/test_product_artifact_writers.py`
- Test: `tests/test_product_bundle_verifier.py`
- Test: `tests/test_product_bundle_transaction.py`

- [ ] **Step 1: Add failing façade sequencing and receipt tests**

Append to `tests/test_product_output_bundle.py`:

```python
from app.product_artifact_writers import ProductArtifactWriters


def test_bundle_returns_complete_required_receipt(tmp_path: Path) -> None:
    receipt = ProductOutputBundle(tmp_path / "demo").write(collection("1"))

    assert receipt.product_ids == ("1",)
    assert sorted(receipt.bytes_by_file) == [
        "gallery.html",
        "products.json",
        "products.xlsx",
    ]
    assert receipt.payload_build_ms >= 0
    assert receipt.json_write_ms >= 0
    assert receipt.gallery_write_ms >= 0
    assert receipt.excel_write_ms >= 0
    assert receipt.verify_ms >= 0
    assert receipt.total_local_ms >= 0


def test_bundle_delegates_writes_to_extracted_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"count": 0}
    real_write = ProductArtifactWriters.write

    def counted(value, directory, *, snapshot):
        calls["count"] += 1
        return real_write(value, directory, snapshot=snapshot)

    monkeypatch.setattr(ProductArtifactWriters, "write", counted)
    ProductOutputBundle(tmp_path / "demo").write(collection("1"))

    assert calls["count"] == 1


def test_bundle_rejects_merged_records_above_ten(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    initial = ProductCollection.from_records(
        [ProductRecord.success_fixture(str(index)) for index in range(1, 11)],
        generated_at="2026-07-16T20:00:00+08:00",
        blocked=False,
    )
    ProductOutputBundle(target).write(initial)

    with pytest.raises(ValueError, match="cannot exceed 10"):
        ProductOutputBundle(target).write(collection("11"))
```

- [ ] **Step 2: Run the façade tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_product_output_bundle.py -q
```

Expected: `test_bundle_delegates_writes_to_extracted_component` fails with
`assert 0 == 1` because the old bundle still owns writer scheduling instead of
calling `ProductArtifactWriters.write()`.

- [ ] **Step 3: Replace the bundle module with orchestration-only code**

Replace `app/product_output_bundle.py` with:

```python
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from app.product_artifact_writers import ProductArtifactWriters
from app.product_bundle_transaction import ProductBundleTransaction
from app.product_bundle_verifier import ProductBundleVerifier
from app.product_excel import ProductExcel, ProductWriteReceipt
from app.product_models import ProductCollection, ProductRecord
from app.product_output_snapshot import build_product_output_snapshot


BUNDLE_LIMIT: int = 10


@dataclass(frozen=True, slots=True)
class BundleWriteReceipt:
    product_ids: tuple[str, ...]
    excel: ProductWriteReceipt
    bytes_by_file: dict[str, int]
    payload_build_ms: float
    json_write_ms: float
    gallery_write_ms: float
    excel_write_ms: float
    verify_ms: float
    total_local_ms: float


class ProductOutputBundle:
    def __init__(self, target_dir: Path) -> None:
        self.target_dir = Path(target_dir)
        self._transaction = ProductBundleTransaction(self.target_dir)

    def read_product_ids(self) -> list[str]:
        return [
            record.product_id
            for record in ProductExcel.read(self.target_dir / "products.xlsx")
        ]

    def cleanup_stale_siblings(
        self, *, max_age_seconds: float
    ) -> tuple[Path, ...]:
        return self._transaction.cleanup_stale_siblings(
            max_age_seconds=max_age_seconds
        )

    def write(self, new_collection: ProductCollection) -> BundleWriteReceipt:
        with self._transaction.locked():
            return self._write_locked(new_collection)

    def _write_locked(
        self, new_collection: ProductCollection
    ) -> BundleWriteReceipt:
        started = time.perf_counter()
        merged_records = self._merged_records(new_collection)
        if len(merged_records) > BUNDLE_LIMIT:
            raise ValueError(
                f"product bundle cannot exceed {BUNDLE_LIMIT} products"
            )
        merged_collection = ProductCollection.from_records(
            list(merged_records),
            generated_at=new_collection.generated_at,
            blocked=new_collection.summary.blocked,
        )
        snapshot_started = time.perf_counter()
        snapshot = build_product_output_snapshot(merged_collection)
        payload_build_ms = (time.perf_counter() - snapshot_started) * 1000.0
        self.cleanup_stale_siblings(max_age_seconds=24 * 60 * 60)

        with self._transaction.staging_directory() as staging:
            artifact_receipt = ProductArtifactWriters.write(
                merged_collection,
                staging,
                snapshot=snapshot,
            )
            verify_ms = ProductBundleVerifier.verify(
                snapshot,
                artifact_receipt,
                staging,
            )
            self._transaction.commit(staging)

        return BundleWriteReceipt(
            product_ids=artifact_receipt.product_ids,
            excel=artifact_receipt.excel,
            bytes_by_file=dict(artifact_receipt.bytes_by_file),
            payload_build_ms=payload_build_ms,
            json_write_ms=artifact_receipt.json_write_ms,
            gallery_write_ms=artifact_receipt.gallery_write_ms,
            excel_write_ms=artifact_receipt.excel_write_ms,
            verify_ms=verify_ms,
            total_local_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _merged_records(
        self, new_collection: ProductCollection
    ) -> list[ProductRecord]:
        existing_workbook = self.target_dir / "products.xlsx"
        if not existing_workbook.exists():
            return list(new_collection.records)
        return ProductExcel.merge_existing(
            existing_workbook,
            list(new_collection.records),
        )


__all__ = [
    "ProductOutputBundle",
    "BundleWriteReceipt",
    "BUNDLE_LIMIT",
]
```

- [ ] **Step 4: Move implementation-detail tests to their new owners**

Delete these tests from `tests/test_product_output_bundle.py` because Tasks 2–4 now cover the same behavior through the owning modules:

```text
test_failed_directory_swap_restores_previous_bundle
test_failed_initial_directory_swap_raises_output_locked_error
test_staging_cleanup_does_not_mask_writer_failure
test_lock_release_does_not_mask_writer_failure
test_windows_lock_acquisition_has_a_bounded_wait
test_writer_shutdown_cancels_pending_futures
test_writer_active_counter_peaks_at_three
test_cleanup_stale_siblings_only_removes_generated_old_dirs
test_cleanup_stale_siblings_rejects_non_positive_threshold
```

Keep façade-level coverage for exact outputs, merge/upsert, same-target serialization, shared snapshot rows, writer failure preserving the old bundle, bundle limit, complete receipt, and one snapshot build.

Update `test_writer_failure_leaves_existing_bundle_and_cleans_siblings` to
patch `app.product_artifact_writers.render_gallery`, because gallery rendering
is now owned by the writer module:

```python
import app.product_artifact_writers as writer_module


def fail_gallery(*args, **kwargs):
    raise RuntimeError("gallery writer failed")


monkeypatch.setattr(writer_module, "render_gallery", fail_gallery)
```

- [ ] **Step 5: Run all output component tests and verify GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest `
  tests/test_product_output_snapshot.py `
  tests/test_product_artifact_writers.py `
  tests/test_product_bundle_verifier.py `
  tests/test_product_bundle_transaction.py `
  tests/test_product_output_bundle.py `
  -q
```

Expected: all selected tests pass; no test imports removed private helpers from `product_output_bundle`.

- [ ] **Step 6: Commit the façade integration**

```powershell
git add app/product_output_bundle.py tests/test_product_output_bundle.py
git commit -m "refactor: reduce product output bundle to facade"
```

## Task 6: Enforce the receipt contract and clean Excel internals

**Files:**

- Modify: `app/main.py`
- Modify: `scripts/benchmark_products.py`
- Modify: `app/product_excel.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_product_excel.py`
- Test: `tests/test_benchmark_products.py`

- [ ] **Step 1: Make the CLI fake return the production receipt type**

Add imports to `tests/test_main.py`:

```python
from app.product_excel import ProductWriteReceipt
from app.product_output_bundle import BundleWriteReceipt
```

Replace `_FakeProductOutputBundle.write()` with:

```python
    def write(
        self, collection: ProductCollection
    ) -> BundleWriteReceipt:
        self.write_calls += 1
        if _FakeProductOutputBundle.raise_on_write is not None:
            raise _FakeProductOutputBundle.raise_on_write
        product_ids = tuple(record.product_id for record in collection.records)
        return BundleWriteReceipt(
            product_ids=product_ids,
            excel=ProductWriteReceipt(
                product_ids=product_ids,
                row_count=len(product_ids),
                bytes_written=100,
            ),
            bytes_by_file={
                "products.xlsx": 100,
                "products.json": 200,
                "gallery.html": 300,
            },
            payload_build_ms=1.0,
            json_write_ms=2.0,
            gallery_write_ms=3.0,
            excel_write_ms=4.0,
            verify_ms=5.0,
            total_local_ms=15.0,
        )
```

Add a test that forbids the old disk fallback:

```python
def test_collect_products_rejects_incomplete_bundle_receipt(
    stub_dependencies: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class IncompleteBundle(_FakeProductOutputBundle):
        def write(self, collection: ProductCollection) -> object:
            self.write_calls += 1
            return object()

    monkeypatch.setattr(main, "ProductOutputBundle", IncompleteBundle)

    rc = execute(products_live_args(stub_dependencies))

    assert rc == 5


def test_collect_products_uses_required_bundle_receipt_fields(
    stub_dependencies: dict,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    rc = execute(products_live_args(stub_dependencies))

    assert rc == 0
    assert "local_output_ms=15.000" in caplog.text
    assert "writers=3" in caplog.text
    assert "records=1" in caplog.text
    assert "bundle_bytes=600" in caplog.text
```

- [ ] **Step 2: Run the CLI test and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_main.py::test_collect_products_uses_required_bundle_receipt_fields -q
```

Expected: `test_collect_products_rejects_incomplete_bundle_receipt` fails with
`assert 0 == 5` because the old implementation silently falls back to files,
collection summary, and zero-valued timing fields.

- [ ] **Step 3: Replace defensive receipt reads in `app/main.py`**

Move receipt extraction into the same `try` block as
`ProductOutputBundle.write()` so an invalid production receipt is logged as an
unexpected output error and returns 5. Replace the receipt fallback block with:

```python
    bytes_by_file = dict(bundle_receipt.bytes_by_file)
    bundle_bytes = sum(bytes_by_file.values())
    writer_count = len(bytes_by_file)
    record_count = len(bundle_receipt.product_ids)
    local_output_ms = bundle_receipt.total_local_ms or elapsed_output_ms
```

Replace the five timing `getattr` calls in the bundle log with direct fields:

```python
        bundle_receipt.payload_build_ms,
        bundle_receipt.json_write_ms,
        bundle_receipt.gallery_write_ms,
        bundle_receipt.excel_write_ms,
        bundle_receipt.verify_ms,
```

In `scripts/benchmark_products.py`, replace:

```python
float(getattr(receipt, "payload_build_ms", 0.0))
```

with:

```python
receipt.payload_build_ms
```

Also consume the required product IDs directly:

```python
len(receipt.product_ids)
```

- [ ] **Step 4: Clean `ProductExcel` during the green refactor phase**

Add this import to `app/product_excel.py`:

```python
from openpyxl.worksheet.worksheet import Worksheet
```

Change the workbook factory annotation to:

```python
    @staticmethod
    def _workbook_for(path: Path) -> tuple[Workbook, Worksheet]:
```

Delete the unused `_row_for()` method. Keep `PRODUCT_COLUMNS`, `write()`, `read()`, and `merge_existing()` unchanged.

Append to `tests/test_product_excel.py`:

```python
def test_workbook_factory_returns_named_products_sheet(tmp_path: Path) -> None:
    workbook, sheet = ProductExcel._workbook_for(tmp_path / "products.xlsx")

    assert workbook.active is sheet
    assert sheet.title == "products"
    assert [cell.value for cell in sheet[1]] == PRODUCT_COLUMNS
```

- [ ] **Step 5: Run CLI, benchmark, and Excel tests and verify GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_main.py tests/test_benchmark_products.py tests/test_product_excel.py -q
```

Expected: all selected tests pass and product metrics log the complete typed receipt.

- [ ] **Step 6: Commit receipt and Excel cleanup**

```powershell
git add app/main.py scripts/benchmark_products.py app/product_excel.py tests/test_main.py tests/test_product_excel.py
git commit -m "refactor: enforce product bundle receipt contract"
```

## Task 7: Run full offline release gates

**Files:**

- Verify: all files changed by Tasks 1–6
- Reference: `docs/superpowers/specs/2026-07-18-product-output-pipeline-refactor-design.md`

- [ ] **Step 1: Run the complete test suite**

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass; the total is greater than the 273-test baseline because four component test modules were added.

- [ ] **Step 2: Run coverage and the core verifier**

```powershell
& .\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=json:artifacts/coverage.json -q
& .\.venv\Scripts\python.exe -m scripts.verify_core --coverage-json artifacts/coverage.json
```

Expected: both commands exit 0 and the verifier reports all configured coverage thresholds satisfied.

- [ ] **Step 3: Run product verification and offline benchmark**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_verify_products.py -q
& .\.venv\Scripts\python.exe -m scripts.benchmark_products --counts 1,5,10 --iterations 5
```

Expected: the product verifier tests generate known bundles under pytest temporary
directories and validate them offline; benchmark JSON reports `writer_workers`
equal to 3, bounded queue depth, and no network/browser activity. For an existing
bundle, the equivalent CLI check is `python -m scripts.verify_products
--output-dir <bundle-directory>`.

- [ ] **Step 4: Run dependency, whitespace, artifact, and secret checks**

```powershell
& .\.venv\Scripts\python.exe -m pip check
git diff --check
git ls-files browser-profile outputs artifacts
git grep -n -I -E 'MINIMAX_API_KEY=|Cookie:|Authorization: Bearer' -- . ':!docs/superpowers/plans/2026-07-18-product-output-pipeline-refactor.md'
```

Expected:

- `pip check` reports no broken requirements;
- `git diff --check` prints nothing;
- tracked runtime directories list only their `.gitkeep` files;
- secret scan prints no credential values.

- [ ] **Step 5: Review the complete branch diff against the spec**

```powershell
git diff --stat origin/main...HEAD
git diff --name-status origin/main...HEAD
git status --short --branch
```

Expected: only the approved spec/plan, output refactor modules, and their tests are changed; `app/sites/web_scraping_dev.py`, `app/product_runner.py`, and the gallery template body are unchanged. Existing untracked workspace files remain unmodified and uncommitted.

- [ ] **Step 6: Request code review before integration**

Provide the reviewer with:

```text
DESCRIPTION: Extracted immutable product output snapshots, bounded local writers,
staging verification, atomic directory transactions, strict receipts, and a thin
ProductOutputBundle façade while preserving all external contracts.
PLAN_OR_REQUIREMENTS: docs/superpowers/specs/2026-07-18-product-output-pipeline-refactor-design.md
BASE_SHA: 1aedf3c
HEAD_SHA: output of git rev-parse HEAD
```

Expected: fix all Critical and Important findings, rerun Steps 1–5, then use the branch-finishing workflow to choose merge, PR, or cleanup.

## Completion audit (2026-07-18)

The implementation through `9941e77` was independently reviewed against the
approved design. The audit found no Critical issues. Both Important transaction
issues were corrected with test-first regressions:

- stale cleanup now accepts only complete generated UUID sibling names and
  explicitly skips symbolic links;
- the second successful rename is the commit point, so a locked obsolete backup
  is retained for later stale cleanup without reporting an ambiguous write
  failure.

The audit also removed the benchmark fallback for required `product_ids`, fixed
the product-verification command above, and updated the CLI receipt comment.

Fresh offline evidence after the corrections:

- full suite: `294 passed`;
- coverage suite: `294 passed`, with all `scripts.verify_core` thresholds met;
- product verifier suite: `16 passed`;
- product benchmark: `writer_workers=3`, `max_queue_depth=2`, and positive median
  speedups for 1, 5, and 10 products;
- `pip check`, `git diff --check`, tracked-artifact scan, and new-diff secret scan
  passed;
- no live browser or network command was run.
