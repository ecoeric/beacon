"""SQLite storage for Beacon.

One database, WAL mode, explicit schema versioning. All writes go through `transaction()`
which retries on `database is locked` (the metrics sampler and request handlers share the
file). The Cherry Studio database is never opened here — see `services/agent_runtime.py`.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS token (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    scopes TEXT NOT NULL,
    token_sha256 TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    last_used_at REAL,
    revoked_at REAL
);

CREATE TABLE IF NOT EXISTS agent_status (
    agent_id TEXT PRIMARY KEY,
    session_id TEXT,
    project TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT '',
    activity TEXT NOT NULL DEFAULT '',
    last_milestone TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT '',
    blockers TEXT NOT NULL DEFAULT '[]',
    awaiting_input INTEGER NOT NULL DEFAULT 0,
    state_override TEXT,
    progress REAL,
    updated_at REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'agent',
    meta TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agent_message (
    id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    delivered_at REAL,
    acknowledged_at REAL,
    processed_at REAL,
    cancelled_at REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    ack_note TEXT,
    processed_note TEXT,
    idempotency_key TEXT UNIQUE,
    client TEXT,
    session_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_message_status ON agent_message(status, seq);

CREATE TABLE IF NOT EXISTS interrupt (
    id TEXT PRIMARY KEY,
    requested_at REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    session_id TEXT,
    pid INTEGER,
    signal TEXT,
    resolved_by TEXT,
    exit_observed_at REAL,
    error TEXT,
    evidence TEXT NOT NULL DEFAULT '[]',
    requested_by TEXT,
    acknowledged_at REAL
);

CREATE TABLE IF NOT EXISTS milestone (
    id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    changes TEXT NOT NULL DEFAULT '[]',
    phase TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    agent_id TEXT,
    session_id TEXT
);

CREATE TABLE IF NOT EXISTS screenshot (
    id TEXT PRIMARY KEY,
    milestone_id TEXT NOT NULL REFERENCES milestone(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL UNIQUE,
    caption TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'upload',
    content_type TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    deleted_at REAL
);

CREATE INDEX IF NOT EXISTS idx_screenshot_milestone ON screenshot(milestone_id, created_at);
CREATE INDEX IF NOT EXISTS idx_screenshot_expiry ON screenshot(expires_at);

CREATE TABLE IF NOT EXISTS notification (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    read_at REAL,
    dedupe_key TEXT UNIQUE,
    payload TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_notification_created ON notification(created_at DESC);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '{}',
    ip TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_at ON audit(at DESC);

CREATE TABLE IF NOT EXISTS service_state (
    key TEXT PRIMARY KEY,
    online INTEGER NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);
"""

_local = threading.local()
_write_lock = threading.RLock()


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> float:
    return time.time()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    # -- connections -------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def conn(self) -> sqlite3.Connection:
        """Thread-local read connection."""
        key = f"conn_{id(self)}"
        conn = getattr(_local, key, None)
        if conn is None:
            conn = self.connect()
            setattr(_local, key, conn)
        return conn

    # -- lifecycle ---------------------------------------------------------
    def initialise(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            conn = self.connect()
            try:
                conn.executescript(SCHEMA)
                row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO meta(key, value, updated_at) VALUES (?,?,?)",
                        ("schema_version", str(SCHEMA_VERSION), now()),
                    )
                elif int(row["value"]) != SCHEMA_VERSION:
                    raise RuntimeError(
                        f"unexpected schema version {row['value']} (expected {SCHEMA_VERSION})"
                    )
            finally:
                conn.close()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with _write_lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def execute(self, sql: str, params: tuple | dict = ()) -> None:
        with self.transaction() as conn:
            conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return list(self.conn().execute(sql, params))

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.conn().execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | dict = ()) -> object:
        row = self.query_one(sql, params)
        return None if row is None else row[0]

    # -- meta --------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.query_one("SELECT value FROM meta WHERE key=?", (key,))
        return default if row is None else row["value"]

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta(key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now()),
        )


_database: Database | None = None
_db_lock = threading.Lock()


def get_db(settings) -> Database:
    global _database
    with _db_lock:
        if _database is None or _database.path != settings.db_path:
            db = Database(settings.db_path)
            db.initialise()
            _database = db
        return _database


def reset_db_for_tests() -> None:
    global _database
    with _db_lock:
        _database = None
