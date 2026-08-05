from __future__ import annotations

from typing import Any, Callable, Protocol


class RankingGenerator(Protocol):
    def __call__(self, jobs: Any, **options: Any) -> dict[str, int]: ...


class MaterialsGenerator(Protocol):
    def __call__(self, job: Any, **options: Any) -> dict[str, Any]: ...


def dispatch(registry: dict[str, Callable[..., Any]], name: str, **kwargs: Any) -> Any:
    """Resolve an implementation without leaking provider selection into callers."""
    try:
        generator = registry[name.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported generation implementation: {name}") from exc
    return generator(**kwargs)

