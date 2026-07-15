import json
from pathlib import Path

import pytest

from scripts.verify_core import CoverageThresholdError, verify_coverage


def write_coverage(path: Path, names: dict[str, float]) -> None:
    report = {
        "files": {
            name: {"summary": {"percent_covered": percent}}
            for name, percent in names.items()
        }
    }
    path.write_text(json.dumps(report), encoding="utf-8")


@pytest.mark.parametrize(
    "names",
    [
        {"app/input_loader.py": 90, "app/matcher.py": 95, "app/sites/douban_movie.py": 91},
        {"app\\input_loader.py": 90, "app\\matcher.py": 95, "app\\sites\\douban_movie.py": 91},
    ],
)
def test_verify_coverage_accepts_platform_specific_keys(tmp_path: Path, names: dict[str, float]) -> None:
    report = tmp_path / "coverage.json"
    write_coverage(report, names)
    assert verify_coverage(report) == {
        "app/input_loader.py": 90,
        "app/matcher.py": 95,
        "app/sites/douban_movie.py": 91,
    }


def test_verify_coverage_rejects_a_module_below_80(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    write_coverage(
        report,
        {"app/input_loader.py": 90, "app/matcher.py": 95, "app/sites/douban_movie.py": 79},
    )
    with pytest.raises(CoverageThresholdError, match="douban_movie.py: 79.00%"):
        verify_coverage(report)
