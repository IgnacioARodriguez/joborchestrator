from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx


ResponseFormat = Literal["text", "json"]
ProviderRole = Literal["ranking", "materials", "ats_cv", "judge", "judge_secondary"]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    raw: dict[str, Any]
    provider: str
    model: str
    usage: dict[str, int]


class LLMProvider(Protocol):
    provider_name: str

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        response_format: ResponseFormat = "text",
        max_tokens: int | None = None,
    ) -> LLMResponse: ...


class LLMProviderError(RuntimeError):
    pass


class OpenAIProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        http_module: Any = httpx,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout
        self._http = http_module

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        response_format: ResponseFormat = "text",
        max_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
        store: bool = False,
        reasoning_effort: str | None = "low",
    ) -> LLMResponse:
        if not self.api_key:
            raise LLMProviderError("OPENAI_API_KEY is required.")
        body: dict[str, Any] = {
            "model": model,
            "store": store,
            "input": messages,
        }
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        if max_tokens is not None:
            body["max_output_tokens"] = max_tokens
        if response_format == "json":
            body["text"] = {
                "format": (
                    {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": response_schema,
                    }
                    if response_schema is not None
                    else {"type": "json_object"}
                )
            }
        if temperature != 0.0:
            body["temperature"] = temperature

        try:
            response = self._http.post(
                f"{self.base_url}/responses",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:1000] if exc.response is not None else ""
            raise LLMProviderError(f"OpenAI request failed: status={exc.response.status_code} body={detail!r}") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"OpenAI request failed: {type(exc).__name__}: {exc!r}") from exc

        raw = response.json()
        return LLMResponse(
            text=_extract_openai_text(raw),
            raw=raw,
            provider=self.provider_name,
            model=model,
            usage=_usage_from_raw(raw),
        )


class NvidiaProvider:
    provider_name = "nvidia"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        http_module: Any = httpx,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")
        self.base_url = (base_url or os.getenv("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1").rstrip("/")
        self.timeout = timeout
        self._http = http_module

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        response_format: ResponseFormat = "text",
        max_tokens: int | None = None,
        top_p: float = 0.95,
        frequency_penalty: float = 0,
        presence_penalty: float = 0,
    ) -> LLMResponse:
        if not self.api_key:
            raise LLMProviderError("NVIDIA_API_KEY or NIM_API_KEY is required.")
        body = self._chat_body(
            messages,
            model=model,
            temperature=temperature,
            response_format=response_format,
            max_tokens=max_tokens,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
        )
        try:
            response = self._http.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:1000] if exc.response is not None else ""
            raise LLMProviderError(f"NVIDIA request failed: status={exc.response.status_code} body={detail!r}") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"NVIDIA request failed: {type(exc).__name__}: {exc!r}") from exc

        raw = response.json()
        return LLMResponse(
            text=_extract_chat_text(raw),
            raw=raw,
            provider=self.provider_name,
            model=model,
            usage=_usage_from_raw(raw),
        )

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        client: httpx.AsyncClient,
        temperature: float = 0.0,
        response_format: ResponseFormat = "text",
        max_tokens: int | None = None,
        top_p: float = 0.95,
        frequency_penalty: float = 0,
        presence_penalty: float = 0,
    ) -> LLMResponse:
        if not self.api_key:
            raise LLMProviderError("NVIDIA_API_KEY or NIM_API_KEY is required.")
        body = self._chat_body(
            messages,
            model=model,
            temperature=temperature,
            response_format=response_format,
            max_tokens=max_tokens,
            top_p=top_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
        )
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:1000] if exc.response is not None else ""
            raise LLMProviderError(f"NVIDIA request failed: status={exc.response.status_code} body={detail!r}") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"NVIDIA request failed: {type(exc).__name__}: {exc!r}") from exc

        raw = response.json()
        return LLMResponse(
            text=_extract_chat_text(raw),
            raw=raw,
            provider=self.provider_name,
            model=model,
            usage=_usage_from_raw(raw),
        )

    def _chat_body(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float,
        response_format: ResponseFormat,
        max_tokens: int | None,
        top_p: float,
        frequency_penalty: float,
        presence_penalty: float,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "top_p": top_p,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
            "stream": False,
            "messages": messages,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format == "json":
            body["response_format"] = {"type": "json_object"}
        return body


class AnthropicProvider:
    provider_name = "anthropic"

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        temperature: float = 0.0,
        response_format: ResponseFormat = "text",
        max_tokens: int | None = None,
    ) -> LLMResponse:
        raise LLMProviderError("AnthropicProvider is not implemented yet.")


class ProviderRegistry:
    _ROLE_ENV = {
        "ranking": "RANKING_PROVIDER",
        "materials": "MATERIALS_PROVIDER",
        "ats_cv": "ATS_CV_PROVIDER",
        "judge": "JUDGE_PROVIDER",
        "judge_secondary": "JUDGE_PROVIDER_SECONDARY",
    }
    _DEFAULTS = {
        "ranking": "nvidia",
        "materials": "openai",
        "ats_cv": "openai",
        "judge": "openai",
        "judge_secondary": "",
    }

    def provider_name_for_role(self, role: ProviderRole) -> str:
        configured = os.getenv(self._ROLE_ENV[role])
        return (configured if configured is not None else self._DEFAULTS[role]).strip().lower()

    def get(
        self,
        role: ProviderRole,
        *,
        provider_name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        http_module: Any = httpx,
    ) -> LLMProvider:
        name = (provider_name or self.provider_name_for_role(role)).strip().lower()
        if not name:
            raise LLMProviderError(f"No provider configured for role {role!r}.")
        return provider_for_name(
            name,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            http_module=http_module,
        )


def provider_for_name(
    provider_name: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    http_module: Any = httpx,
) -> LLMProvider:
    normalized = provider_name.strip().lower()
    if normalized == "openai":
        return OpenAIProvider(api_key=api_key, base_url=base_url, timeout=timeout or 60.0, http_module=http_module)
    if normalized == "nvidia":
        return NvidiaProvider(api_key=api_key, base_url=base_url, timeout=timeout or 120.0, http_module=http_module)
    if normalized == "anthropic":
        return AnthropicProvider()
    raise LLMProviderError(f"Unsupported LLM provider: {provider_name}")


def _extract_openai_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return str(response["output_text"])
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return str(content["text"])
    raise LLMProviderError("OpenAI response did not include text output.")


def _extract_chat_text(response: dict[str, Any]) -> str:
    try:
        return str(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMProviderError("Chat completion response did not include message content.") from exc


def _usage_from_raw(raw: dict[str, Any]) -> dict[str, int]:
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    try:
        input_value = int(input_tokens or 0)
    except (TypeError, ValueError):
        input_value = 0
    try:
        output_value = int(output_tokens or 0)
    except (TypeError, ValueError):
        output_value = 0
    return {
        "input_tokens": input_value,
        "output_tokens": output_value,
    }
