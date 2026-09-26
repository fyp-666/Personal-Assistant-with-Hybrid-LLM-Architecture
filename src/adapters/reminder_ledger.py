"""Persist Google reminder snapshots and delivery attempts, without calendar CRUD."""

import fcntl
import json
import os
import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from features.calendar_actions import (
    CalendarBusyError,
    CalendarError,
    CalendarItem,
    aware_time,
)


class ReminderLedger:
    """Lazy delivery ledger; the caller supplies a per-Google-calendar path.

    Only the current version 2 ledger schema is supported.
    Event payloads are synchronized snapshots, never editable calendar records.
    """

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self.path.with_suffix(".lock").open("a") as lock:
                os.chmod(lock.name, 0o600)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise CalendarBusyError(
                        "提醒账本正在处理其他操作，请稍后重试。"
                    ) from None
                if not self.path.exists():
                    fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.close(fd)
                conn = sqlite3.connect(self.path, timeout=5)
                conn.row_factory = sqlite3.Row
                try:
                    version = conn.execute("PRAGMA user_version").fetchone()[0]
                    if version == 0:
                        if conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchone():
                            raise CalendarError("提醒账本格式不受支持。")
                        conn.executescript("""
                            CREATE TABLE events (
                                id TEXT PRIMARY KEY, version TEXT NOT NULL,
                                start REAL NOT NULL, payload TEXT NOT NULL
                            );
                            CREATE INDEX events_start ON events(start);
                            CREATE TABLE reminders (
                                event_id TEXT NOT NULL, version TEXT NOT NULL,
                                due REAL NOT NULL, status TEXT NOT NULL,
                                PRIMARY KEY(event_id, version)
                            );
                            CREATE INDEX reminders_due ON reminders(status, due);
                            PRAGMA user_version=2;
                        """)
                        conn.commit()
                    elif version != 2:
                        raise CalendarError("提醒账本版本不受支持。")
                    yield conn
                finally:
                    conn.close()
        except (OSError, sqlite3.Error):
            raise CalendarError("提醒账本无法读写，请检查数据库及目录权限。") from None

    @staticmethod
    def _item(row) -> CalendarItem:
        try:
            item = CalendarItem.from_dict(json.loads(row["payload"]))
            if item.event_id != row["id"] or item.version != str(row["version"]):
                raise ValueError("Mismatched record")
            if aware_time(item.starts_at).timestamp() != row["start"]:
                raise ValueError("Mismatched time")
            return item
        except (TypeError, ValueError, KeyError, OverflowError):
            raise CalendarError("提醒账本记录损坏，本次操作未执行。") from None

    def reconcile_external(
        self,
        items: list[CalendarItem],
        *,
        starts_after: datetime,
        starts_before: datetime,
    ) -> None:
        """Replace a COMPLETE source window, preserving delivery state across ETag changes.

        Use a separate database per external calendar. This cache must never become
        a second source for CRUD operations or an offline fallback.
        """
        from features.calendar_actions import CalendarQuery

        CalendarQuery(starts_after, starts_before)
        items = [CalendarItem.from_dict(item.__dict__) for item in items]
        if len({item.event_id for item in items}) != len(items) or any(
            item.status != "confirmed"
            or not starts_after <= aware_time(item.starts_at) < starts_before
            for item in items
        ):
            raise CalendarError("日历同步快照无效，本次未采用。")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            seen = {item.event_id for item in items}
            rows = conn.execute(
                "SELECT * FROM events WHERE start >= ? AND start < ?",
                (starts_after.timestamp(), starts_before.timestamp()),
            ).fetchall()
            for row in rows:
                if row["id"] not in seen:
                    conn.execute(
                        "UPDATE reminders SET status='cancelled' WHERE event_id=? AND status='pending'",
                        (row["id"],),
                    )
                    conn.execute("DELETE FROM events WHERE id=?", (row["id"],))
            for item in items:
                row = conn.execute(
                    "SELECT * FROM events WHERE id=?", (item.event_id,)
                ).fetchone()
                old = self._item(row) if row else None
                if old == item:
                    continue
                prior = (
                    conn.execute(
                        "SELECT status FROM reminders WHERE event_id=? AND version=?",
                        (old.event_id, old.version),
                    ).fetchone()
                    if old
                    else None
                )
                same_schedule = old is not None and (
                    aware_time(old.starts_at) == aware_time(item.starts_at)
                    and old.reminder_minutes == item.reminder_minutes
                )
                state = prior["status"] if same_schedule and prior else "pending"
                if state == "sending":
                    state = "unknown"
                conn.execute(
                    "UPDATE reminders SET status='cancelled' WHERE event_id=? AND status='pending'",
                    (item.event_id,),
                )
                start = aware_time(item.starts_at)
                conn.execute(
                    "INSERT OR REPLACE INTO events VALUES (?, ?, ?, ?)",
                    (
                        item.event_id,
                        item.version,
                        start.timestamp(),
                        json.dumps(item.__dict__, ensure_ascii=False),
                    ),
                )
                if item.reminder_minutes is not None:
                    due = start.astimezone(UTC) - timedelta(
                        minutes=item.reminder_minutes
                    )
                    conn.execute(
                        "INSERT INTO reminders VALUES (?, ?, ?, ?) ON CONFLICT(event_id,version) DO NOTHING",
                        (item.event_id, item.version, due.timestamp(), state),
                    )
            conn.commit()

    def send_due(
        self,
        send: Callable[[CalendarItem], None],
        *,
        now: datetime | None = None,
        grace: timedelta = timedelta(minutes=15),
        verify: Callable[[CalendarItem], bool] | None = None,
    ) -> dict[str, int]:
        """Claim before sending. Uncertain sends/crashes are never automatically replayed.

        The same lock protects snapshot reconciliation and dispatch. Google events
        are rechecked by the caller-provided verifier before each delivery claim.
        """
        from adapters.messaging import DeliveryError, MessageContentError

        current = now if now is not None else datetime.now(UTC)
        if current.utcoffset() is None or not timedelta(0) <= grace <= timedelta(
            days=1
        ):
            raise ValueError("提醒检查时间或补发窗口无效。")
        counts = {"sent": 0, "failed": 0, "unknown": 0, "expired": 0}
        with self._connection() as conn:
            # Interrupted sends require manual inspection, never an automatic retry.
            conn.execute("UPDATE reminders SET status='unknown' WHERE status='sending'")
            counts["expired"] = conn.execute(
                "UPDATE reminders SET status='expired' WHERE status='pending' AND due < ?",
                ((current - grace).timestamp(),),
            ).rowcount
            conn.commit()
            rows = conn.execute(
                "SELECT r.event_id, r.version FROM reminders r "
                "WHERE r.status='pending' AND r.due <= ? ORDER BY r.due, r.event_id LIMIT 10",
                (current.timestamp(),),
            ).fetchall()
            for row in rows:
                event = conn.execute(
                    "SELECT * FROM events WHERE id=?", (row["event_id"],)
                ).fetchone()
                item = self._item(event) if event is not None else None
                key = (row["event_id"], row["version"])
                if (
                    item is None
                    or item.status != "confirmed"
                    or item.version != str(row["version"])
                ):
                    conn.execute(
                        "UPDATE reminders SET status='cancelled' WHERE event_id=? AND version=?",
                        key,
                    )
                    conn.commit()
                    continue
                # A changed source needs the next reconciliation; don't cancel a valid
                # reminder just because a title/ETag changed after the list request.
                if verify is not None and not verify(item):
                    continue
                conn.execute(
                    "UPDATE reminders SET status='sending' WHERE event_id=? AND version=?",
                    key,
                )
                conn.commit()
                try:
                    send(item)
                except MessageContentError:
                    outcome = "failed"
                except DeliveryError:
                    outcome = "unknown"
                except BaseException:
                    conn.execute(
                        "UPDATE reminders SET status='unknown' WHERE event_id=? AND version=?",
                        key,
                    )
                    conn.commit()
                    raise
                else:
                    outcome = "sent"
                conn.execute(
                    "UPDATE reminders SET status=? WHERE event_id=? AND version=?",
                    (outcome, *key),
                )
                conn.commit()
                counts[outcome] += 1
        return counts

    def preview_due(
        self, *, now: datetime | None = None, grace: timedelta = timedelta(minutes=15)
    ) -> list[CalendarItem]:
        """Preview dispatchable reminders without claiming, expiring or sending."""
        current = now if now is not None else datetime.now(UTC)
        if current.utcoffset() is None or not timedelta(0) <= grace <= timedelta(
            days=1
        ):
            raise ValueError("提醒检查时间或补发窗口无效。")
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT e.* FROM reminders r JOIN events e ON e.id=r.event_id AND e.version=r.version "
                "WHERE r.status='pending' AND r.due >= ? AND r.due <= ? ORDER BY r.due, e.id LIMIT 10",
                ((current - grace).timestamp(), current.timestamp()),
            ).fetchall()
            return [
                item for row in rows if (item := self._item(row)).status == "confirmed"
            ]

    def reminder_status(self) -> dict[str, int]:
        with self._connection() as conn:
            return {
                row["status"]: row["count"]
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM reminders GROUP BY status"
                )
            }
