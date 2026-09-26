"""Explicit Google Calendar authorization and binding; no model calls."""

import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

from adapters.google_calendar import GoogleCalendar, api_call
from adapters.google_calendar_auth import (
    authorize,
    build_service,
    calendar_home,
    configuration_lock,
    load_config,
    save_json,
)
from features.calendar_actions import (
    CalendarError,
    CalendarQuery,
    CalendarRequest,
    aware_time,
    render_calendar_result,
)


def connect(
    *,
    calendar_id: str | None,
    name: str | None,
    timezone: str,
    home: Path | None = None,
):
    directory = home if home is not None else calendar_home()
    ZoneInfo(timezone)
    if (calendar_id is None) == (name is None):
        raise CalendarError(
            "Choose an existing calendar ID or a name for a new calendar."
        )
    if name is not None and (
        not name.strip() or len(name) > 200 or any(ord(c) < 32 for c in name)
    ):
        raise CalendarError("Invalid calendar name.")
    # Build before locking: token refresh uses the same lock.
    service = build_service(directory)
    with configuration_lock(directory):
        if (directory / "config.json").exists():
            raise CalendarError(
                "A Google calendar is already bound. This command does not create another or replace the binding."
            )
        pending = directory / "pending-calendar.json"
        if calendar_id is not None:
            resource = api_call(service.calendars(), "get", calendarId=calendar_id)
        else:
            if pending.exists():
                raise CalendarError(
                    "The previous calendar creation still needs verification. Check Google; bind an existing calendar with --calendar-id rather than creating it again."
                )
            save_json(pending, {"summary": name, "timezone": timezone})
            resource = api_call(
                service.calendars(),
                "insert",
                body={"summary": name, "timeZone": timezone},
            )
            # Retain the actual ID if final binding fails, for manual recovery.
            save_json(pending, resource)
        try:
            config = {
                "calendar_id": resource["id"],
                "timezone": resource["timeZone"],
                "summary": resource["summary"],
            }
            if (
                not all(isinstance(value, str) and value for value in config.values())
                or config["calendar_id"] == "primary"
            ):
                raise ValueError
            ZoneInfo(config["timezone"])
        except (KeyError, ValueError, TypeError):
            raise CalendarError(
                "Google returned incomplete calendar data. Verify the actual result in Google first."
            ) from None
        save_json(directory / "config.json", config)
        if pending.exists():
            pending.unlink()
        return config


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        prog="hybrid-assistant calendar google", description=__doc__
    )
    commands = parser.add_subparsers(dest="command", required=True)
    auth = commands.add_parser(
        "auth", help="Authorize in a browser and save private OAuth credentials only"
    )
    auth.add_argument(
        "--client-secrets",
        type=Path,
        required=True,
        help="Google desktop application JSON (WSL path)",
    )
    auth.add_argument(
        "--existing",
        action="store_true",
        help="Request event access for your existing calendars; default scope is limited to calendars created by the app",
    )
    auth.add_argument("--port", type=int, default=8765)
    binding = commands.add_parser(
        "connect", help="Bind an existing calendar or explicitly create a separate one"
    )
    target = binding.add_mutually_exclusive_group(required=True)
    target.add_argument("--calendar-id")
    target.add_argument(
        "--name", help="Name for a new separate calendar, for example AI Assistant"
    )
    binding.add_argument("--timezone", default="America/Los_Angeles")
    commands.add_parser(
        "status",
        help="Read Google calendar details to check the current binding and authorization",
    )
    query = commands.add_parser(
        "query", help="Query Google directly for verification without calling a model"
    )
    query.add_argument(
        "--from",
        dest="starts_after",
        required=True,
        help="Offset-bearing ISO datetime, inclusive start",
    )
    query.add_argument(
        "--until",
        dest="starts_before",
        required=True,
        help="Offset-bearing ISO datetime, exclusive end",
    )
    query.add_argument("--text")
    query.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        if args.command == "auth":
            authorize(args.client_secrets, existing=args.existing, port=args.port)
            print(
                "Google Calendar authorization saved. Next, run calendar google connect to bind a calendar."
            )
        elif args.command == "connect":
            config = connect(
                calendar_id=args.calendar_id, name=args.name, timezone=args.timezone
            )
            print(
                f"Google calendar bound: {config['summary']} ({config['timezone']}). Chat and reminders now use this calendar."
            )
        elif args.command == "status":
            config = load_config()
            resource = api_call(
                build_service().calendars(), "get", calendarId=config["calendar_id"]
            )
            print(
                f"Google Calendar connection is working: {resource['summary']} ({resource['timeZone']})."
            )
            print(
                "Source: Google Calendar. For Telegram reminders, run calendar reminders --send --watch."
            )
        else:
            request = CalendarRequest(
                "query",
                query=CalendarQuery(
                    aware_time(args.starts_after),
                    aware_time(args.starts_before),
                    args.text,
                    args.limit,
                ),
            )
            print(render_calendar_result(GoogleCalendar().execute(request)))
    except KeyboardInterrupt:
        parser.exit(1, "Authorization or connection interrupted.\n")
    except (CalendarError, ValueError, KeyError, OSError) as error:
        message = (
            str(error)
            if isinstance(error, (CalendarError, ValueError))
            else "Invalid calendar configuration or returned data."
        )
        parser.exit(1, f"{message}\n")
