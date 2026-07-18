from joborchestrator.llm.provider import AnthropicProvider, ProviderRegistry


def test_provider_registry_reads_role_env(monkeypatch):
    monkeypatch.delenv("RANKING_PROVIDER", raising=False)
    monkeypatch.delenv("MATERIALS_PROVIDER", raising=False)
    monkeypatch.delenv("JUDGE_PROVIDER_SECONDARY", raising=False)
    monkeypatch.delenv("JUDGE_PROVIDER_TERTIARY", raising=False)

    registry = ProviderRegistry()

    assert registry.provider_name_for_role("ranking") == "nvidia"
    assert registry.provider_name_for_role("materials") == "openai"
    assert registry.provider_name_for_role("judge_secondary") == ""
    assert registry.provider_name_for_role("judge_tertiary") == ""

    monkeypatch.setenv("MATERIALS_PROVIDER", "nvidia")
    monkeypatch.setenv("JUDGE_PROVIDER_SECONDARY", "openai")
    monkeypatch.setenv("JUDGE_PROVIDER_TERTIARY", "anthropic")

    assert registry.provider_name_for_role("materials") == "nvidia"
    assert registry.provider_name_for_role("judge_secondary") == "openai"
    assert registry.provider_name_for_role("judge_tertiary") == "anthropic"


def test_anthropic_provider_uses_messages_api_with_system_prompt():
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "content": [{"type": "text", "text": '"passed":true}'}],
                "model": "claude-test",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }

    class FakeHttp:
        @staticmethod
        def post(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse()

    provider = AnthropicProvider(api_key="anthropic-key", http_module=FakeHttp)
    response = provider.complete(
        [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Return JSON"},
        ],
        model="claude-test",
        response_format="json",
    )

    assert response.text == '{"passed":true}'
    assert calls[0][0] == "https://api.anthropic.com/v1/messages"
    assert calls[0][1]["headers"]["x-api-key"] == "anthropic-key"
    assert calls[0][1]["headers"]["anthropic-version"] == "2023-06-01"
    assert calls[0][1]["json"]["system"] == "System prompt"
    assert calls[0][1]["json"]["messages"][0] == {"role": "user", "content": "Return JSON"}
    assert calls[0][1]["json"]["messages"][1] == {"role": "assistant", "content": "{"}
