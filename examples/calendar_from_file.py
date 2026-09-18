"""Read a synthetic calendar file and summarize its selected date with local Gemma."""

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from hybrid_assistant.calendar import (
    CalendarEvent,
    build_calendar_briefing,
    select_events_for_date,
)
from hybrid_assistant.runtime import create_providers


def main() -> None:
    source = Path(__file__).parent / "data" / "calendar.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    target_date = date.fromisoformat(data["target_date"])
    timezone = ZoneInfo(data["timezone"])
    events = [
        CalendarEvent(
            title=item["title"],
            starts_at=datetime.fromisoformat(item["starts_at"]),
            duration_minutes=item["duration_minutes"],
            location=item["location"],
        )
        for item in data["events"]
    ]
    selected = select_events_for_date(events, target_date, timezone)
    print(f"目标日期：{target_date}（{timezone.key}）")
    print(f"读取 {len(events)} 条日程，选中 {len(selected)} 条。\n")
    print(build_calendar_briefing(selected, create_providers(), timezone=timezone))


if __name__ == "__main__":
    main()
