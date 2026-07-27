import json

from joborchestrator import prompts
from joborchestrator.prompts import PromptRegistryError, active_prompt_version, load_prompt


def test_load_prompt_uses_registry_active_version():
    assert active_prompt_version("ranking", "nvidia_response_contract") == "v9"
    assert "Decision calibration" in load_prompt("ranking", "nvidia_response_contract")
    assert "central_requirement_thresholds" in load_prompt("ranking", "nvidia_response_contract")
    assert "Evidence completeness is mandatory" in load_prompt("ranking", "nvidia_response_contract")
    assert "RabbitMQ, EPC, VFD, STATCOM" in load_prompt("ranking", "nvidia_response_contract")
    assert "must always be one JSON object with a top-level `rankings` array" in load_prompt(
        "ranking", "nvidia_response_contract"
    )
    assert active_prompt_version("judge", "semantic_rubric") == "v1"
    assert "calibrated evaluator" in load_prompt("judge", "semantic_rubric")
    assert active_prompt_version("materials", "nvidia_cv_contract") == "v4"
    assert active_prompt_version("materials", "nvidia_kit_contract") == "v4"
    assert "forbidden claim family" in load_prompt("materials", "nvidia_cv_contract")
    assert "AWS Lambda, DynamoDB, and API Gateway" in load_prompt("materials", "nvidia_cv_contract")


def test_ranking_contract_requires_unlisted_central_terms_generically():
    contract = load_prompt("ranking", "nvidia_response_contract")

    assert "central technologies, protocols, platforms, domain acronyms, or domain terms" in contract
    assert "even when the candidate does not support them" in contract
    assert "RabbitMQ, EPC, VFD, STATCOM" in contract
    assert "Terraform" not in contract
    assert "Snowflake" not in contract


def test_ranking_contract_distinguishes_skip_from_avoid():
    contract = load_prompt("ranking", "nvidia_response_contract")

    assert "Use SKIP for low hiring probability in an adjacent software/domain role" in contract
    assert "Use AVOID only for hard blockers" in contract
    assert "security/AppSec/DevSecOps" in contract
    assert "normally not AVOID" in contract


def test_prompt_registry_reports_missing_key(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"active_environment": "default", "environments": {"default": {}}}), encoding="utf-8")
    monkeypatch.setattr(prompts, "REGISTRY_PATH", registry)

    try:
        active_prompt_version("ranking", "missing")
    except PromptRegistryError as exc:
        assert "Prompt version not configured" in str(exc)
    else:
        raise AssertionError("Expected PromptRegistryError")
