"""Message queue lifecycle, ordering, idempotency and safe delivery."""

from __future__ import annotations

import json

from beacon.db import get_db
from beacon.services import message_queue


def test_queue_delivers_in_order_at_checkpoint(client, auth, env):
    first = client.post("/api/v1/agent/messages", json={"text": "first"}, headers=auth("admin")).json()
    second = client.post("/api/v1/agent/messages", json={"text": "second"}, headers=auth("admin")).json()
    assert first["seq"] < second["seq"]
    assert client.get("/api/v1/agent/status", headers=auth()).json()["queue"]["pending"] == 2

    checkpoint = client.post("/api/v1/agent/checkpoint", headers=auth("agent")).json()
    assert [message["body"] for message in checkpoint["delivered"]] == ["first", "second"]
    assert all(message["status"] == "delivered" for message in checkpoint["delivered"])
    assert checkpoint["pending_remaining"] == 0

    second_checkpoint = client.post("/api/v1/agent/checkpoint", headers=auth("agent")).json()
    assert second_checkpoint["delivered"] == []

    inbox = env.agent_dir / "inbox.jsonl"
    assert inbox.exists()
    lines = [json.loads(line) for line in inbox.read_text().splitlines()]
    assert [line["body"] for line in lines] == ["first", "second"]


def test_ack_and_processed_transitions(client, auth):
    message = client.post("/api/v1/agent/messages", json={"text": "do it"}, headers=auth("admin")).json()
    client.post("/api/v1/agent/checkpoint", headers=auth("agent"))
    acked = client.post(
        f"/api/v1/agent/messages/{message['id']}/ack",
        json={"note": "on it"},
        headers=auth("agent"),
    )
    assert acked.status_code == 200
    assert acked.json()["status"] == "acknowledged"
    assert acked.json()["ack_note"] == "on it"

    processed = client.post(
        f"/api/v1/agent/messages/{message['id']}/processed",
        json={"note": "done"},
        headers=auth("agent"),
    )
    assert processed.status_code == 200
    assert processed.json()["status"] == "processed"

    again = client.post(
        f"/api/v1/agent/messages/{message['id']}/processed", json={}, headers=auth("agent")
    )
    assert again.status_code == 409
    assert again.json()["error"] == "invalid_transition"


def test_cannot_ack_before_delivery(client, auth):
    message = client.post("/api/v1/agent/messages", json={"text": "x"}, headers=auth("admin")).json()
    response = client.post(f"/api/v1/agent/messages/{message['id']}/ack", json={}, headers=auth("agent"))
    assert response.status_code == 409


def test_cancel_only_while_pending(client, auth):
    message = client.post("/api/v1/agent/messages", json={"text": "cancel me"}, headers=auth("admin")).json()
    cancelled = client.delete(f"/api/v1/agent/messages/{message['id']}", headers=auth("admin"))
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    second = client.post("/api/v1/agent/messages", json={"text": "too late"}, headers=auth("admin")).json()
    client.post("/api/v1/agent/checkpoint", headers=auth("agent"))
    refused = client.delete(f"/api/v1/agent/messages/{second['id']}", headers=auth("admin"))
    assert refused.status_code == 409


def test_idempotency_key_prevents_duplicates(client, auth):
    payload = {"text": "only once", "idempotency_key": "abc-123"}
    first = client.post("/api/v1/agent/messages", json=payload, headers=auth("admin")).json()
    second = client.post("/api/v1/agent/messages", json=payload, headers=auth("admin")).json()
    assert first["id"] == second["id"]
    rows = client.get("/api/v1/agent/messages", headers=auth()).json()
    assert len([row for row in rows if row["body"] == "only once"]) == 1


def test_empty_message_rejected(client, auth):
    response = client.post("/api/v1/agent/messages", json={"text": "   "}, headers=auth("admin"))
    assert response.status_code == 422


def test_continue_without_text(client, auth):
    response = client.post("/api/v1/agent/continue", json={}, headers=auth("admin"))
    assert response.status_code == 201
    message = response.json()
    assert message["kind"] == "continue"
    assert "Continue" in message["body"]


def test_continue_with_note(client, auth):
    response = client.post(
        "/api/v1/agent/continue", json={"note": "also update the docs"}, headers=auth("admin")
    )
    assert response.status_code == 201
    assert "also update the docs" in response.json()["body"]


def test_checkpoint_requires_agent_scope(client, auth):
    response = client.post("/api/v1/agent/checkpoint", headers=auth("admin"))
    assert response.status_code == 403


def test_delivered_messages_are_never_rewritten(client, auth, env):
    message = client.post("/api/v1/agent/messages", json={"text": "immutable"}, headers=auth("admin")).json()
    client.post("/api/v1/agent/checkpoint", headers=auth("agent"))
    db = get_db(env)
    row = db.query_one("SELECT * FROM agent_message WHERE id=?", (message["id"],))
    assert row["body"] == "immutable"
    assert row["attempts"] == 1
    # A second checkpoint must not re-deliver or reset state.
    client.post("/api/v1/agent/checkpoint", headers=auth("agent"))
    row = db.query_one("SELECT * FROM agent_message WHERE id=?", (message["id"],))
    assert row["attempts"] == 1
    assert row["status"] == "delivered"


def test_queue_stats_expose_checkpoint_age(client, auth):
    client.post("/api/v1/agent/checkpoint", headers=auth("agent"))
    stats = client.get("/api/v1/agent/queue", headers=auth()).json()
    assert stats["pending"] == 0
    assert stats["checkpoint_age_seconds"] is not None


def test_queue_module_refuses_unknown_kind(env):
    db = get_db(env)
    try:
        message_queue.enqueue(db, text="x", kind="pause")
    except message_queue.QueueError as exc:
        assert exc.code == "invalid_kind"
    else:  # pragma: no cover
        raise AssertionError("expected QueueError")
