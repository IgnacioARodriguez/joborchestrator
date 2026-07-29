import json
from pathlib import Path

from scripts.build_materials_review_packet import load_records, render_packet


def test_review_packet_dedupes_summary_records_and_excludes_generated_text(tmp_path: Path) -> None:
    artifact_root = tmp_path / "materials"
    artifact_root.mkdir()
    artifact_path = artifact_root / "20260729_case_a.json"
    artifact_path.write_text(
        json.dumps(
            {
                "case": "case_a",
                "job": {"title": "Backend Developer", "company": "Acme"},
                "cv": {
                    "ats_cv_text": "SECRET GENERATED CV TEXT\nProfessional Experience",
                    "_generation_metadata": {"validation_attempts": 2},
                },
                "kit": {
                    "cover_letter": "SECRET GENERATED COVER LETTER",
                    "recruiter_message": "SECRET RECRUITER MESSAGE",
                    "_generation_metadata": {"validation_attempts": 1},
                },
                "semantic_eval": {
                    "materials": {"passed": True, "score": 100, "issues": []},
                    "ats_cv": {"passed": True, "score": 100, "issues": []},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summary_path = artifact_root / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "case": "case_a",
                        "artifact": str(artifact_path),
                        "cv_status": "completed",
                        "kit_status": "completed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    records = load_records(artifact_root, include_cases=["case_a"], include_all=False)
    packet = render_packet(records, artifact_root)

    assert len(records) == 1
    assert "Backend Developer @ Acme" in packet
    assert "CV: completed" in packet
    assert "100" in packet
    assert "SECRET GENERATED CV TEXT" not in packet
    assert "SECRET GENERATED COVER LETTER" not in packet
    assert "SECRET RECRUITER MESSAGE" not in packet


def test_review_packet_truncates_long_errors() -> None:
    records = [
        {
            "case": "failed_case",
            "artifact": "data/materials_live_probe/failed.json",
            "job": {"title": "Backend Developer", "company": "Acme"},
            "cv_status": "failed",
            "kit_status": "completed",
            "cv_error": "x" * 500,
            "cv_metadata": {"validation_attempts": 1},
            "kit_metadata": {"validation_attempts": 1},
        }
    ]

    packet = render_packet(records, Path("data/materials_live_probe"))

    assert "xxx..." in packet
    assert "x" * 400 not in packet
