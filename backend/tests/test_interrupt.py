"""Direct interrupt: runtime resolution, SIGINT delivery, evidence and guard rails."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from beacon.services import agent_runtime


def _clear_limiter() -> None:
    from beacon import deps

    deps._rate_limiter._hits.clear()


def _spawn_fake_runtime(tmp_path: Path, session_id: str) -> tuple[subprocess.Popen, Path, Path]:
    runtime_root = tmp_path / "fake-runtime"
    bin_mjs = runtime_root / "dsh-bridge" / "dist" / "runtime" / "bin.mjs"
    bin_mjs.parent.mkdir(parents=True, exist_ok=True)
    bin_mjs.write_text("# fake dsh runtime\n")
    compositions = tmp_path / "Agents" / ".dsh" / "compositions"
    compositions.mkdir(parents=True, exist_ok=True)
    composition = compositions / f"{session_id}.00000000-0000.yml"
    composition.write_text("id: fake\n")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)", str(bin_mjs), str(composition)]
    )
    return proc, bin_mjs, composition


def _wait_for_proc(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not Path(f"/proc/{pid}").exists():
            return True
        time.sleep(0.05)
    return not Path(f"/proc/{pid}").exists()


@pytest.fixture
def fake_session(env, monkeypatch, tmp_path, cherry):
    from beacon.config import reset_settings_for_tests

    monkeypatch.setenv("BEACON_SESSION_ID", cherry.session_id)
    monkeypatch.setenv("BEACON_CHERRY_AGENTS_DIR", str(tmp_path / "Agents"))
    reset_settings_for_tests()
    _clear_limiter()
    yield cherry.session_id


def test_signal_interrupt_kills_resolved_runtime(client, auth, fake_session, tmp_path):
    proc, bin_mjs, composition = _spawn_fake_runtime(tmp_path / "run1", fake_session)
    try:
        response = client.post(
            "/api/v1/agent/interrupt",
            json={"mode": "signal", "reason": "test stop"},
            headers=auth("admin", **{"X-Beacon-Confirm": "agent-interrupt"}),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "signalled"
        assert payload["pid"] == proc.pid
        assert payload["signal"] == "SIGINT"
        assert payload["exit_observed_at"] is not None
        assert any("SIGINT delivered" in item for item in payload["evidence"])
        proc.wait(timeout=5)
        assert proc.returncode is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_interrupt_without_runtime_returns_409(client, auth, fake_session):
    response = client.post(
        "/api/v1/agent/interrupt",
        json={"mode": "signal"},
        headers=auth("admin", **{"X-Beacon-Confirm": "agent-interrupt"}),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "no_runtime"
    history = client.get("/api/v1/agent/interrupts", headers=auth()).json()
    assert history[0]["status"] == "unavailable"
    assert history[0]["error"]
    assert history[0]["evidence"]


def test_interrupt_is_rate_limited(client, auth, fake_session):
    proc, _bin, _composition = _spawn_fake_runtime(Path("/tmp"), fake_session) if False else (None, None, None)
    first = client.post(
        "/api/v1/agent/interrupt",
        json={"mode": "checkpoint"},
        headers=auth("admin", **{"X-Beacon-Confirm": "agent-interrupt"}),
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/agent/interrupt",
        json={"mode": "checkpoint"},
        headers=auth("admin", **{"X-Beacon-Confirm": "agent-interrupt"}),
    )
    assert second.status_code == 429


def test_checkpoint_interrupt_is_delivered_to_the_agent(client, auth, fake_session):
    _clear_limiter()
    created = client.post(
        "/api/v1/agent/interrupt",
        json={"mode": "checkpoint", "reason": "please wrap up"},
        headers=auth("admin", **{"X-Beacon-Confirm": "agent-interrupt"}),
    )
    assert created.status_code == 200
    interrupt = created.json()
    assert interrupt["status"] == "requested"

    status_value = client.get("/api/v1/agent/status", headers=auth()).json()
    assert status_value["state"] == "interrupted"
    assert status_value["latest_interrupt"]["id"] == interrupt["id"]

    checkpoint = client.post("/api/v1/agent/checkpoint", headers=auth("agent")).json()
    assert [item["id"] for item in checkpoint["interrupts"]] == [interrupt["id"]]

    acked = client.post(
        f"/api/v1/agent/interrupts/{interrupt['id']}/ack",
        json={"note": "stopping after the current file"},
        headers=auth("agent"),
    )
    assert acked.status_code == 200
    assert acked.json()["status"] == "acknowledged"
    assert client.get("/api/v1/agent/interrupts/pending", headers=auth("agent")).json() == []


def test_interrupt_evidence_is_audited(client, auth, fake_session):
    _clear_limiter()
    proc, _bin, _composition = _spawn_fake_runtime(Path("/tmp") / f"run-{os.getpid()}-{time.time_ns()}", fake_session)
    try:
        client.post(
            "/api/v1/agent/interrupt",
            json={"mode": "signal"},
            headers=auth("admin", **{"X-Beacon-Confirm": "agent-interrupt"}),
        )
        trail = client.get("/api/v1/audit", headers=auth()).json()
        actions = [row["action"] for row in trail]
        assert "agent.interrupt.request" in actions
        assert "agent.interrupt.signal" in actions
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_interrupt_refuses_when_confirmation_wrong(client, auth, fake_session):
    response = client.post(
        "/api/v1/agent/interrupt",
        json={"mode": "signal"},
        headers=auth("admin", **{"X-Beacon-Confirm": "nope"}),
    )
    assert response.status_code == 428


def test_interrupt_mode_validation(client, auth, fake_session):
    response = client.post(
        "/api/v1/agent/interrupt",
        json={"mode": "shell"},
        headers=auth("admin", **{"X-Beacon-Confirm": "agent-interrupt"}),
    )
    assert response.status_code == 422


def test_interrupt_refuses_when_target_changes_before_signal(client, auth, fake_session, tmp_path, monkeypatch):
    proc, _bin, _composition = _spawn_fake_runtime(tmp_path / "run-change", fake_session)
    original = agent_runtime.resolve_runtime
    calls = {"count": 0}

    def flaky(settings, session_id):
        calls["count"] += 1
        return original(settings, session_id) if calls["count"] == 1 else None

    monkeypatch.setattr(agent_runtime, "resolve_runtime", flaky)
    try:
        response = client.post(
            "/api/v1/agent/interrupt",
            json={"mode": "signal"},
            headers=auth("admin", **{"X-Beacon-Confirm": "agent-interrupt"}),
        )
        assert response.status_code == 409
        assert response.json()["error"] == "target_changed"
        assert proc.poll() is None, "the process must not be signalled after re-verification fails"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
