"""Read-only evidence from the Cherry Studio agent runtime.

Nothing in this module writes to Cherry Studio. The SQLite database is opened with
``mode=ro`` (WAL-aware, so no ``immutable=1``) and the runtime process is discovered from
``/proc`` — the composition YAML file name contains the session id, which is the mapping
between the desktop app's runtime child process and a session.

Every function degrades to ``available=False`` with an error string instead of raising, so a
dashboard request never fails because the agent app is closed.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings


@dataclass
class RuntimeProcess:
    pid: int
    argv: list[str]
    uid: int
    started_at: float | None = None


@dataclass
class SessionInfo:
    id: str
    name: str
    agent_id: str | None
    agent_name: str | None
    last_activity_at: float | None


@dataclass
class SessionMessage:
    id: str
    role: str
    status: str
    created_at: float
    updated_at: float
    model: str | None = None
    preview: str = ""


@dataclass
class CherryEvidence:
    available: bool = False
    error: str | None = None
    session: SessionInfo | None = None
    messages: list[SessionMessage] = field(default_factory=list)
    runtime: RuntimeProcess | None = None
    transcript_updated_at: float | None = None

    @property
    def turn_running(self) -> bool:
        return any(m.role == "assistant" and m.status == "pending" for m in self.messages)

    @property
    def last_message_at(self) -> float | None:
        if not self.messages:
            return None
        return max(m.updated_at for m in self.messages)

    @property
    def last_activity_kind(self) -> str | None:
        if not self.messages:
            return None
        latest = max(self.messages, key=lambda m: m.updated_at)
        if latest.role == "user":
            return "Instruction received"
        if latest.status == "pending":
            return "Assistant turn running"
        if latest.status == "error":
            return "Assistant turn failed"
        return "Assistant replied"

    @property
    def last_activity_at(self) -> float | None:
        values = [v for v in (self.last_message_at, self.transcript_updated_at) if v]
        if self.session and self.session.last_activity_at:
            values.append(self.session.last_activity_at)
        return max(values) if values else None


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _ms_to_seconds(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number / 1000.0 if number > 10_000_000_000 else number


def list_sessions(
    settings: Settings, *, limit: int = 12, all_agents: bool = False
) -> list[SessionInfo]:
    """Sessions ordered by last activity.

    When ``BEACON_AGENT_ID`` is configured only that agent's sessions are returned, so the
    dashboard can never bind itself to a different agent that happens to be newer.
    """
    if not settings.cherry_db.exists():
        return []
    try:
        conn = _connect_readonly(settings.cherry_db)
    except sqlite3.Error:
        return []
    sql = """
        SELECT s.id, s.name, s.agent_id, a.name AS agent_name, s.last_activity_at
        FROM agent_session s
        LEFT JOIN agent a ON a.id = s.agent_id
        WHERE s.agent_id IS NOT NULL
        ORDER BY s.last_activity_at DESC
        LIMIT ?
    """
    params: tuple = (limit,)
    if settings.agent_id and not all_agents:
        sql = sql.replace("ORDER BY", "AND s.agent_id = ? ORDER BY")
        params = (settings.agent_id, limit)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    sessions = []
    for row in rows:
        sessions.append(
            SessionInfo(
                id=row["id"],
                name=row["name"] or "",
                agent_id=row["agent_id"],
                agent_name=row["agent_name"],
                last_activity_at=_ms_to_seconds(row["last_activity_at"]),
            )
        )
    return sessions


def _message_preview(data: str | None, searchable: str | None) -> str:
    text = searchable or ""
    if not text and data:
        text = data
    text = " ".join(text.split())
    return text[:180]


def session_messages(
    settings: Settings, session_id: str, *, limit: int = 12
) -> list[SessionMessage]:
    if not settings.cherry_db.exists():
        return []
    try:
        conn = _connect_readonly(settings.cherry_db)
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            """
            SELECT id, role, status, created_at, updated_at, message_snapshot,
                   searchable_text
            FROM agent_session_message
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    out: list[SessionMessage] = []
    for row in rows:
        model = None
        snapshot = row["message_snapshot"]
        if snapshot:
            import json

            try:
                model = (json.loads(snapshot) or {}).get("model", {}).get("name")
            except (ValueError, AttributeError):
                model = None
        out.append(
            SessionMessage(
                id=row["id"],
                role=row["role"],
                status=row["status"],
                created_at=_ms_to_seconds(row["created_at"]) or 0.0,
                updated_at=_ms_to_seconds(row["updated_at"]) or 0.0,
                model=model,
                preview=_message_preview(None, row["searchable_text"]),
            )
        )
    return out


def _read_proc_cmdline(pid: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def _read_proc_uid(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("Uid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def resolve_runtime(settings: Settings, session_id: str) -> RuntimeProcess | None:
    """Find the DSH runtime child process serving ``session_id``.

    Matches the decoded cmdline for the composition file
    ``.dsh/compositions/<session-id>.<composition>.yml``. Only processes owned by the
    current uid are considered.
    """
    if not session_id:
        return None
    own_uid = os.getuid()
    marker = f"compositions/{session_id}."
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        argv = _read_proc_cmdline(pid)
        if not argv:
            continue
        if not any("dsh-bridge" in part and part.endswith("bin.mjs") for part in argv):
            continue
        if not any(marker in part for part in argv):
            continue
        uid = _read_proc_uid(pid)
        if uid is not None and uid != own_uid:
            continue
        return RuntimeProcess(pid=pid, argv=argv, uid=uid if uid is not None else own_uid)
    return None


def transcript_updated_at(settings: Settings, session_id: str) -> float | None:
    base = settings.cherry_agents_dir / ".dsh" / "sessions"
    if not base.exists():
        return None
    try:
        for slug in base.iterdir():
            candidate = slug / session_id / "session.jsonl.zstd"
            if candidate.exists():
                return candidate.stat().st_mtime
    except OSError:
        return None
    return None


def collect(settings: Settings, *, selected_session_id: str | None, message_limit: int = 12) -> CherryEvidence:
    evidence = CherryEvidence()
    sessions = list_sessions(settings)
    if not sessions and not settings.cherry_db.exists():
        evidence.error = f"Cherry Studio database not found at {settings.cherry_db}"
        return evidence
    if not sessions:
        evidence.error = "No agent sessions found in Cherry Studio"
        return evidence

    session = None
    if selected_session_id:
        session = next((s for s in sessions if s.id == selected_session_id), None)
    if session is None and settings.agent_id:
        session = next((s for s in sessions if s.agent_id == settings.agent_id), None)
    if session is None:
        session = sessions[0]

    evidence.session = session
    evidence.available = True
    evidence.messages = session_messages(settings, session.id, limit=message_limit)
    evidence.runtime = resolve_runtime(settings, session.id)
    evidence.transcript_updated_at = transcript_updated_at(settings, session.id)
    return evidence


def process_start_time(pid: int) -> float | None:
    """Wall-clock start time of a pid (for uptime display)."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        fields = raw[raw.rindex(")") + 2 :].split()
        start_ticks = float(fields[19])
        clk = os.sysconf("SC_CLK_TCK")
        btime = None
        for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
            if line.startswith("btime "):
                btime = float(line.split()[1])
                break
        if btime is None:
            return None
        return btime + start_ticks / clk
    except (OSError, ValueError, IndexError):
        return None


def session_is_live(settings: Settings, session_id: str | None) -> bool:
    if not session_id:
        return False
    return resolve_runtime(settings, session_id) is not None


def now_seconds() -> float:
    return time.time()
