"""Dashboard composition.

One call composes the home screen so the iPhone makes a single request per refresh. It also
performs the service up/down edge detection that feeds the in-app activity feed: polling is
the only trigger, so a flapping service cannot flood the feed (dedupe keys + state table).
"""

from __future__ import annotations

import asyncio
import time

from ..config import Settings
from ..db import Database, now
from ..schemas import (
    DashboardSummary,
    LunaStatus,
    MinecraftStatus,
    PiholeStatus,
    ServiceStatus,
    ServerOverview,
)
from . import (
    agent_status,
    docker_monitor,
    luna,
    milestones,
    minecraft,
    notifications,
    pihole,
    system_metrics,
)

DISK_WARNING_PERCENT = 92.0


def _agent_service(status) -> ServiceStatus:
    mapping = {
        "working": ("up", "Working"),
        "idle": ("up", "Idle"),
        "completed": ("up", "Completed"),
        "waiting_for_input": ("degraded", "Waiting for input"),
        "waiting_for_messages": ("degraded", "Queued messages waiting"),
        "interrupted": ("degraded", "Interrupted"),
        "failed": ("down", "Last turn failed"),
        "disconnected": ("down", "Disconnected"),
        "unknown": ("unknown", "Unknown"),
    }
    state, summary = mapping.get(status.state, ("unknown", status.state_label))
    return ServiceStatus(
        key="agent",
        label="AI agent",
        state=state,
        summary=summary,
        detail=status.project or None,
        checked_at=time.time(),
        latency_ms=None,
    )


def _pihole_service(status: PiholeStatus) -> ServiceStatus:
    if not status.available:
        return ServiceStatus(
            key="pihole",
            label="Pi-hole",
            state="down",
            summary="Unreachable",
            detail=status.error,
            checked_at=status.generated_at,
        )
    container = status.container
    if container is not None and container.health and container.health not in {"healthy"}:
        return ServiceStatus(
            key="pihole",
            label="Pi-hole",
            state="degraded",
            summary=f"API up · container {container.health}",
            detail=container.status,
            checked_at=status.generated_at,
        )
    blocking = "blocking" if status.blocking == "enabled" else "not blocking"
    return ServiceStatus(
        key="pihole",
        label="Pi-hole",
        state="up",
        summary=f"DNS up · {blocking}",
        detail=container.status if container else None,
        checked_at=status.generated_at,
    )


def _minecraft_service(status: MinecraftStatus) -> ServiceStatus:
    if status.state == "running":
        players = f"{status.players_online}/{status.players_max}" if status.players_online is not None else "online"
        return ServiceStatus(
            key="minecraft",
            label="Minecraft",
            state="up",
            summary=f"Online · {players} players",
            detail=status.version,
            checked_at=status.generated_at,
        )
    if status.state == "unreachable":
        return ServiceStatus(
            key="minecraft",
            label="Minecraft",
            state="degraded",
            summary="Process running · not answering ping",
            detail=status.error,
            checked_at=status.generated_at,
        )
    return ServiceStatus(
        key="minecraft",
        label="Minecraft",
        state="down",
        summary="Stopped",
        detail=status.error,
        checked_at=status.generated_at,
    )


def _luna_service(status: LunaStatus) -> ServiceStatus:
    if status.state == "running":
        players = f"{status.players_online or 0}/{status.players_max}" if status.players_max else "online"
        return ServiceStatus(
            key="luna",
            label="KSP · Luna",
            state="up",
            summary=f"Online · {players} players",
            detail=status.server_name,
            checked_at=status.generated_at,
        )
    if status.state == "process-only":
        return ServiceStatus(
            key="luna",
            label="KSP · Luna",
            state="degraded",
            summary="Process running · status endpoint unavailable",
            detail=status.error,
            checked_at=status.generated_at,
        )
    return ServiceStatus(
        key="luna",
        label="KSP · Luna",
        state="down",
        summary="Stopped",
        detail=status.error,
        checked_at=status.generated_at,
    )


def _server_service(server: ServerOverview) -> ServiceStatus:
    detail = None
    state = "up"
    if server.unavailable:
        state = "degraded" if server.cpu.percent is not None else "unknown"
        detail = "; ".join(server.unavailable)[:200]
    return ServiceStatus(
        key="server",
        label="Host metrics",
        state=state,
        summary=(
            f"CPU {server.cpu.percent:.0f}% · RAM {server.memory.percent:.0f}%"
            if server.cpu.percent is not None and server.memory is not None
            else "Partial metrics"
        ),
        detail=detail,
        checked_at=server.generated_at,
    )


