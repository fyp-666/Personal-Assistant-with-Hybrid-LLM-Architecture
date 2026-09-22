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
    """Another local calendar operation currently owns the dispatch/write lock."""


def aware_time(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("日历时间须为带 UTC 偏移的日期时间。")
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("日历时间须包含 UTC 偏移。")
    return result


def _text(value: object, limit: int, *, empty: bool = False) -> None:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value.strip())
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("日历文本为空、过长或包含控制字符。")


def validate_event(fields: dict) -> dict:
    """Normalize a complete event, rejecting DST gaps and contradictory offsets."""
    if not isinstance(fields, dict) or set(fields) != EVENT_FIELDS:
        raise ValueError("日程字段不完整。")
    _text(fields["title"], 200)
    _text(fields["location"], 200, empty=True)
    _text(fields["timezone"], 64)
    zone = ZoneInfo(fields["timezone"])
    start = aware_time(fields["starts_at"])
    local = start.astimezone(zone)
    if start.replace(tzinfo=None) != local.replace(tzinfo=None) or (
        start.utcoffset() != local.utcoffset()
    ):
        raise ValueError("开始时间与时区不一致，或处于夏令时不存在的时间。")
    duration = fields["duration_minutes"]
    if type(duration) is not int or not 0 <= duration <= 10080:
        raise ValueError("时长须为 0 到 10080 分钟；0 表示单次提醒事项。")
    reminder = fields["reminder_minutes"]
    if reminder is not None and (
        type(reminder) is not int or not 0 <= reminder <= 40320
    ):
        raise ValueError("提前提醒须为 0 到 40320 分钟，或 null。")
    # Validate arithmetic now, before an event could be committed.
    start.astimezone(UTC) + timedelta(minutes=duration)
    if reminder is not None:
        start.astimezone(UTC) - timedelta(minutes=reminder)
    return {**fields, "starts_at": local.isoformat()}


def validate_event_proposal(proposal: dict) -> dict:
    """Validate a model-computed full event; never infer a missing time value."""
    if not isinstance(proposal, dict) or set(proposal) != EVENT_FIELDS | {"ends_at"}:
        raise ValueError("模型须提供完整日程，包括开始、结束时间和时长。")
    fields = validate_event(
        {key: value for key, value in proposal.items() if key != "ends_at"}
    )
    end = aware_time(proposal["ends_at"])
    local_end = end.astimezone(ZoneInfo(fields["timezone"]))
    if (
        end.replace(tzinfo=None) != local_end.replace(tzinfo=None)
        or end.utcoffset() != local_end.utcoffset()
    ):
        raise ValueError("结束时间与时区不一致。")
    start = aware_time(fields["starts_at"])
    if end.astimezone(UTC) - start.astimezone(UTC) != timedelta(
        minutes=fields["duration_minutes"]
    ):
        raise ValueError("模型给出的开始、结束时间与时长不一致；本次未写入。")
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
                raise ValueError("查询边界须包含时区。")
        span = self.starts_before.astimezone(UTC) - self.starts_after.astimezone(UTC)
        if not timedelta(0) < span <= timedelta(days=366):
            raise ValueError("查询区间须大于零且不超过 366 天。")
        if self.text is not None:
            _text(self.text, 200)
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_CALENDAR_RESULTS:
            raise ValueError("每次查询上限为 1 到 10 条。")

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {
            "starts_after",
            "starts_before",
            "text",
            "limit",
        }:
            raise ValueError("无效的日历查询字段。")
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
            raise ValueError("不支持的日历操作。")
        if self.operation == "query":
            if not isinstance(self.query, CalendarQuery) or any(
                v is not None for v in (self.event_id, self.version, self.changes)
            ):
                raise ValueError("查询只接受 query。")
            return
        if self.query is not None:
            raise ValueError("写入操作不能同时包含查询。")
        if self.operation == "create":
            if self.event_id is not None or self.version is not None:
                raise ValueError("新建日程不能指定已有日程编号。")
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
                raise ValueError("取消日程不能同时修改字段。")
        elif (
            not isinstance(self.changes, dict)
            or not self.changes
            or set(self.changes) - (EVENT_FIELDS | {"ends_at"})
        ):
            raise ValueError("修改只接受非空日程字段。")
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
            raise ValueError("无效的日历操作字段。")
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
            raise ValueError("无效的日程状态。")
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
            raise ValueError("无效的日程记录。")
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
            raise ValueError("无效的日历结果。")
        if (
            not isinstance(self.items, list)
            or len(self.items) > MAX_CALENDAR_RESULTS
            or any(not isinstance(item, CalendarItem) for item in self.items)
            or len({item.event_id for item in self.items}) != len(self.items)
            or type(self.has_more) is not bool
        ):
            raise ValueError("无效的日历记录。")
        if self.operation == "query":
            if (
                not isinstance(self.query, CalendarQuery)
                or len(self.items) > self.query.limit
            ):
                raise ValueError("日历结果缺少查询条件或超出上限。")
        elif self.query is not None or self.has_more or len(self.items) != 1:
            raise ValueError("日历操作必须返回一条实际结果。")

        if not isinstance(self.warnings, list) or len(self.warnings) > 3:
            raise ValueError("无效的日历提示。")
        for warning in self.warnings:
            _text(warning, 300)

        if self.source_label is not None:
            _text(self.source_label, 300)

        expected_status = "cancelled" if self.operation == "cancel" else "confirmed"
        if any(item.status != expected_status for item in self.items):
            raise ValueError("日历操作状态与返回记录不一致。")

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
            raise ValueError("无效的日历快照。")
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


def render_calendar_item(item: CalendarItem) -> str:
    reminder = (
        "不提醒"
        if item.reminder_minutes is None
        else "到时提醒"
        if item.reminder_minutes == 0
        else f"提前 {item.reminder_minutes} 分钟提醒"
    )
    duration = f"{item.duration_minutes} 分钟" if item.duration_minutes else "提醒事项"
    return (
        f"{item.title}\n时间：{item.starts_at}（{item.timezone}）\n"
        f"时长：{duration}；地点：{item.location or '未设置'}；Telegram：{reminder}\n"
        f"编号：{item.event_id}；版本：{item.version}"
    )


def render_calendar_result(result: CalendarResult) -> str:
    label = {
        "query": "日程查询",
        "create": "已创建日程",
        "update": "已修改日程",
        "cancel": "已取消日程",
    }
    lines = [label[result.operation]]
    if result.source_label:
        lines.append(f"日历：{result.source_label}")
        if result.query:
            lines.append("本次仅查询上述日历。")
    if result.query:
        lines.append(
            f"开始时间范围：{result.query.starts_after.isoformat()}（含）至 "
            f"{result.query.starts_before.isoformat()}（不含）；上限 {result.query.limit} 条。"
        )
        if result.query.text:
            lines.append(f"标题包含：{result.query.text}")
    lines.extend(
        f"[{i}] {render_calendar_item(item)}" for i, item in enumerate(result.items, 1)
    )
    if not result.items:
        lines.append(
            "本次没有返回可处理的日程。" if result.warnings else "没有符合条件的日程。"
        )
    if result.has_more:
        lines.append("还有日程未展示，请缩小范围。")
    lines.extend(result.warnings)
    return "\n".join(lines)
