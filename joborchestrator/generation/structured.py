from __future__ import annotations

import json
import inspect
from typing import Any

from joborchestrator.llm.provider import LLMProviderError, ProviderRegistry


class StructuredGenerationError(RuntimeError):
    """A provider-independent structured generation failure."""


def provider_complete(provider: Any, messages: list[dict[str, Any]], **options: Any) -> Any:
    """Call an adapter with only options supported by that adapter."""
    parameters = inspect.signature(provider.complete).parameters
    accepted = {
        key: value
        for key, value in options.items()
        if value is not None and (key in parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()))
    }
    return provider.complete(messages, **accepted)


async def provider_acomplete(provider: Any, messages: list[dict[str, Any]], **options: Any) -> Any:
    """Async equivalent of provider_complete for shared ranking/materials paths."""
    parameters = inspect.signature(provider.acomplete).parameters
    accepted = {
        key: value
        for key, value in options.items()
        if value is not None and (key in parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()))
    }
    return await provider.acomplete(messages, **accepted)


def generate_json(
    messages: list[dict[str, Any]],
    *,
    role: str,
    provider_name: str | None,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    schema: dict[str, Any] | None = None,
    schema_name: str = "response",
    max_tokens: int | None = None,
    temperature: float = 0.0,
    transport_retries: int = 0,
    **provider_options: Any,
) -> dict[str, Any]:
    """Generate and decode JSON through any configured LLM adapter."""
    try:
        provider = ProviderRegistry().get(
            role, provider_name=provider_name, api_key=api_key,
            base_url=base_url, timeout=timeout,
        )
        options: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "response_format": "json",
            "max_tokens": max_tokens,
            **provider_options,
        }
        if schema is not None and provider.provider_name in {"openai", "openrouter"}:
            options.update(response_schema=schema, schema_name=schema_name)
        last_error: StructuredGenerationError | None = None
        for _ in range(max(0, int(transport_retries)) + 1):
            try:
                response = provider_complete(provider, messages, **options)
                try:
                    return json.loads(response.text)
                except json.JSONDecodeError as exc:
                    raise StructuredGenerationError("Provider returned invalid JSON.") from exc
            except (LLMProviderError, StructuredGenerationError) as exc:
                last_error = exc if isinstance(exc, StructuredGenerationError) else StructuredGenerationError(str(exc))
        raise last_error or StructuredGenerationError("Structured generation failed.")
    except LLMProviderError as exc:
        raise StructuredGenerationError(str(exc)) from exc
