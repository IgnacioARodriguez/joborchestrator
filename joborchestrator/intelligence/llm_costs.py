from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_1m: float
    output_per_1m: float
    batch_input_per_1m: float
    batch_output_per_1m: float


MODEL_PRICING: dict[str, ModelPricing] = {
    "gpt-5.4-nano": ModelPricing(
        input_per_1m=0.20,
        output_per_1m=1.25,
        batch_input_per_1m=0.10,
        batch_output_per_1m=0.625,
    ),
    "gpt-5.4-mini": ModelPricing(
        input_per_1m=0.75,
        output_per_1m=4.50,
        batch_input_per_1m=0.375,
        batch_output_per_1m=2.25,
    ),
}


def estimate_tokens_from_text(text: str | None) -> int:
    """Cheap conservative token estimate for UI planning."""
    return max(1, int(len(text or "") / 3.5))


def estimate_ranking_tokens(job_count: int, avg_description_chars: int = 7000) -> tuple[int, int]:
    input_per_job = estimate_tokens_from_text("x" * avg_description_chars) + 700
    output_per_job = 650
    return job_count * input_per_job, job_count * output_per_job


def estimate_application_kit_tokens(job_count: int, avg_description_chars: int = 7000) -> tuple[int, int]:
    input_per_job = estimate_tokens_from_text("x" * avg_description_chars) + 1200
    output_per_job = 2200
    return job_count * input_per_job, job_count * output_per_job


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = "gpt-5.4-mini",
    *,
    batch: bool = False,
) -> float:
    pricing = MODEL_PRICING.get(model) or MODEL_PRICING["gpt-5.4-mini"]
    input_rate = pricing.batch_input_per_1m if batch else pricing.input_per_1m
    output_rate = pricing.batch_output_per_1m if batch else pricing.output_per_1m
    return (input_tokens / 1_000_000 * input_rate) + (output_tokens / 1_000_000 * output_rate)
