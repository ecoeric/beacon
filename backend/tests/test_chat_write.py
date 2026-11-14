"""Writeable Chats: Cherry Studio durable delivery rows."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest

from beacon.services import chat_write


@pytest.fixture
def writer(env):
    from dataclasses import replace

    return replace(env, chat_write_enabled=True)


def _row(cherry, message_id: str) -> sqlite3.Row:
    cherry.conn.row_factory = sqlite3.Row
    return cherry.conn.execute(
        "SELECT * FROM agent_session_message WHERE id = ?", (message_id,)
    ).fetchone()


def test_enqueue_creates_accepted_delivery(writer, cherry):
    result = chat_write.enqueue_user_message(
        writer, session_id=cherry.session_id, text="  hello from the phone  "
    )
    assert result.created is True

    row = _row(cherry, result.message_id)
    assert row["session_id"] == cherry.session_id
    assert row["role"] == "user"
    assert row["status"] == "success"
    assert row["delivery_status"] == "accepted"
    assert row["delivery_turn_ref"] is None
    assert row["delivery_sender_session_id"] == cherry.session_id

    data = json.loads(row["data"])
    assert data == {"parts": [{"type": "text", "text": "hello from the phone"}]}

    delivery = json.loads(row["delivery"])
    assert delivery["version"] == 1
    assert delivery["receiver"] == {"agentId": "agent-test", "sessionId": cherry.session_id}
    assert delivery["replyPolicy"] == "none"
    assert delivery["statusAt"].endswith("Z")


def test_client_message_id_is_idempotent(writer, cherry):
    first = chat_write.enqueue_user_message(
        writer, session_id=cherry.session_id, text="once", client_message_id="phone-1"
    )
    second = chat_write.enqueue_user_message(
        writer, session_id=cherry.session_id, text="once", client_message_id="phone-1"
    )
    assert first.message_id == second.message_id
    assert first.created is True
    assert second.created is False
    count = cherry.conn.execute(
        "SELECT COUNT(*) FROM agent_session_message WHERE id = ?", (first.message_id,)
    ).fetchone()[0]
    assert count == 1


def test_unknown_session_is_rejected(writer):
    with pytest.raises(chat_write.ChatWriteError) as raised:
        chat_write.enqueue_user_message(writer, session_id="does-not-exist", text="hi")
    assert raised.value.code == "session_not_found"


def test_empty_and_oversized_messages_are_rejected(writer, cherry):
    with pytest.raises(chat_write.ChatWriteError) as empty:
        chat_write.enqueue_user_message(writer, session_id=cherry.session_id, text="   ")
    assert empty.value.code == "empty_message"

    with pytest.raises(chat_write.ChatWriteError) as long:
        chat_write.enqueue_user_message(writer, session_id=cherry.session_id, text="x" * 4001)
    assert long.value.code == "message_too_long"


def test_disabled_writer_is_rejected(env, cherry, monkeypatch):
    from dataclasses import replace

    disabled = replace(env, chat_write_enabled=False)
    with pytest.raises(chat_write.ChatWriteError) as raised:
        chat_write.enqueue_user_message(disabled, session_id=cherry.session_id, text="hi")
    assert raised.value.code == "chat_write_disabled"


def test_endpoint_sends_into_cherry(client, auth, cherry, writer, monkeypatch):
    monkeypatch.setattr("beacon.routers.agent.get_settings", lambda: writer)
    response = client.post(
        f"/api/v1/agent/sessions/{cherry.session_id}/messages",
        json={"text": "from iOS", "client_message_id": "ios-1"},
        headers=auth("admin"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["delivered"] is True
    assert body["mode"] == "cherry"
    row = _row(cherry, body["message_id"])
    assert row["delivery_status"] == "accepted"
    assert json.loads(row["data"])["parts"][0]["text"] == "from iOS"


def test_endpoint_falls_back_to_queue_when_cherry_is_unavailable(client, auth, cherry, writer, monkeypatch):
    monkeypatch.setattr("beacon.routers.agent.get_settings", lambda: writer)

    def fail(*args, **kwargs):
        raise chat_write.ChatWriteError("cherry_busy", "database is locked")

    monkeypatch.setattr("beacon.routers.agent.chat_write.enqueue_user_message", fail)
    response = client.post(
        f"/api/v1/agent/sessions/{cherry.session_id}/messages",
        json={"text": "still queued"},
        headers=auth("admin"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["delivered"] is False
    assert body["mode"] == "queue"
    assert body["queued_id"]


def test_endpoint_requires_action_scope(client, cherry, auth):
    response = client.post(
        f"/api/v1/agent/sessions/{cherry.session_id}/messages",
        json={"text": "nope"},
        headers=auth("read"),
    )
    assert response.status_code == 403


def test_forward_one_marks_queue_row_processed(writer, cherry):
    from beacon.db import get_db
    from beacon.services import chat_delivery, message_queue

    db = get_db(writer)
    message, _ = message_queue.enqueue(
        db,
        text="legacy queued message",
        kind="suggestion",
        client="test",
        session_id=cherry.session_id,
    )
    assert chat_delivery.forward_one(writer, db, message.id) is True
    updated = message_queue.get(db, message.id)
    assert updated is not None
    assert updated.status == "processed"
    assert updated.processed_at is not None
    assert "forwarded to Cherry chat" in (updated.processed_note or "")

    row = cherry.conn.execute(
        "SELECT * FROM agent_session_message WHERE id = ?",
        (chat_write._message_id(cherry.session_id, f"queue:{message.id}").__str__(),),
    ).fetchone()
    assert row is not None


def test_forward_one_leaves_row_pending_when_cherry_is_unavailable(writer, cherry, monkeypatch):
    from beacon.db import get_db
    from beacon.services import chat_delivery, message_queue

    db = get_db(writer)
    message, _ = message_queue.enqueue(
        db,
        text="keep me",
        kind="suggestion",
        client="test",
        session_id=cherry.session_id,
    )

    def fail(*args, **kwargs):
        raise chat_write.ChatWriteError("cherry_busy", "database is locked")

    monkeypatch.setattr("beacon.services.chat_delivery.chat_write.enqueue_user_message", fail)
    assert chat_delivery.forward_one(writer, db, message.id) is False
    updated = message_queue.get(db, message.id)
    assert updated is not None
    assert updated.status == "pending"


def test_legacy_queue_endpoint_forwards_to_cherry(client, auth, cherry, writer, monkeypatch):
    monkeypatch.setattr("beacon.routers.agent.get_settings", lambda: writer)
    response = client.post(
        "/api/v1/agent/messages",
        json={"text": "legacy path", "kind": "suggestion"},
        headers=auth("admin"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "processed"
    assert body["processed_at"] is not None
    row = cherry.conn.execute(
        "SELECT * FROM agent_session_message WHERE session_id = ? AND role = 'user' ORDER BY created_at DESC LIMIT 1",
        (cherry.session_id,),
    ).fetchone()
    assert row is not None
    assert "legacy path" in row[3]


def test_forward_false_stays_in_the_queue(client, auth, cherry, writer, monkeypatch):
    monkeypatch.setattr("beacon.routers.agent.get_settings", lambda: writer)
    response = client.post(
        "/api/v1/agent/messages",
        json={"text": "checkpoint only", "forward": False},
        headers=auth("admin"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "pending"

    from beacon.db import get_db
    from beacon.services import chat_delivery

    db = get_db(writer)
    assert chat_delivery.forward_pending(writer, db) == 0
    row = db.query_one("SELECT status FROM agent_message WHERE id=?", (body["id"],))
    assert row is not None and row["status"] == "pending"
