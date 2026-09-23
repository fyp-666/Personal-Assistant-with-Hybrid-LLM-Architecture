"""Bounded shared conversation context, separate from long-term USER.md preferences."""

import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

from core.routing import Complexity
from features.calendar_actions import MAX_CALENDAR_RESULTS, CalendarItem, CalendarResult
from features.email import MAX_EMAIL_RESULTS, Email, EmailQuery, EmailSearchResult

MAX_TURNS = 6
HISTORY_CHARS = 12000
EMAIL_CHARS = 16000
EMAIL_HEADER_CHARS = 1000
_TRUNCATED = "\n[后续邮件正文未保留]"


class ConversationError(RuntimeError):
    """Conversation state could not be safely loaded or saved."""


@contextmanager
def conversation_session(path: Path) -> Generator["Conversation", None, None]:
    """Persist successful turns and privacy restrictions even when a turn fails."""
    state = load_conversation(path)
    was_private = state.private
    try:
        yield state
    except BaseException as error:
        # Failed requests must not reopen the cloud boundary. A second failed
        # save must preserve an existing storage error's confirmed tool receipt.
        if state.private and not was_private:
            try:
                save_conversation(path, state)
            except ConversationError:
                if isinstance(error, ConversationError):
                    raise error from None
                raise
        raise
    else:
        save_conversation(path, state)


def bound_email_result(result: EmailSearchResult) -> EmailSearchResult:
    """Copy ordered results into a shared body budget, including truncation notices."""
    if (
        not isinstance(result, EmailSearchResult)
        or not isinstance(result.query, EmailQuery)
        or type(result.query.limit) is not int
        or not 1 <= result.query.limit <= MAX_EMAIL_RESULTS
        or not isinstance(result.emails, list)
        or len(result.emails) > result.query.limit
        or type(result.has_more) is not bool
    ):
        raise ValueError("Invalid email search result")
    if any(
        not isinstance(email, Email)
        or any(
            not isinstance(value, str)
            for value in (email.sender, email.subject, email.body)
        )
        for email in result.emails
    ):
        raise ValueError("Invalid email snapshot")
    if not result.emails:
        return EmailSearchResult(result.query, [], result.has_more)
    body_budget, extra = divmod(EMAIL_CHARS, len(result.emails))
    emails = []
    for index, email in enumerate(result.emails):
        limit = body_budget + (index < extra)
        body = email.body
        if len(body) > limit:
            body = body[: limit - len(_TRUNCATED)] + _TRUNCATED
        emails.append(
            Email(
                email.sender[:EMAIL_HEADER_CHARS],
                email.subject[:EMAIL_HEADER_CHARS],
                body,
            )
        )
    return EmailSearchResult(result.query, emails, result.has_more)


