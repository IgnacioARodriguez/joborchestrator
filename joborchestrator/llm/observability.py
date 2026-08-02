"""Provider-agnostic structured logging for outbound LLM requests."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMRequestContext:
    operation: str = "unknown"
    batch_id: str | None = None
    offer_count: int | None = None


def request_started(
    logger: logging.Logger,
    *,
    provider: str,
    model: str,
    context: LLMRequestContext,
) -> float:
    started = time.perf_counter()
    logger.info(
        "LLM request started provider=%s model=%s operation=%s batch_id=%s offer_count=%s",
        provider,
        model,
        context.operation,
        context.batch_id or "-",
        context.offer_count if context.offer_count is not None else "-",
    )
    return started


def request_finished(
    logger: logging.Logger,
    *,
    started: float,
    provider: str,
    model: str,
    context: LLMRequestContext,
    status_code: int | None,
    request_id: str | None,
) -> None:
    logger.info(
        "LLM request finished provider=%s model=%s operation=%s batch_id=%s offer_count=%s duration_ms=%d http_status=%s request_id=%s error_type=- timeout=false",
        provider,
        model,
        context.operation,
        context.batch_id or "-",
        context.offer_count if context.offer_count is not None else "-",
        int((time.perf_counter() - started) * 1000),
        status_code if status_code is not None else "-",
        request_id or "-",
    )


def request_failed(
    logger: logging.Logger,
    *,
    started: float,
    provider: str,
    model: str,
    context: LLMRequestContext,
    status_code: int | None,
    request_id: str | None,
    error: BaseException,
    timeout: bool,
) -> None:
    logger.warning(
        "LLM request failed provider=%s model=%s operation=%s batch_id=%s offer_count=%s duration_ms=%d http_status=%s request_id=%s error_type=%s timeout=%s error=%s",
        provider,
        model,
        context.operation,
        context.batch_id or "-",
        context.offer_count if context.offer_count is not None else "-",
        int((time.perf_counter() - started) * 1000),
        status_code if status_code is not None else "-",
        request_id or "-",
        type(error).__name__,
        timeout,
        str(error)[:500],
    )


def response_request_id(response: Any, raw: dict[str, Any] | None = None) -> str | None:
    headers = getattr(response, "headers", {})
    for key in ("x-request-id", "request-id", "nvidia-request-id"):
        value = headers.get(key)
        if value:
            return str(value)
    if raw:
        for key in ("id", "request_id", "requestId"):
            value = raw.get(key)
            if value:
                return str(value)
    return None
