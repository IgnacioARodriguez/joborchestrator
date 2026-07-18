import json

from joborchestrator import prompts
from joborchestrator.prompts import PromptRegistryError, active_prompt_version, load_prompt


def test_load_prompt_uses_registry_active_version():
    assert active_prompt_version("ranking", "nvidia_response_contract") == "v2"
    assert "Critical rules" in load_prompt("ranking", "nvidia_response_contract")


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
