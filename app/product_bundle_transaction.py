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
                # The second rename is the commit point. A locked backup is
                # safe to leave for the bounded stale-sibling cleanup on a
                # later write; reporting failure here would make the already
                # committed target outcome ambiguous to the caller.
                pass

    def _sibling_path(self, role: str) -> Path:
        return self.target_dir.with_name(
            f".{self.target_dir.name}.{role}-{uuid.uuid4().hex}"
        )


__all__ = [
    "BUNDLE_LOCK_TIMEOUT_SECONDS",
    "ProductBundleTransaction",
]
