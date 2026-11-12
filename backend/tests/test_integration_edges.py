"""Docker parsing, agent-runtime edge cases and backup integrity."""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from beacon.db import get_db, get_db as get_database  # noqa: F401 - explicit import for clarity
from beacon.services import agent_runtime, docker_monitor, milestones, screenshots

def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (80, 60), (10, 40, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _snapshot_path(tmp_path, *, age: float = 0.0, containers: list[dict] | None = None):
    path = tmp_path / "docker.json"
    payload = {
        "fetched_at": time.time() - age,
        "containers": containers
        if containers is not None
        else [
            {
                "name": "pihole",
                "image": "pihole/pihole:2026.10.1",
                "state": "running",
                "status": "Up 5 days (healthy)",
                "health": "healthy",
                "cpu_percent": 0.39,
                "memory_bytes": 38_895_616,
                "memory_limit_bytes": 16_619_683_840,
                "started_at": None,
                "error": None,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_snapshot_reads_fresh_file(env, tmp_path):
    settings = replace(env, docker_snapshot_file=_snapshot_path(tmp_path))
    docker_monitor.reset_cache()
    snapshot = docker_monitor.snapshot(settings, cache_seconds=0)
    assert snapshot.available is True
    assert [container.name for container in snapshot.containers] == ["pihole"]
    container = snapshot.containers[0]
    assert container.health == "healthy"
    assert container.cpu_percent == pytest.approx(0.39)
    assert container.memory_bytes == 38_895_616
    assert docker_monitor.find_container(snapshot, "pihole") is container
    docker_monitor.reset_cache()


def test_snapshot_reports_missing_file(env, tmp_path):
    settings = replace(env, docker_snapshot_file=tmp_path / "absent.json")
    docker_monitor.reset_cache()
    snapshot = docker_monitor.snapshot(settings, cache_seconds=0)
    assert snapshot.available is False
    assert "not available" in (snapshot.error or "").lower()
    assert snapshot.containers == []
    docker_monitor.reset_cache()


def test_snapshot_reports_staleness(env, tmp_path):
    settings = replace(env, docker_snapshot_file=_snapshot_path(tmp_path, age=300))
    docker_monitor.reset_cache()
    snapshot = docker_monitor.snapshot(settings, cache_seconds=0)
    assert snapshot.available is False
    assert "stale" in (snapshot.error or "").lower()
    docker_monitor.reset_cache()


def test_snapshot_reports_malformed_file(env, tmp_path):
    path = tmp_path / "docker.json"
    path.write_text("not json", encoding="utf-8")
    settings = replace(env, docker_snapshot_file=path)
    docker_monitor.reset_cache()
    snapshot = docker_monitor.snapshot(settings, cache_seconds=0)
    assert snapshot.available is False
    assert "unreadable" in (snapshot.error or "").lower()
    docker_monitor.reset_cache()


def test_snapshot_is_cached(tmp_path, env):
    settings = replace(env, docker_snapshot_file=_snapshot_path(tmp_path))
    docker_monitor.reset_cache()
    first = docker_monitor.snapshot(settings)
    second = docker_monitor.snapshot(settings)
    assert first is second
    docker_monitor.reset_cache()


# --------------------------------------------------------------------- agent runtime
def test_missing_cherry_database_is_reported(env, tmp_path):
    settings = replace(env, cherry_db=tmp_path / "absent.sqlite")
    evidence = agent_runtime.collect(settings, selected_session_id=None)
    assert evidence.available is False
    assert "not found" in (evidence.error or "").lower()


def test_corrupt_cherry_database_does_not_crash(env, tmp_path):
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_text("this is not a database", encoding="utf-8")
    settings = replace(env, cherry_db=corrupt)
    assert agent_runtime.list_sessions(settings) == []
    evidence = agent_runtime.collect(settings, selected_session_id=None)
    assert evidence.available is False
    assert evidence.error


def test_sessions_are_filtered_by_configured_agent(env, cherry):
    # A newer session for a different agent must not win.
    cherry.conn.execute(
        "INSERT INTO agent(id, type, name, order_key, created_at, updated_at) "
        "VALUES ('other-agent','dsh','Other','b',1,1)"
    )
    cherry.conn.execute(
        "INSERT INTO agent_session(id, agent_id, name, workspace_id, order_key, last_activity_at, created_at, updated_at) "
        "VALUES ('other-session','other-agent','Newer work','w','b',?,1,1)",
        (int(__import__("time").time() * 1000) + 60_000,),
    )
    sessions = agent_runtime.list_sessions(env)
    assert [session.id for session in sessions] == [cherry.session_id]
    assert all(session.agent_id == "agent-test" for session in sessions)
    all_sessions = agent_runtime.list_sessions(env, all_agents=True)
    assert {session.id for session in all_sessions} == {cherry.session_id, "other-session"}


def test_transcript_mtime_and_runtime_resolution(env, tmp_path):
    transcript = (
        tmp_path
        / "Agents"
        / ".dsh"
        / "sessions"
        / "--some-slug--"
        / "session-test-0001"
        / "session.jsonl.zstd"
    )
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_bytes(b"\x00")
    os.utime(transcript, (1_700_000_000, 1_700_000_000))
    settings = replace(env, cherry_agents_dir=tmp_path / "Agents")
    assert agent_runtime.transcript_updated_at(settings, "session-test-0001") == pytest.approx(
        1_700_000_000, abs=1
    )
    assert agent_runtime.transcript_updated_at(settings, "unknown-session") is None
    assert agent_runtime.resolve_runtime(settings, "unknown-session") is None


# ----------------------------------------------------------------------------- backup
def test_backup_copies_database_secrets_and_screenshots(env, tokens, tmp_path):
    from beacon import cli

    db = get_db(env)
    milestone = milestones.create(db, title="backup check", summary="round trip")
    screenshots.store(
        env,
        db,
        milestone_id=milestone.id,
        content=_png(),
        caption="backup image",
        source="test",
    )
    target = tmp_path / "backup"
    assert cli.main(["backup", "--to", str(target)]) == 0

    database = target / "beacon.sqlite"
    assert database.exists()
    with sqlite3.connect(database) as copy:
        rows = copy.execute("SELECT title FROM milestone").fetchall()
    assert rows == [("backup check",)]
    assert (target / "secrets" / "ios.token").exists()
    files = list((target / "screenshots").rglob("*.png"))
    assert len(files) == 1
    assert files[0].read_bytes() == _png()


def test_backup_without_optional_directories(env, tmp_path):
    from beacon import cli

    target = tmp_path / "empty-backup"
    # No screenshots or TLS material yet: the backup must still succeed.
    assert cli.main(["backup", "--to", str(target)]) == 0
    assert (target / "beacon.sqlite").exists()


def test_backup_can_be_restored_and_served(env, tokens, tmp_path, monkeypatch):
    """Restore the backup into a fresh data directory and serve the API from it."""
    import shutil

    from fastapi.testclient import TestClient

    from beacon import cli
    from beacon.config import reset_settings_for_tests
    from beacon.db import reset_db_for_tests
    from beacon.main import create_app

    db = get_db(env)
    milestone = milestones.create(db, title="backup check", summary="restore round trip")
    screenshots.store(
        env, db, milestone_id=milestone.id, content=_png(), caption="restored image", source="test"
    )
    backup = tmp_path / "backup"
    assert cli.main(["backup", "--to", str(backup)]) == 0

    restored = tmp_path / "restored"
    restored.mkdir()
    for name in ("secrets", "screenshots"):
        if (backup / name).exists():
            shutil.copytree(backup / name, restored / name)
    shutil.copyfile(backup / "beacon.sqlite", restored / "beacon.sqlite")

    monkeypatch.setenv("BEACON_DATA_DIR", str(restored))
    monkeypatch.setenv("BEACON_TLS_CERT", str(restored / "tls" / "server.crt"))
    monkeypatch.setenv("BEACON_TLS_KEY", str(restored / "tls" / "server.key"))
    reset_settings_for_tests()
    reset_db_for_tests()

    token = (restored / "secrets" / "ios.token").read_text(encoding="utf-8").strip()
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        rows = client.get("/api/v1/milestones", headers=headers).json()
        assert [row["title"] for row in rows] == ["backup check"]
        image = client.get(rows[0]["screenshots"][0]["url"], headers=headers)
        assert image.status_code == 200
        assert image.content == _png()
    reset_settings_for_tests()
    reset_db_for_tests()


def test_screenshot_store_enforces_total_quota(env):
    from dataclasses import replace

    from beacon.db import get_db
    from beacon.services import screenshots

    small = replace(env, screenshot_max_total_bytes=100)
    db = get_db(env)
    with pytest.raises(screenshots.ScreenshotError) as excinfo:
        screenshots.store(
            small,
            db,
            milestone_id="m",
            content=_png(),
            caption="quota",
        )
    assert excinfo.value.code == "quota_exceeded"
