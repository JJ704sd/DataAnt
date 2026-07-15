import pytest

from app.main import build_parser


def test_run_command_requires_input_and_output() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--input", "in.csv", "--output", "out.xlsx"])
    assert args.command == "run"
    assert args.input == "in.csv"
    assert args.output == "out.xlsx"
    assert args.headed is True


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--input", "in.csv"],
        ["--output", "out.xlsx"],
    ],
)
def test_run_command_rejects_missing_required_arguments(arguments: list[str]) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["run", *arguments])

    assert exc_info.value.code == 2


def test_run_command_can_disable_headed_mode() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["run", "--input", "in.csv", "--output", "out.xlsx", "--no-headed"]
    )

    assert args.headed is False


def test_run_command_collects_repeated_retry_statuses() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run",
            "--input",
            "in.csv",
            "--output",
            "out.xlsx",
            "--retry-status",
            "failed",
            "--retry-status",
            "missing",
        ]
    )

    assert args.retry_status == ["failed", "missing"]


def test_parser_uses_stable_program_name() -> None:
    parser = build_parser()

    assert parser.prog == "browser-bot-demo"
