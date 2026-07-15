from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_COVERAGE = {
    "app/input_loader.py": 80.0,
    "app/matcher.py": 80.0,
    "app/sites/douban_movie.py": 80.0,
}


class CoverageThresholdError(AssertionError):
    pass


def verify_coverage(path: Path) -> dict[str, float]:
    report = json.loads(path.read_text(encoding="utf-8"))
    files = {name.replace("\\", "/"): data for name, data in report["files"].items()}
    actual: dict[str, float] = {}
    for name, threshold in REQUIRED_COVERAGE.items():
        percent = float(files[name]["summary"]["percent_covered"])
        if percent < threshold:
            raise CoverageThresholdError(f"{name}: {percent:.2f}% is below {threshold:.2f}%")
        actual[name] = percent
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage-json", type=Path, required=True)
    args = parser.parse_args()
    for name, percent in verify_coverage(args.coverage_json).items():
        print(f"{name}: {percent:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
