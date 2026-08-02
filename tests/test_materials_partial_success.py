import pytest

from joborchestrator.intelligence import llm_application_materials as llm


def _routing() -> dict:
    return {
        "requested_cv_strategy": "controlled",
        "selected_pipeline": "controlled_cv",
        "effective_flags": {
            "controlled_cv_enabled": True,
            "nvidia_planner_enabled": True,
            "openai_fallback_enabled": False,
        },
    }


def _cv_response() -> dict:
    return {
        "ats_cv_text": "Ignacio Rodriguez\n\nProfessional Summary\nBackend developer.\n\nTechnical Skills\nPython\n\nProfessional Experience\nBackend Developer | Acme | 2022 - Present\n- Built APIs.\n\nEducation\nBootcamp",
        "risk_flags": [],
        "keywords_used": ["Python"],
        "_generation_metadata": {
            "pipeline": "controlled_cv",
            "stage": "cv_render",
            "validation_attempts": 1,
            "validation_errors": [],
            "accepted": True,
        },
    }


def _patch_common(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_materials_payload", lambda *args, **kwargs: {"job": {"title": "Backend Engineer"}})
    monkeypatch.setattr(llm, "materials_routing_snapshot", lambda strategy: _routing())
    monkeypatch.setattr(llm, "_call_nvidia_controlled_cv", lambda *args, **kwargs: _cv_response())


def test_cv_only_target_skips_kit_generation(monkeypatch) -> None:
    _patch_common(monkeypatch)

    def unexpected_kit(*args, **kwargs):
        raise AssertionError("kit generation must be skipped for an ats_cv-only request")

    monkeypatch.setattr(llm, "_call_nvidia_kit", unexpected_kit)

    result = llm.build_application_kit_with_nvidia(
        {"title": "Backend Engineer"},
        api_key="test-key",
        targets=["ats_cv"],
    )

    assert result["ats_cv_text"].startswith("Ignacio Rodriguez")
    assert result["_generation_metadata"]["material_statuses"] == {"ats_cv": "ready"}
    assert result["_generation_metadata"]["partial_success"] is False


def test_valid_cv_is_returned_when_kit_fails(monkeypatch) -> None:
    _patch_common(monkeypatch)

    def failed_kit(*args, **kwargs):
        raise llm.LLMMaterialsError(
            "NVIDIA kit response was incomplete: recruiter_message is too long",
            generation_metadata={
                "stage": "kit_generation",
                "validation_attempts": 2,
                "validation_errors": ["recruiter_message is too long"],
                "accepted": False,
                "output_text": "rejected kit",
            },
        )

    monkeypatch.setattr(llm, "_call_nvidia_kit", failed_kit)

    result = llm.build_application_kit_with_nvidia(
        {"title": "Backend Engineer"},
        api_key="test-key",
        targets=["ats_cv", "cover_letter", "recruiter_message", "autofill"],
    )

    metadata = result["_generation_metadata"]
    assert result["ats_cv_text"].startswith("Ignacio Rodriguez")
    assert result["cover_letter"] == ""
    assert result["recruiter_message"] == ""
    assert result["autofill_notes"] == ""
    assert metadata["partial_success"] is True
    assert metadata["material_statuses"] == {
        "ats_cv": "ready",
        "cover_letter": "failed_validation",
        "recruiter_message": "failed_validation",
        "autofill": "failed_validation",
    }
    assert metadata["failed_materials"] == ["cover_letter", "recruiter_message", "autofill"]
    assert metadata["stage_attempts"][-1]["accepted"] is False


def test_kit_failure_still_raises_when_no_cv_was_requested(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_materials_payload", lambda *args, **kwargs: {"job": {"title": "Backend Engineer"}})
    monkeypatch.setattr(llm, "materials_routing_snapshot", lambda strategy: _routing())
    monkeypatch.setattr(
        llm,
        "_call_nvidia_kit",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            llm.LLMMaterialsError("kit failed", generation_metadata={"validation_errors": ["kit failed"]})
        ),
    )

    with pytest.raises(llm.LLMMaterialsError, match="kit failed"):
        llm.build_application_kit_with_nvidia(
            {"title": "Backend Engineer"},
            api_key="test-key",
            targets=["cover_letter"],
        )


def test_recruiter_message_is_truncated_deterministically() -> None:
    repaired, repairs = llm._repair_kit_response_basics(
        {"recruiter_message": "A" * 400, "cover_letter": "Valid cover", "autofill_notes": "Valid notes"}
    )

    assert len(repaired["recruiter_message"]) <= llm.RECRUITER_MESSAGE_MAX_CHARS
    assert repairs == ["recruiter_message_truncated"]


def test_combined_metadata_preserves_failed_stage() -> None:
    metadata = llm._combined_generation_metadata(
        [
            {"_generation_metadata": {"stage": "cv_render", "validation_attempts": 1, "accepted": True}},
            {"_generation_metadata": {"stage": "kit_generation", "validation_attempts": 2, "accepted": False}},
        ]
    )

    assert metadata["stage_attempts"][0]["accepted"] is True
    assert metadata["stage_attempts"][1]["accepted"] is False
