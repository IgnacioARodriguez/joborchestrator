from __future__ import annotations

import json

from scripts.seed_application_answers import build_work_authorization_answers, write_answers_file


def test_build_work_authorization_answers_derives_without_sponsorship_answer() -> None:
    answers = build_work_authorization_answers(
        based_us_canada="No",
        permanent_authorization="No",
        requires_sponsorship="Yes",
        eligible_without_sponsorship=None,
    )

    by_key = {str(answer["canonical_key"]): answer for answer in answers}
    assert by_key["based_in_us_canada"]["value"] == "No"
    assert by_key["work_authorization_permanent"]["value"] == "No"
    assert by_key["requires_sponsorship"]["value"] == "Yes"
    assert by_key["eligible_without_sponsorship"]["value"] == "No"
    assert all(answer["source"] == "approved" for answer in answers)
    assert all(answer["requires_confirmation"] is False for answer in answers)


def test_write_answers_file_outputs_json(tmp_path) -> None:
    path = tmp_path / "answers.json"
    answers = build_work_authorization_answers(
        based_us_canada="No",
        permanent_authorization="No",
        requires_sponsorship="Yes",
        eligible_without_sponsorship=None,
    )

    write_answers_file(path, answers)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored) == 4
    assert stored[0]["canonical_key"] == "based_in_us_canada"
