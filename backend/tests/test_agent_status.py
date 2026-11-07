"""Agent status derivation, the Status action, and message queue behaviour."""

from __future__ import annotations

import json
import time

import pytest

from beacon.config import get_settings
from beacon.db import get_db
from beacon.services import agent_runtime, agent_status, interrupts, message_queue, status_summary


def _publish_status(client, auth, **overrides):
    payload = {
        "project": "Beacon",
        "stage": "Phase 3 — agent integration",
        "activity": "wiring the queue",
        "last_milestone": "Phase 2 foundation",
        "next_action": "test interrupt",
        "awaiting_input": False,
    }
    payload.update(overrides)
    response = client.put("/api/v1/agent/status", json=payload, headers=auth("agent"))
    assert response.status_code == 200, response.text
    return response.json()


def test_agent_status_snapshot_roundtrip(client, auth):
    body = _publish_status(client, auth)
    assert body["project"] == "Beacon"
    assert body["activity"] == "wiring the queue"
    assert body["state"] in {"idle", "working"}
    assert body["session"]["id"] is not None
    assert body["data_age_seconds"] is not None


def test_state_is_working_when_a_turn_is_pending(client, auth, cherry):
    cherry.message("user", "success", "keep going")
    cherry.message("assistant", "pending", "")
    _publish_status(client, auth)
    body = client.get("/api/v1/agent/status", headers=auth()).json()
    assert body["state"] == "working"
    assert body["session"]["turn_running"] is True


def test_state_is_waiting_for_messages_when_queue_has_pending(client, auth):
    _publish_status(client, auth, awaiting_input=False)
    response = client.post(
        "/api/v1/agent/messages", json={"text": "please also add tests"}, headers=auth("admin")
    )
    assert response.status_code == 201
    body = client.get("/api/v1/agent/status", headers=auth()).json()
    assert body["state"] == "waiting_for_messages"
    assert body["queue"]["pending"] == 1


def test_state_is_waiting_for_input_when_agent_asks(client, auth):
    _publish_status(client, auth, awaiting_input=True, blockers=["need a decision on TLS pinning"])
    body = client.get("/api/v1/agent/status", headers=auth()).json()
    assert body["state"] == "waiting_for_input"
    assert body["blockers"] == ["need a decision on TLS pinning"]
    activity = client.get("/api/v1/activity", headers=auth()).json()
    assert any(item["kind"] == "agent_waiting_for_input" for item in activity["items"])


def test_state_failed_when_last_turn_errored(client, auth, cherry):
    cherry.message("assistant", "error", "boom")
    _publish_status(client, auth)
    body = client.get("/api/v1/agent/status", headers=auth()).json()
    assert body["state"] == "failed"


def test_status_action_is_deterministic_and_short(client, auth):
    _publish_status(client, auth)
    first = client.get("/api/v1/agent/status/summary", headers=auth()).json()
    second = client.get("/api/v1/agent/status/summary", headers=auth()).json()
    assert first["summary"] == second["summary"]
    assert first["deterministic"] is True
    sentences = [part for part in first["summary"].replace("!", ".").split(".") if part.strip()]
    assert 1 <= len(sentences) <= 3
    assert "Beacon" in first["summary"]


def test_status_action_does_not_touch_the_queue_or_snapshot(client, auth, cherry):
    _publish_status(client, auth)
    before = client.get("/api/v1/agent/status", headers=auth()).json()
    messages_before = client.get("/api/v1/agent/messages", headers=auth()).json()
    client.get("/api/v1/agent/status/summary", headers=auth())
    after = client.get("/api/v1/agent/status", headers=auth()).json()
    messages_after = client.get("/api/v1/agent/messages", headers=auth()).json()
    assert before["updated_at"] == after["updated_at"]
    assert messages_before == messages_after
    assert after["session"]["turn_running"] is False


def test_derive_state_prefers_disconnected_without_runtime():
    settings = get_settings()
    evidence = agent_runtime.CherryEvidence(available=True)
    evidence.session = agent_runtime.SessionInfo("s", "n", "a", "agent", time.time() - 10_000)
    old = agent_status.Snapshot(
        agent_id="a",
        session_id="s",
        project="p",
        stage="",
        activity="",
        last_milestone="",
        next_action="",
        blockers=[],
        awaiting_input=False,
        state_override=None,
        progress=None,
        updated_at=time.time() - 100_000,
        source="agent",
        meta={},
    )
    state, notes = agent_status.derive_state(
        snapshot=old,
        evidence=evidence,
        queue=agent_status.QueueCounts(),
        interrupt=None,
        at=time.time(),
        settings=settings,
    )
    assert state == "disconnected"
    assert notes


def test_derive_state_unknown_without_any_evidence():
    settings = get_settings()
    evidence = agent_runtime.CherryEvidence(available=True)
    state, notes = agent_status.derive_state(
        snapshot=None,
        evidence=evidence,
        queue=agent_status.QueueCounts(),
        interrupt=None,
        at=time.time(),
        settings=settings,
    )
    assert state == "unknown"
    assert notes


@pytest.mark.parametrize(
    "state",
    ["idle", "working", "waiting_for_input", "waiting_for_messages", "completed", "interrupted", "failed", "disconnected", "unknown"],
)
def test_status_summary_is_one_to_three_sentences_for_every_state(state):
    from beacon.schemas import AgentSessionInfo, AgentStatusResponse

    status_value = AgentStatusResponse(
        state=state,
        state_label=state,
        project="Beacon",
        stage="Phase 3",
        activity="testing",
        last_milestone="Phase 2",
        next_action="Phase 4",
        data_age_seconds=120,
        session=AgentSessionInfo(last_activity_kind="Assistant replied"),
        notes=[],
    )
    summary, _ = status_summary.render_status_summary(status_value)
    assert summary
    sentences = [part for part in summary.replace("!", ".").split(".") if part.strip()]
    assert 1 <= len(sentences) <= 3, summary


def test_status_summary_handles_abbreviations_and_filenames():
    """Filenames and versions contain dots but must not create extra sentences."""
    import re

    from beacon.schemas import AgentSessionInfo, AgentStatusResponse

    status_value = AgentStatusResponse(
        state="working",
        state_label="Working",
        project="Beacon",
        stage="Phase 6",
        activity="see docs/SETUP.md section 5",
        last_milestone="v0.1.0 released",
        next_action="read docs/API.md",
        data_age_seconds=10,
        session=AgentSessionInfo(lastActivityKind="Assistant replied"),
    )
    summary, _ = status_summary.render_status_summary(status_value)
    terminators = re.findall(r"[.!?](?=\s|$)", summary)
    assert 1 <= len(terminators) <= 3, summary
