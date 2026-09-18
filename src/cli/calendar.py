"""读取本地日历 JSON，生成指定日期的日程简报；尚不定时推送。"""

import argparse
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from adapters.calendar_file import load_calendar_file
from app.runtime import create_providers
from features.calendar import (
    build_calendar_briefing,
    select_events_for_date,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="hybrid-assistant calendar", description=__doc__
    )
    parser.add_argument(
        "file", type=Path, help="日历 JSON 文件；格式见 config/calendar.example.json"
    )
    parser.add_argument("--date", help="覆盖文件中的目标日期，格式 YYYY-MM-DD")
    parser.add_argument("--timezone", help="覆盖文件中的时区，例如 America/Los_Angeles")
    args = parser.parse_args(argv)
    try:
        events, target_date, timezone = load_calendar_file(args.file)
        if args.date is not None:
            target_date = date.fromisoformat(args.date)
        if args.timezone is not None:
            timezone = ZoneInfo(args.timezone)
        selected = select_events_for_date(events, target_date, timezone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        parser.exit(2, f"日历输入无效：{error}\n")
    print(f"目标日期：{target_date}（{timezone.key}）")
    print(f"读取 {len(events)} 条日程，选中 {len(selected)} 条。\n")
    print(build_calendar_briefing(selected, create_providers(), timezone=timezone))


if __name__ == "__main__":
    main()
