"""Google is the event source; SQLite only keeps a reconciled reminder delivery ledger."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from adapters.google_calendar_auth import build_service, calendar_home, load_config
from adapters.reminder_ledger import ReminderLedger
from features.calendar_actions import (
    CalendarError,
    CalendarItem,
    CalendarQuery,
    CalendarRequest,
    CalendarResult,
    aware_time,
    validate_event,
)


class GoogleNotFound(CalendarError):
    """A resource was removed remotely."""


class UnsupportedEvent(ValueError):
    """A source event cannot be represented by this bounded, single-event interface."""


def api_call(resource, method: str, *, etag: str | None = None, **kwargs):
    """One API attempt; safe errors never expose Google's response body."""
    import httplib2
    from google.auth.exceptions import GoogleAuthError
    from googleapiclient.errors import HttpError

    try:
        request = getattr(resource, method)(**kwargs)
        if etag is not None:
            request.headers["If-Match"] = etag
        return request.execute(num_retries=0)
    except HttpError as error:
        code = error.resp.status
        if code == 412:
            message = (
                "The event changed in Google. Query it again before making changes."
            )
        elif code in {404, 410}:
            raise GoogleNotFound(
                "The Google calendar or event no longer exists. Query again or check the binding."
            ) from None
        elif code in {401, 403}:
            message = "Google Calendar authorization, permissions, or API quota are unavailable. Check the configuration."
        elif code == 409:
            message = "This ID already exists in Google. Query first to verify the actual result."
        elif method in {"insert", "patch", "delete"} and code >= 500:
            message = "The Google write outcome is uncertain. Check the calendar before creating anything again."
        else:
            message = "The Google Calendar request did not complete. Check the arguments or try again later."
        raise CalendarError(message) from None
    except (OSError, httplib2.HttpLib2Error, GoogleAuthError):
        message = (
            "The Google write outcome is uncertain. Check the calendar before creating anything again."
            if method in {"insert", "patch", "delete"}
            else "Google Calendar is temporarily unavailable. Cached data will not be used for operations or reminders."
        )
        raise CalendarError(message) from None


