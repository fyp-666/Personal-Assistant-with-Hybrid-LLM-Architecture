"""日历授权、简报和提醒检查；日程管理使用 chat 或 Telegram 对话。"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from adapters.calendar_file import load_calendar_file
from adapters.calendar_store import LocalCalendarStore
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
        epilog="Google 接入：calendar google --help；提醒检查：calendar reminders --help。",
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


def _reminders(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="hybrid-assistant calendar reminders",
        description="默认仅预览到期提醒；--send 才实际发送到已绑定的 Telegram。",
    )
    parser.add_argument("--store", type=Path, help="本地日历数据库路径")
    parser.add_argument("--send", action="store_true", help="实际发送并记录结果")
    parser.add_argument(
        "--watch", action="store_true", help="持续检查，须同时 --send；Ctrl+C 停止"
    )
    parser.add_argument(
        "--interval", type=int, default=30, help="持续检查间隔秒数，默认30"
    )
    parser.add_argument("--status", action="store_true", help="仅查看所有提醒状态计数")
    args = parser.parse_args(argv)
    if not 1 <= args.interval <= 3600:
        parser.error("interval 须为 1 到 3600 秒。")
    if args.watch and not args.send:
        parser.error("--watch 须同时使用 --send。")
    if args.status and (args.send or args.watch):
        parser.error("--status 不能与发送或持续检查并用。")
    try:
        store = LocalCalendarStore(args.store) if args.store else create_calendar()
        if args.status:
            labels = {
                "pending": "待发送",
                "sending": "发送中待核查",
                "sent": "已发送",
                "unknown": "结果不确定待核查",
                "failed": "发送前失败",
                "expired": "超出补发窗口",
                "cancelled": "已取消",
            }
            status = store.reminder_status()
            print(
                "；".join(
                    f"{labels.get(key, key)}：{count}" for key, count in status.items()
                )
                or "暂无提醒记录。"
            )
            return
        if not args.send:
            items = store.preview_due()
            print("到期待发送提醒预览（未发送；Google 模式会刷新本地同步记录）：")
            print(
                "\n\n".join(render_calendar_item(item) for item in items)
                or "暂无到期提醒。"
            )
            if getattr(store, "skipped_items", 0):
                print(
                    f"另有 {store.skipped_items} 条暂不支持的 Google 日程，请在 Google 查看。"
                )
            return
        config = load_telegram_config(Path.home() / ".hermes/profiles/hw3-local")

        def deliver(item):
            send_message(
                "日程提醒\n" + render_calendar_item(item),
                target=f"telegram:{config.chat_id}",
            )

        while True:
            try:
                result = store.send_due(deliver)
            except CalendarBusyError:
                if not args.watch:
                    raise
                print("日历正在处理其他操作，下次继续检查。", flush=True)
                time.sleep(args.interval)
                continue
            print(
                f"已发送 {result['sent']}；发送前失败 {result['failed']}；"
                f"结果不确定 {result['unknown']}；超时未补发 {result['expired']}。",
                flush=True,
            )
            if getattr(store, "skipped_items", 0):
                print(
                    f"另有 {store.skipped_items} 条暂不支持的 Google 日程，本批未为它们发送提醒。",
                    flush=True,
                )
            if not args.watch:
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("提醒检查已停止。")
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
