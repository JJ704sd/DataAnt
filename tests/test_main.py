from app.main import build_parser


def test_run_command_requires_input_and_output() -> None:
    parser = build_parser()
    args = parser.parse_args(["run", "--input", "in.csv", "--output", "out.xlsx"])
    assert args.command == "run"
    assert args.input == "in.csv"
    assert args.output == "out.xlsx"
    assert args.headed is True
