"""Server, Pi-hole and Minecraft monitoring and guarded controls."""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import AdminDep, DbDep, ReadDep, client_ip, throttle
from ..schemas import (
    DockerContainerInfo,
    MinecraftStatus,
    PiholeStatus,
    ServerOverview,
)
from ..security import audit
from ..services import docker_monitor, minecraft, notifications, pihole, system_metrics

router = APIRouter(tags=["monitoring"])


class BlockingUpdate(BaseModel):
    enabled: bool


class MinecraftControlRequest(BaseModel):
    action: Literal["start", "stop", "restart"]
    force: bool = Field(default=False, description="required when players are online")


def _server_overview() -> ServerOverview:
    settings = get_settings()
    server = system_metrics.overview(settings)
    docker = docker_monitor.snapshot(settings)
    server.docker = docker.containers
    server.docker_available = docker.available
    server.docker_error = docker.error
    return server


@router.get("/server/overview", response_model=ServerOverview, summary="Host metrics")
async def server_overview(db: DbDep, token: ReadDep) -> ServerOverview:
    return await asyncio.to_thread(_server_overview)


@router.get("/docker/containers", response_model=list[DockerContainerInfo], summary="Docker containers (read-only)")
async def docker_containers(token: ReadDep) -> list[DockerContainerInfo]:
    settings = get_settings()
    snapshot = await asyncio.to_thread(docker_monitor.snapshot, settings)
    if not snapshot.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "docker_unavailable", "message": snapshot.error or "docker not readable"},
        )
    return snapshot.containers


@router.get("/pihole/status", response_model=PiholeStatus, summary="Pi-hole status and statistics")
async def pihole_status(token: ReadDep) -> PiholeStatus:
    settings = get_settings()
    snapshot = await asyncio.to_thread(docker_monitor.snapshot, settings)
    container = docker_monitor.find_container(snapshot, "pihole") if snapshot.available else None
    return await pihole.get_client(settings).status(container)


@router.post("/pihole/blocking", summary="Enable or disable Pi-hole blocking")
async def set_pihole_blocking(
    payload: BlockingUpdate,
    request: Request,
    db: DbDep,
    token: AdminDep,
    confirmation: Annotated[str | None, Header(alias="X-Beacon-Confirm")] = None,
) -> dict:
    from ..deps import require_confirmation

    require_confirmation(confirmation, "pihole-blocking", "changing Pi-hole blocking")
    throttle(f"{token.name}:pihole-blocking", limit=5, window_seconds=60)
    settings = get_settings()
    result = await pihole.get_client(settings).set_blocking(payload.enabled)
    audit(
        db,
        actor=token.name,
        action="pihole.blocking",
        target="blocking",
        detail={"enabled": payload.enabled, "result": result},
        ip=client_ip(request),
    )
    notifications.notify(
        db,
        kind="pihole_blocking",
        severity="info",
        title=f"Pi-hole blocking {'enabled' if payload.enabled else 'disabled'}",
        body="Changed from the Beacon dashboard.",
        dedupe_key=f"pihole-blocking:{'on' if payload.enabled else 'off'}:{int(__import__('time').time() // 60)}",
    )
    return result


@router.get("/minecraft/status", response_model=MinecraftStatus, summary="Minecraft server status")
async def minecraft_status(db: DbDep, token: ReadDep) -> MinecraftStatus:
    settings = get_settings()
    result = await minecraft.status(settings)
    notifications.transition(
        db,
        key="minecraft",
        online=result.state == "running",
        detail={"state": result.state},
        offline_notification=(
            "minecraft_offline",
            "Minecraft server went offline",
            "The server no longer answers on its port.",
        ),
        online_notification=(
            "minecraft_online",
            "Minecraft server is online",
            f"{result.version or 'Server'} · {result.players_online or 0} players",
        ),
    )
    return result


@router.get("/minecraft/logs", summary="Recent Minecraft log lines")
def minecraft_logs(
    token: ReadDep,
    lines: int = Query(default=80, ge=10, le=300),
) -> dict:
    settings = get_settings()
    path = settings.minecraft_dir / "logs" / "latest.log"
    from pathlib import Path

    if not Path(path).exists():
        raise HTTPException(
            status_code=404, detail={"code": "no_log", "message": "latest.log not found"}
        )
    analysis = minecraft.analyse_logs(settings)
    tail = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            tail = handle.readlines()[-lines:]
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail={"code": "log_unreadable", "message": str(exc)}
        ) from exc
    return {
        "lines": [minecraft.COLOUR.sub("", line.rstrip("\n"))[:400] for line in tail],
        "errors": analysis["errors"],
        "events": analysis["events"],
        "tick_warnings": analysis["tick_warnings"],
        "updated_at": analysis["log_updated_at"],
    }


@router.post("/minecraft/control", summary="Start, stop or restart the Minecraft server")
async def minecraft_control(
    payload: MinecraftControlRequest,
    request: Request,
    db: DbDep,
    token: AdminDep,
    confirmation: Annotated[str | None, Header(alias="X-Beacon-Confirm")] = None,
) -> dict:
    from ..deps import require_confirmation

    require_confirmation(confirmation, f"minecraft-{payload.action}", f"minecraft {payload.action}")
    throttle(f"{token.name}:minecraft-{payload.action}", limit=2, window_seconds=60)
    settings = get_settings()

    if payload.action == "start":
        result = await asyncio.to_thread(minecraft.start, settings)
    elif payload.action == "stop":
        result = await asyncio.to_thread(minecraft.stop, settings, force=payload.force)
    else:
        result = await asyncio.to_thread(minecraft.restart, settings, force=payload.force)

    audit(
        db,
        actor=token.name,
        action=f"minecraft.{payload.action}",
        target="server",
        detail={"force": payload.force, "result": result},
        ip=client_ip(request),
    )
    notifications.notify(
        db,
        kind=f"minecraft_{payload.action}",
        severity="info",
        title=f"Minecraft {payload.action} requested",
        body=(result.get("detail") or result.get("method") or "")[:300],
        dedupe_key=f"minecraft-{payload.action}:{int(__import__('time').time() // 30)}",
    )
    return result
