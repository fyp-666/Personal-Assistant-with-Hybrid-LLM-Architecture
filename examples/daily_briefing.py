"""Build a daily briefing with real local calendar and email summaries in WSL."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from hybrid_assistant.briefing import build_daily_briefing
from hybrid_assistant.calendar import CalendarEvent, select_events_for_date
from hybrid_assistant.email import Email
from hybrid_assistant.runtime import create_providers


def main() -> None:
    target_date = date(2026, 9, 8)
    timezone = ZoneInfo("America/Los_Angeles")
    events = [
        CalendarEvent(
            title="项目讨论",
            starts_at=datetime.fromisoformat("2026-09-08T14:00:00-07:00"),
            duration_minutes=45,
            location="会议室 A",
        ),
        CalendarEvent(
            title="团队会议",
            starts_at=datetime.fromisoformat("2026-09-08T10:00:00-07:00"),
            duration_minutes=30,
            location="线上",
        ),
        CalendarEvent(
            title="次日课程",
            starts_at=datetime.fromisoformat("2026-09-09T09:00:00-07:00"),
            duration_minutes=60,
            location="教室 B",
        ),
    ]
    emails = [
        Email(
            sender="课程助教 <ta@example.com>",
            subject="项目演示材料提交",
            body=(
                "请在 2026-09-08 16:00（UTC-07:00）前提交项目演示材料，"
                "需要包含 1 份 PDF 和 2 张截图。请在提交前检查附件能否打开。"
            ),
        ),
        Email(
            sender="组员 <teammate@example.com>",
            subject="小组讨论准备",
            body=(
                "请在 2026-09-09 10:00（UTC-07:00）的小组讨论前阅读第 3 章，"
                "并准备 2 个问题。"
            ),
        ),
    ]
    selected_events = select_events_for_date(events, target_date, timezone)
    providers = create_providers()
    print(build_daily_briefing(selected_events, emails, providers, timezone=timezone))


if __name__ == "__main__":
    main()
