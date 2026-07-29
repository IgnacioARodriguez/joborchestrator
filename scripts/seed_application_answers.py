from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_work_authorization_answers(
    *,
    based_us_canada: str,
    permanent_authorization: str,
    requires_sponsorship: str,
    eligible_without_sponsorship: str | None,
) -> list[dict[str, object]]:
    normalized_eligible = eligible_without_sponsorship or _inverse_yes_no(requires_sponsorship)
    return [
        {
            "canonical_key": "based_in_us_canada",
            "question_patterns": [
                "re:will you be based in the u\\.?s\\.? or canada",
                "re:based in the united states or canada",
            ],
            "answer_type": "select",
            "value": based_us_canada,
            "source": "approved",
            "status": "approved",
            "sensitivity": "sensitive",
            "requires_confirmation": False,
        },
        {
            "canonical_key": "work_authorization_permanent",
            "question_patterns": [
                "re:permanent authorization to work",
                "re:permanent work authorization",
            ],
            "answer_type": "select",
            "value": permanent_authorization,
            "source": "approved",
            "status": "approved",
            "sensitivity": "sensitive",
            "requires_confirmation": False,
        },
        {
            "canonical_key": "requires_sponsorship",
            "question_patterns": [
                "re:require .*sponsorship",
                "re:require work authorization",
                "re:need .*sponsorship",
                "re:now or in the future require sponsorship",
            ],
            "answer_type": "select",
            "value": requires_sponsorship,
            "source": "approved",
            "status": "approved",
            "sensitivity": "sensitive",
            "requires_confirmation": False,
        },
        {
            "canonical_key": "eligible_without_sponsorship",
            "question_patterns": [
                "re:eligible to work .* without sponsorship",
                "re:authorized to work .* without sponsorship",
                "re:work .* without .*sponsorship",
            ],
            "answer_type": "select",
            "value": normalized_eligible,
            "source": "approved",
            "status": "approved",
            "sensitivity": "sensitive",
            "requires_confirmation": False,
        },
    ]


def write_answers_file(path: Path, answers: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answers, indent=2, sort_keys=True), encoding="utf-8")


def seed_answers(answers: list[dict[str, object]]) -> dict[str, object]:
    from joborchestrator.storage import db_connection
    from joborchestrator.storage import persistence as db

    db.init_db()
    saved = [db.upsert_answer_definition(answer) for answer in answers]
    return {
        "db_mode": db_connection.connection_mode(),
        "saved": len(saved),
        "canonical_keys": [item["canonical_key"] for item in saved],
    }


def _inverse_yes_no(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"yes", "y", "si", "sí", "true", "1"}:
        return "No"
    if normalized in {"no", "n", "false", "0"}:
        return "Yes"
    raise ValueError("--eligible-without-sponsorship is required when --requires-sponsorship is not yes/no.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed approved application answers into the active database.")
    parser.add_argument("--based-us-canada", required=True, choices=["Yes", "No"])
    parser.add_argument("--permanent-authorization", required=True, choices=["Yes", "No"])
    parser.add_argument("--requires-sponsorship", required=True, choices=["Yes", "No"])
    parser.add_argument("--eligible-without-sponsorship", choices=["Yes", "No"])
    parser.add_argument("--answers-out", type=Path, help="Write the generated answers JSON instead of seeding the database.")
    args = parser.parse_args(argv)

    answers = build_work_authorization_answers(
        based_us_canada=args.based_us_canada,
        permanent_authorization=args.permanent_authorization,
        requires_sponsorship=args.requires_sponsorship,
        eligible_without_sponsorship=args.eligible_without_sponsorship,
    )
    if args.answers_out:
        write_answers_file(args.answers_out, answers)
        print(json.dumps({"answers_path": str(args.answers_out), "answers": len(answers)}, indent=2, sort_keys=True))
        return 0
    print(json.dumps(seed_answers(answers), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
