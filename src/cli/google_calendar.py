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
        raise CalendarError("请选择一个已有日历 ID 或新日历名称。")
    if name is not None and (
        not name.strip() or len(name) > 200 or any(ord(c) < 32 for c in name)
    ):
        raise CalendarError("日历名称无效。")
    # Build before locking: token refresh uses the same lock.
    service = build_service(directory)
    with configuration_lock(directory):
        if (directory / "config.json").exists():
            raise CalendarError("已绑定 Google 日历；本命令不重复创建或覆盖现有绑定。")
        pending = directory / "pending-calendar.json"
        if calendar_id is not None:
            resource = api_call(service.calendars(), "get", calendarId=calendar_id)
        else:
            if pending.exists():
                raise CalendarError(
                    "上次新建日历的结果尚待核查。请在 Google 查看；已创建的日历请用 --calendar-id 绑定，勿再次新建。"
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
                "Google 返回的日历资料不完整，请先在 Google 核查实际结果。"
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
    auth = commands.add_parser("auth", help="浏览器授权，仅保存私有 OAuth 凭据")
    auth.add_argument(
        "--client-secrets",
        type=Path,
        required=True,
        help="Google 桌面应用 JSON（WSL 路径）",
    )
    auth.add_argument(
        "--existing",
        action="store_true",
        help="申请管理自己已有日历的事件权限；默认只申请应用新建日历权限",
    )
    auth.add_argument("--port", type=int, default=8765)
    binding = commands.add_parser(
        "connect", help="绑定已有日历，或明确创建一个独立日历"
    )
    target = binding.add_mutually_exclusive_group(required=True)
    target.add_argument("--calendar-id")
    target.add_argument("--name", help="新建独立日历名称，例如 AI 助手")
    binding.add_argument("--timezone", default="America/Los_Angeles")
    commands.add_parser("status", help="读取 Google 日历资料，检查当前绑定和授权")
    query = commands.add_parser(
        "query", help="直接查询 Google，便于核对，期间不调用模型"
    )
    query.add_argument(
        "--from", dest="starts_after", required=True, help="带偏移 ISO 日期时间，含起点"
    )
    query.add_argument(
        "--until",
        dest="starts_before",
        required=True,
        help="带偏移 ISO 日期时间，不含终点",
    )
    query.add_argument("--text")
    query.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        if args.command == "auth":
            authorize(args.client_secrets, existing=args.existing, port=args.port)
            print(
                "Google 日历授权已保存。下一步运行 calendar google connect 绑定日历。"
            )
        elif args.command == "connect":
            config = connect(
                calendar_id=args.calendar_id, name=args.name, timezone=args.timezone
            )
            print(
                f"已绑定 Google 日历：{config['summary']}（{config['timezone']}）。聊天和提醒现在使用这个日历。"
            )
        elif args.command == "status":
            config = load_config()
            resource = api_call(
                build_service().calendars(), "get", calendarId=config["calendar_id"]
            )
            print(
                f"Google 日历连接正常：{resource['summary']}（{resource['timeZone']}）。"
            )
            print(
                "数据源：Google Calendar；Telegram 提醒需运行 calendar reminders --send --watch。"
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
        parser.exit(1, "授权或连接已中断。\n")
    except (CalendarError, ValueError, KeyError, OSError) as error:
        message = (
            str(error)
            if isinstance(error, (CalendarError, ValueError))
            else "日历配置或返回资料无效。"
        )
        parser.exit(1, f"{message}\n")
