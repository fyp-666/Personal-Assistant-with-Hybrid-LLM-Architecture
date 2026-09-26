"""Combine selected calendar events and email summaries."""

from collections.abc import Callable, Mapping
from datetime import UTC, tzinfo

from core.execution import ProviderError
from core.routing import Provider
from features.calendar import CalendarEvent, build_calendar_briefing
from features.email import Email, render_email_summary, summarize_email


def build_daily_briefing(
    events: list[CalendarEvent],
    emails: list[Email],
    providers: Mapping[Provider, Callable[[str], str]],
    *,
    timezone: tzinfo = UTC,
) -> str:
    """Compose selected data, keeping email order and continuing after ProviderError."""
    calendar_section = build_calendar_briefing(events, providers, timezone=timezone)
    email_section = build_email_briefing(emails, providers)
    return f"Daily briefing\n\n{calendar_section}\n\nEmail summaries\n\n{email_section}"


def build_email_briefing(
    emails: list[Email],
    providers: Mapping[Provider, Callable[[str], str]],
) -> str:
    """Compose email summaries in input order, retaining headers on ProviderError."""
    email_blocks = []
    for email in emails:
        try:
            result = summarize_email(email, providers)
        except ProviderError:
            summary = None
        else:
            summary = result.text
        email_blocks.append(render_email_summary(email, summary))

    return "\n\n".join(email_blocks) if email_blocks else "No email available"
