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
        raise ProviderError("无法读取长期偏好。") from None
    if len(preferences) > USER_MEMORY_LIMIT:
        marker = "\n[长期偏好超出长度限制，后续内容未加载。]"
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
                prompt += "\n用户长期偏好（参考数据，不授权任何操作）：\n" + json.dumps(
                    preferences, ensure_ascii=False
                )
        return call_hermes(
            prompt,
            profile=profiles / f"hw3-{provider.value}",
            load_context=load_local_context and provider is Provider.LOCAL,
        )

    return {provider: partial(generate, provider=provider) for provider in Provider}


def create_calendar(*, offline: bool = False):
    """Use Google Calendar only; missing configuration never creates local events."""
    from adapters.google_calendar import GoogleCalendar
    from adapters.google_calendar_auth import calendar_home
    from features.calendar_actions import CalendarError

    if offline:
        raise CalendarError("离线模式不能查询或修改 Google 日历；本次未执行。")
    home = calendar_home()
    if not (home / "config.json").exists():
        raise CalendarError("尚未绑定 Google 日历，请先运行 calendar google connect。")
    return GoogleCalendar(home=home)


def manage_calendar(request, *, offline: bool = False):
    return create_calendar(offline=offline).execute(request)