class GoogleCalendar:
    def __init__(
        self, *, home: Path | None = None, service=None, config: dict | None = None
    ):
        self.home = home if home is not None else calendar_home()
        self._service = service
        self._config = config
        self.skipped_items = 0

    @property
    def config(self):
        if self._config is None:
            self._config = load_config(self.home)
        return self._config

    @property
    def prefix(self):
        # Source-bound IDs stop an old conversation targeting another calendar/backend.
        digest = hashlib.sha256(self.config["calendar_id"].encode()).hexdigest()[:16]
        return f"gcal:{digest}:"

    @property
    def ledger(self):
        return ReminderLedger(
            self.home / f"reminders-{self.prefix.split(':')[1]}.sqlite3"
        )

    def _events(self):
        # Reload persisted credentials for each operation/batch in a long-running watcher.
        return (
            self._service.events()
            if self._service is not None
            else build_service(self.home).events()
        )

    def _id(self, event_id: str) -> str:
        if not event_id.startswith(self.prefix):
            raise CalendarError(
                "This event belongs to another calendar or a former local calendar. Query it again first."
            )
        raw = event_id[len(self.prefix) :]
        if not raw or len(raw) > 1024:
            raise CalendarError("Invalid Google event ID. Query again.")
        return raw

    def _item(self, event: dict) -> CalendarItem:
        try:
            if not isinstance(event, dict):
                raise TypeError
            if (
                event.get("recurrence")
                or event.get("recurringEventId")
                or event.get("eventType", "default") != "default"
                or event.get("status", "confirmed") != "confirmed"
                or "dateTime" not in event["start"]
                or "dateTime" not in event["end"]
            ):
                raise ValueError
            zone = event["start"].get("timeZone", self.config["timezone"])
            start = aware_time(event["start"]["dateTime"]).astimezone(ZoneInfo(zone))
            end = aware_time(event["end"]["dateTime"])
            seconds = (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds()
            if seconds <= 0 or seconds % 60:
                raise ValueError
            duration = int(seconds / 60)
            private = event.get("extendedProperties", {}).get("private", {})
            if private.get("hw3PointReminder") == "1" and duration == 1:
                duration = 0
            reminders = event.get("reminders", {})
            overrides = (
                reminders.get("overrides", [])
                if not reminders.get("useDefault", False)
                else []
            )
            if len(overrides) > 1 or any(r.get("method") != "popup" for r in overrides):
                raise ValueError
            etag = event["etag"]
            if (
                not isinstance(etag, str)
                or len(etag) < 3
                or not (etag.startswith('"') and etag.endswith('"'))
            ):
                raise ValueError
            # HTTP quotes belong to the transport, not the model's version token.
            return CalendarItem(
                self.prefix + event["id"],
                etag[1:-1],
                event.get("summary") or "(Untitled)",
                start.isoformat(),
                zone,
                duration,
                event.get("location", ""),
                overrides[0]["minutes"] if overrides else None,
            )
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
            raise UnsupportedEvent from None

    def _list(self, events, query: CalendarQuery):
        params = {
            "calendarId": self.config["calendar_id"],
            "timeMin": query.starts_after.isoformat(),
            "timeMax": query.starts_before.isoformat(),
            "singleEvents": True,
            "showDeleted": False,
            "orderBy": "startTime",
            "maxResults": 250,
            "timeZone": self.config["timezone"],
        }
        items, skipped, tokens = [], 0, set()
        for _ in range(20):
            page = api_call(events, "list", **params)
            if not isinstance(page, dict) or not isinstance(
                page.get("items", []), list
            ):
                raise CalendarError("Google Calendar returned an invalid list.")
            for raw in page.get("items", []):
                try:
                    item = self._item(raw)
                except UnsupportedEvent:
                    skipped += 1
                    continue
                start = aware_time(item.starts_at)
                # Google's timeMin filters END time; preserve our start-time contract.
                if (
                    query.starts_after.timestamp()
                    <= start.timestamp()
                    < query.starts_before.timestamp()
                    and (
                        query.text is None
                        or query.text.casefold() in item.title.casefold()
                    )
                ):
                    items.append(item)
            token = page.get("nextPageToken")
            if not token:
                return sorted(
                    items,
                    key=lambda i: (aware_time(i.starts_at).timestamp(), i.event_id),
                ), skipped
            if not isinstance(token, str) or token in tokens:
                raise CalendarError(
                    "Invalid Google Calendar pagination. These results were not used."
                )
            tokens.add(token)
            params["pageToken"] = token
        raise CalendarError(
            "Too many events in this range. Narrow the range; incomplete results were not used."
        )

    def _get(self, events, event_id: str):
        return api_call(
            events,
            "get",
            calendarId=self.config["calendar_id"],
            eventId=self._id(event_id),
        )

    @staticmethod
    def _body(fields: dict, previous: dict | None = None) -> dict:
        start = aware_time(fields["starts_at"])
        # Google events require an end. Point reminders occupy one free minute on Google.
        end = start.astimezone(UTC) + timedelta(
            minutes=max(1, fields["duration_minutes"])
        )
        private = dict(
            (previous or {}).get("extendedProperties", {}).get("private", {})
        )
        private["hw3PointReminder"] = "1" if fields["duration_minutes"] == 0 else "0"
        reminder = fields["reminder_minutes"]
        return {
            "summary": fields["title"],
            "location": fields["location"],
            "start": {"dateTime": start.isoformat(), "timeZone": fields["timezone"]},
            "end": {
                "dateTime": end.astimezone(ZoneInfo(fields["timezone"])).isoformat(),
                "timeZone": fields["timezone"],
            },
            "extendedProperties": {"private": private},
            "reminders": {
                "useDefault": False,
                "overrides": []
                if reminder is None
                else [{"method": "popup", "minutes": reminder}],
            },
        }

    def execute(
        self, request: CalendarRequest, *, now: datetime | None = None
    ) -> CalendarResult:
        try:
            request = CalendarRequest.from_dict(request.to_dict())
        except (TypeError, ValueError, KeyError, OverflowError):
            raise CalendarError(
                "Invalid calendar arguments. No write was performed."
            ) from None
        current = now if now is not None else datetime.now(UTC)
        if current.utcoffset() is None:
            raise CalendarError("The current time must include a timezone.")
        if request.event_id is not None:
            self._id(
                request.event_id
            )  # Reject stale source IDs before any network call.
        events = self._events()
        if request.operation == "query":
            items, skipped = self._list(events, request.query)
            warnings = (
                [
                    f"{skipped} Google records are unsupported by this version (such as all-day, recurring, or multiple-reminder events). View them in Google Calendar."
                ]
                if skipped
                else []
            )
            return CalendarResult(
                "query",
                items[: request.query.limit],
                request.query,
                len(items) > request.query.limit,
                warnings,
                source_label="Google Calendar / " + self.config["summary"],
            )
        previous, old = None, None
        if request.operation != "create":
            previous = self._get(events, request.event_id)
            try:
                old = self._item(previous)
            except UnsupportedEvent:
                raise CalendarError(
                    "This Google event is cancelled or unsupported. It was not modified."
                ) from None
            if old.version != request.version:
                raise CalendarError(
                    "The event changed in Google. Query it again before making changes."
                )
            if (
                previous.get("attendees")
                or previous.get("attendeesOmitted")
                or previous.get("locked")
            ):
                raise CalendarError(
                    "This version cannot modify events with attendees or locked events. Use Google Calendar."
                )
        if request.operation == "cancel":
            api_call(
                events,
                "delete",
                calendarId=self.config["calendar_id"],
                eventId=self._id(old.event_id),
                etag=previous["etag"],
            )
            return CalendarResult(
                "cancel",
                [replace(old, status="cancelled")],
                source_label="Google Calendar / " + self.config["summary"],
            )
        try:
            fields = validate_event(
                {**(old.fields() if old else {}), **request.changes}
            )
        except (TypeError, ValueError, KeyError, OverflowError):
            raise CalendarError(
                "Invalid event fields or time. No write was performed."
            ) from None
        start = aware_time(fields["starts_at"])
        if start.timestamp() <= current.timestamp():
            raise CalendarError(
                "Created or updated events must start in the future. Specify the date and time."
            )
        reminder = fields["reminder_minutes"]
        same_schedule = (
            old is not None
            and start == aware_time(old.starts_at)
            and reminder == old.reminder_minutes
        )
        if (
            reminder is not None
            and start.astimezone(UTC) - timedelta(minutes=reminder) < current
            and not same_schedule
        ):
            raise CalendarError(
                "The reminder time is in the past. Reduce the advance notice or adjust the event time."
            )
        try:
            body = self._body(fields, previous)
        except (ValueError, OverflowError):
            raise CalendarError(
                "The event end time exceeds the supported range. No write was performed."
            ) from None
        if request.operation == "create":
            body.update(
                id=uuid4().hex,
                visibility="private",
                transparency="transparent"
                if fields["duration_minutes"] == 0
                else "opaque",
            )
            saved = api_call(
                events, "insert", calendarId=self.config["calendar_id"], body=body
            )
        else:
            # PATCH preserves description, colour, attachments and other unrelated fields.
            changed_fields = {
                key for key, value in fields.items() if value != old.fields()[key]
            }
            keys = set()
            for field, google_key in (
                ("title", "summary"),
                ("location", "location"),
                ("reminder_minutes", "reminders"),
            ):
                if field in changed_fields:
                    keys.add(google_key)
            if changed_fields & {"starts_at", "timezone", "duration_minutes"}:
                keys.update({"start", "end"})
            if "duration_minutes" in changed_fields:
                keys.add("extendedProperties")
            body = {key: value for key, value in body.items() if key in keys}
            if "duration_minutes" in changed_fields:
                body["transparency"] = (
                    "transparent" if fields["duration_minutes"] == 0 else "opaque"
                )
            saved = api_call(
                events,
                "patch",
                calendarId=self.config["calendar_id"],
                eventId=self._id(old.event_id),
                etag=previous["etag"],
                body=body,
            )
        try:
            item = self._item(saved)
        except UnsupportedEvent:
            raise CalendarError(
                "Google responded to the write, but its response could not be parsed. Query to verify before creating anything again."
            ) from None
        return CalendarResult(
            request.operation,
            [item],
            source_label="Google Calendar / " + self.config["summary"],
        )

    def _synchronize(self, *, now: datetime, grace: timedelta):
        # The maximum reminder lead is 28 days, so every currently due event is in this window.
        query = CalendarQuery(now - grace, now + timedelta(days=28, seconds=1))
        events = self._events()
        items, skipped = self._list(events, query)
        self.skipped_items = skipped
        self.ledger.reconcile_external(
            items, starts_after=query.starts_after, starts_before=query.starts_before
        )
        return events

    def preview_due(
        self, *, now: datetime | None = None, grace: timedelta = timedelta(minutes=15)
    ):
        current = now if now is not None else datetime.now(UTC)
        self._synchronize(now=current, grace=grace)
        return self.ledger.preview_due(now=current, grace=grace)

    def send_due(
        self,
        send,
        *,
        now: datetime | None = None,
        grace: timedelta = timedelta(minutes=15),
    ):
        current = now if now is not None else datetime.now(UTC)
        events = self._synchronize(now=current, grace=grace)

        def verify(item):
            try:
                raw = self._get(events, item.event_id)
            except GoogleNotFound:
                return False
            if raw.get("status") == "cancelled":
                return False
            try:
                fresh = self._item(raw)
            except UnsupportedEvent:
                return False
            return fresh == item

        return self.ledger.send_due(send, now=current, grace=grace, verify=verify)

    def reminder_status(self):
        return self.ledger.reminder_status()
