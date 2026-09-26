"""Structured calendar operations and source-backed replies, independent of storage."""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

MAX_CALENDAR_RESULTS = 10
EVENT_FIELDS = {
    "title",
    "starts_at",
    "timezone",
    "duration_minutes",
    "location",
    "reminder_minutes",
}


class CalendarError(RuntimeError):
    """A calendar operation did not complete; its safe message may be displayed."""


class CalendarBusyError(CalendarError):
    """Another reminder synchronization or delivery batch owns the ledger lock."""


def aware_time(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("Calendar times must be datetimes with UTC offsets.")
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Calendar times must include UTC offsets.")
    return result


def _text(value: object, limit: int, *, empty: bool = False) -> None:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value.strip())
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError(
            "Calendar text is empty, too long, or contains control characters."
        )


def validate_event(fields: dict) -> dict:
    """Normalize a complete event, rejecting DST gaps and contradictory offsets."""
    if not isinstance(fields, dict) or set(fields) != EVENT_FIELDS:
        raise ValueError("Incomplete event fields.")
    _text(fields["title"], 200)
    _text(fields["location"], 200, empty=True)
    _text(fields["timezone"], 64)
    zone = ZoneInfo(fields["timezone"])
    start = aware_time(fields["starts_at"])
    local = start.astimezone(zone)
    if start.replace(tzinfo=None) != local.replace(tzinfo=None) or (
        start.utcoffset() != local.utcoffset()
    ):
        raise ValueError(
            "The start time does not match its timezone or falls in a daylight-saving gap."
        )
    duration = fields["duration_minutes"]
    if type(duration) is not int or not 0 <= duration <= 10080:
        raise ValueError(
            "Duration must be between 0 and 10080 minutes; 0 denotes a standalone reminder."
        )
    reminder = fields["reminder_minutes"]
    if reminder is not None and (
        type(reminder) is not int or not 0 <= reminder <= 40320
    ):
        raise ValueError(
            "Reminder advance notice must be between 0 and 40320 minutes, or null."
        )
    # Validate arithmetic now, before an event could be committed.
    start.astimezone(UTC) + timedelta(minutes=duration)
    if reminder is not None:
        start.astimezone(UTC) - timedelta(minutes=reminder)
    return {**fields, "starts_at": local.isoformat()}


def validate_event_proposal(proposal: dict) -> dict:
    """Validate a model-computed full event; never infer a missing time value."""
    if not isinstance(proposal, dict) or set(proposal) != EVENT_FIELDS | {"ends_at"}:
        raise ValueError(
            "The model must provide a complete event, including start time, end time, and duration."
        )
    fields = validate_event(
        {key: value for key, value in proposal.items() if key != "ends_at"}
    )
    end = aware_time(proposal["ends_at"])
    local_end = end.astimezone(ZoneInfo(fields["timezone"]))
    if (
        end.replace(tzinfo=None) != local_end.replace(tzinfo=None)
        or end.utcoffset() != local_end.utcoffset()
    ):
        raise ValueError("The end time does not match its timezone.")
    start = aware_time(fields["starts_at"])
    if end.astimezone(UTC) - start.astimezone(UTC) != timedelta(
        minutes=fields["duration_minutes"]
    ):
        raise ValueError(
            "The proposed start time, end time, and duration are inconsistent. No write was performed."
        )
    return fields


@dataclass(frozen=True)
class CalendarQuery:
    starts_after: datetime
    starts_before: datetime
    text: str | None = None
    limit: int = MAX_CALENDAR_RESULTS

    def __post_init__(self):
        for value in (self.starts_after, self.starts_before):
            if not isinstance(value, datetime) or value.utcoffset() is None:
                raise ValueError("Query boundaries must include timezones.")
        span = self.starts_before.astimezone(UTC) - self.starts_after.astimezone(UTC)
        if not timedelta(0) < span <= timedelta(days=366):
            raise ValueError(
                "The query interval must be positive and at most 366 days."
            )
        if self.text is not None:
            _text(self.text, 200)
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_CALENDAR_RESULTS:
            raise ValueError("The query limit must be between 1 and 10.")

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {
            "starts_after",
            "starts_before",
            "text",
            "limit",
        }:
            raise ValueError("Invalid calendar query fields.")
        return cls(
            aware_time(data["starts_after"]),
            aware_time(data["starts_before"]),
            data["text"],
            data["limit"],
        )

    def to_dict(self):
        return {
            **asdict(self),
            "starts_after": self.starts_after.isoformat(),
            "starts_before": self.starts_before.isoformat(),
        }


