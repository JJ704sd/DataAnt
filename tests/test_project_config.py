from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).parents[1]


def test_project_dependencies_use_drissionpage_without_playwright() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as config_file:
        config = tomllib.load(config_file)

    dependencies = config["project"]["dependencies"]

    assert dependencies == [
        "DrissionPage>=4.1.1,<4.2",
        "openpyxl>=3.1,<4",
    ]
    assert all("playwright" not in dependency.casefold() for dependency in dependencies)


def test_browser_profile_placeholder_matches_gitignore_rules() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert gitignore == [
        ".worktrees/",
        ".venv/",
        "__pycache__/",
        "*.py[cod]",
        ".pytest_cache/",
        ".coverage",
        "htmlcov/",
        ".env",
        "browser-profile/*",
        "!browser-profile/.gitkeep",
        "outputs/*",
        "!outputs/.gitkeep",
        "artifacts/*",
        "!artifacts/.gitkeep",
    ]
    assert all("playwright/.auth" not in rule.casefold() for rule in gitignore)
    assert (PROJECT_ROOT / "browser-profile" / ".gitkeep").is_file()
    assert not (PROJECT_ROOT / "playwright" / ".auth" / ".gitkeep").exists()
