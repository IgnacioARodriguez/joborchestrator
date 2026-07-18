from joborchestrator.llm.provider import ProviderRegistry


def test_provider_registry_reads_role_env(monkeypatch):
    monkeypatch.delenv("RANKING_PROVIDER", raising=False)
    monkeypatch.delenv("MATERIALS_PROVIDER", raising=False)
    monkeypatch.delenv("JUDGE_PROVIDER_SECONDARY", raising=False)

    registry = ProviderRegistry()

    assert registry.provider_name_for_role("ranking") == "nvidia"
    assert registry.provider_name_for_role("materials") == "openai"
    assert registry.provider_name_for_role("judge_secondary") == ""

    monkeypatch.setenv("MATERIALS_PROVIDER", "nvidia")
    monkeypatch.setenv("JUDGE_PROVIDER_SECONDARY", "openai")

    assert registry.provider_name_for_role("materials") == "nvidia"
    assert registry.provider_name_for_role("judge_secondary") == "openai"
