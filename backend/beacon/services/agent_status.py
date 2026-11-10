"""Derived agent state and the read-only status payload.

The state machine is documented in docs/ARCHITECTURE.md §6. Only evidence that was actually
collected is used; whenever the evidence is insufficient the state is ``unknown`` and the
payload says why. Nothing here calls an LLM, opens a socket to the agent, or mutates the
agent's conversation.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from ..config import Settings
from ..db import Database
from ..schemas import (
    AgentSessionInfo,
    AgentStatusResponse,
    EvidenceItem,
    InterruptInfo,
    QueueCounts,
)
from . import agent_runtime, message_queue
from .interrupts import latest_interrupt

STATE_LABELS = {
    "idle": "Idle",
    "working": "Working",
    "waiting_for_input": "Waiting for input",
    "waiting_for_messages": "Queued messages waiting",
    "completed": "Completed",
    "interrupted": "Interrupted",
    "failed": "Failed",
    "disconnected": "Disconnected",
    "unknown": "Unknown",
}


@dataclass
class Snapshot:
    agent_id: str
    session_id: str | None
    project: str
    stage: str
    activity: str
    last_milestone: str
    next_action: str
    blockers: list[str]
    awaiting_input: bool
    state_override: str | None
    progress: float | None
    updated_at: float
    source: str
    meta: dict


def load_snapshot(db: Database, agent_id: str | None = None) -> Snapshot | None:
    row = None
    if agent_id:
        row = db.query_one("SELECT * FROM agent_status WHERE agent_id=?", (agent_id,))
    if row is None:
        row = db.query_one("SELECT * FROM agent_status ORDER BY updated_at DESC LIMIT 1")
    if row is None:
        return None
    try:
        blockers = json.loads(row["blockers"] or "[]")
        if not isinstance(blockers, list):
            blockers = []
    except ValueError:
        blockers = []
    try:
        meta = json.loads(row["meta"] or "{}")
        if not isinstance(meta, dict):
            meta = {}
    except ValueError:
        meta = {}
    return Snapshot(
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        project=row["project"] or "",
        stage=row["stage"] or "",
        activity=row["activity"] or "",
        last_milestone=row["last_milestone"] or "",
        next_action=row["next_action"] or "",
        blockers=[str(item) for item in blockers],
        awaiting_input=bool(row["awaiting_input"]),
        state_override=row["state_override"],
        progress=row["progress"],
        updated_at=float(row["updated_at"]),
        source=row["source"] or "agent",
        meta=meta,
    )


def _age_seconds(timestamp: float | None, *, at: float) -> float | None:
    if timestamp is None:
        return None
    return max(0.0, at - timestamp)


def derive_state(
    *,
    snapshot: Snapshot | None,
    evidence: agent_runtime.CherryEvidence,
    queue: QueueCounts,
    interrupt: InterruptInfo | None,
    at: float,
    settings: Settings,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    snapshot_age = _age_seconds(snapshot.updated_at if snapshot else None, at=at)
    live_runtime = evidence.runtime is not None
    last_activity_age = _age_seconds(evidence.last_activity_at, at=at)

    if not evidence.available:
        notes.append(evidence.error or "Agent runtime state unavailable")
        return ("disconnected" if snapshot_age is None or snapshot_age > settings.stale_disconnect_seconds else "unknown"), notes

    if snapshot_age is not None and snapshot_age > settings.stale_disconnect_seconds and not live_runtime:
        notes.append(
            f"Status snapshot is {int(snapshot_age)}s old and no runtime process is serving the session"
        )
        return "disconnected", notes

    if interrupt is not None and interrupt.status in {"signalled", "requested"}:
        newer_snapshot = snapshot is not None and snapshot.updated_at > interrupt.requested_at
        if not newer_snapshot or snapshot is not None and snapshot.state_override == "failed":
            notes.append(f"Last interrupt ({interrupt.mode}) has not been acknowledged by the agent yet")
            return "interrupted", notes

    failed_recently = False
    for message in evidence.messages:
        if message.role == "assistant" and message.status == "error":
            age = _age_seconds(message.updated_at, at=at) or 0.0
            failed_recently = age < 600
            break
    if failed_recently or (snapshot is not None and snapshot.state_override == "failed"):
        notes.append("Last assistant turn ended in an error state")
        return "failed", notes

    if evidence.turn_running:
        if not live_runtime:
            notes.append("A turn is marked pending but its runtime process is not visible")
        return "working", notes
    if live_runtime and last_activity_age is not None and last_activity_age < settings.stale_working_seconds:
        return "working", notes

    if queue.pending > 0:
        notes.append(f"{queue.pending} message(s) queued for the next checkpoint")
        return "waiting_for_messages", notes

    if snapshot is not None and snapshot.awaiting_input:
        notes.append("Agent reported that it is waiting for input")
        return "waiting_for_input", notes

    if snapshot is not None and snapshot.state_override == "completed":
        return "completed", notes

    if snapshot is not None and snapshot.state_override == "failed":
        return "failed", notes

    if live_runtime:
        if last_activity_age is not None and last_activity_age > 900:
            notes.append("Runtime is running but the session has been quiet for a while")
        return "idle", notes

    if snapshot is not None and snapshot_age is not None:
        if snapshot_age > 900:
            notes.append("No live runtime; status snapshot is the only evidence")
        return "idle", notes

    notes.append("No status snapshot and no live runtime")
    return "unknown", notes


def _interrupt_model(row) -> InterruptInfo:
    try:
        evidence = json.loads(row["evidence"] or "[]")
        if not isinstance(evidence, list):
            evidence = []
    except ValueError:
        evidence = []
    return InterruptInfo(
        id=row["id"],
        requested_at=row["requested_at"],
        mode=row["mode"],
        status=row["status"],
        reason=row["reason"] or "",
        pid=row["pid"],
        signal=row["signal"],
        resolved_by=row["resolved_by"],
        exit_observed_at=row["exit_observed_at"],
        error=row["error"],
        evidence=[str(item) for item in evidence],
    )


def _queue_counts(db: Database, *, at: float) -> QueueCounts:
    rows = db.query("SELECT status, COUNT(*) AS n FROM agent_message GROUP BY status")
    counts = {row["status"]: int(row["n"]) for row in rows}
    processed = db.scalar(
        "SELECT COUNT(*) FROM agent_message WHERE status='processed' AND processed_at > ?",
        (at - 86400,),
    )
    return QueueCounts(
        pending=counts.get("pending", 0),
        delivered=counts.get("delivered", 0),
        acknowledged=counts.get("acknowledged", 0),
        processed_last_24h=int(processed or 0),
    )


def build_agent_status(settings: Settings, db: Database, *, at: float | None = None) -> AgentStatusResponse:
    at = at or time.time()
    snapshot = load_snapshot(db)
    selected_session = None
    if settings.session_id:
        selected_session = settings.session_id
    elif snapshot is not None and snapshot.session_id:
        selected_session = snapshot.session_id

    evidence = agent_runtime.collect(settings, selected_session_id=selected_session)
    session_id = evidence.session.id if evidence.session else selected_session
    queue = _queue_counts(db, at=at)
    interrupt_row = latest_interrupt(db)
    interrupt = _interrupt_model(interrupt_row) if interrupt_row else None
    state, notes = derive_state(
        snapshot=snapshot,
        evidence=evidence,
        queue=queue,
        interrupt=interrupt,
        at=at,
        settings=settings,
    )

    data_age = _age_seconds(snapshot.updated_at if snapshot else None, at=at)
    evidence_items: list[EvidenceItem] = []
    if snapshot is not None:
        evidence_items.append(
            EvidenceItem(
                source="agent_snapshot",
                detail=f"Pushed by {snapshot.source} at {snapshot.updated_at:.0f}",
                age_seconds=_age_seconds(snapshot.updated_at, at=at),
            )
        )
    if evidence.session is not None:
        evidence_items.append(
            EvidenceItem(
                source="cherry_session",
                detail=f"{evidence.session.agent_name or 'agent'} · {evidence.session.name[:80]}",
                age_seconds=_age_seconds(evidence.last_activity_at, at=at),
            )
        )
    evidence_items.append(
        EvidenceItem(
            source="runtime_process",
            detail=(
                f"pid {evidence.runtime.pid} serving this session"
                if evidence.runtime
                else (evidence.error or "no runtime process found")
            ),
            age_seconds=None,
        )
    )
    evidence_items.append(
        EvidenceItem(
            source="message_queue",
            detail=f"{queue.pending} pending · {queue.delivered} delivered · {queue.acknowledged} acknowledged",
            age_seconds=None,
        )
    )
    if interrupt is not None:
        evidence_items.append(
            EvidenceItem(
                source="interrupt",
                detail=f"{interrupt.mode} interrupt {interrupt.status} at {interrupt.requested_at:.0f}"
                + (f" ({interrupt.error})" if interrupt.error else ""),
                age_seconds=_age_seconds(interrupt.requested_at, at=at),
            )
        )

    session_info = AgentSessionInfo(
        id=session_id,
        name=evidence.session.name if evidence.session else None,
        agent_id=evidence.session.agent_id if evidence.session else None,
        agent_name=evidence.session.agent_name if evidence.session else None,
        runtime_pid=evidence.runtime.pid if evidence.runtime else None,
        runtime_alive=evidence.runtime is not None,
        last_activity_at=evidence.last_activity_at,
        last_activity_kind=evidence.last_activity_kind,
        turn_running=evidence.turn_running,
        transcript_updated_at=evidence.transcript_updated_at,
    )

    return AgentStatusResponse(
        state=state,  # type: ignore[arg-type]
        state_label=STATE_LABELS[state],
        project=snapshot.project if snapshot else "",
        stage=snapshot.stage if snapshot else "",
        activity=snapshot.activity if snapshot else "",
        last_milestone=snapshot.last_milestone if snapshot else "",
        next_action=snapshot.next_action if snapshot else "",
        blockers=snapshot.blockers if snapshot else [],
        awaiting_input=bool(snapshot.awaiting_input) if snapshot else False,
        progress=snapshot.progress if snapshot else None,
        updated_at=snapshot.updated_at if snapshot else None,
        data_age_seconds=data_age,
        is_stale=state in {"unknown", "disconnected"},
        stale_after_seconds=settings.stale_working_seconds,
        snapshot_source=snapshot.source if snapshot else "none",
        session=session_info,
        queue=queue,
        latest_interrupt=interrupt,
        evidence=evidence_items,
        notes=notes,
    )


__all__ = [
    "STATE_LABELS",
    "Snapshot",
    "build_agent_status",
    "derive_state",
    "load_snapshot",
]
