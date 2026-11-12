"""Read-only Docker visibility via a root-written snapshot file.

The API process does **not** run `sudo`, does not join the `docker` group and never speaks to
the Docker socket. A small root-owned timer (`beacon-docker.timer`) executes two fixed docker
commands and atomically writes `/run/beacon/docker.json` (0644). This module only reads and
validates that file, reporting it as unavailable when it is missing, stale or malformed.

Why: a process that can call `sudo` (on this host `eric` has NOPASSWD) has no meaningful
privilege boundary, and Docker socket access is root-equivalent. Splitting the privileged read
into a fixed two-command timer lets the API run with `NoNewPrivileges=yes`.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

from ..config import Settings
from ..schemas import DockerContainerInfo

DEFAULT_MAX_AGE = 90.0
CACHE_SECONDS = 5.0

_cache: tuple[float, "DockerSnapshot"] | None = None
_lock = threading.Lock()


@dataclass
class DockerSnapshot:
    available: bool
    error: str | None
    containers: list[DockerContainerInfo] = field(default_factory=list)
    fetched_at: float = 0.0


def _container(raw: dict) -> DockerContainerInfo | None:
    if not isinstance(raw, dict) or not raw.get("name"):
        return None
    return DockerContainerInfo(
        name=str(raw.get("name")),
        image=str(raw.get("image") or ""),
        state=str(raw.get("state") or "unknown"),
        status=str(raw.get("status") or ""),
        health=(str(raw["health"]) if raw.get("health") else None),
        cpu_percent=(
            float(raw["cpu_percent"]) if isinstance(raw.get("cpu_percent"), (int, float)) else None
        ),
        memory_bytes=(
            int(raw["memory_bytes"]) if isinstance(raw.get("memory_bytes"), (int, float)) else None
        ),
        memory_limit_bytes=(
            int(raw["memory_limit_bytes"])
            if isinstance(raw.get("memory_limit_bytes"), (int, float))
            else None
        ),
        started_at=(
            float(raw["started_at"]) if isinstance(raw.get("started_at"), (int, float)) else None
        ),
        error=str(raw["error"]) if raw.get("error") else None,
    )


def snapshot(
    settings: Settings, *, max_age: float = DEFAULT_MAX_AGE, cache_seconds: float = CACHE_SECONDS
) -> DockerSnapshot:
    global _cache
    with _lock:
        now_monotonic = time.monotonic()
        if _cache is not None and now_monotonic - _cache[0] < cache_seconds:
            return _cache[1]
        path = settings.docker_snapshot_file
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            result = DockerSnapshot(
                available=False,
                error="Docker snapshot is not available yet (beacon-docker.timer)",
                fetched_at=0.0,
            )
            _cache = (now_monotonic, result)
            return result
        except (OSError, ValueError):
            result = DockerSnapshot(
                available=False,
                error="Docker snapshot file is unreadable or malformed",
                fetched_at=0.0,
            )
            _cache = (now_monotonic, result)
            return result

        fetched_at = payload.get("fetched_at")
        fetched = float(fetched_at) if isinstance(fetched_at, (int, float)) else 0.0
        age = max(0.0, time.time() - fetched) if fetched else float("inf")
        containers: list[DockerContainerInfo] = []
        for raw in payload.get("containers") or []:
            container = _container(raw)
            if container is not None:
                containers.append(container)
        if age > max_age:
            result = DockerSnapshot(
                available=False,
                error=(
                    "Docker snapshot is stale "
                    f"({int(age)}s old; beacon-docker.timer should refresh it every 15s)"
                ),
                containers=containers,
                fetched_at=fetched,
            )
        else:
            result = DockerSnapshot(available=True, error=None, containers=containers, fetched_at=fetched)
        _cache = (now_monotonic, result)
        return result


def find_container(snapshot_value: DockerSnapshot, name: str) -> DockerContainerInfo | None:
    for container in snapshot_value.containers:
        if container.name == name:
            return container
    return None


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None
