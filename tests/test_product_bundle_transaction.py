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
    stale = tmp_path / f".demo.staging-{'0' * 32}"
    fresh = tmp_path / f".demo.backup-{'1' * 32}"
    malformed = tmp_path / ".demo.staging-not-a-generated-uuid"
    unrelated = tmp_path / ".demo-not-generated"
    for path in (stale, fresh, malformed, unrelated):
        path.mkdir()
    old = time.time() - 48 * 60 * 60
    os.utime(stale, (old, old))
    os.utime(malformed, (old, old))

    removed = ProductBundleTransaction(target).cleanup_stale_siblings(
        max_age_seconds=24 * 60 * 60
    )

    assert removed == (stale,)
    assert not stale.exists()
    assert fresh.exists()
    assert malformed.exists()
    assert unrelated.exists()


def test_backup_cleanup_failure_does_not_make_committed_swap_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    transaction = ProductBundleTransaction(target)

    monkeypatch.setattr(
        transaction_module.shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(PermissionError("backup locked")),
    )

    with transaction.staging_directory() as staging:
        (staging / "new.txt").write_text("new", encoding="utf-8")
        transaction.commit(staging)

    assert (target / "new.txt").read_text(encoding="utf-8") == "new"
    assert len(list(tmp_path.glob(".demo.backup-*"))) == 1


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
