from typing import get_type_hints

from app.models import Candidate


def test_candidate_kind_is_optional() -> None:
    assert get_type_hints(Candidate)["kind"] == str | None