@dataclass
class Conversation:
    turns: list[dict[str, str]] = field(default_factory=list)
    private: bool = False
    email_result: EmailSearchResult | None = None
    complexity: Complexity = Complexity.NORMAL
    calendar_result: CalendarResult | None = None
    calendar_items: list[CalendarItem] = field(default_factory=list)

    def __post_init__(self):
        if not self.calendar_items and self.calendar_result is not None:
            self.calendar_items = list(self.calendar_result.items)
        if (
            not isinstance(self.calendar_items, list)
            or len(self.calendar_items) > MAX_CALENDAR_RESULTS
            or any(not isinstance(item, CalendarItem) for item in self.calendar_items)
            or len({item.event_id for item in self.calendar_items})
            != len(self.calendar_items)
        ):
            raise ValueError("无效的日历上下文。")

    def apply_results(
        self,
        *,
        email_result: EmailSearchResult | None = None,
        calendar_result: CalendarResult | None = None,
    ) -> None:
        """Apply confirmed tool facts between decisions without adding a fake turn."""
        bounded = bound_email_result(email_result) if email_result is not None else None
        calendar = (
            CalendarResult.from_dict(calendar_result.to_dict())
            if calendar_result is not None
            else None
        )
        if calendar is not None:
            if (
                calendar.operation == "query"
                or self.calendar_result is None
                or self.calendar_result.source_label != calendar.source_label
            ):
                # A new query (including empty) or source replaces the working set.
                self.calendar_items = list(calendar.items)
            else:
                # Keep the latest receipt separate from other known target records.
                known = {item.event_id: item for item in self.calendar_items}
                for item in calendar.items:
                    known[item.event_id] = item
                self.calendar_items = list(known.values())[-MAX_CALENDAR_RESULTS:]
            self.calendar_result = calendar
        if bounded is not None:
            # An empty result is still the current query; never reuse older mail.
            self.email_result = bounded

    def record(
        self,
        message: str,
        answer: str,
        *,
        private: bool,
        complexity: Complexity,
        email_result: EmailSearchResult | None = None,
        calendar_result: CalendarResult | None = None,
    ) -> None:
        self.apply_results(email_result=email_result, calendar_result=calendar_result)
        self.private = self.private or private
        self.complexity = complexity
        self.turns.append(
            {
                "user": message[: HISTORY_CHARS // 2],
                "assistant": answer[: HISTORY_CHARS // 2],
            }
        )
        self.turns = self.turns[-MAX_TURNS:]
        while (
            len(self.turns) > 1
            and sum(len(t["user"]) + len(t["assistant"]) for t in self.turns)
            > HISTORY_CHARS
        ):
            self.turns.pop(0)

    def payload(self) -> dict:
        """Provide the same context to every request, without a follow-up gate."""
        data = {
            "history": self.turns,
            "previous_complexity": self.complexity.value,
        }
        if self.email_result is not None:
            data["email_result"] = {
                "query": self.email_result.query.to_dict(),
                "emails": [
                    {"number": index, **asdict(email)}
                    for index, email in enumerate(self.email_result.emails, start=1)
                ],
                "has_more": self.email_result.has_more,
            }
        if self.calendar_result is not None:
            data["calendar_result"] = {
                **self.calendar_result.to_dict(),
                "items": [item.model_data() for item in self.calendar_result.items],
            }
        if self.calendar_items:
            data["calendar_items"] = [item.model_data() for item in self.calendar_items]
        return data


def _email_from_dict(data: object, *, body_limit: int = EMAIL_CHARS) -> Email:
    if (
        not isinstance(data, dict)
        or set(data) != {"sender", "subject", "body"}
        or any(not isinstance(value, str) for value in data.values())
        or len(data["body"]) > body_limit
        or len(data["sender"]) > EMAIL_HEADER_CHARS
        or len(data["subject"]) > EMAIL_HEADER_CHARS
    ):
        raise ValueError("Invalid email snapshot")
    return Email(**data)


def _result_from_dict(data: object) -> EmailSearchResult | None:
    if data is None:
        return None
    if (
        not isinstance(data, dict)
        or set(data) != {"query", "emails", "has_more"}
        or not isinstance(data["emails"], list)
        or type(data["has_more"]) is not bool
    ):
        raise ValueError("Invalid email search result")
    query = EmailQuery.from_dict(data["query"])
    if any(
        value is not None and "T" not in value
        for value in (data["query"]["received_since"], data["query"]["received_before"])
    ):
        raise ValueError("Stored query dates must retain their timezone offsets")
    emails = [_email_from_dict(item) for item in data["emails"]]
    if (
        len(emails) > query.limit
        or sum(len(email.body) for email in emails) > EMAIL_CHARS
    ):
        raise ValueError("Email result exceeds budget")
    return EmailSearchResult(query, emails, data["has_more"])


def load_conversation(path: Path) -> Conversation:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or type(data.get("private")) is not bool:
            raise ValueError("Invalid conversation privacy flag")
        if (
            isinstance(data, dict)
            and type(data.get("version")) is int
            and data["version"] == 2
        ):
            if set(data) != {
                "version",
                "turns",
                "private",
                "email_result",
                "complexity",
            }:
                raise ValueError("Invalid version 2 conversation")
            data = {
                **data,
                "version": 3,
                "calendar_result": None,
                "private": data["private"] or data["email_result"] is not None,
            }
        if (
            isinstance(data, dict)
            and type(data.get("version")) is int
            and data["version"] == 3
        ):
            if set(data) != {
                "version",
                "turns",
                "private",
                "email_result",
                "calendar_result",
                "complexity",
            }:
                raise ValueError("Invalid version 3 conversation")
            snapshot = data["calendar_result"]
            data = {
                **data,
                "version": 4,
                "calendar_items": snapshot["items"] if snapshot is not None else [],
            }
        if (
            isinstance(data, dict)
            and type(data.get("version")) is int
            and data["version"] == 4
        ):
            expected = {
                "version",
                "turns",
                "private",
                "email_result",
                "calendar_result",
                "calendar_items",
                "complexity",
            }
            if set(data) != expected:
                raise ValueError("Invalid version 4 conversation")
            data = {
                **data,
                "version": 5,
                "private": data["private"]
                or data["email_result"] is not None
                or data["calendar_result"] is not None,
            }
        legacy = isinstance(data, dict) and set(data) == {
            "turns",
            "private",
            "email",
            "complexity",
        }
        if (
            not isinstance(data, dict)
            or (
                not legacy
                and (
                    set(data)
                    != {
                        "version",
                        "turns",
                        "private",
                        "email_result",
                        "calendar_result",
                        "calendar_items",
                        "complexity",
                    }
                    or type(data["version"]) is not int
                    or data["version"] != 5
                )
            )
            or type(data["private"]) is not bool
        ):
            raise ValueError("Invalid conversation")
        turns = data["turns"]
        if (
            not isinstance(turns, list)
            or len(turns) > MAX_TURNS
            or any(
                not isinstance(turn, dict)
                or set(turn) != {"user", "assistant"}
                or any(not isinstance(value, str) for value in turn.values())
                for turn in turns
            )
        ):
            raise ValueError("Invalid turns")
        if sum(len(t["user"]) + len(t["assistant"]) for t in turns) > HISTORY_CHARS:
            raise ValueError("History exceeds budget")
        if legacy:
            raw_email = data["email"]
            email_result = (
                None
                if raw_email is None
                else bound_email_result(
                    EmailSearchResult(
                        EmailQuery(limit=1),
                        [_email_from_dict(raw_email, body_limit=EMAIL_CHARS + 100)],
                    )
                )
            )
        else:
            email_result = _result_from_dict(data["email_result"])
        calendar_result = (
            CalendarResult.from_dict(data["calendar_result"])
            if not legacy and data["calendar_result"] is not None
            else None
        )
        raw_items = [] if legacy else data["calendar_items"]
        if not isinstance(raw_items, list):
            raise TypeError("Invalid calendar context")
        calendar_items = [CalendarItem.from_dict(item) for item in raw_items]
        return Conversation(
            turns,
            data["private"] or (legacy and email_result is not None),
            email_result,
            Complexity(data["complexity"]),
            calendar_result,
            calendar_items,
        )
    except FileNotFoundError:
        return Conversation()
    except (OSError, ValueError, TypeError, KeyError):
        raise ConversationError(
            "会话文件无法读取；请检查本地文件，或开始新会话。"
        ) from None


def save_conversation(path: Path, conversation: Conversation) -> None:
    temporary = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        result = conversation.email_result
        data = {
            "version": 5,
            "turns": conversation.turns,
            "private": conversation.private,
            "email_result": (
                {
                    "query": result.query.to_dict(),
                    "emails": [asdict(email) for email in result.emails],
                    "has_more": result.has_more,
                }
                if result is not None
                else None
            ),
            "calendar_result": (
                conversation.calendar_result.to_dict()
                if conversation.calendar_result is not None
                else None
            ),
            "calendar_items": [asdict(item) for item in conversation.calendar_items],
            "complexity": conversation.complexity.value,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(data, stream, ensure_ascii=False)
        os.replace(temporary, path)
    except OSError:
        raise ConversationError("会话文件保存失败，本轮结果未保存。") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
