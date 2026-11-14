"""Bridge Beacon's durable message queue into Cherry Studio's delivery queue.

The legacy queue only hands messages to an agent that calls ``/agent/checkpoint``. The DSH
runtime Cherry launches does not call that endpoint, so a queue-only message can sit forever.
This module forwards pending queue rows into the same durable delivery table used by the
writeable Chats composer, then records the queue row as processed.

It is deliberately best-effort: Cherry may be closed, busy, or mid-upgrade. On failure the row
stays pending and the next sweep retries.
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..db import Database
from . import chat_write, interrupts, message_queue

logger = logging.getLogger("beacon.chat_delivery")


def forward_one(settings: Settings, db: Database, message_id: str) -> bool:
    """Forward one pending queue row. Returns True only after the row is marked processed."""
    if not settings.chat_write_enabled:
        return False
    row = db.query_one(
        "SELECT id, body, session_id, status FROM agent_message WHERE id=?", (message_id,)
    )
    if row is None or row["status"] != "pending":
        return False
    session_id = row["session_id"] or interrupts.resolve_session(settings, db)
    if not session_id:
        return False
    try:
        result = chat_write.enqueue_user_message(
            settings,
            session_id=str(session_id),
            text=str(row["body"]),
            client_message_id=f"queue:{row['id']}",
        )
    except chat_write.ChatWriteError as exc:
        logger.info("queue message %s left pending: %s (%s)", message_id, exc.message, exc.code)
        return False
    message_queue.mark_forwarded(
        db,
        message_id,
        note=f"forwarded to Cherry chat {result.message_id}",
    )
    return True


def forward_pending(settings: Settings, db: Database, *, limit: int = 10) -> int:
    """Forward up to ``limit`` pending messages. Returns the number handed off."""
    if not settings.chat_write_enabled:
        return 0
    forwarded = 0
    for row in message_queue.pending_for_forwarding(db, limit=limit):
        if forward_one(settings, db, str(row["id"])):
            forwarded += 1
    return forwarded
