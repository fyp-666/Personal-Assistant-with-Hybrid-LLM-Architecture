"""Execute a trusted route plan with its permitted fallbacks."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from core.routing import Provider, RoutePlan


class ProviderError(RuntimeError):
    """An expected model-call failure that permits a planned fallback."""


@dataclass(frozen=True)
class ExecutionResult:
    """The provider used, its reply, and whether it was a fallback."""

    provider: Provider
    text: str
    used_fallback: bool = False


def execute_plan(
    plan: RoutePlan,
    prompt: str,
    providers: Mapping[Provider, Callable[[str], str]],
) -> ExecutionResult:
    """Try the planned route in order, falling back only on ProviderError."""
    route = (plan.primary, *plan.fallbacks)
    for index, provider in enumerate(route):
        generate = providers[provider]
        try:
            text = generate(prompt)
        except ProviderError:
            if index == len(route) - 1:
                raise
            continue
        return ExecutionResult(
            provider=provider,
            text=text,
            used_fallback=index > 0,
        )
