"""Deterministic hybrid routing, independent of Hermes and provider execution."""

from dataclasses import dataclass
from enum import Enum


class Privacy(Enum):
    UNKNOWN = "unknown"
    PUBLIC = "public"
    SENSITIVE = "sensitive"


class Source(Enum):
    UNKNOWN = "unknown"
    USER_INPUT = "user_input"
    EMAIL = "email"
    CALENDAR = "calendar"


class Complexity(Enum):
    NORMAL = "normal"
    COMPLEX = "complex"


class Provider(Enum):
    OPENAI = "openai"
    NIM = "nim"
    LOCAL = "local"


@dataclass(frozen=True)
class RequestContext:
    """Routing metadata; source and cloud restrictions are controlled by the caller."""

    privacy: Privacy = Privacy.UNKNOWN
    source: Source = Source.UNKNOWN
    offline: bool = False
    cloud_allowed: bool = True
    complexity: Complexity = Complexity.NORMAL

    def __post_init__(self) -> None:
        if not isinstance(self.privacy, Privacy):
            raise TypeError("privacy must be a Privacy value")
        if not isinstance(self.source, Source):
            raise TypeError("source must be a Source value")
        if not isinstance(self.offline, bool):
            raise TypeError("offline must be a bool")
        if not isinstance(self.cloud_allowed, bool):
            raise TypeError("cloud_allowed must be a bool")
        if not isinstance(self.complexity, Complexity):
            raise TypeError("complexity must be a Complexity value")


@dataclass(frozen=True)
class RoutePlan:
    """An execution plan; fallbacks list permitted alternatives in order."""

    primary: Provider
    fallbacks: tuple[Provider, ...]
    reason: str


def plan_route(context: RequestContext) -> RoutePlan:
    """Choose permitted model routes from trusted metadata, without model calls."""
    # Check cloud restrictions first; offline wins when both restrictions apply.
    if context.offline:
        return RoutePlan(
            primary=Provider.LOCAL,
            fallbacks=(),
            reason="offline_mode",
        )

    if not context.cloud_allowed:
        return RoutePlan(
            primary=Provider.LOCAL,
            fallbacks=(),
            reason="cloud_forbidden",
        )

    if context.privacy is Privacy.SENSITIVE:
        return RoutePlan(Provider.LOCAL, (), "explicit_private")
    return RoutePlan(Provider.OPENAI, (Provider.LOCAL,), "default_gpt")
