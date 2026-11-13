"""Agent status, message queue, Continue and Interrupt endpoints."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from ..config import get_settings
from ..deps import (
    ActionDep,
    AdminDep,
    RuntimeDep,
    DbDep,
    ReadDep,
    client_ip,
    require_confirmation,
    throttle,
)
from ..schemas import (
    AckRequest,
    AgentChatMessage,
    AgentSessionSummary,
    AgentStatusResponse,
    AgentStatusUpdate,
    CheckpointResponse,
    ContinueRequest,
    InterruptInfo,
    InterruptRequest,
    MessageCreate,
    MessageModel,
    StatusSummaryResponse,
)
from ..security import audit
from ..services import agent_runtime
from ..services import agent_status as agent_status_service
from ..services import interrupts, message_queue, notifications, status_summary
from ..db import now as time_now

router = APIRouter(prefix="/agent", tags=["agent"])

CONTINUE_DEFAULT = "Continue your work from the current checkpoint."


def _interrupt_model(record: interrupts.InterruptRecord) -> InterruptInfo:
    return InterruptInfo(
        id=record.id,
        requested_at=record.requested_at,
        mode=record.mode,
        status=record.status,
        session_id=record.session_id,
        reason=record.reason,
        pid=record.pid,
        signal=record.signal,
        resolved_by=record.resolved_by,
        exit_observed_at=record.exit_observed_at,
        error=record.error,
        evidence=record.evidence,
    )


@router.get("/status", response_model=AgentStatusResponse, summary="Structured agent status (read-only)")
def get_status(db: DbDep, token: ReadDep) -> AgentStatusResponse:
    return agent_status_service.build_agent_status(get_settings(), db)


@router.get(
    "/status/summary",
    response_model=StatusSummaryResponse,
    summary="One-to-three sentence status, composed without invoking the agent",
)
def get_status_summary(db: DbDep, token: ReadDep) -> StatusSummaryResponse:
    status_value = agent_status_service.build_agent_status(get_settings(), db)
    summary, timestamps = status_summary.render_status_summary(status_value)
    return StatusSummaryResponse(
        summary=summary,
        state=status_value.state,
        generated_at=time.time(),
        data_age_seconds=status_value.data_age_seconds,
        is_stale=status_value.is_stale,
        based_on=[item.source for item in status_value.evidence if item.source != "interrupt"]
        + (["interrupt"] if status_value.latest_interrupt else []),
        deterministic=True,
    )


@router.get(
    "/sessions",
    response_model=list[AgentSessionSummary],
    summary="Read-only list of Cherry Studio agent sessions",
)
def list_sessions(
    token: ReadDep,
    limit: int = Query(20, ge=1, le=50),
) -> list[AgentSessionSummary]:
    settings = get_settings()
    return [
        AgentSessionSummary(
            id=item.id,
            name=item.name,
            agent_id=item.agent_id,
            agent_name=item.agent_name,
            last_activity_at=item.last_activity_at,
        )
        for item in agent_runtime.list_sessions(settings, limit=limit)
    ]


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[AgentChatMessage],
    summary="Read-only transcript for a Cherry Studio agent session",
)
def session_messages(
    session_id: str,
    token: ReadDep,
    limit: int = Query(100, ge=1, le=200),
) -> list[AgentChatMessage]:
    settings = get_settings()
    sessions = agent_runtime.list_sessions(settings, limit=50)
    if session_id not in {item.id for item in sessions}:
        raise HTTPException(status_code=404, detail="session not found")
    messages = [
        AgentChatMessage(
            id=item.id,
            role=item.role,
            text=(item.text or item.preview).strip(),
            status=item.status,
            created_at=item.created_at,
            model=item.model,
        )
        for item in agent_runtime.session_messages(
            settings, session_id, limit=limit, oldest_first=True
        )
    ]
    return [message for message in messages if message.text and not message.text.startswith('{"parts"')]


@router.put("/status", response_model=AgentStatusResponse, summary="Agent: publish a status snapshot")
def put_status(payload: AgentStatusUpdate, db: DbDep, token: RuntimeDep) -> AgentStatusResponse:
    settings = get_settings()
    current = agent_status_service.load_snapshot(db)
    agent_id = (
        current.agent_id if current else (settings.agent_id or db.get_meta("agent_id") or "agent")
    )
    session_id = (
        payload.session_id
        or (current.session_id if current else None)
        or settings.session_id
        or interrupts.resolve_session(settings, db)
    )
    project = payload.project if payload.project is not None else (current.project if current else "")
    stage = payload.stage if payload.stage is not None else (current.stage if current else "")
    activity = payload.activity if payload.activity is not None else (current.activity if current else "")
    last_milestone = (
        payload.last_milestone if payload.last_milestone is not None else (current.last_milestone if current else "")
    )
    next_action = (
        payload.next_action if payload.next_action is not None else (current.next_action if current else "")
    )
    blockers = payload.blockers if payload.blockers is not None else (current.blockers if current else [])
    awaiting = int(payload.awaiting_input) if payload.awaiting_input is not None else int(
        current.awaiting_input if current else False
    )
    override = payload.state_override if payload.state_override is not None else (
        current.state_override if current else None
    )
    progress = payload.progress if payload.progress is not None else (current.progress if current else None)

    import json

    db.execute(
        """
        INSERT INTO agent_status(agent_id, session_id, project, stage, activity, last_milestone,
                                 next_action, blockers, awaiting_input, state_override, progress,
                                 updated_at, source, meta)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(agent_id) DO UPDATE SET
            session_id=excluded.session_id,
            project=excluded.project,
            stage=excluded.stage,
            activity=excluded.activity,
            last_milestone=excluded.last_milestone,
            next_action=excluded.next_action,
            blockers=excluded.blockers,
            awaiting_input=excluded.awaiting_input,
            state_override=excluded.state_override,
            progress=excluded.progress,
            updated_at=excluded.updated_at,
            source=excluded.source,
            meta=excluded.meta
        """,
        (
            agent_id,
            session_id,
            project[:200],
            stage[:200],
            activity[:1000],
            last_milestone[:300],
            next_action[:300],
            json.dumps(blockers[:20], separators=(",", ":")),
            awaiting,
            override,
            progress,
            time_now(),
            token.name,
            json.dumps({"session_id": session_id}, separators=(",", ":")),
        ),
    )
    if awaiting:
        notifications.notify(
            db,
            kind="agent_waiting_for_input",
            severity="warning",
            title="Agent is waiting for your input",
            body=activity[:300],
            dedupe_key=f"agent-input:{int(time_now() // 600)}",
            payload={"project": project, "stage": stage},
        )
    if override == "completed":
        notifications.notify(
            db,
            kind="agent_completed",
            severity="success",
            title="Agent reports the task is complete",
            body=(last_milestone or activity)[:300],
            dedupe_key=f"agent-completed:{int(time_now() // 600)}",
            payload={"project": project},
        )
    audit(db, actor=token.name, action="agent.status.update", target=agent_id, detail={"state": override})
    return agent_status_service.build_agent_status(settings, db)


@router.get("/messages", response_model=list[MessageModel], summary="Recent queued/delivered messages")
def list_messages(
    db: DbDep,
    token: ReadDep,
    limit: int = Query(default=25, ge=1, le=100),
) -> list[MessageModel]:
    return message_queue.list_messages(db, limit=limit)


@router.post(
    "/messages",
    response_model=MessageModel,
    status_code=status.HTTP_201_CREATED,
    summary="Queue a suggestion/instruction for the agent",
)
def create_message(
    payload: MessageCreate, request: Request, db: DbDep, token: ActionDep
) -> MessageModel:
    throttle(f"{token.id}:queue", limit=20, window_seconds=60)
    settings = get_settings()
    session = interrupts.resolve_session(settings, db)
    message, created = message_queue.enqueue(
        db,
        text=payload.text,
        kind=payload.kind,
        idempotency_key=payload.idempotency_key,
        client=token.name,
        session_id=session,
    )
    if created:
        audit(
            db,
            actor=token.name,
            action="agent.message.queue",
            target=message.id,
            detail={"kind": message.kind, "chars": len(message.body)},
            ip=client_ip(request),
        )
    return message


@router.post("/continue", response_model=MessageModel, status_code=status.HTTP_201_CREATED, summary="Tell the agent to continue")
def continue_agent(payload: ContinueRequest, request: Request, db: DbDep, token: ActionDep) -> MessageModel:
    throttle(f"{token.id}:continue", limit=10, window_seconds=60)
    settings = get_settings()
    note = (payload.note or "").strip()
    body = f"{CONTINUE_DEFAULT}\n\n{note}" if note else CONTINUE_DEFAULT
    message, created = message_queue.enqueue(
        db,
        text=body,
        kind="continue",
        client=token.name,
        session_id=interrupts.resolve_session(settings, db),
    )
    if created:
        audit(
            db,
            actor=token.name,
            action="agent.continue",
            target=message.id,
            detail={"with_note": bool(note)},
            ip=client_ip(request),
        )
    return message


@router.delete("/messages/{message_id}", response_model=MessageModel, summary="Cancel a pending message")
def cancel_message(message_id: str, db: DbDep, token: ActionDep, request: Request) -> MessageModel:
    message = message_queue.cancel(db, message_id)
    audit(
        db,
        actor=token.name,
        action="agent.message.cancel",
        target=message_id,
        ip=client_ip(request),
    )
    return message


@router.get("/queue", summary="Queue statistics")
def queue_stats(db: DbDep, token: ReadDep) -> dict:
    stats = message_queue.stats(db)
    stats["checkpoint_age_seconds"] = _checkpoint_age(db)
    return stats


def _checkpoint_age(db) -> float | None:
    value = db.get_meta("agent_checkpoint_at")
    if not value:
        return None
    try:
        return max(0.0, time.time() - float(value))
    except ValueError:
        return None


@router.post(
    "/interrupt",
    response_model=InterruptInfo,
    summary="Interrupt the active execution (bypasses the message queue)",
)
def interrupt_agent(
    payload: InterruptRequest,
    request: Request,
    db: DbDep,
    token: AdminDep,
    confirmation: Annotated[str | None, Header(alias="X-Beacon-Confirm")] = None,
) -> InterruptInfo:
    require_confirmation(confirmation, "agent-interrupt", "interrupting the agent")
    throttle(f"{token.id}:interrupt", limit=1, window_seconds=15)
    record = interrupts.request_interrupt(
        get_settings(),
        db,
        mode=payload.mode,
        reason=payload.reason,
        actor=token.name,
        ip=client_ip(request),
        requested_session=payload.session_id,
    )
    notifications.notify(
        db,
        kind="agent_interrupted",
        severity="warning",
        title="Agent interrupted",
        body=(payload.reason or f"{payload.mode} interrupt requested")[:300],
        dedupe_key=f"interrupt:{record.id}",
        payload={"interrupt_id": record.id, "mode": record.mode, "pid": record.pid},
    )
    audit(
        db,
        actor=token.name,
        action="agent.interrupt.request",
        target=record.id,
        detail={"mode": record.mode, "status": record.status, "pid": record.pid},
        ip=client_ip(request),
    )
    return _interrupt_model(record)


@router.get("/interrupts", response_model=list[InterruptInfo], summary="Interrupt history")
def list_interrupts(db: DbDep, token: ReadDep, limit: int = Query(default=10, ge=1, le=50)) -> list[InterruptInfo]:
    return [_interrupt_model(record) for record in interrupts.list_interrupts(db, limit=limit)]


@router.post("/checkpoint", response_model=CheckpointResponse, summary="Agent: collect queued work at a safe point")
def checkpoint(db: DbDep, token: RuntimeDep) -> CheckpointResponse:
    settings = get_settings()
    session = interrupts.resolve_session(settings, db)
    messages = message_queue.checkpoint(db, settings=settings, session_id=session)
    pending = interrupts.pending_interrupts(db)
    db.set_meta("agent_checkpoint_at", str(time.time()))
    if messages:
        audit(
            db,
            actor=token.name,
            action="agent.checkpoint.deliver",
            target=",".join(message.id for message in messages),
            detail={"count": len(messages), "session_id": session},
        )
    for message in messages:
        notifications.notify(
            db,
            kind="agent_message_delivered",
            severity="info",
            title="Instruction delivered to the agent",
            body=message.body[:200],
            dedupe_key=f"delivered:{message.id}",
            payload={"message_id": message.id, "seq": message.seq},
        )
    return CheckpointResponse(
        server_time=time.time(),
        delivered=messages,
        interrupts=[_interrupt_model(record) for record in pending],
        session_id=session,
        pending_remaining=message_queue.pending_count(db),
    )


@router.post("/messages/{message_id}/ack", response_model=MessageModel, summary="Agent: acknowledge a delivered message")
def ack_message(message_id: str, payload: AckRequest, db: DbDep, token: RuntimeDep) -> MessageModel:
    message = message_queue.acknowledge(db, message_id, note=payload.note)
    audit(db, actor=token.name, action="agent.message.ack", target=message_id)
    return message


@router.post(
    "/messages/{message_id}/nack",
    response_model=MessageModel,
    summary="Agent: return a delivered message to the queue",
)
def nack_message(message_id: str, payload: AckRequest, db: DbDep, token: RuntimeDep) -> MessageModel:
    message = message_queue.nack(db, message_id, note=payload.note)
    audit(db, actor=token.name, action="agent.message.nack", target=message_id)
    return message


@router.post("/messages/{message_id}/processed", response_model=MessageModel, summary="Agent: mark a message processed")
def processed_message(message_id: str, payload: AckRequest, db: DbDep, token: RuntimeDep) -> MessageModel:
    message = message_queue.mark_processed(db, message_id, note=payload.note)
    audit(db, actor=token.name, action="agent.message.processed", target=message_id)
    return message


@router.get("/interrupts/pending", response_model=list[InterruptInfo], summary="Agent: pending checkpoint interrupts")
def pending_interrupts(db: DbDep, token: RuntimeDep) -> list[InterruptInfo]:
    return [_interrupt_model(record) for record in interrupts.pending_interrupts(db)]


@router.post("/interrupts/{interrupt_id}/ack", response_model=InterruptInfo, summary="Agent: acknowledge an interrupt")
def ack_interrupt(interrupt_id: str, payload: AckRequest, db: DbDep, token: RuntimeDep) -> InterruptInfo:
    record = interrupts.acknowledge(db, interrupt_id, actor=token.name, note=payload.note or "")
    return _interrupt_model(record)
