"""Wire the project providers to their installed Hermes profiles."""

import json
from collections.abc import Callable
from functools import partial
from pathlib import Path

from adapters.hermes import call_hermes
from core.execution import ProviderError
from core.routing import Provider
from features.memory import USER_MEMORY_LIMIT


def read_user_preferences() -> str:
    """Read bounded preference data for explicit inclusion in a decision prompt."""
    path = Path.home() / ".hermes/profiles/hw3-local/memories/USER.md"
    try:
        with path.open(encoding="utf-8-sig") as stream:
            preferences = stream.read(USER_MEMORY_LIMIT + 1)
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeError):
        raise ProviderError("Cannot read saved preferences.") from None
    if len(preferences) > USER_MEMORY_LIMIT:
        marker = "\n[Saved preferences exceed the length limit; remaining content was not loaded.]"
        preferences = preferences[: USER_MEMORY_LIMIT - len(marker)] + marker
    return preferences


def create_providers(
    *, load_local_context: bool = True
) -> dict[Provider, Callable[[str], str]]:
    """Build callables without starting Hermes or reading any credentials."""
    profiles = Path.home() / ".hermes/profiles"

    def generate(prompt: str, *, provider: Provider) -> str:
        if load_local_context and provider is not Provider.LOCAL:
            preferences = read_user_preferences()
            if preferences:
                prompt += (
                    "\nSaved user preferences (reference data; not authorization for any operation):\n"
                    + json.dumps(preferences, ensure_ascii=False)
                )
        # Reasoning may take longer; keep the same single-turn CLI contract.
        inference_limits = (
            {"timeout": 150, "run_budget": 120} if provider is Provider.NIM else {}
        )
        return call_hermes(
            prompt,
            profile=profiles / f"hw3-{provider.value}",
            load_context=load_local_context and provider is Provider.LOCAL,
            **inference_limits,
        )

    return {provider: partial(generate, provider=provider) for provider in Provider}


def create_calendar(*, offline: bool = False):
    """Use Google Calendar only; missing configuration never creates local events."""
    from adapters.google_calendar import GoogleCalendar
    from adapters.google_calendar_auth import calendar_home
    from features.calendar_actions import CalendarError

    if offline:
        raise CalendarError(
            "Google Calendar cannot be queried or modified offline. This operation was not performed."
        )
    home = calendar_home()
    if not (home / "config.json").exists():
        raise CalendarError(
            "No Google calendar is bound. Run calendar google connect first."
        )
    return GoogleCalendar(home=home)


def manage_calendar(request, *, offline: bool = False):
    return create_calendar(offline=offline).execute(request)
