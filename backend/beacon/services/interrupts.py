"""Direct, out-of-band interrupt of the active agent execution.

Two modes
---------
``signal`` (default)
    Resolve the DSH runtime child process that serves the bound session and send ``SIGINT``.
    ``bin.mjs`` in the runtime installs a SIGINT handler that disposes the fiber tree and
    exits, so the turn stops immediately while the on-disk session journal keeps the work.
    The signal goes straight to the process — it never enters the message queue and it is not
    a chat message.

``checkpoint``
    Record an interrupt request that is handed to the agent at its next safe checkpoint
    (returned by the checkpoint endpoint). Used when no runtime process is resolvable.

Every attempt is stored in the ``interrupt`` table with pid, signal, exit observation and
evidence, and is written to the audit log by the router.
"""

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import dataclass

from ..config import Settings
from pathlib import Path

from ..db import Database, new_id, now
from ..security import audit
from . import agent_runtime, procs


class InterruptError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class InterruptRecord:
    id: str
    requested_at: float
    reason: str
    mode: str
    status: str
    session_id: str | None
    pid: int | None
    signal: str | None
    resolved_by: str | None
    exit_observed_at: float | None
    error: str | None
    evidence: list[str]
    requested_by: str | None
    acknowledged_at: float | None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "requested_at": self.requested_at,
            "reason": self.reason,
            "mode": self.mode,
            "status": self.status,
            "session_id": self.session_id,
            "pid": self.pid,
            "signal": self.signal,
            "resolved_by": self.resolved_by,
            "exit_observed_at": self.exit_observed_at,
            "error": self.error,
            "evidence": self.evidence,
            "requested_by": self.requested_by,
            "acknowledged_at": self.acknowledged_at,
        }


def _to_record(row) -> InterruptRecord:
    try:
        evidence = json.loads(row["evidence"] or "[]")
        if not isinstance(evidence, list):
            evidence = []
    except ValueError:
        evidence = []
    return InterruptRecord(
        id=row["id"],
        requested_at=row["requested_at"],
        reason=row["reason"] or "",
        mode=row["mode"],
        status=row["status"],
        session_id=row["session_id"],
        pid=row["pid"],
        signal=row["signal"],
        resolved_by=row["resolved_by"],
        exit_observed_at=row["exit_observed_at"],
        error=row["error"],
        evidence=[str(item) for item in evidence],
        requested_by=row["requested_by"],
        acknowledged_at=row["acknowledged_at"],
    )


def _fetch(db: Database, interrupt_id: str) -> InterruptRecord:
    row = db.query_one("SELECT * FROM interrupt WHERE id=?", (interrupt_id,))
    if row is None:
        raise InterruptError("not_found", "interrupt not found", status_code=404)
    return _to_record(row)


def latest_interrupt(db: Database):
    return db.query_one("SELECT * FROM interrupt ORDER BY requested_at DESC LIMIT 1")


def latest_interrupt_record(db: Database) -> InterruptRecord | None:
    row = latest_interrupt(db)
    return _to_record(row) if row else None


def list_interrupts(db: Database, *, limit: int = 10) -> list[InterruptRecord]:
    rows = db.query("SELECT * FROM interrupt ORDER BY requested_at DESC LIMIT ?", (limit,))
    return [_to_record(row) for row in rows]


def pending_interrupts(db: Database) -> list[InterruptRecord]:
    rows = db.query(
        "SELECT * FROM interrupt WHERE status='requested' AND mode='checkpoint' "
        "ORDER BY requested_at"
    )
    return [_to_record(row) for row in rows]


def trusted_sessions(settings: Settings) -> list[str]:
    """Session ids that exist in the read-only Cherry Studio database, newest first.

    The agent-pushed status snapshot is deliberately **not** used as a source: the agent could
    otherwise point a privileged interrupt at a different session.
    """
    return [session.id for session in agent_runtime.list_sessions(settings, limit=25)]


def resolve_session(
    settings: Settings, db: Database, *, requested: str | None = None
) -> str | None:
    if requested:
        return requested if requested in trusted_sessions(settings) else None
    if settings.session_id:
        return settings.session_id
    sessions = trusted_sessions(settings)
    return sessions[0] if sessions else None