@dataclass(frozen=True)
class CalendarRequest:
    operation: str
    query: CalendarQuery | None = None
    event_id: str | None = None
    version: str | None = None
    changes: dict | None = None

    def __post_init__(self):
        if self.operation not in {"query", "create", "update", "cancel"}:
            raise ValueError("Unsupported calendar operation.")
        if self.operation == "query":
            if not isinstance(self.query, CalendarQuery) or any(
                v is not None for v in (self.event_id, self.version, self.changes)
            ):
                raise ValueError("A query operation accepts only query arguments.")
            return
        if self.query is not None:
            raise ValueError("A write operation cannot also contain a query.")
        if self.operation == "create":
            if self.event_id is not None or self.version is not None:
                raise ValueError(
                    "Creating an event cannot specify an existing event ID."
                )
            object.__setattr__(
                self,
                "changes",
                validate_event_proposal(self.changes)
                if isinstance(self.changes, dict) and "ends_at" in self.changes
                else validate_event(self.changes),
            )
            return
        _text(self.event_id, 1152)
        _text(self.version, 128)
        if self.operation == "cancel":
            if self.changes is not None:
                raise ValueError("Cancelling an event cannot also modify fields.")
        elif (
            not isinstance(self.changes, dict)
            or not self.changes
            or set(self.changes) - (EVENT_FIELDS | {"ends_at"})
        ):
            raise ValueError("Updates require nonempty event fields.")
        if self.operation == "update" and "ends_at" in self.changes:
            object.__setattr__(self, "changes", validate_event_proposal(self.changes))

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {
            "operation",
            "query",
            "event_id",
            "version",
            "changes",
        }:
            raise ValueError("Invalid calendar operation fields.")
        return cls(
            data["operation"],
            CalendarQuery.from_dict(data["query"])
            if data["query"] is not None
            else None,
            data["event_id"],
            data["version"],
            data["changes"],
        )

    def to_dict(self):
        return {
            **asdict(self),
            "query": self.query.to_dict() if self.query else None,
        }


@dataclass(frozen=True)
class CalendarItem:
    event_id: str
    version: str
    title: str
    starts_at: str
    timezone: str
    duration_minutes: int
    location: str
    reminder_minutes: int | None
    status: str = "confirmed"

    def __post_init__(self):
        _text(self.event_id, 1152)
        _text(self.version, 128)
        if self.status not in {"confirmed", "cancelled"}:
            raise ValueError("Invalid event status.")
        validate_event(self.fields())

    def fields(self):
        return {
            key: value for key, value in asdict(self).items() if key in EVENT_FIELDS
        }

    def model_data(self) -> dict:
        start = aware_time(self.starts_at)
        end = (
            start.astimezone(UTC) + timedelta(minutes=self.duration_minutes)
        ).astimezone(ZoneInfo(self.timezone))
        return {**asdict(self), "ends_at": end.isoformat()}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != EVENT_FIELDS | {
            "event_id",
            "version",
            "status",
        }:
            raise ValueError("Invalid event record.")
        return cls(**data)


