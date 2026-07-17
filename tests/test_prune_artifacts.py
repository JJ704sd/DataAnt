import os
import time
from pathlib import Path

import pytest

from scripts.prune_artifacts import (
    prune_files,
    validate_artifacts_root,
)


def test_prune_files_dry_run_does_not_delete_old_file(tmp_path: Path) -> None:
    old_file = tmp_path / "old.log"
    old_file.write_text("old", encoding="utf-8")
    old = time.time() - 2 * 24 * 60 * 60
    os.utime(old_file, (old, old))
    result = prune_files(tmp_path, older_than_days=1, apply=False)
    assert result == (old_file,)
    assert old_file.exists()


def test_prune_files_apply_deletes_only_old_files(tmp_path: Path) -> None:
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


def test_prune_command_rejects_root_outside_repository_artifacts(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="artifacts"):
        validate_artifacts_root(tmp_path)