def request_interrupt(
    settings: Settings,
    db: Database,
    *,
    mode: str = "signal",
    reason: str = "",
    actor: str = "admin",
    ip: str | None = None,
    settle_seconds: float = 5.0,
    requested_session: str | None = None,
) -> InterruptRecord:
    if mode not in {"signal", "checkpoint"}:
        raise InterruptError("invalid_mode", "mode must be 'signal' or 'checkpoint'", status_code=422)

    if requested_session and requested_session not in trusted_sessions(settings):
        raise InterruptError(
            "unknown_session",
            "The requested session does not exist in the agent's read-only session list",
        )
    session_id = resolve_session(settings, db, requested=requested_session)
    interrupt_id = new_id()
    db.execute(
        "INSERT INTO interrupt(id, requested_at, reason, mode, status, session_id, requested_by) "
        "VALUES (?,?,?,?,?,?,?)",
        (interrupt_id, now(), reason[:500], mode, "requested", session_id, actor),
    )

    if mode == "checkpoint":
        record = _fetch(db, interrupt_id)
        audit(
            db,
            actor=actor,
            action="agent.interrupt.checkpoint",
            target=interrupt_id,
            detail={"reason": reason, "session_id": session_id},
            ip=ip,
        )
        return record

    if not session_id:
        _finish(
            db,
            interrupt_id,
            status="unavailable",
            error="No active agent session could be resolved",
            evidence=["no session id in config, status snapshot, or Cherry Studio database"],
        )
        raise InterruptError(
            "no_session",
            "No active agent session to interrupt",
        )

    runtime = agent_runtime.resolve_runtime(settings, session_id)
    if runtime is None:
        _finish(
            db,
            interrupt_id,
            status="unavailable",
            error="No DSH runtime process found for the bound session",
            evidence=[
                f"session {session_id} has no matching .dsh/compositions process under /proc",
                "use mode=checkpoint for cooperative interruption",
            ],
        )
        raise InterruptError(
            "no_runtime",
            "The agent runtime process is not running for this session, so there is nothing to signal",
        )

    argv = " ".join(runtime.argv)
    if runtime.uid != os.getuid():
        _finish(
            db,
            interrupt_id,
            status="refused",
            error=f"runtime process owned by uid {runtime.uid}, not by the API user",
            evidence=[f"pid {runtime.pid}", argv[:300]],
        )
        raise InterruptError("foreign_process", "Refusing to signal a process owned by another user", status_code=403)

    if runtime.pid in (0, 1) or runtime.pid == os.getpid():
        _finish(
            db,
            interrupt_id,
            status="refused",
            error="resolved pid is not a valid target",
            evidence=[f"pid {runtime.pid}"],
        )
        raise InterruptError("invalid_target", "Refusing to signal this pid", status_code=400)

    # Re-resolve right before signalling so a recycled pid cannot be hit by mistake.
    current = agent_runtime.resolve_runtime(settings, session_id)
    if current is None or current.pid != runtime.pid:
        _finish(
            db,
            interrupt_id,
            status="refused",
            error="the runtime process changed or disappeared before the signal was sent",
            evidence=[f"pid {runtime.pid}", "target re-verification failed"],
        )
        raise InterruptError(
            "target_changed",
            "The agent runtime changed between resolution and signalling; nothing was sent",
        )

    evidence = [f"pid {runtime.pid}", f"uid {runtime.uid}", f"cmdline {argv[:240]}"]
    try:
        mechanism = procs.send_signal(runtime.pid, signal.SIGINT)
    except ProcessLookupError:
        _finish(
            db,
            interrupt_id,
            status="failed",
            error="runtime process disappeared before the signal was sent",
            evidence=evidence,
        )
        raise InterruptError("gone", "The runtime process exited before the signal was sent")
    except PermissionError:
        _finish(
            db,
            interrupt_id,
            status="refused",
            error="permission denied sending SIGINT",
            evidence=evidence,
        )
        raise InterruptError("permission_denied", "Permission denied sending SIGINT", status_code=403)

    evidence.append(f"SIGINT delivered via {mechanism}")
    exit_observed = _wait_for_exit(runtime.pid, settle_seconds)
    if exit_observed:
        evidence.append(f"runtime process exited within {settle_seconds:.0f}s")
    else:
        evidence.append(
            f"runtime process still alive {settle_seconds:.0f}s after SIGINT (turn may still be unwinding)"
        )

    _finish(
        db,
        interrupt_id,
        status="signalled",
        pid=runtime.pid,
        signal="SIGINT",
        resolved_by=f"sysinfo:/proc/{runtime.pid}",
        exit_observed_at=now() if exit_observed else None,
        evidence=evidence,
    )
    record = _fetch(db, interrupt_id)
    audit(
        db,
        actor=actor,
        action="agent.interrupt.signal",
        target=interrupt_id,
        detail={
            "pid": runtime.pid,
            "signal": "SIGINT",
            "session_id": session_id,
            "exit_observed": exit_observed,
            "reason": reason,
        },
        ip=ip,
    )
    return record


def process_alive(pid: int) -> bool:
    """True when the pid exists and is not a zombie.

    A freshly signalled runtime can stay visible in /proc as ``Z`` until its parent reaps it;
    that process no longer executes anything, so it must count as exited.
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        state = stat[stat.rindex(")") + 2]
    except ValueError:
        return False
    return state not in {"Z", "X"}


def _wait_for_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(0.05)
    return not process_alive(pid)


def _finish(
    db: Database,
    interrupt_id: str,
    *,
    status: str,
    pid: int | None = None,
    signal_name: str | None = None,
    resolved_by: str | None = None,
    exit_observed_at: float | None = None,
    error: str | None = None,
    evidence: list[str] | None = None,
    signal: str | None = None,
) -> None:
    signal_value = signal_name if signal_name is not None else signal
    db.execute(
        """
        UPDATE interrupt
           SET status=?, pid=?, signal=?, resolved_by=?, exit_observed_at=?, error=?, evidence=?
         WHERE id=?
        """,
        (
            status,
            pid,
            signal_value,
            resolved_by,
            exit_observed_at,
            error,
            json.dumps(evidence or [], separators=(",", ":")),
            interrupt_id,
        ),
    )


def acknowledge(db: Database, interrupt_id: str, *, actor: str = "agent", note: str = "") -> InterruptRecord:
    record = _fetch(db, interrupt_id)
    if record.status not in {"requested", "signalled"}:
        raise InterruptError(
            "invalid_transition", f"cannot acknowledge interrupt in state '{record.status}'"
        )
    evidence = list(record.evidence)
    if note:
        evidence.append(f"agent note: {note[:300]}")
    db.execute(
        "UPDATE interrupt SET status='acknowledged', acknowledged_at=?, evidence=? WHERE id=?",
        (now(), json.dumps(evidence, separators=(",", ":")), interrupt_id),
    )
    audit(
        db,
        actor=actor,
        action="agent.interrupt.acknowledge",
        target=interrupt_id,
        detail={"note": note[:300]},
    )
    return _fetch(db, interrupt_id)
