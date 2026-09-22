"""Read a selected Gmail message over TLS without changing mailbox flags."""

import imaplib
import json
import ssl
import time
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path

from features.email import Email, EmailQuery, EmailSearchResult


class GmailError(RuntimeError):
    """An expected Gmail connection or message-reading failure."""


def load_gmail_credentials() -> tuple[str, str]:
    """Read the shared WSL-home configuration without exposing secret values."""
    path = Path.home() / ".hermes/profiles/hw3-local/gmail.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        address = config["address"].strip()
        password = config["app_password"].strip()
        if not address or not password:
            raise ValueError("Incomplete configuration")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise GmailError(f"请先在 {path} 填写 address 和 app_password。") from None
    return address, password


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li", "tr"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li", "tr"} and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def parse_email(raw: bytes) -> Email:
    """Decode MIME headers/body, preferring plain text and ignoring attachments."""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    part = message.get_body(preferencelist=("plain", "html"))
    # A bodyless/image-only message is still a matching mailbox result.
    # Preserve its headers and position; an empty body explicitly means that
    # there is no text available to summarize, not that fetching failed.
    body = ""
    if part is not None:
        try:
            body = part.get_content()
        except (LookupError, UnicodeError):
            raise GmailError("无法解码这封邮件的正文。") from None
        if part.get_content_type() == "text/html":
            parser = _HTMLText()
            parser.feed(body)
            body = "".join(parser.parts)
    return Email(
        sender=str(message.get("From", "")),
        subject=str(message.get("Subject", "")),
        body=body.strip(),
    )


def read_gmail_email(
    address: str, app_password: str, *, subject: str | None = None
) -> Email | None:
    """Read one latest message through the shared batch reader."""
    emails = read_gmail_emails(address, app_password, limit=1, subject=subject)
    return emails[0] if emails else None


def query_gmail(query: EmailQuery) -> EmailSearchResult:
    """Read a bounded INBOX result set, checking one extra match for truncation."""
    emails, has_more = _read_gmail_emails(
        *load_gmail_credentials(),
        subject=query.subject,
        received_since=query.received_since,
        received_before=query.received_before,
        limit=query.limit,
        check_more=True,
    )
    return EmailSearchResult(query=query, emails=emails, has_more=has_more)


def read_gmail_emails(
    address: str,
    app_password: str,
    *,
    limit: int | None = 1,
    subject: str | None = None,
    received_since: datetime | None = None,
    received_before: datetime | None = None,
) -> list[Email]:
    """Read INBOX in descending UID order, within [since, before); None means all."""
    emails, _ = _read_gmail_emails(
        address,
        app_password,
        limit=limit,
        subject=subject,
        received_since=received_since,
        received_before=received_before,
    )
    return emails


def _read_gmail_emails(
    address: str,
    app_password: str,
    *,
    limit: int | None,
    subject: str | None,
    received_since: datetime | None,
    received_before: datetime | None,
    check_more: bool = False,
) -> tuple[list[Email], bool]:
    """Share filtering and fetching; lookahead needs only a matching UID, not its body."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer or None")
    if (received_since is None) != (received_before is None):
        raise ValueError("both received-time boundaries are required")
    if received_since is not None:
        if any(
            not isinstance(value, datetime) or value.utcoffset() is None
            for value in (received_since, received_before)
        ):
            raise ValueError("received-time boundaries must be timezone-aware")
        received_since = received_since.astimezone(UTC)
        received_before = received_before.astimezone(UTC)
        if received_since >= received_before:
            raise ValueError("received_since must precede received_before")
    criteria = ("ALL",)
    if subject is not None:
        if not subject.strip() or any(char in subject for char in "\r\n\0"):
            raise ValueError("subject must be nonempty and contain no line breaks")
        quoted = '"' + subject.replace("\\", "\\\\").replace('"', '\\"') + '"'
        criteria = ("CHARSET", "UTF-8", "SUBJECT", quoted.encode("utf-8"))
    if received_since is not None:
        # IMAP date search ignores time/offset; widen it, then check INTERNALDATE.
        criteria += (
            "SINCE",
            _imap_date(received_since - timedelta(days=1)),
            "BEFORE",
            _imap_date(received_before + timedelta(days=2)),
        )
    try:
        with imaplib.IMAP4_SSL(
            "imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=30
        ) as mailbox:
            mailbox.login(address, app_password.replace(" ", ""))
            status, _ = mailbox.select("INBOX", readonly=True)
            if status != "OK":
                raise GmailError("无法以只读方式打开 Gmail 收件箱。")
            status, data = mailbox.uid("search", *criteria)
            if status != "OK":
                raise GmailError("Gmail 邮件搜索失败。")
            ids = data[0].split() if data and data[0] else []
            emails = []
            for uid in sorted(ids, key=int, reverse=True):
                if received_since is not None:
                    status, data = mailbox.uid("fetch", uid, "(INTERNALDATE)")
                    if status != "OK":
                        raise GmailError("Gmail 邮件收件时间读取失败。")
                    received_at = _received_at(data)
                    if not received_since <= received_at < received_before:
                        continue
                if limit is not None and len(emails) >= limit:
                    return emails, True
                status, data = mailbox.uid("fetch", uid, "(BODY.PEEK[])")
                if status != "OK":
                    raise GmailError("Gmail 邮件读取失败。")
                raw = next((item[1] for item in data if isinstance(item, tuple)), None)
                if not isinstance(raw, bytes):
                    raise GmailError("Gmail 未返回邮件正文。")
                emails.append(parse_email(raw))
                if limit is not None and len(emails) >= limit and not check_more:
                    break
            return emails, False
    except (imaplib.IMAP4.error, OSError):
        raise GmailError("Gmail 连接或登录失败，请检查网络和应用专用密码。") from None


def _imap_date(value: datetime) -> str:
    months = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    return f"{value.day:02d}-{months[value.month - 1]}-{value.year:04d}"


def _received_at(data: list) -> datetime:
    """Convert the server's INTERNALDATE, including offset, to an exact UTC instant."""
    metadata = b" ".join(part for part in data if isinstance(part, bytes))
    try:
        local_time = imaplib.Internaldate2tuple(metadata)
        if local_time is not None:
            return datetime.fromtimestamp(time.mktime(local_time), UTC)
    except (ValueError, KeyError, OverflowError, OSError):
        pass
    raise GmailError("Gmail 返回了无效的收件时间。")