@dataclass(frozen=True)
class CalendarResult:
    operation: str
    items: list[CalendarItem]
    query: CalendarQuery | None = None
    has_more: bool = False
    warnings: list[str] = field(default_factory=list)
    source_label: str | None = None

    def __post_init__(self):
        if self.operation not in {"query", "create", "update", "cancel"}:
            raise ValueError("Invalid calendar result.")
        if (
            not isinstance(self.items, list)
            or len(self.items) > MAX_CALENDAR_RESULTS
            or any(not isinstance(item, CalendarItem) for item in self.items)
            or len({item.event_id for item in self.items}) != len(self.items)
            or type(self.has_more) is not bool
        ):
            raise ValueError("Invalid calendar record.")
        if self.operation == "query":
            if (
                not isinstance(self.query, CalendarQuery)
                or len(self.items) > self.query.limit
            ):
                raise ValueError(
                    "Calendar results lack query conditions or exceed the limit."
                )
        elif self.query is not None or self.has_more or len(self.items) != 1:
            raise ValueError("A calendar write must return exactly one actual result.")

        if not isinstance(self.warnings, list) or len(self.warnings) > 3:
            raise ValueError("Invalid calendar warning.")
        for warning in self.warnings:
            _text(warning, 300)

        if self.source_label is not None:
            _text(self.source_label, 300)

        expected_status = "cancelled" if self.operation == "cancel" else "confirmed"
        if any(item.status != expected_status for item in self.items):
            raise ValueError(
                "The calendar operation status does not match the returned record."
            )

    def to_dict(self):
        return {
            "operation": self.operation,
            "items": [asdict(item) for item in self.items],
            "query": self.query.to_dict() if self.query else None,
            "has_more": self.has_more,
            "warnings": list(self.warnings),
            "source_label": self.source_label,
        }

    @classmethod
    def from_dict(cls, data):
        if (
            not isinstance(data, dict)
            or not {"operation", "items", "query", "has_more"} <= set(data)
            or set(data)
            - {"operation", "items", "query", "has_more", "warnings", "source_label"}
            or not isinstance(data["items"], list)
        ):
            raise ValueError("Invalid calendar snapshot.")
        return cls(
            data["operation"],
            [CalendarItem.from_dict(item) for item in data["items"]],
            CalendarQuery.from_dict(data["query"])
            if data["query"] is not None
            else None,
            data["has_more"],
            data.get("warnings", []),
            data.get("source_label"),
        )


def render_calendar_item(
    item: CalendarItem, *, include_identifiers: bool = True
) -> str:
    reminder = (
        "No reminder"
        if item.reminder_minutes is None
        else "Remind at the start"
        if item.reminder_minutes == 0
        else f"Remind {item.reminder_minutes} minutes before"
    )
    if item.status == "cancelled":
        reminder = "Cancelled; no further reminders"
    duration = (
        f"{item.duration_minutes} minutes"
        if item.duration_minutes
        else "Standalone reminder"
    )
    identifiers = (
        f"\nID: {item.event_id}; version: {item.version}" if include_identifiers else ""
    )
    return (
        f"{item.title}\nTime: {item.starts_at} ({item.timezone})\n"
        f"Duration: {duration}; location: {item.location or 'Not set'}; Telegram: {reminder}"
        f"{identifiers}"
    )


def render_calendar_result(
    result: CalendarResult, *, include_identifiers: bool = True
) -> str:
    label = {
        "query": "Calendar query",
        "create": "Event created",
        "update": "Event updated",
        "cancel": "Event cancelled",
    }
    lines = [label[result.operation]]
    if result.source_label:
        lines.append(f"Calendar: {result.source_label}")
        if result.query:
            lines.append("Only the calendar above was queried.")
    if result.query:
        lines.append(
            f"Event start range: {result.query.starts_after.isoformat()} (inclusive) to "
            f"{result.query.starts_before.isoformat()} (exclusive); limit {result.query.limit}."
        )
        if result.query.text:
            lines.append(f"Title contains: {result.query.text}")
    lines.extend(
        f"[{i}] {render_calendar_item(item, include_identifiers=include_identifiers)}"
        for i, item in enumerate(result.items, 1)
    )
    if not result.items:
        lines.append(
            "No supported events were returned."
            if result.warnings
            else "No matching events."
        )
    if result.has_more:
        lines.append("More events are available. Narrow the range.")
    lines.extend(result.warnings)
    return "\n".join(lines)
