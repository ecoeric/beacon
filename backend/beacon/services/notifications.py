"""In-app activity feed.

External push (APNs) is deliberately out of scope for the first implementation; this module is
the extension point: every event carries a stable ``kind`` and JSON ``payload`` so a future
push bridge can subscribe without reshaping the API. Deduplication is by ``dedupe_key`` so a
flapping service cannot flood the feed, and state transitions are computed against the
``service_state`` table (edge detection, not level polling).
"""

from __future__ import annotations

import json
import time

from ..db import Database, new_id, now
from ..schemas import ActivityFeed, NotificationModel

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
SEVERITY_SUCCESS = "success"


def notify(
    db: Database,
    *,
    kind: str,
    severity: str,
    title: str,
    body: str = "",
    dedupe_key: str | None = None,
    payload: dict | None = None,
) -> str | None:
    notification_id = new_id()
    try:
        with db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO notification(id, kind, severity, title, body, created_at, dedupe_key, payload)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    notification_id,
                    kind,
                    severity,
                    title[:200],
                    body[:1000],
                    now(),
                    dedupe_key,
                    json.dumps(payload or {}, separators=(",", ":")),
                ),
            )
    except Exception as exc:  # sqlite3.IntegrityError for the dedupe key
        if "UNIQUE" in str(exc).upper():
            return None
        raise
    return notification_id


def _to_model(row) -> NotificationModel:
    try:
        payload = json.loads(row["payload"] or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        payload = {}
    return NotificationModel(
        id=row["id"],
        kind=row["kind"],
        severity=row["severity"],
        title=row["title"],
        body=row["body"] or "",
        created_at=row["created_at"],
        read_at=row["read_at"],
        payload=payload,
    )


def feed(db: Database, *, limit: int = 30) -> ActivityFeed:
    rows = db.query("SELECT * FROM notification ORDER BY created_at DESC LIMIT ?", (limit,))
    unread = int(db.scalar("SELECT COUNT(*) FROM notification WHERE read_at IS NULL") or 0)
    return ActivityFeed(unread=unread, items=[_to_model(row) for row in rows])


def mark_read(db: Database, notification_id: str) -> bool:
    row = db.query_one("SELECT id FROM notification WHERE id=?", (notification_id,))
    if row is None:
        return False
    db.execute("UPDATE notification SET read_at=? WHERE id=? AND read_at IS NULL", (now(), notification_id))
    return True


def mark_all_read(db: Database) -> int:
    count = int(db.scalar("SELECT COUNT(*) FROM notification WHERE read_at IS NULL") or 0)
    db.execute("UPDATE notification SET read_at=? WHERE read_at IS NULL", (now(),))
    return count


def transition(
    db: Database,
    *,
    key: str,
    online: bool,
    detail: dict | None = None,
    offline_notification: tuple[str, str, str] | None = None,
    online_notification: tuple[str, str, str] | None = None,
) -> str | None:
    """Track a service's up/down edge and emit a notification when it changes.

    ``offline_notification``/``online_notification`` are ``(kind, title, body)`` tuples.
    Returns the id of a created notification, if any.
    """
    row = db.query_one("SELECT online, detail FROM service_state WHERE key=?", (key,))
    detail_json = json.dumps(detail or {}, separators=(",", ":"))
    if row is None:
        db.execute(
            "INSERT INTO service_state(key, online, detail, updated_at) VALUES (?,?,?,?)",
            (key, 1 if online else 0, detail_json, now()),
        )
        return None
    was_online = bool(row["online"])
    if was_online == online:
        db.execute(
            "UPDATE service_state SET detail=?, updated_at=? WHERE key=?", (detail_json, now(), key)
        )
        return None
    db.execute(
        "UPDATE service_state SET online=?, detail=?, updated_at=? WHERE key=?",
        (1 if online else 0, detail_json, now(), key),
    )
    spec = online_notification if online else offline_notification
    if spec is None:
        return None
    kind, title, body = spec
    return notify(
        db,
        kind=kind,
        severity=SEVERITY_SUCCESS if online else SEVERITY_ERROR,
        title=title,
        body=body,
        payload={"service": key, "online": online, **(detail or {})},
    )


def bootstrap_known_state(db: Database, *, key: str, online: bool) -> None:
    """Record the current state without emitting an event (used at first observation)."""
    row = db.query_one("SELECT key FROM service_state WHERE key=?", (key,))
    if row is None:
        db.execute(
            "INSERT INTO service_state(key, online, detail, updated_at) VALUES (?,?,?,?)",
            (key, 1 if online else 0, "{}", now()),
        )


def summary_line(activity: ActivityFeed) -> str:
    if activity.unread:
        latest = activity.items[0].title if activity.items else ""
        return f"{activity.unread} unread · {latest}"[:120]
    return "No unread activity"


def recent_events(db: Database, *, limit: int = 5) -> list[NotificationModel]:
    return feed(db, limit=limit).items


def timestamp_now() -> float:
    return time.time()