def _track(db: Database, pihole_status: PiholeStatus, minecraft_status: MinecraftStatus, luna_status: LunaStatus, server: ServerOverview, agent) -> None:
    pihole_online = pihole_status.available and pihole_status.online
    notifications.transition(
        db,
        key="pihole",
        online=pihole_online,
        detail={"error": pihole_status.error, "blocking": pihole_status.blocking},
        offline_notification=(
            "pihole_offline",
            "Pi-hole became unavailable",
            pihole_status.error or "The Pi-hole API stopped responding.",
        ),
        online_notification=("pihole_online", "Pi-hole is back", "The Pi-hole API is responding again."),
    )
    minecraft_online = minecraft_status.state == "running"
    notifications.transition(
        db,
        key="minecraft",
        online=minecraft_online,
        detail={"state": minecraft_status.state},
        offline_notification=(
            "minecraft_offline",
            "Minecraft server went offline",
            "The server no longer answers on port 25565.",
        ),
        online_notification=(
            "minecraft_online",
            "Minecraft server is online",
            f"{minecraft_status.version or 'Server'} · {minecraft_status.players_online or 0} players",
        ),
    )
    luna_online = luna_status.state == "running"
    notifications.transition(
        db,
        key="luna",
        online=luna_online,
        detail={"state": luna_status.state},
        offline_notification=(
            "luna_offline",
            "KSP Luna server went offline",
            "The Luna Multiplayer server is not answering.",
        ),
        online_notification=(
            "luna_online",
            "KSP Luna server is online",
            f"{luna_status.server_name or 'Luna'} · {luna_status.players_online or 0} players",
        ),
    )
    for disk in server.disks:
        if disk.percent < DISK_WARNING_PERCENT:
            continue
        notifications.transition(
            db,
            key=f"disk:{disk.mount}",
            online=False,
            detail={"percent": disk.percent},
            offline_notification=(
                "disk_pressure",
                f"Disk {disk.mount} is {disk.percent:.0f}% full",
                f"{disk.free_bytes // (1024**3)} GiB free on {disk.filesystem}.",
            ),
            online_notification=(
                "disk_recovered",
                f"Disk {disk.mount} recovered",
                f"Usage is back to {disk.percent:.0f}%.",
            ),
        )
    if agent.state in {"failed", "interrupted"}:
        notifications.transition(
            db,
            key="agent-health",
            online=False,
            detail={"state": agent.state},
            offline_notification=(
                f"agent_{agent.state}",
                "Agent needs attention",
                f"The agent is {agent.state_label.lower()}: {agent.activity or agent.project or 'no detail'}",
            ),
            online_notification=(
                "agent_recovered",
                "Agent recovered",
                "The agent is active again.",
            ),
        )
    elif agent.state in {"working", "idle", "completed"}:
        notifications.transition(db, key="agent-health", online=True, detail={"state": agent.state})


async def build_summary(settings: Settings, db: Database) -> DashboardSummary:
    agent = agent_status.build_agent_status(settings, db)
    docker = await asyncio.to_thread(docker_monitor.snapshot, settings)
    pihole_container = docker_monitor.find_container(docker, "pihole") if docker.available else None
    pihole_status, minecraft_status, luna_status, server = await asyncio.gather(
        pihole.get_client(settings).status(pihole_container),
        minecraft.status(settings),
        asyncio.to_thread(luna.status, settings),
        asyncio.to_thread(system_metrics.overview, settings),
    )
    server.docker = docker.containers
    server.docker_available = docker.available
    server.docker_error = docker.error

    _track(db, pihole_status, minecraft_status, luna_status, server, agent)

    services = [
        ServiceStatus(
            key="api",
            label="Dashboard API",
            state="up",
            summary="Responding",
            checked_at=now(),
        ),
        _agent_service(agent),
        _pihole_service(pihole_status),
        _minecraft_service(minecraft_status),
        _luna_service(luna_status),
        _server_service(server),
        ServiceStatus(
            key="docker",
            label="Docker",
            state="up" if docker.available else "unavailable",
            summary="Read-only monitor" if docker.available else "Not configured",
            detail=docker.error,
            checked_at=docker.fetched_at or now(),
        ),
    ]
    return DashboardSummary(
        generated_at=now(),
        agent=agent,
        services=services,
        server=server,
        pihole=pihole_status,
        minecraft=minecraft_status,
        luna=luna_status,
        latest_milestone=milestones.latest(db),
        activity=notifications.feed(db, limit=20),
        data_age_seconds=agent.data_age_seconds,
    )
