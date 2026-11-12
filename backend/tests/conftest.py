"""Test fixtures.

Every test runs against a throwaway data directory, a synthetic Cherry Studio SQLite database
with the same schema the service reads, and a Pi-hole/Minecraft endpoint that is guaranteed to
be unreachable. Nothing here touches the real agent runtime, the real Pi-hole, or the real
Minecraft server.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

_BOOTSTRAP = tempfile.mkdtemp(prefix="beacon-bootstrap-")
os.environ.setdefault("BEACON_DATA_DIR", _BOOTSTRAP)
os.environ.setdefault("BEACON_CHERRY_DB", str(Path(_BOOTSTRAP) / "cherrystudio.sqlite"))
os.environ.setdefault("BEACON_CHERRY_AGENTS_DIR", str(Path(_BOOTSTRAP) / "Agents"))
os.environ.setdefault("BEACON_PIHOLE_URL", "http://127.0.0.1:9")
os.environ.setdefault("BEACON_MINECRAFT_DIR", str(Path(_BOOTSTRAP) / "minecraft"))
os.environ.setdefault("BEACON_MINECRAFT_HOST", "127.0.0.1")
os.environ.setdefault("BEACON_MINECRAFT_PORT", "1")
os.environ.setdefault("BEACON_DOCKER_SNAPSHOT_FILE", str(Path(_BOOTSTRAP) / "no-docker-snapshot.json"))
os.environ.setdefault("BEACON_SESSION_ID", "")
os.environ.setdefault("BEACON_AGENT_ID", "agent-test")

CHERRY_SCHEMA = """
CREATE TABLE agent (
    id TEXT PRIMARY KEY, type TEXT, name TEXT, description TEXT DEFAULT '', instructions TEXT,
    model TEXT, plan_model TEXT, small_model TEXT, disabled_tools TEXT DEFAULT '[]',
    configuration TEXT DEFAULT '{}', order_key TEXT, created_at INTEGER, updated_at INTEGER,
    deleted_at INTEGER
);
CREATE TABLE agent_session (
    id TEXT PRIMARY KEY, agent_id TEXT, name TEXT, is_name_manually_edited INTEGER DEFAULT 0,
    description TEXT DEFAULT '', workspace_id TEXT, task_schedule_id TEXT, trace_id TEXT,
    order_key TEXT, last_activity_at INTEGER, created_at INTEGER, updated_at INTEGER
);
CREATE TABLE agent_session_message (
    id TEXT PRIMARY KEY, session_id TEXT, role TEXT, data TEXT, searchable_text TEXT DEFAULT '',
    status TEXT, model_id TEXT, message_snapshot TEXT, stats TEXT, runtime_resume_token TEXT,
    delivery TEXT, delivery_status TEXT, delivery_turn_ref TEXT, delivery_in_reply_to TEXT,
    delivery_sender_session_id TEXT, fts_rowid INTEGER, created_at INTEGER, updated_at INTEGER
);
"""


class CherryFactory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.executescript(CHERRY_SCHEMA)
        self.conn.execute(
            "INSERT INTO agent(id, type, name, model, order_key, created_at, updated_at) "
            "VALUES ('agent-test','dsh','Test Agent','deepseek::deepseek-flash','a',1,1)"
        )
        self.session_id = "session-test-0001"
        self.conn.execute(
            "INSERT INTO agent_session(id, agent_id, name, workspace_id, order_key, last_activity_at, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                self.session_id,
                "agent-test",
                "Beacon dashboard build",
                "workspace",
                "a",
                int(time.time() * 1000),
                1,
                1,
            ),
        )
        self._counter = 0

    def message(self, role: str, status: str = "success", text: str = "hi", model: str | None = None) -> str:
        self._counter += 1
        message_id = f"msg-{self._counter:04d}"
        now_ms = int(time.time() * 1000)
        self.conn.execute(
            "INSERT INTO agent_session_message(id, session_id, role, data, searchable_text, status, "
            "model_id, message_snapshot, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                message_id,
                self.session_id,
                role,
                json.dumps({"parts": [{"type": "text", "text": text}]}),
                text,
                status,
                model,
                json.dumps({"model": {"name": model or "Test Model"}}),
                now_ms,
                now_ms,
            ),
        )
        return message_id

    def touch(self, session_id: str | None = None) -> None:
        self.conn.execute(
            "UPDATE agent_session SET last_activity_at=? WHERE id=?",
            (int(time.time() * 1000), session_id or self.session_id),
        )

    def close(self) -> None:
        self.conn.close()


@pytest.fixture
def cherry(tmp_path) -> CherryFactory:
    factory = CherryFactory(tmp_path / "cherrystudio.sqlite")
    factory.message("user", "success", "build the dashboard")
    factory.message("assistant", "success", "phase 1 done")
    yield factory
    factory.close()


@pytest.fixture
def env(tmp_path, monkeypatch, cherry):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BEACON_DATA_DIR", str(data))
    monkeypatch.setenv("BEACON_CHERRY_DB", str(cherry.path))
    monkeypatch.setenv("BEACON_CHERRY_AGENTS_DIR", str(tmp_path / "Agents"))
    monkeypatch.setenv("BEACON_PIHOLE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("BEACON_PIHOLE_PASSWORD_FILE", str(data / "secrets" / "pihole.password"))
    monkeypatch.setenv("BEACON_MINECRAFT_DIR", str(tmp_path / "minecraft"))
    monkeypatch.setenv("BEACON_MINECRAFT_HOST", "127.0.0.1")
    monkeypatch.setenv("BEACON_MINECRAFT_PORT", "1")
    monkeypatch.setenv("BEACON_DOCKER_SNAPSHOT_FILE", str(tmp_path / "docker-snapshot.json"))
    monkeypatch.setenv("BEACON_AGENT_ID", "agent-test")
    monkeypatch.setenv("BEACON_SESSION_ID", "")
    monkeypatch.setenv("BEACON_TLS_CERT", str(data / "tls" / "server.crt"))
    monkeypatch.setenv("BEACON_TLS_KEY", str(data / "tls" / "server.key"))
    monkeypatch.setenv("BEACON_STALE_WORKING_SECONDS", "90")
    monkeypatch.setenv("BEACON_MAX_REQUEST_BYTES", str(2 * 1024 * 1024))

    from beacon.config import get_settings, reset_settings_for_tests
    from beacon.db import reset_db_for_tests

    reset_settings_for_tests()
    reset_db_for_tests()
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    yield settings
    reset_settings_for_tests()
    reset_db_for_tests()


@pytest.fixture
def tokens(env) -> dict[str, str]:
    from beacon.db import get_db
    from beacon.security import create_token

    db = get_db(env)
    raw = {}
    raw["admin"], _ = create_token(db, env.secrets_dir, "ios", "read,action,admin")
    raw["agent"], _ = create_token(db, env.secrets_dir, "agent", "agent,read")
    raw["read"], _ = create_token(db, env.secrets_dir, "viewer", "read")
    return raw


@pytest.fixture
def client(env, tokens):
    from fastapi.testclient import TestClient

    from beacon.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def auth(tokens):
    def headers(role: str = "admin", **extra: str) -> dict[str, str]:
        value = {"Authorization": f"Bearer {tokens[role]}"}
        value.update(extra)
        return value

    return headers
