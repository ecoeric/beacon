"""Authentication, scopes, confirmation and health."""

from __future__ import annotations


def test_health_is_unauthenticated(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"


def test_missing_token_is_rejected(client):
    response = client.get("/api/v1/summary")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"


def test_bad_token_is_rejected(client):
    response = client.get("/api/v1/whoami", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_whoami_reports_scopes(client, auth):
    response = client.get("/api/v1/whoami", headers=auth("read"))
    assert response.status_code == 200
    assert response.json()["scopes"] == ["read"]


def test_read_token_cannot_interrupt(client, auth):
    response = client.post(
        "/api/v1/agent/interrupt",
        json={"mode": "signal"},
        headers=auth("read", **{"X-Beacon-Confirm": "agent-interrupt"}),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "insufficient_scope"


def test_admin_scope_implies_action(client, auth):
    response = client.post(
        "/api/v1/agent/messages", json={"text": "hello"}, headers=auth("admin")
    )
    assert response.status_code == 201


def test_agent_token_cannot_queue_ios_messages(client, auth):
    response = client.post("/api/v1/agent/messages", json={"text": "hello"}, headers=auth("agent"))
    assert response.status_code == 403


def test_interrupt_requires_confirmation_header(client, auth):
    response = client.post("/api/v1/agent/interrupt", json={"mode": "checkpoint"}, headers=auth("admin"))
    assert response.status_code == 428
    assert response.json()["detail"]["code"] == "confirmation_required"


def test_interrupt_requires_admin_scope(client, auth):
    response = client.post(
        "/api/v1/agent/interrupt",
        json={"mode": "checkpoint"},
        headers=auth("read", **{"X-Beacon-Confirm": "agent-interrupt"}),
    )
    assert response.status_code == 403


def test_docs_are_disabled_by_default(client):
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404


def test_capabilities_are_honest_about_unavailable_sources(client, auth):
    response = client.get("/api/v1/capabilities", headers=auth())
    assert response.status_code == 200
    payload = response.json()
    assert payload["monitoring"]["docker"] is False
    assert payload["monitoring"]["pihole"] is False
    assert payload["notifications"]["push"] is False
    assert payload["screenshots"]["retention_days"] == 7


def test_token_last_used_is_throttled(client, auth, env, monkeypatch):
    from beacon.db import get_db
    from beacon.security import reset_security_state_for_tests, verify_token

    reset_security_state_for_tests()
    db = get_db(env)
    raw = auth("read")["Authorization"].split(" ", 1)[1]
    updates = []
    original = db.execute

    def counting(sql, params=()):
        if "UPDATE token SET last_used_at" in sql:
            updates.append(sql)
        return original(sql, params)

    monkeypatch.setattr(db, "execute", counting)
    assert verify_token(db, raw) is not None
    assert verify_token(db, raw) is not None
    assert len(updates) == 1, "last_used_at must be flushed at most once per window"
    reset_security_state_for_tests()
