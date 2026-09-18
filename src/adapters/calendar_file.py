"""Read an explicit local calendar source, without starting a model."""

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from features.calendar import CalendarEvent


class CalendarFileError(ValueError):
    """The local calendar file could not be read or validated."""


def load_calendar_file(path: Path) -> tuple[list[CalendarEvent], date, ZoneInfo]:
    """Load the documented events/target_date/timezone JSON format."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) - {"description"} != {
            "events",
            "target_date",
            "timezone",
        }:
            raise ValueError("Invalid calendar document")
        target_date = date.fromisoformat(data["target_date"])
        timezone = ZoneInfo(data["timezone"])
        if not isinstance(data["events"], list):
            raise TypeError("Invalid events")
        events = []
        for item in data["events"]:
            if (
                not isinstance(item, dict)
                or set(item) != {"title", "starts_at", "duration_minutes", "location"}
                or any(
                    not isinstance(item[key], str)
                    for key in ("title", "starts_at", "location")
                )
            ):
                raise ValueError("Invalid event")
            events.append(
                CalendarEvent(
                    title=item["title"],
                    starts_at=datetime.fromisoformat(item["starts_at"]),
                    duration_minutes=item["duration_minutes"],
                    location=item["location"],
                )
            )
        return events, target_date, timezone
    except (OSError, ValueError, TypeError, KeyError, ZoneInfoNotFoundError):
        raise CalendarFileError(
            "无法读取日历文件：请检查 UTF-8 JSON、日期、时区和事件字段；开始时间须包含 UTC 偏移，时长须为正整数。"
        ) from None
