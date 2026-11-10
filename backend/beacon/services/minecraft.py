"""Minecraft server integration for the *existing* NeoForge installation.

Read path (always available, no configuration changes)
------------------------------------------------------
* Server-list ping (``enable-status=true`` verified in ``server.properties``) gives online
  state, version, protocol, MOTD, player count and sampled player names.
* ``/proc`` gives pid, CPU, RSS and start time for the running java process.
* ``logs/latest.log`` is tailed for joins/leaves, startup completion and the most recent
  errors. Tick metrics (TPS/MSPT) are reported as unavailable with the reason, because this
  server has neither spark nor RCON/console polling enabled — no numbers are invented.

Control path (safeguarded)
--------------------------
1. **Supervised console** — if Beacon started the instance it owns a pty and can type
   ``stop`` exactly like a human at the console. This is the preferred and safest path.
2. **RCON** — used only when ``enable-rcon=true`` and a password file is configured.
3. **SIGINT** — only when the installed server jar actually contains the
   ``"Server Shutdown Thread"`` JVM shutdown hook (verified on disk, cached), i.e. the same
   code path as Ctrl+C. The server is never force-killed; if it does not exit within the
   timeout the API reports that instead of escalating.

Every control requires an admin token, a confirmation header, a rate limit and the
``force`` flag when players are online. Starting is refused when a server is already running.
"""

from __future__ import annotations

import asyncio
import json
import os
import pty
import re
import select
import shutil
import signal
import socket
import struct
import subprocess
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings
from ..schemas import (
    MinecraftControls,
    MinecraftStatus,
)

LOG_TAIL_BYTES = 512 * 1024
COLOUR = re.compile(r"\x1b\[[0-9;]*m")
ERROR_MARKERS = ("[ERROR]", "FATAL", "Exception", "Caused by:")


class MinecraftError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}


# --------------------------------------------------------------------------- ping
def _pack_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _read_varint(sock: socket.socket) -> int:
    result = 0
    shift = 0
    while True:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("connection closed during varint")
        byte = chunk[0]
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return result


def _ping_sync(host: str, port: int, timeout: float) -> dict:
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        host_bytes = host.encode("utf-8")
        payload = (
            _pack_varint(0)
            + _pack_varint(767)
            + _pack_varint(len(host_bytes))
            + host_bytes
            + struct.pack(">H", port)
            + _pack_varint(1)
        )
        sock.sendall(_pack_varint(len(payload)) + payload)
        sock.sendall(_pack_varint(1) + _pack_varint(0))
        _read_varint(sock)
        _read_varint(sock)
        length = _read_varint(sock)
        chunks = bytearray()
        while len(chunks) < length:
            piece = sock.recv(length - len(chunks))
            if not piece:
                break
            chunks.extend(piece)
        return json.loads(bytes(chunks).decode("utf-8"))
    finally:
        sock.close()


async def ping(host: str, port: int, timeout: float = 2.5) -> dict | None:
    try:
        return await asyncio.to_thread(_ping_sync, host, port, timeout)
    except (OSError, ValueError, ConnectionError, json.JSONDecodeError, struct.error):
        return None


