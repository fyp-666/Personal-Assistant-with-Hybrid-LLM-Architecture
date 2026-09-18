"""Read selected Gmail messages and summarize them with local Gemma in WSL."""

import argparse
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from adapters.gmail import (
    GmailError,
    load_gmail_credentials,
    read_gmail_emails,
)
from adapters.messaging import DeliveryError, send_message
from app.runtime import create_providers
from core.execution import ProviderError
from features.briefing import build_email_briefing
from features.email import render_email_summary, summarize_email


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="hybrid-assistant gmail", description=__doc__)
    parser.add_argument(
        "--subject", help="可选：匹配主题中的文字；默认从整个收件箱选择"
    )
    parser.add_argument(
        "--send", action="store_true", help="将摘要发送到已配置的 Telegram 私聊"
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--limit", type=int, help="最多读取几封邮件，默认 1")
    selection.add_argument(
        "--daily", action="store_true", help="汇总过去 24 小时收到的全部收件箱邮件"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="发送时只输出状态，适合定时运行"
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须是正整数")
    if args.quiet and not args.send:
        parser.error("--quiet 需要与 --send 一起使用")
    limit = None if args.daily else (args.limit or 1)
    try:
        address, password = load_gmail_credentials()
        if args.daily:
            end = datetime.now(UTC).replace(microsecond=0)
            start = end - timedelta(hours=24)
            emails = read_gmail_emails(
                address,
                password,
                limit=None,
                subject=args.subject,
                received_since=start,
                received_before=end,
            )
        else:
            emails = read_gmail_emails(
                address, password, limit=limit, subject=args.subject
            )
        if not emails and not args.daily:
            message = (
                "收件箱为空。"
                if args.subject is None
                else "收件箱中没有匹配主题的邮件。"
            )
            parser.exit(1, f"{message}\n")
        providers = create_providers()
        if args.daily:
            pacific = ZoneInfo("America/Los_Angeles")
            summary = (
                "每日邮件简报（过去 24 小时）\n"
                f"统计范围：{start.astimezone(pacific).isoformat(sep=' ')}"
                f" 至 {end.astimezone(pacific).isoformat(sep=' ')}\n"
                f"邮件数量：{len(emails)} 封\n\n"
                + (
                    build_email_briefing(emails, providers)
                    if emails
                    else "过去 24 小时暂无新邮件。"
                )
            )
        elif limit == 1:
            result = summarize_email(emails[0], providers)
            summary = render_email_summary(emails[0], result.text)
        else:
            summary = f"邮件简报（{len(emails)} 封）\n\n" + build_email_briefing(
                emails, providers
            )
    except (GmailError, ProviderError) as error:
        parser.exit(1, f"{error}\n")
    if not args.quiet:
        print(summary, flush=True)
    if args.send:
        try:
            send_message(summary, target="telegram")
        except DeliveryError as error:
            parser.exit(1, f"{error}\n")
        if args.quiet:
            print(f"已发送邮件简报，包含 {len(emails)} 封邮件。", flush=True)
        parser.exit(0, "摘要已发送到 Telegram。\n")


if __name__ == "__main__":
    main()
