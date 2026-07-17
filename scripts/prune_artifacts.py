"""Bounded cleanup of the repository ``artifacts/`` runtime directory.

The product pipeline occasionally leaves dated screenshots, debug
exports, and other transient files under ``D:\\DataAnt\\artifacts``.
This script is the single supported way to prune that directory: it
defaults to a dry-run so operators can preview deletions, and the
``--apply`` flag is required to actually remove anything. The root
itself is hard-blocked to ``<repo>/artifacts`` so a misconfigured
``--root`` cannot reach into other trees.

The two pure functions are also reused directly by tests (no CLI, no
real artifacts directory touched). ``prune_files`` walks the supplied
root, ignores ``.gitkeep`` placeholders, and never descends into
directories outside ``root``. ``validate_artifacts_root`` is the
guard that the CLI runs before scanning anything.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path


__all__ = [
    "validate_artifacts_root",
    "prune_files",
    "main",
]


def validate_artifacts_root(root: Path) -> Path:
    """Resolve ``root`` and reject anything outside ``<repo>/artifacts``.

    The script may only operate on the repository's own ``artifacts/``
    directory; any other resolved location raises :class:`ValueError`
    so the CLI fails fast before the filesystem is walked.
    """
    repo_root = Path(__file__).resolve().parents[1]
    allowed = (repo_root / "artifacts").resolve()
    resolved = Path(root).resolve()
    if resolved != allowed:
        raise ValueError(f"root must resolve to {allowed}")
    return resolved


def prune_files(
    root: Path,
    *,
    older_than_days: int,
    apply: bool,
) -> tuple[Path, ...]:
    """Return files under ``root`` older than ``older_than_days``.

    ``.gitkeep`` placeholders are always skipped. When ``apply`` is
    ``False`` the returned paths are still reported but left on disk
    so the caller can present a dry-run preview. Only files are
    removed; directories are never deleted by this helper.
    """
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prune files older than a threshold from the repository "
            "artifacts/ directory. Defaults to a dry-run preview; "
            "pass --apply to actually delete."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Root directory to scan; must resolve to <repo>/artifacts",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        required=True,
        help="Delete files whose mtime is older than this many days",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the files (default: dry-run preview)",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    root = validate_artifacts_root(args.root)
    candidates = prune_files(
        root,
        older_than_days=args.older_than_days,
        apply=args.apply,
    )
    mode = "DELETE" if args.apply else "DRY-RUN"
    print(f"{mode}: {len(candidates)} files under {root}")
    for path in candidates:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
