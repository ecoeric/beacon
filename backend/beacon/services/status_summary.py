"""Deterministic Status text.

Requirement: pressing **Status** returns a concise one-to-three-sentence explanation derived
from the existing structured status snapshot. It must not start an inference, add a message to
the conversation, or consume context.

``render_status_summary`` is a pure function over an :class:`AgentStatusResponse`: no I/O, no
time source other than the payload timestamps, no HTTP client in this module. A test asserts
that it is deterministic and that 1 <= sentences <= 3 for every state.
"""

from __future__ import annotations

import re

from ..schemas import AgentStatusResponse

_MAX_SENTENCES = 3


def _clean(text: str) -> str:
    text = " ".join(text.split())
    return text.rstrip(" .;:")


def _human_age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown time"
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    if seconds < 172800:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _project_phrase(status: AgentStatusResponse) -> str:
    if not status.project:
        return "an unspecified project"
    if status.stage:
        return f"{status.project} ({status.stage})"
    return status.project


def _work_phrase(status: AgentStatusResponse) -> str:
    if status.activity:
        return _clean(status.activity)
    if status.session.last_activity_kind:
        return _clean(status.session.last_activity_kind).lower()
    return ""


def _closing_sentence(status: AgentStatusResponse) -> str:
    parts: list[str] = []
    if status.last_milestone:
        parts.append(f"Last completed: {_clean(status.last_milestone)}.")
    if status.next_action:
        parts.append(f"Next: {_clean(status.next_action)}.")
    if parts:
        return " ".join(parts)
    if status.queue.pending:
        return f"{status.queue.pending} queued instruction(s) are waiting for the next checkpoint."
    return ""


def render_status_summary(status: AgentStatusResponse) -> tuple[str, list[float]]:
    """Return ``(summary, timestamps_used)`` for the current status payload."""
    project = _project_phrase(status)
    work = _work_phrase(status)
    state = status.state
    sentences: list[str] = []

    if state == "working":
        detail = f" on {work}" if work else ""
        sentences.append(f"The agent is working on {project}{detail}.")
    elif state == "idle":
        sentences.append(f"The agent is idle on {project}, with its runtime connected and no turn in flight.")
    elif state == "waiting_for_messages":
        detail = f" ({work})" if work else ""
        sentences.append(
            f"The agent is working on {project}{detail} and has "
            f"{status.queue.pending} queued message(s) waiting for its next safe checkpoint."
        )
    elif state == "waiting_for_input":
        detail: list[str] = []
        if status.last_milestone and not status.last_milestone.endswith("."):
            detail.append(f"after completing {_clean(status.last_milestone)}")
        reason = f" ({_clean(status.activity)})" if status.activity else ""
        detail_text = f" {' '.join(detail)}" if detail else ""
        sentences.append(f"The agent is waiting for your input on {project}{detail_text}{reason}.")
        if status.blockers:
            sentences.append("Blockers: " + "; ".join(_clean(b) for b in status.blockers[:3]) + ".")
    elif state == "completed":
        sentences.append(f"The agent reports that its work on {project} is complete.")
    elif state == "interrupted":
        interrupt = status.latest_interrupt
        when = _human_age(status.data_age_seconds)
        if interrupt is not None:
            sentences.append(
                f"The agent's last execution was interrupted ({interrupt.mode} interrupt, "
                f"requested {when} ago) and it has not reported a fresh status yet."
            )
        else:
            sentences.append(
                f"The agent's execution was interrupted and no fresh status snapshot is available."
            )
    elif state == "failed":
        sentences.append(f"The agent's last turn on {project} failed.")
        if status.notes:
            sentences.append(_clean(status.notes[0]).capitalize() + ".")
    elif state == "disconnected":
        age = _human_age(status.data_age_seconds)
        sentences.append(
            f"The agent is disconnected: no live session runtime is serving {project}, "
            f"and the last structured status is {age} old."
        )
    else:
        sentences.append(
            f"The agent's state cannot be verified right now for {project}; "
            "the dashboard will keep showing the last known values as stale."
        )

    if state in {"working", "idle", "waiting_for_messages", "completed"}:
        closing = _closing_sentence(status)
        if closing:
            sentences.append(closing)

    # Normalise to individual sentences and enforce the 1–3 sentence contract. Freshness is
    # reported separately in the payload (data_age_seconds / is_stale) instead of as an extra
    # sentence, so the summary can never exceed three sentences.
    flat: list[str] = []
    for chunk in sentences:
        flat.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+", chunk.strip()) if part.strip())
    flat = flat[: _MAX_SENTENCES]
    sentences = flat if flat else sentences[:1]

    summary = " ".join(s.strip() for s in sentences if s.strip())
    summary = re.sub(r"\s+", " ", summary).strip()
    stamps = [ts for ts in (status.updated_at, status.session.last_activity_at) if ts is not None]
    return summary, stamps
