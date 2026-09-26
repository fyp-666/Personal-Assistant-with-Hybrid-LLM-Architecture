"""Calendar authorization, briefings, and reminder checks; use chat or Telegram to manage events."""

import argparse
import sys
import time
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from adapters.calendar_file import load_calendar_file
from adapters.messaging import send_message
from adapters.telegram import TelegramError, load_telegram_config
from app.runtime import create_calendar, create_providers
from features.calendar import (
    build_calendar_briefing,
    select_events_for_date,
)
from features.calendar_actions import (
    CalendarBusyError,
    CalendarError,
    render_calendar_item,
)


def _briefing(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="hybrid-assistant calendar",
        description=__doc__,
        epilog="Google setup: calendar google --help; reminder checks: calendar reminders --help.",
    )
    parser.add_argument(
        "file",
        type=Path,
        help="Calendar JSON file; see config/calendar.example.json for the format",
    )
    parser.add_argument(
        "--date", help="Override the target date from the file, in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--timezone",
        help="Override the timezone from the file, for example America/Los_Angeles",
    )
    args = parser.parse_args(argv)
    try:
        events, target_date, timezone = load_calendar_file(args.file)
        if args.date is not None:
            target_date = date.fromisoformat(args.date)
        if args.timezone is not None:
            timezone = ZoneInfo(args.timezone)
        selected = select_events_for_date(events, target_date, timezone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        parser.exit(2, f"Invalid calendar input: {error}\n")
    print(f"Target date: {target_date} ({timezone.key})")
    print(f"Read {len(events)} events; selected {len(selected)}.\n")
    print(build_calendar_briefing(selected, create_providers(), timezone=timezone))


def _reminders(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="hybrid-assistant calendar reminders",
        description="Preview due reminders by default; --send delivers them to the bound Telegram chat.",
    )
    parser.add_argument(
        "--send", action="store_true", help="Send reminders and record their outcomes"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Check continuously; requires --send. Ctrl+C stops the checker",
    )
    parser.add_argument(
        "--interval", type=int, default=30, help="Check interval in seconds; default 30"
    )
    parser.add_argument(
        "--status", action="store_true", help="Show reminder status counts only"
    )
    args = parser.parse_args(argv)
    if not 1 <= args.interval <= 3600:
        parser.error("interval must be between 1 and 3600 seconds.")
    if args.watch and not args.send:
        parser.error("--watch requires --send.")
    if args.status and (args.send or args.watch):
        parser.error("--status cannot be combined with sending or continuous checks.")
    try:
        calendar = create_calendar()
        if args.status:
            labels = {
                "pending": "Pending",
                "sending": "Sending; verification needed",
                "sent": "Sent",
                "unknown": "Unknown; verification needed",
                "failed": "Failed before sending",
                "expired": "Expired",
                "cancelled": "Cancelled",
            }
            status = calendar.reminder_status()
            print(
                "; ".join(
                    f"{labels.get(key, key)}: {count}" for key, count in status.items()
                )
                or "No reminder records."
            )
            return
        if not args.send:
            items = calendar.preview_due()
            print("Due reminder preview (not sent; synchronized with Google Calendar):")
            print(
                "\n\n".join(render_calendar_item(item) for item in items)
                or "No due reminders."
            )
            if calendar.skipped_items:
                print(
                    f"{calendar.skipped_items} additional Google events are unsupported. View them in Google Calendar."
                )
            return
        config = load_telegram_config(Path.home() / ".hermes/profiles/hw3-local")

        def deliver(item):
            send_message(
                "Event reminder\n" + render_calendar_item(item),
                target=f"telegram:{config.chat_id}",
            )

        while True:
            try:
                result = calendar.send_due(deliver)
            except CalendarBusyError:
                if not args.watch:
                    raise
                print(
                    "The calendar is busy with another operation. Checking will resume on the next pass.",
                    flush=True,
                )
                time.sleep(args.interval)
                continue
            print(
                f"Sent {result['sent']}; failed before sending {result['failed']}; "
                f"unknown {result['unknown']}; expired {result['expired']}.",
                flush=True,
            )
            if calendar.skipped_items:
                print(
                    f"{calendar.skipped_items} additional Google events are unsupported; no reminders were sent for them in this batch.",
                    flush=True,
                )
            if not args.watch:
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Reminder checker stopped.")
    except (CalendarError, TelegramError, ValueError) as error:
        parser.exit(1, f"{error}\n")


def main(argv: list[str] | None = None) -> None:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments and arguments[0] == "google":
        from cli.google_calendar import main as google_main

        google_main(arguments[1:])
    elif arguments and arguments[0] == "reminders":
        _reminders(arguments[1:])
    else:
        _briefing(arguments)


if __name__ == "__main__":
    main()
