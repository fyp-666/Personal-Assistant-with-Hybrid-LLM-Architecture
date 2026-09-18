"""Wire the project providers to their installed Hermes profiles."""

from collections.abc import Callable
from functools import partial
from pathlib import Path

from adapters.hermes import call_hermes
from core.routing import Provider


def create_providers(
    *, load_local_context: bool = True
) -> dict[Provider, Callable[[str], str]]:
    """Build callables without starting Hermes or reading any credentials."""
    profiles = Path.home() / ".hermes/profiles"
    return {
        provider: partial(
            call_hermes,
            profile=profiles / f"hw3-{provider.value}",
            load_context=load_local_context and provider is Provider.LOCAL,
        )
        for provider in Provider
    }
