"""Milestone metadata.

A milestone is an agent-reported development checkpoint: title, short summary, the concrete
changes, and up to four screenshots. Screenshot *bytes* live in ``services/screenshots.py``;
this module only joins metadata and keeps ordering (monotonic ``seq``).
"""

from __future__ import annotations

import json
import time

from ..db import Database, new_id, now
from ..schemas import MilestoneModel
from . import screenshots


def create(
    db: Database,
    *,
    title: str,
    summary: str = "",
    changes: list[str] | None = None,
    phase: str = "",
    agent_id: str | None = None,
    session_id: str | None = None,
) -> MilestoneModel:
    milestone_id = new_id()
    with db.transaction() as conn:
        seq = int(conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM milestone").fetchone()[0])
        conn.execute(
            "INSERT INTO milestone(id, seq, title, summary, changes, phase, created_at, agent_id, session_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                milestone_id,
                seq,
                title[:200],
                summary[:4000],
                json.dumps(changes or [], separators=(",", ":")),
                phase[:80],
                now(),
                agent_id,
                session_id,
            ),
        )
    return get(db, milestone_id)  # type: ignore[return-value]


def _to_model(db: Database, row) -> MilestoneModel:
    try:
        changes = json.loads(row["changes"] or "[]")
        if not isinstance(changes, list):
            changes = []
    except ValueError:
        changes = []
    metas, expired_count = screenshots.meta_for_milestone(db, row["id"])
    return MilestoneModel(
        id=row["id"],
        seq=row["seq"],
        title=row["title"],
        summary=row["summary"] or "",
        changes=[str(item) for item in changes],
        phase=row["phase"] or "",
        created_at=row["created_at"],
        screenshots=metas,
        expired_screenshots=expired_count,
    )


def get(db: Database, milestone_id: str) -> MilestoneModel | None:
    row = db.query_one("SELECT * FROM milestone WHERE id=?", (milestone_id,))
    return _to_model(db, row) if row else None


def list_milestones(db: Database, *, limit: int = 20, offset: int = 0) -> list[MilestoneModel]:
    rows = db.query(
        "SELECT * FROM milestone ORDER BY seq DESC LIMIT ? OFFSET ?", (limit, offset)
    )
    return [_to_model(db, row) for row in rows]


def latest(db: Database) -> MilestoneModel | None:
    row = db.query_one("SELECT * FROM milestone ORDER BY seq DESC LIMIT 1")
    return _to_model(db, row) if row else None


def count(db: Database) -> int:
    return int(db.scalar("SELECT COUNT(*) FROM milestone") or 0)


def attached_screenshots(db: Database, milestone_id: str) -> int:
    return int(
        db.scalar(
            "SELECT COUNT(*) FROM screenshot WHERE milestone_id=? AND deleted_at IS NULL",
            (milestone_id,),
        )
        or 0
    )


def model_as_marker(milestone: MilestoneModel) -> dict:
    return {
        "id": milestone.id,
        "title": milestone.title,
        "seq": milestone.seq,
        "created_at": milestone.created_at,
        "screenshots": len(milestone.screenshots),
        "at": time.time(),
    }
