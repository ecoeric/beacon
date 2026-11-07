"""Health, dashboard summary, identity, activity feed and diagnostics."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query

from .. import __version__
from ..config import get_settings
from ..deps import AdminDep, DbDep, ReadDep, TokenDep
from ..schemas import ActivityFeed, DashboardSummary, HealthResponse, WhoAmI
from ..services import docker_monitor, minecraft, notifications, pihole, summary, system_metrics

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Unauthenticated liveness probe")
def health() -> HealthResponse:
    settings = get_settings()
    database = "ok"
    try:
        from ..db import get_db

        get_db(settings).scalar("SELECT 1")
    except Exception as exc:  # pragma: no cover - only on a broken data directory
        database = f"error: {exc}"
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        version=__version__,
        time=time.time(),
        database=database,
        tls=settings.tls_cert.exists(),
    )


@router.get("/whoami", response_model=WhoAmI, summary="Token identity and scopes")
def whoami(token: TokenDep) -> WhoAmI:
    return WhoAmI(token_id=token.id, name=token.name, scopes=sorted(token.scopes))


@router.get("/summary", response_model=DashboardSummary, summary="Everything the home screen needs")
async def dashboard_summary(db: DbDep, token: ReadDep) -> DashboardSummary:
    return await summary.build_summary(get_settings(), db)


@router.get("/activity", response_model=ActivityFeed, summary="In-app activity feed")
def activity(db: DbDep, token: ReadDep, limit: int = Query(default=30, ge=1, le=100)) -> ActivityFeed:
    return notifications.feed(db, limit=limit)


@router.post("/activity/{notification_id}/read", summary="Mark one activity item read")
def mark_activity_read(notification_id: str, db: DbDep, token: ReadDep) -> dict:
    ok = notifications.mark_read(db, notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "activity item not found"})
    return {"read": True}


@router.post("/activity/read-all", summary="Mark all activity read")
def mark_all_activity_read(db: DbDep, token: ReadDep) -> dict:
    return {"read": notifications.mark_all_read(db)}


@router.get("/capabilities", summary="What this deployment can actually read and control")
async def capabilities(db: DbDep, token: ReadDep) -> dict:
    settings = get_settings()
    docker = docker_monitor.snapshot(settings)
    server = system_metrics.overview(settings)
    minecraft_status = await minecraft.status(settings)
    pihole_status = await pihole.get_client(settings).status(
        docker_monitor.find_container(docker, "pihole") if docker.available else None
    )
    return {
        "agent": {
            "binding_mode": "cherry-studio dsh runtime",
            "configured_agent_id": settings.agent_id or None,
            "runtime_resolvable": bool(
                __import__("os").environ.get("BEACON_AGENT_ID") or settings.agent_id
            ),
            "status_source": "agent snapshot + Cherry Studio SQLite (read-only) + /proc",
        },
        "message_delivery": {"mode": "checkpoint", "max_message_chars": 4000},
        "interrupt": {"modes": ["signal", "checkpoint"], "signal": "SIGINT"},
        "screenshots": {
            "retention_days": settings.screenshot_retention_days,
            "sources": ["text", "api", "window", "file"],
            "max_per_milestone": 4,
        },
        "monitoring": {
            "docker": docker.available,
            "docker_error": docker.error,
            "gpu": server.gpu.available,
            "gpu_error": server.gpu.error,
            "cpu_temperature": server.cpu.temperature_c is not None,
            "minecraft_tick_metrics": minecraft_status.tps is not None,
            "minecraft_control_actions": minecraft_status.controls.actions,
            "pihole": pihole_status.available,
        },
        "notifications": {"in_app": True, "push": False, "push_note": "APNs is an extension point, not implemented"},
    }


@router.get("/audit", summary="Recent audit trail (admin)")
def audit_trail(db: DbDep, token: AdminDep, limit: int = Query(default=40, ge=1, le=200)) -> list[dict]:
    rows = db.query("SELECT * FROM audit ORDER BY at DESC LIMIT ?", (limit,))
    return [dict(row) for row in rows]
