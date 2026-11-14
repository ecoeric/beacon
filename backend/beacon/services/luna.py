"""Read-only status for the Luna Multiplayer (LMP) KSP server.

The LMP server exposes a JSON document on loopback (default http://127.0.0.1:8900). It is
read-only; Beacon never starts, stops or signals the service. The systemd unit is deliberately
not controlled from the API because luna-server.service is a root-owned system service and the
API runs with NoNewPrivileges.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..config import Settings
from ..schemas import LunaStatus


def _read_cmdline(pid: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def _process(marker: str) -> tuple[int | None, int | None, float | None]:
    """Return (pid, rss bytes, uptime seconds) for the LMP server process."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        argv = _read_cmdline(pid)
        if not argv or not any(marker in arg for arg in argv):
            continue
        rss = None
        try:
            statm = Path(f"/proc/{pid}/statm").read_text(encoding="utf-8").split()
            rss = int(statm[1]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            pass
        started = None
        try:
            raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            fields = raw[raw.rindex(")") + 2 :].split()
            start_ticks = float(fields[19])
            btime = None
            for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
                if line.startswith("btime "):
                    btime = float(line.split()[1])
                    break
            if btime is not None:
                started = btime + start_ticks / os.sysconf("SC_CLK_TCK")
        except (OSError, ValueError, IndexError):
            pass
        return pid, rss, (time.time() - started) if started else None
    return None, None, None


def _udp_8800_listening() -> bool:
    for path in ("/proc/net/udp", "/proc/net/udp6"):
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                port = int(parts[1].rsplit(":", 1)[1], 16)
            except (ValueError, IndexError):
                continue
            if port == 8800:
                return True
    return False


def _fetch(url: str) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _player_names(players: Any) -> list[str]:
    if not isinstance(players, list):
        return []
    names: list[str] = []
    for player in players:
        if isinstance(player, dict):
            for key in ("Username", "Name", "PlayerName", "playerName"):
                value = player.get(key)
                if isinstance(value, str) and value:
                    names.append(value)
                    break
        elif isinstance(player, str) and player:
            names.append(player)
    return names


def _parse_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        return {}
    current = payload.get("CurrentState") or {}
    general = payload.get("GeneralSettings") or {}
    warp = payload.get("WarpSettings") or {}
    if not isinstance(current, dict) or not isinstance(general, dict):
        return {}
    return {
        "server_name": general.get("ServerName"),
        "description": general.get("Description"),
        "game_mode": general.get("GameMode"),
        "players_max": _int(general.get("MaxPlayers")),
        "has_password": _bool(general.get("HasPassword")),
        "mod_control": _bool(general.get("ModControl")),
        "warp_mode": warp.get("WarpMode") if isinstance(warp, dict) else None,
        "players": _player_names(current.get("CurrentPlayers")),
        "vessels": len(current.get("CurrentVessels") or []) if isinstance(current.get("CurrentVessels"), list) else None,
        "server_memory_bytes": _int(current.get("BytesUsed")),
    }


def status(settings: Settings) -> LunaStatus:
    pid, rss, uptime = _process(settings.luna_process_marker)
    udp = _udp_8800_listening()
    try:
        payload = _fetch(settings.luna_status_url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return LunaStatus(
            available=False,
            online=False,
            state="process-only" if pid else "stopped",
            pid=pid,
            uptime_seconds=uptime,
            memory_bytes=rss,
            udp_listening=udp,
            generated_at=time.time(),
            error=f"status endpoint unavailable: {exc}",
        )

    parsed = _parse_payload(payload)
    players = parsed.get("players") or []
    return LunaStatus(
        available=True,
        online=True,
        state="running",
        server_name=parsed.get("server_name"),
        description=parsed.get("description"),
        game_mode=parsed.get("game_mode"),
        players_online=len(players),
        players_max=parsed.get("players_max"),
        players=players,
        vessels=parsed.get("vessels"),
        has_password=parsed.get("has_password"),
        mod_control=parsed.get("mod_control"),
        warp_mode=parsed.get("warp_mode"),
        udp_listening=udp,
        pid=pid,
        uptime_seconds=uptime,
        memory_bytes=rss,
        server_memory_bytes=parsed.get("server_memory_bytes"),
        generated_at=time.time(),
        error=None,
    )
