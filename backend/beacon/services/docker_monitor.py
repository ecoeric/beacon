"""Read-only Docker visibility through a narrow, sudo-allow-listed helper.

The API process is not in the ``docker`` group and never talks to the Docker socket. It runs
``sudo -n /usr/local/lib/beacon/docker-read <ps|stats>`` — a wrapper that only accepts those
two read-only subcommands (see ``deploy/docker-read`` and ``deploy/sudoers-beacon``).
Result is cached for a few seconds because ``docker stats --no-stream`` takes ~1s.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

from ..config import Settings
from ..schemas import DockerContainerInfo

_MEM_UNITS = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4}


def _parse_bytes(value: str) -> int | None:
    match = re.match(r"^\s*([0-9.]+)\s*([KMGT]?i?B)\s*$", value.strip(), re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).upper()
    factor = _MEM_UNITS.get(unit)
    if factor is None:
        return None
    return int(number * factor)


def _percent(value: str) -> float | None:
    try:
        return round(float(value.strip().rstrip("%")), 2)
    except (TypeError, ValueError):
        return None


@dataclass
class DockerSnapshot:
    available: bool
    error: str | None
    containers: list[DockerContainerInfo] = field(default_factory=list)
    fetched_at: float = 0.0


_cache: tuple[float, DockerSnapshot] | None = None
_lock = threading.Lock()


def _run_helper(settings: Settings, args: list[str], timeout: float = 12.0) -> tuple[int, str, str]:
    helper = settings.docker_read_helper
    if not helper.exists():
        return 127, "", f"docker read helper not installed at {helper}"
    try:
        proc = subprocess.run(
            ["sudo", "-n", str(helper), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 126, "", f"helper execution failed: {exc}"
    return proc.returncode, proc.stdout, proc.stderr


def _parse_ps(stdout: str) -> list[DockerContainerInfo]:
    containers: list[DockerContainerInfo] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        status = data.get("Status", "")
        health = None
        if "(healthy)" in status:
            health = "healthy"
        elif "(unhealthy)" in status:
            health = "unhealthy"
        elif "health: starting" in status:
            health = "starting"
        containers.append(
            DockerContainerInfo(
                name=data.get("Names", ""),
                image=data.get("Image", ""),
                state=(data.get("State") or "unknown").lower(),
                status=status,
                health=health,
            )
        )
    return containers


def _merge_stats(containers: list[DockerContainerInfo], stdout: str) -> None:
    by_name = {container.name: container for container in containers}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        name = data.get("Name") or data.get("Container") or ""
        container = by_name.get(name)
        if container is None:
            continue
        container.cpu_percent = _percent(data.get("CPUPerc", ""))
        usage = data.get("MemUsage", "")
        if "/" in usage:
            used, _, limit = usage.partition("/")
            container.memory_bytes = _parse_bytes(used)
            container.memory_limit_bytes = _parse_bytes(limit)


def snapshot(settings: Settings, *, max_age: float = 10.0) -> DockerSnapshot:
    global _cache
    with _lock:
        now = time.monotonic()
        if _cache is not None and now - _cache[0] < max_age:
            return _cache[1]
        code, stdout, stderr = _run_helper(settings, ["ps"])
        if code != 0:
            message = (stderr or stdout or f"helper exited {code}").strip().splitlines()
            result = DockerSnapshot(
                available=False,
                error=message[0][:300] if message else f"helper exited {code}",
                fetched_at=time.time(),
            )
            _cache = (now, result)
            return result
        containers = _parse_ps(stdout)
        stats_code, stats_out, _stats_err = _run_helper(settings, ["stats"])
        if stats_code == 0:
            _merge_stats(containers, stats_out)
        result = DockerSnapshot(available=True, error=None, containers=containers, fetched_at=time.time())
        _cache = (now, result)
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
