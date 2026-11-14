"""Durable agent message queue.

States
------
``pending`` → ``delivered`` → ``acknowledged`` → ``processed`` (terminal)
``pending`` → ``cancelled`` (terminal, only before delivery)
``pending``/``delivered`` → ``failed`` (only by an explicit admin/system action)

There is no transition that rewrites a delivered body. Ordering is by ``seq``.
Delivery happens exclusively through :func:`checkpoint`, called by the agent token at a safe
point between operations — the queue never injects into a running turn.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..db import Database, new_id, now
from ..schemas import MessageModel

KINDS = ("suggestion", "continue")
DELIVERY_STATES = ("pending", "delivered", "acknowledged", "processed")


class QueueError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _row_to_model(row) -> MessageModel:
    return MessageModel.from_row(row)


def get(db: Database, message_id: str) -> MessageModel | None:
    row = db.query_one("SELECT * FROM agent_message WHERE id=?", (message_id,))
    return _row_to_model(row) if row else None


def enqueue(
    db: Database,
    *,
    text: str,
    kind: str = "suggestion",
    idempotency_key: str | None = None,
    client: str | None = None,
    session_id: str | None = None,
    forward: bool = True,
) -> tuple[MessageModel, bool]:
    """Add a message. Returns ``(message, created)``; an existing idempotency key wins."""
    if kind not in KINDS:
        raise QueueError("invalid_kind", f"kind must be one of {KINDS}", status_code=422)
    body = text.strip()
    if not body:
        raise QueueError("empty_message", "message text must not be empty", status_code=422)

    # Namespace the key by client so two devices that happen to use "1" cannot read or collide
    # with each other's messages.
    effective_key = f"{client or 'unknown'}:{idempotency_key}" if idempotency_key else None
    if effective_key:
        existing = db.query_one(
            "SELECT * FROM agent_message WHERE idempotency_key=?", (effective_key,)
        )
        if existing is not None:
            return _row_to_model(existing), False

    message_id = new_id()
    created = True
    with db.transaction() as conn:
        seq = int(conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM agent_message").fetchone()[0])
        if effective_key:
            # One statement closes the race: a concurrent duplicate inserts nothing and we
            # return the winner's row instead of raising IntegrityError.
            cursor = conn.execute(
                """
                INSERT INTO agent_message(
                    id, seq, kind, body, status, created_at, idempotency_key, client, session_id, forward
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    message_id,
                    seq,
                    kind,
                    body,
                    "pending",
                    now(),
                    effective_key,
                    client,
                    session_id,
                    1 if forward else 0,
                ),
            )
            if cursor.rowcount == 0:
                created = False
                message_id = ""
        else:
            conn.execute(
                """
                INSERT INTO agent_message(
                    id, seq, kind, body, status, created_at, idempotency_key, client, session_id, forward
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    message_id,
                    seq,
                    kind,
                    body,
                    "pending",
                    now(),
                    None,
                    client,
                    session_id,
                    1 if forward else 0,
                ),
            )
    if not created:
        row = db.query_one(
            "SELECT * FROM agent_message WHERE idempotency_key=?", (effective_key,)
        )
        assert row is not None
        return _row_to_model(row), False
    row = db.query_one("SELECT * FROM agent_message WHERE id=?", (message_id,))
    assert row is not None
    return _row_to_model(row), True


def list_messages(
    db: Database, *, limit: int = 25, include_cancelled: bool = True
) -> list[MessageModel]:
    clause = "" if include_cancelled else "WHERE status != 'cancelled'"
    rows = db.query(
        f"SELECT * FROM agent_message {clause} ORDER BY seq DESC LIMIT ?",
        (limit,),
    )
    return [_row_to_model(row) for row in rows]


def pending_count(db: Database) -> int:
    return int(db.scalar("SELECT COUNT(*) FROM agent_message WHERE status='pending'") or 0)


def pending_for_forwarding(db: Database, *, limit: int = 10) -> list[dict]:
    """Pending queue rows that a writeable-chat writer may forward immediately.

    The raw ``session_id`` is intentionally included: it is routing metadata, not part of the
    public ``MessageModel``.
    """
    rows = db.query(
        "SELECT id, seq, body, session_id FROM agent_message "
        "WHERE status='pending' AND forward=1 ORDER BY seq LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in rows]


def mark_forwarded(db: Database, message_id: str, *, note: str) -> MessageModel:
    """Mark a queue row as handed to Cherry Studio's durable delivery queue.

    This is not an agent checkpoint: Cherry owns the turn from here. Recording the terminal
    state keeps the row from being forwarded twice (the deterministic Cherry message id is the
    second line of defence).
    """
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM agent_message WHERE id=?", (message_id,)).fetchone()
        if row is None:
            raise QueueError("not_found", "message not found", status_code=404)
        if row["status"] not in ("pending", "delivered", "acknowledged", "processed"):
            raise QueueError(
                "invalid_transition",
                f"cannot forward a message in state '{row['status']}'",
            )
        if row["status"] != "processed":
            stamp = now()
            conn.execute(
                """
                UPDATE agent_message
                   SET status='processed', delivered_at=COALESCE(delivered_at, ?),
                       acknowledged_at=COALESCE(acknowledged_at, ?), processed_at=?,
                       ack_note=COALESCE(ack_note, ?), processed_note=?
                 WHERE id=?
                """,
                (stamp, stamp, stamp, note, note, message_id),
            )
    return get(db, message_id)  # type: ignore[return-value]


def checkpoint(
    db: Database,
    *,
    settings,
    session_id: str | None,
    limit: int = 10,
) -> list[MessageModel]:
    """Hand pending messages to the agent. Delivery is atomic per message."""
    limit = max(1, min(limit, 25))
    delivered_rows = []
    lease_seconds = getattr(settings, "message_lease_seconds", 120)
    max_attempts = getattr(settings, "message_max_attempts", 5)
    lease_cutoff = now() - lease_seconds
    with db.transaction() as conn:
        # Pending work, plus deliveries whose lease expired without an acknowledgement (the
        # agent may have died mid-request). Bodies are never rewritten.
        rows = conn.execute(
            """
            SELECT * FROM agent_message
             WHERE status='pending'
                OR (status='delivered' AND delivered_at IS NOT NULL AND delivered_at <= ?
                    AND attempts < ?)
             ORDER BY seq
             LIMIT ?
            """,
            (lease_cutoff, max_attempts, limit),
        ).fetchall()
        stamp = now()
        for row in rows:
            conn.execute(
                """
                UPDATE agent_message
                   SET status='delivered', delivered_at=?, attempts=attempts+1, session_id=COALESCE(?, session_id)
                 WHERE id=? AND status IN ('pending', 'delivered')
                """,
                (stamp, session_id, row["id"]),
            )
            delivered_rows.append(conn.execute("SELECT * FROM agent_message WHERE id=?", (row["id"],)).fetchone())
    messages = [_row_to_model(row) for row in delivered_rows if row is not None]
    if messages:
        _mirror_to_inbox(settings, messages)
    return messages


def _mirror_to_inbox(settings, messages: list[MessageModel]) -> None:
    """Append delivered messages to a JSONL inbox the agent can read from the filesystem."""
    path = Path(settings.agent_dir) / "inbox.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for message in messages:
                handle.write(
                    json.dumps(
                        {
                            "type": "message",
                            "id": message.id,
                            "seq": message.seq,
                            "kind": message.kind,
                            "body": message.body,
                            "delivered_at": message.delivered_at,
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        # The queue is still authoritative; the mirror is best-effort telemetry.
        pass


def nack(db: Database, message_id: str, *, note: str | None = None) -> MessageModel:
    """Return a delivered message to the queue (agent could not process it)."""
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM agent_message WHERE id=?", (message_id,)).fetchone()
        if row is None:
            raise QueueError("not_found", "message not found", status_code=404)
        if row["status"] != "delivered":
            raise QueueError(
                "invalid_transition",
                f"cannot nack a message in state '{row['status']}'",
            )
        conn.execute(
            "UPDATE agent_message SET status='pending', delivered_at=NULL, ack_note=? WHERE id=?",
            (note or row["ack_note"], message_id),
        )
    return get(db, message_id)  # type: ignore[return-value]


def acknowledge(db: Database, message_id: str, *, note: str | None = None) -> MessageModel:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM agent_message WHERE id=?", (message_id,)).fetchone()
        if row is None:
            raise QueueError("not_found", "message not found", status_code=404)
        if row["status"] != "delivered":
            raise QueueError(
                "invalid_transition",
                f"cannot acknowledge a message in state '{row['status']}'",
            )
        conn.execute(
            "UPDATE agent_message SET status='acknowledged', acknowledged_at=?, ack_note=? WHERE id=?",
            (now(), (note or None), message_id),
        )
    return get(db, message_id)  # type: ignore[return-value]


def mark_processed(db: Database, message_id: str, *, note: str | None = None) -> MessageModel:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM agent_message WHERE id=?", (message_id,)).fetchone()
        if row is None:
            raise QueueError("not_found", "message not found", status_code=404)
        if row["status"] not in ("delivered", "acknowledged"):
            raise QueueError(
                "invalid_transition",
                f"cannot mark a message processed in state '{row['status']}'",
            )
        conn.execute(
            "UPDATE agent_message SET status='processed', processed_at=?, processed_note=? WHERE id=?",
            (now(), (note or None), message_id),
        )
    return get(db, message_id)  # type: ignore[return-value]


def cancel(db: Database, message_id: str) -> MessageModel:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM agent_message WHERE id=?", (message_id,)).fetchone()
        if row is None:
            raise QueueError("not_found", "message not found", status_code=404)
        if row["status"] != "pending":
            raise QueueError(
                "invalid_transition",
                "only pending messages can be cancelled (already delivered messages must be handled by the agent)",
            )
        conn.execute(
            "UPDATE agent_message SET status='cancelled', cancelled_at=? WHERE id=?",
            (now(), message_id),
        )
    return get(db, message_id)  # type: ignore[return-value]


def stats(db: Database) -> dict[str, int]:
    rows = db.query("SELECT status, COUNT(*) AS n FROM agent_message GROUP BY status")
    counts = {row["status"]: int(row["n"]) for row in rows}
    oldest_pending = db.scalar(
        "SELECT MIN(created_at) FROM agent_message WHERE status='pending'"
    )
    return {
        "pending": counts.get("pending", 0),
        "delivered": counts.get("delivered", 0),
        "acknowledged": counts.get("acknowledged", 0),
        "processed": counts.get("processed", 0),
        "cancelled": counts.get("cancelled", 0),
        "oldest_pending_at": int(oldest_pending) if oldest_pending else 0,
        "now": int(time.time()),
    }
