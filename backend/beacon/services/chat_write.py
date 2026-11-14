"""Write a user turn into Cherry Studio's durable agent-session delivery queue.

Cherry Studio has no public local API for sending a message. Its own Session delivery
service, however, treats a row in ``agent_session_message`` with ``delivery_status='accepted'``
as a durable inbound message and dispatches it on the next delivery sweep (or as soon as the
target runtime becomes idle). This module produces exactly that row.

This is deliberately a *compatibility* integration:
- it is gated by ``BEACON_CHAT_WRITE`` (off means fall back to the Beacon queue);
- it validates the session/agent and all values before writing;
- it never invents a model turn: Cherry's normal dispatch path creates the assistant message;
- it is transactionally one row, with SQLite's WAL/busy handling.

The schema is Cherry Studio's, so a Cherry upgrade can change it. Failures are surfaced as
``ChatWriteError`` and the API falls back to the ordinary Beacon message queue.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings


class ChatWriteError(Exception):
    """A user-visible reason the Cherry delivery row could not be created."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ChatWriteResult:
    message_id: str
    created: bool
    session_id: str


def _connect_rw(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise ChatWriteError("cherry_unavailable", "Cherry Studio database was not found")
    uri = f"file:{urllib.parse.quote(str(path))}?mode=rw"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7, matching Cherry Studio's message id ordering."""
    millis = int(time.time() * 1000) & ((1 << 48) - 1)
    random_bits = int.from_bytes(os.urandom(10), "big")  # 74 random bits + 6 version/variant bits
    value = millis << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 68) & 0xFFF) << 64
    value |= 0x2 << 62
    value |= random_bits & ((1 << 62) - 1)
    return uuid.UUID(int=value)


def _message_id(session_id: str, client_message_id: str | None) -> uuid.UUID:
    if client_message_id:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"beacon-chat:{session_id}:{client_message_id}")
    return _uuid7()


def _iso_now() -> str:
    # Cherry stores delivery.statusAt as an ISO-8601 datetime string.
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"


def _session_row(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT s.id, s.name, s.agent_id, a.name AS agent_name
        FROM agent_session s
        LEFT JOIN agent a ON a.id = s.agent_id
        WHERE s.id = ? AND s.agent_id IS NOT NULL
          AND (a.id IS NULL OR a.deleted_at IS NULL)
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        raise ChatWriteError("session_not_found", "That chat is not available to Cherry Studio")
    return row


def enqueue_user_message(
    settings: Settings,
    *,
    session_id: str,
    text: str,
    client_message_id: str | None = None,
) -> ChatWriteResult:
    """Create one accepted delivery row for a user message.

    Duplicate ``client_message_id`` values are idempotent: the existing row is returned.
    """
    if not settings.chat_write_enabled:
        raise ChatWriteError("chat_write_disabled", "Writeable chats are disabled")

    body = (text or "").strip()
    if not body:
        raise ChatWriteError("empty_message", "Message is empty")
    if len(body) > 4000:
        raise ChatWriteError("message_too_long", "Message is longer than 4000 characters")
    if "\x00" in body:
        raise ChatWriteError("invalid_message", "Message contains an invalid character")

    try:
        conn = _connect_rw(settings.cherry_db)
    except sqlite3.Error as exc:
        raise ChatWriteError("cherry_unavailable", f"Cherry Studio database is unavailable: {exc}") from exc

    message_uuid = _message_id(session_id, client_message_id)
    message_id = str(message_uuid)
    now_ms = int(time.time() * 1000)
    created = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        session = _session_row(conn, session_id)

        existing = conn.execute(
            "SELECT id, role FROM agent_session_message WHERE id = ?",
            (message_id,),
        ).fetchone()
        if existing is not None:
            if existing["role"] != "user":
                raise ChatWriteError("idempotency_conflict", "Message id already belongs to another role")
            conn.commit()
            return ChatWriteResult(message_id=message_id, created=False, session_id=session_id)

        agent_id = str(session["agent_id"])
        agent_name = str(session["agent_name"] or "Agent")
        session_name = str(session["name"] or "Agent chat")
        delivery = {
            "version": 1,
            "sender": {"agentId": agent_id, "sessionId": session_id},
            "receiver": {"agentId": agent_id, "sessionId": session_id},
            "senderSnapshot": {"agentName": "Beacon", "sessionName": "Phone"},
            "receiverSnapshot": {"agentName": agent_name, "sessionName": session_name},
            "replyPolicy": "none",
            "sourceMessageId": None,
            "outcome": None,
            "error": None,
            "statusAt": _iso_now(),
        }
        data = {"parts": [{"type": "text", "text": body}]}

        conn.execute(
            """
            INSERT INTO agent_session_message (
                id, session_id, role, data, searchable_text, status,
                model_id, message_snapshot, stats, runtime_resume_token,
                delivery, delivery_status, delivery_turn_ref, delivery_in_reply_to,
                delivery_sender_session_id, fts_rowid, created_at, updated_at
            ) VALUES (?, ?, 'user', ?, '', 'success', NULL, NULL, NULL, NULL,
                      ?, 'accepted', NULL, NULL, ?, NULL, ?, ?)
            """,
            (
                message_id,
                session_id,
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                json.dumps(delivery, ensure_ascii=False, separators=(",", ":")),
                session_id,
                now_ms,
                now_ms,
            ),
        )
        conn.execute(
            "UPDATE agent_session SET last_activity_at = ?, updated_at = ? WHERE id = ?",
            (now_ms, now_ms, session_id),
        )
        conn.commit()
        created = True
        return ChatWriteResult(message_id=message_id, created=created, session_id=session_id)
    except ChatWriteError:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        # A racing retry may have inserted the same deterministic id.
        try:
            row = conn.execute(
                "SELECT id, role FROM agent_session_message WHERE id = ?",
                (message_id,),
            ).fetchone()
            if row is not None and row["role"] == "user":
                return ChatWriteResult(message_id=message_id, created=False, session_id=session_id)
        except sqlite3.Error:
            pass
        raise ChatWriteError("cherry_write_failed", f"Cherry Studio rejected the message: {exc}") from exc
    except sqlite3.OperationalError as exc:
        conn.rollback()
        raise ChatWriteError("cherry_busy", f"Cherry Studio database is busy: {exc}") from exc
    except sqlite3.Error as exc:
        conn.rollback()
        raise ChatWriteError("cherry_write_failed", f"Could not write the message: {exc}") from exc
    finally:
        conn.close()
