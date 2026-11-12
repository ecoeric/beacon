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


def _age_delivery(env, message_id, seconds=3600):
    import time as _time

    from beacon.db import get_db as _get_db

    _get_db(env).execute(
        "UPDATE agent_message SET delivered_at=? WHERE id=?", (_time.time() - seconds, message_id)
    )


def test_expired_delivery_is_redelivered(client, auth, env):
    message = client.post("/api/v1/agent/messages", json={"text": "lease me"}, headers=auth("admin")).json()
    first = client.post("/api/v1/agent/checkpoint", headers=auth("agent")).json()
    assert [item["id"] for item in first["delivered"]] == [message["id"]]
    _age_delivery(env, message["id"])
    second = client.post("/api/v1/agent/checkpoint", headers=auth("agent")).json()
    assert [item["id"] for item in second["delivered"]] == [message["id"]]
    assert second["delivered"][0]["attempts"] == 2


def test_acknowledged_message_is_not_redelivered(client, auth, env):
    message = client.post("/api/v1/agent/messages", json={"text": "ack me"}, headers=auth("admin")).json()
    client.post("/api/v1/agent/checkpoint", headers=auth("agent"))
    client.post(f"/api/v1/agent/messages/{message['id']}/ack", json={}, headers=auth("agent"))
    _age_delivery(env, message["id"])
    checkpoint = client.post("/api/v1/agent/checkpoint", headers=auth("agent")).json()
    assert checkpoint["delivered"] == []


def test_nack_returns_the_message_to_the_queue(client, auth, env):
    message = client.post("/api/v1/agent/messages", json={"text": "nack me"}, headers=auth("admin")).json()
    client.post("/api/v1/agent/checkpoint", headers=auth("agent"))
    nacked = client.post(
        f"/api/v1/agent/messages/{message['id']}/nack",
        json={"note": "runtime died mid-request"},
        headers=auth("agent"),
    )
    assert nacked.status_code == 200
    assert nacked.json()["status"] == "pending"
    assert nacked.json()["delivered_at"] is None
    again = client.post("/api/v1/agent/checkpoint", headers=auth("agent")).json()
    assert [item["id"] for item in again["delivered"]] == [message["id"]]


def test_nack_requires_delivered_state(client, auth):
    message = client.post("/api/v1/agent/messages", json={"text": "never delivered"}, headers=auth("admin")).json()
    response = client.post(f"/api/v1/agent/messages/{message['id']}/nack", json={}, headers=auth("agent"))
    assert response.status_code == 409


def test_delivery_stops_after_max_attempts(client, auth, env):
    from beacon.db import get_db as _get_db

    message = client.post("/api/v1/agent/messages", json={"text": "poison"}, headers=auth("admin")).json()
    client.post("/api/v1/agent/checkpoint", headers=auth("agent"))
    _get_db(env).execute("UPDATE agent_message SET attempts=5 WHERE id=?", (message["id"],))
    _age_delivery(env, message["id"])
    checkpoint = client.post("/api/v1/agent/checkpoint", headers=auth("agent")).json()
    assert checkpoint["delivered"] == []


def test_idempotency_keys_are_namespaced_per_client(client, auth, env):
    import time as _time

    from beacon.db import get_db as _get_db
    from beacon.security import create_token

    db = _get_db(env)
    second_token, _info = create_token(db, env.secrets_dir, "ios2", "read,action,admin")
    payload = {"text": "shared key", "idempotency_key": "same-key"}
    first = client.post("/api/v1/agent/messages", json=payload, headers=auth("admin")).json()
    second = client.post(
        "/api/v1/agent/messages",
        json=payload,
        headers={"Authorization": f"Bearer {second_token}"},
    ).json()
    assert first["id"] != second["id"], "different clients must not share an idempotency key"
    assert first["body"] == second["body"] == "shared key"
    _ = _time


def test_idempotency_insert_race_returns_the_winner(env):
    import time as _time

    from beacon.db import get_db as _get_db
    from beacon.services import message_queue

    db = _get_db(env)
    with db.transaction() as conn:
        seq = int(conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM agent_message").fetchone()[0])
        conn.execute(
            "INSERT INTO agent_message(id, seq, kind, body, status, created_at, idempotency_key, client) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("winner-id", seq, "suggestion", "first writer", "pending", _time.time(), "ios:race", "ios"),
        )
    message, created = message_queue.enqueue(
        db, text="second writer", client="ios", idempotency_key="race"
    )
    assert created is False
    assert message.id == "winner-id"
    assert message.body == "first writer"
