from pathlib import Path

import pytest

from app.input_loader import InputError, load_tasks


def test_load_tasks_handles_bom_and_optional_year(tmp_path: Path) -> None:
    input_path = tmp_path / "tasks.csv"
    input_path.write_text(
        "\ufeffquery,year\n肖申克的救赎,1994\n阿甘正传,\n",
        encoding="utf-8",
    )

    tasks = load_tasks(input_path)

    assert [(task.query, task.query_year) for task in tasks] == [
        ("肖申克的救赎", "1994"),
        ("阿甘正传", None),
    ]


def test_load_tasks_assigns_distinct_stable_ids_to_duplicates(tmp_path: Path) -> None:
    input_path = tmp_path / "tasks.csv"
    input_path.write_text(
        "query,year\n英雄,2002\n英雄,2002\n",
        encoding="utf-8",
    )

    first_load = load_tasks(input_path)
    second_load = load_tasks(input_path)
    first_ids = [task.task_id for task in first_load]

    assert first_ids[0] != first_ids[1]
    assert first_ids == [task.task_id for task in second_load]


@pytest.mark.parametrize(
    "body",
    [
        "year\n1994\n",
        "query,year\n,1994\n",
        "query,year\n电影,94\n",
    ],
)
def test_load_tasks_rejects_invalid_csv_bodies(tmp_path: Path, body: str) -> None:
    input_path = tmp_path / "tasks.csv"
    input_path.write_text(body, encoding="utf-8")

    with pytest.raises(InputError):
        load_tasks(input_path)
