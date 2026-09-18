"""Summarize deliberately unsorted synthetic events with real local Gemma."""

from datetime import datetime
from zoneinfo import ZoneInfo

from hybrid_assistant.calendar import CalendarEvent, build_calendar_briefing
from hybrid_assistant.runtime import create_providers


def main() -> None:
    events = [
        CalendarEvent(
            title="项目讨论",
            starts_at=datetime.fromisoformat("2026-09-07T14:00:00-07:00"),
            duration_minutes=45,
            location="会议室 A",
        ),
        CalendarEvent(
            title="团队会议",
            starts_at=datetime.fromisoformat("2026-09-07T10:00:00-07:00"),
            duration_minutes=30,
            location="线上",
        ),
    ]
    print(
        build_calendar_briefing(
            events, create_providers(), timezone=ZoneInfo("America/Los_Angeles")
        )
    )


if __name__ == "__main__":
    main()