# ----------------------------------------------------------------------- process
def _proc_cmdline(pid: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def _proc_cwd(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def find_process(settings: Settings) -> int | None:
    server_dir = settings.minecraft_dir.resolve()
    own_uid = os.getuid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        cwd = _proc_cwd(pid)
        if cwd is None:
            continue
        try:
            if Path(cwd).resolve() != server_dir:
                continue
        except OSError:
            continue
        argv = _proc_cmdline(pid)
        if not argv:
            continue
        joined = " ".join(argv).lower()
        if "java" not in joined:
            continue
        if not any(token in joined for token in ("neoforge", "minecraft", "forge")):
            continue
        try:
            if entry.stat().st_uid != own_uid:
                continue
        except OSError:
            continue
        return pid
    return None


_cpu_cache: dict[int, tuple[float, float, float]] = {}
_cpu_lock = threading.Lock()


def _clk_tck() -> int:
    return os.sysconf("SC_CLK_TCK")


def process_stats(pid: int) -> dict:
    out: dict = {"pid": pid, "cpu_percent": None, "memory_bytes": None, "started_at": None}
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = raw[raw.rindex(")") + 2 :].split()
        utime = float(fields[11])
        stime = float(fields[12])
        rss_pages = float(fields[21])
        start_ticks = float(fields[19])
    except (OSError, ValueError, IndexError):
        return out
    try:
        statm = Path(f"/proc/{pid}/statm").read_text(encoding="utf-8").split()
        resident_pages = float(statm[1])
    except (OSError, ValueError, IndexError):
        resident_pages = rss_pages
    page_size = os.sysconf("SC_PAGE_SIZE")
    out["memory_bytes"] = int(resident_pages * page_size)

    ticks = utime + stime
    current = time.monotonic()
    with _cpu_lock:
        previous = _cpu_cache.get(pid)
        _cpu_cache[pid] = (ticks, current, time.time())
    if previous is not None:
        delta_ticks = ticks - previous[0]
        delta_seconds = current - previous[1]
        if delta_seconds > 0 and delta_ticks >= 0:
            out["cpu_percent"] = round(
                100.0 * (delta_ticks / _clk_tck()) / delta_seconds, 1
            )
    try:
        btime = None
        for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
            if line.startswith("btime "):
                btime = float(line.split()[1])
                break
        if btime is not None:
            out["started_at"] = btime + start_ticks / _clk_tck()
    except (OSError, ValueError):
        pass
    return out


# -------------------------------------------------------------------------- logs
def _read_tail(path: Path, max_bytes: int = LOG_TAIL_BYTES) -> tuple[str, float | None]:
    try:
        stat = path.stat()
    except OSError:
        return "", None
    try:
        with path.open("rb") as handle:
            if stat.st_size > max_bytes:
                handle.seek(-max_bytes, os.SEEK_END)
                handle.readline()
            data = handle.read()
    except OSError:
        return "", stat.st_mtime
    return data.decode("utf-8", "replace"), stat.st_mtime


def analyse_logs(settings: Settings) -> dict:
    log_path = settings.minecraft_dir / "logs" / "latest.log"
    text, mtime = _read_tail(log_path)
    errors: list[str] = []
    events: list[str] = []
    tick_warnings = 0
    if text:
        for line in text.splitlines():
            line = COLOUR.sub("", line).strip()
            if not line:
                continue
            if "Can't keep up" in line or "Running behind" in line:
                tick_warnings += 1
            if any(marker in line for marker in ERROR_MARKERS):
                if len(errors) < 40:
                    errors.append(line[:300])
            if any(
                token in line
                for token in ("joined the game", "left the game", "Done (", "Stopping server", "Preparing level")
            ):
                events.append(line[:300])
    return {
        "errors": errors[-5:],
        "events": events[-5:],
        "tick_warnings": tick_warnings,
        "log_updated_at": mtime,
    }


def backup_info(settings: Settings) -> tuple[float | None, str | None]:
    candidates = [
        settings.minecraft_dir / "backups",
        settings.minecraft_dir / "backup",
        settings.minecraft_dir / "world" / "backups",
    ]
    newest: float | None = None
    found = False
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        found = True
        try:
            for entry in candidate.iterdir():
                if entry.name.startswith("."):
                    continue
                try:
                    newest = max(newest or 0.0, entry.stat().st_mtime)
                except OSError:
                    continue
        except OSError:
            continue
    if not found:
        return None, "No backup directory found in the server folder — no existing mechanism detected"
    if newest is None:
        return None, "Backup directory exists but contains no entries"
    return newest, None


def loader_info(settings: Settings) -> tuple[str | None, int | None]:
    """Detect the mod loader/version from installed libraries and count installed mods."""
    loader: str | None = None
    for family, label in (("neoforge", "NeoForge"), ("forge", "Forge")):
        base = settings.minecraft_dir / "libraries" / "net" / "neoforged" / family
        try:
            versions = sorted(entry.name for entry in base.iterdir() if entry.is_dir())
        except OSError:
            continue
        if versions:
            loader = f"{label} {versions[-1]}"
            break
    mods_count: int | None = None
    mods_dir = settings.minecraft_dir / "mods"
    if mods_dir.is_dir():
        try:
            mods_count = sum(1 for entry in mods_dir.iterdir() if entry.suffix.lower() == ".jar")
        except OSError:
            mods_count = None
    return loader, mods_count


def _spark_installed(settings: Settings) -> bool:
    mods = settings.minecraft_dir / "mods"
    if not mods.is_dir():
        return False
    try:
        return any("spark" in entry.name.lower() for entry in mods.iterdir())
    except OSError:
        return False


def _read_properties(settings: Settings) -> dict[str, str]:
    props: dict[str, str] = {}
    try:
        text = (settings.minecraft_dir / "server.properties").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return props
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        props[key.strip()] = value.strip().replace("\\:", ":")
    return props


_graceful_cache: tuple[bool, str] | None = None


def graceful_signal_supported(settings: Settings) -> tuple[bool, str]:
    """Does the installed server jar contain the JVM shutdown hook (Ctrl+C semantics)?"""
    global _graceful_cache
    if _graceful_cache is not None:
        return _graceful_cache
    base = settings.minecraft_dir / "libraries" / "net" / "minecraft" / "server"
    if not base.is_dir():
        _graceful_cache = (False, "server jar directory not found")
        return _graceful_cache
    try:
        jars = sorted(base.rglob("*.jar"))
    except OSError:
        _graceful_cache = (False, "server jar directory not readable")
        return _graceful_cache
    for jar in jars[:8]:
        try:
            with zipfile.ZipFile(jar) as archive:
                for name in archive.namelist():
                    if not name.endswith(".class"):
                        continue
                    if name.count("/") > 4:
                        continue
                    data = archive.read(name)
                    if b"Server Shutdown Thread" in data:
                        _graceful_cache = (True, f"shutdown hook found in {jar.name}:{name}")
                        return _graceful_cache
        except (OSError, zipfile.BadZipFile, KeyError):
            continue
    _graceful_cache = (False, "no 'Server Shutdown Thread' hook found in the installed server jars")
    return _graceful_cache


# ------------------------------------------------------------------ supervision
class Supervisor:
    """Owns a Minecraft instance started by Beacon through a pty (console access)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._master: int | None = None
        self._started_at: float | None = None
        self._log_file = None
        self._reader: threading.Thread | None = None
        self.last_command_at: float | None = None

    def running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return None
            return self._proc.pid

    @property
    def started_at(self) -> float | None:
        return self._started_at

    def start(self, settings: Settings) -> dict:
        with self._lock:
            if self.running():
                raise MinecraftError("already_running", "Beacon is already supervising a running server")
            if find_process(settings) is not None:
                raise MinecraftError(
                    "instance_already_running",
                    "A Minecraft process is already running for this server folder; stop it in its console first",
                )
            script = settings.minecraft_dir / settings.minecraft_launch_script
            if not script.exists():
                raise MinecraftError("no_launch_script", f"launch script not found: {script}", status_code=500)
            log_path = settings.logs_dir / "minecraft-console.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            master, slave = pty.openpty()
            log_file = log_path.open("ab", buffering=0)
            proc = subprocess.Popen(
                [str(script)],
                cwd=str(settings.minecraft_dir),
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
                close_fds=True,
                env={**os.environ, "TERM": "dumb"},
            )
            os.close(slave)
            self._proc = proc
            self._master = master
            self._started_at = time.time()
            self._log_file = log_file
            self._reader = threading.Thread(
                target=self._drain, args=(master, log_file), name="mc-console", daemon=True
            )
            self._reader.start()
            return {"pid": proc.pid, "started_at": self._started_at, "console_log": str(log_path)}

    def _drain(self, master: int, log_file) -> None:
        while True:
            try:
                ready, _, _ = select.select([master], [], [], 1.0)
                if not ready:
                    if self._proc is not None and self._proc.poll() is not None:
                        break
                    continue
                chunk = os.read(master, 8192)
                if not chunk:
                    break
                log_file.write(chunk)
            except OSError:
                break
        with self._lock:
            try:
                log_file.close()
            except OSError:
                pass
            if self._master is not None:
                try:
                    os.close(self._master)
                except OSError:
                    pass
                self._master = None

    def command(self, text: str) -> None:
        with self._lock:
            if not self.running() or self._master is None:
                raise MinecraftError("not_supervised", "No supervised console is attached")
            try:
                os.write(self._master, (text.strip() + "\n").encode("utf-8"))
            except OSError as exc:
                raise MinecraftError(
                    "console_write_failed", f"could not write to the server console: {exc}"
                ) from exc
            self.last_command_at = time.time()

    def stop(self, timeout: int) -> bool:
        if not self.running():
            return True
        self.command("stop")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.running():
                return True
            time.sleep(0.2)
        return False

    def shutdown(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def reset(self) -> None:
        """Stop any supervised process and clear state (used by tests and teardown)."""
        self.shutdown()
        with self._lock:
            self._proc = None
            self._master = None
            self._started_at = None
            self._log_file = None
            self._reader = None


supervisor = Supervisor()


# ------------------------------------------------------------------------ status
def _players_from_log(settings: Settings) -> list[str]:
    text, _ = _read_tail(settings.minecraft_dir / "logs" / "latest.log", 256 * 1024)
    online: list[str] = []
    if not text:
        return online
    for line in text.splitlines():
        line = COLOUR.sub("", line)
        match = re.search(r": ([A-Za-z0-9_]{1,16}) joined the game", line)
        if match:
            if match.group(1) not in online:
                online.append(match.group(1))
            continue
        match = re.search(r": ([A-Za-z0-9_]{1,16}) left the game", line)
        if match and match.group(1) in online:
            online.remove(match.group(1))
    return online


def controls_capabilities(settings: Settings) -> MinecraftControls:
    props = _read_properties(settings)
    rcon_enabled = props.get("enable-rcon", "false").lower() == "true"
    rcon_password = settings.minecraft_rcon_password
    graceful, _hint = graceful_signal_supported(settings)
    supervised = supervisor.running()
    path = find_process(settings)
    online = path is not None or supervised

    actions = ["start"] if not online else []
    stop_method = None
    if supervised:
        stop_method = "console"
    elif rcon_enabled and rcon_password:
        stop_method = "rcon"
    elif graceful:
        stop_method = "sigint"
    if stop_method:
        actions.extend(["stop", "restart"])

    reason = None
    if not online:
        reason = "Server is stopped; start is available"
    elif stop_method is None:
        reason = (
            "Cannot stop safely: instance is not supervised by Beacon, RCON is disabled and "
            "the installed server jar has no graceful shutdown hook"
        )
    if rcon_enabled and not rcon_password:
        reason = "enable-rcon=true but no RCON password file is configured"
    return MinecraftControls(
        available=bool(actions),
        actions=actions,
        stop_method=stop_method,
        start_method="pty-console" if not online else None,
        reason=reason,
    )


async def status(settings: Settings) -> MinecraftStatus:
    generated = time.time()
    controls = controls_capabilities(settings)
    supervised_pid = supervisor.pid
    pid = supervised_pid or find_process(settings)
    ping_result = await ping(settings.minecraft_host, settings.minecraft_port)
    logs = analyse_logs(settings)
    backup_at, backup_note = backup_info(settings)
    props = _read_properties(settings)

    version = None
    protocol = None
    motd = None
    loader, mods_count = loader_info(settings)
    players_online = None
    players_max = None
    players: list[str] = []
    if ping_result:
        version_obj = ping_result.get("version") or {}
        version = version_obj.get("name")
        protocol = version_obj.get("protocol")
        description = ping_result.get("description")
        if isinstance(description, str):
            motd = description
        elif isinstance(description, dict):
            motd = description.get("text") or json.dumps(description)[:200]
        players_obj = ping_result.get("players") or {}
        players_online = players_obj.get("online")
        players_max = players_obj.get("max")
        players = [entry.get("name", "") for entry in players_obj.get("sample") or [] if entry.get("name")]

    stats = process_stats(pid) if pid else {"cpu_percent": None, "memory_bytes": None, "started_at": None}
    started_at = supervisor.started_at or stats.get("started_at")
    uptime = round(generated - started_at, 1) if started_at else None

    if not players:
        players = _players_from_log(settings)

    if ping_result:
        state = "running"
    elif pid is not None:
        state = "unreachable"
    else:
        state = "stopped"

    spark = _spark_installed(settings)
    rcon_enabled = props.get("enable-rcon", "false").lower() == "true"
    if spark:
        tps_note = "spark is installed but not queried live (no RCON/console command channel configured)"
    elif rcon_enabled:
        tps_note = "RCON is enabled; tick metrics are available only when the console channel is configured"
    else:
        tps_note = "Tick metrics unavailable: no spark/TPS provider installed and RCON/query are disabled"

    return MinecraftStatus(
        available=True,
        online=ping_result is not None,
        state=state,  # type: ignore[arg-type]
        version=version,
        loader=loader,
        mods_count=mods_count,
        protocol=protocol,
        motd=motd,
        players_online=players_online,
        players_max=players_max,
        players=players,
        uptime_seconds=uptime,
        pid=pid,
        cpu_percent=stats.get("cpu_percent"),
        memory_bytes=stats.get("memory_bytes"),
        tps=None,
        mspt=None,
        tick_metrics_note=tps_note,
        recent_errors=logs["errors"],
        recent_events=logs["events"],
        log_updated_at=logs["log_updated_at"],
        last_backup_at=backup_at,
        backup_note=backup_note,
        controls=controls,
        generated_at=generated,
    )


def _process_alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        state = stat[stat.rindex(")") + 2]
    except ValueError:
        return False
    return state not in {"Z", "X"}


def _wait_gone(pid: int, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(0.25)
    return not _process_alive(pid)


def start(settings: Settings) -> dict:
    info = supervisor.start(settings)
    return {"action": "start", "method": "pty-console", **info}


def _require_players_offline(settings: Settings, force: bool) -> None:
    if force:
        return
    log_players = _players_from_log(settings)
    if log_players:
        raise MinecraftError(
            "players_online",
            f"{len(log_players)} player(s) appear to be online; pass force=true to stop anyway",
            detail={"players": log_players},
        )


def stop(settings: Settings, *, force: bool = False, actor: str = "admin") -> dict:
    _require_players_offline(settings, force)
    if supervisor.running():
        pid = supervisor.pid
        ok = supervisor.stop(settings.minecraft_stop_timeout_seconds)
        return {
            "action": "stop",
            "method": "console",
            "pid": pid,
            "stopped": ok,
            "detail": "typed 'stop' into the supervised console"
            if ok
            else "stop command sent but the process did not exit within the timeout",
        }

    pid = find_process(settings)
    if pid is None:
        if find_process(settings) is None and supervisor.pid is None:
            raise MinecraftError("not_running", "No Minecraft server process found")
        pid = find_process(settings)

    props = _read_properties(settings)
    if props.get("enable-rcon", "false").lower() == "true" and settings.minecraft_rcon_password:
        try:
            reply = rcon_command(
                settings,
                props.get("rcon.password", settings.minecraft_rcon_password) or "",
                "stop",
            )
        except MinecraftError:
            raise
        return {
            "action": "stop",
            "method": "rcon",
            "pid": pid,
            "stopped": _wait_gone(pid, settings.minecraft_stop_timeout_seconds) if pid else True,
            "detail": reply[:200],
        }

    graceful, hint = graceful_signal_supported(settings)
    if not graceful or pid is None:
        raise MinecraftError(
            "no_safe_channel",
            "No safe stop channel available for this instance",
            detail={"graceful_signal": graceful, "hint": hint, "pid": pid},
        )

    if find_process(settings) != pid:
        raise MinecraftError(
            "target_changed",
            f"the Minecraft process for pid {pid} changed or exited; nothing was signalled",
        )

    try:
        os.kill(pid, signal.SIGINT)
    except OSError as exc:
        raise MinecraftError("signal_failed", f"could not signal pid {pid}: {exc}") from exc
    exited = _wait_gone(pid, settings.minecraft_stop_timeout_seconds)
    if not exited:
        raise MinecraftError(
            "stop_timeout",
            f"SIGINT sent to pid {pid} but the process is still running after "
            f"{settings.minecraft_stop_timeout_seconds}s; the server was not killed",
            status_code=504,
        )
    return {
        "action": "stop",
        "method": "sigint",
        "pid": pid,
        "stopped": True,
        "detail": hint,
    }


def restart(settings: Settings, *, force: bool = False) -> dict:
    result = {"restarted": False}
    pid = find_process(settings)
    if supervisor.running() or pid is not None:
        stop_result = stop(settings, force=force)
        result["stop"] = stop_result
        if not stop_result.get("stopped", False):
            result["detail"] = "stop did not complete; refusing to start a second instance"
            return result
    result["start"] = start(settings)
    result["restarted"] = True
    return result


# ------------------------------------------------------------------------- rcon
def _rcon_packet(request_id: int, kind: int, payload: str) -> bytes:
    body = struct.pack("<ii", request_id, kind) + payload.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(body)) + body


def _read_exact(sock: socket.socket, length: int) -> bytes:
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("rcon connection closed")
        data += chunk
    return data


def rcon_command(settings: Settings, password: str, command: str, timeout: float = 5.0) -> str:
    if not password:
        raise MinecraftError("rcon_no_password", "RCON password is not configured")
    try:
        sock = socket.create_connection(
            (settings.minecraft_host, settings.minecraft_port), timeout=timeout
        )
    except OSError as exc:
        raise MinecraftError("rcon_unreachable", f"RCON connect failed: {exc}") from exc
    try:
        sock.sendall(_rcon_packet(1, 3, password))
        length = struct.unpack("<i", _read_exact(sock, 4))[0]
        body = _read_exact(sock, length)
        request_id = struct.unpack("<i", body[:4])[0]
        if request_id == -1:
            raise MinecraftError("rcon_auth_failed", "RCON authentication rejected")
        sock.sendall(_rcon_packet(2, 2, command))
        length = struct.unpack("<i", _read_exact(sock, 4))[0]
        body = _read_exact(sock, length)
        return body[8:].decode("utf-8", "replace").strip("\x00")
    except (OSError, ConnectionError, struct.error) as exc:
        raise MinecraftError("rcon_error", f"RCON failure: {exc}") from exc
    finally:
        sock.close()


def reset_graceful_cache() -> None:
    global _graceful_cache
    _graceful_cache = None
