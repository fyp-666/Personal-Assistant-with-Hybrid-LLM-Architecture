"""Read selected Gmail messages and summarize them through the configured GPT/Local route in WSL."""

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
        "--subject",
        help="Optional subject substring; select from the entire inbox by default",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send the summary to the configured Telegram private chat",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--limit", type=int, help="Maximum number of messages to read; default 1"
    )
    selection.add_argument(
        "--daily",
        action="store_true",
        help="Summarize all inbox messages received in the past 24 hours",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only delivery status, suitable for scheduled runs",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be a positive integer")
    if args.quiet and not args.send:
        parser.error("--quiet requires --send")
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
                "The inbox is empty."
                if args.subject is None
                else "No inbox messages match the subject."
            )
            parser.exit(1, f"{message}\n")
        providers = create_providers()
        if args.daily:
            pacific = ZoneInfo("America/Los_Angeles")
            summary = (
                "Daily email briefing (past 24 hours)\n"
                f"Range: {start.astimezone(pacific).isoformat(sep=' ')}"
                f" to {end.astimezone(pacific).isoformat(sep=' ')}\n"
                f"Messages: {len(emails)}\n\n"
                + (
                    build_email_briefing(emails, providers)
                    if emails
                    else "No new email in the past 24 hours."
                )
            )
        elif limit == 1:
            result = summarize_email(emails[0], providers)
            summary = render_email_summary(emails[0], result.text)
        else:
            summary = (
                f"Email briefing ({len(emails)} messages)\n\n"
                + build_email_briefing(emails, providers)
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
            print(f"Sent an email briefing with {len(emails)} messages.", flush=True)
        parser.exit(0, "Summary sent to Telegram.\n")


if __name__ == "__main__":
    main()
