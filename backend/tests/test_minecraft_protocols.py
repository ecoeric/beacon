"""Minecraft protocol and control-path tests, fully offline.

Covers the three code paths that cannot be exercised against the live server without
disrupting players:

* server-list ping parsing, against a fake server that speaks the real handshake;
* the RCON client (auth success/failure, command reply), against a fake RCON server;
* the supervised pty console (start → type ``stop`` → process exits → log captured);
* the graceful SIGINT fallback and the refusal when no safe channel exists.

None of these tests touch `~/Desktop/NeoForgeServer` or port 25565.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from beacon.config import get_settings
from beacon.services import minecraft


# --------------------------------------------------------------------------- helpers
def _varint(value: int) -> bytes:
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
            raise ConnectionError("closed")
        byte = chunk[0]
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return result


def _read_exact(sock: socket.socket, length: int) -> bytes:
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data += chunk
    return data


class FakePingServer(threading.Thread):
    def __init__(self, payload: dict) -> None:
        super().__init__(daemon=True)
        self.payload = payload
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.error: Exception | None = None

    def run(self) -> None:  # pragma: no cover - thread body
        try:
            conn, _ = self.sock.accept()
            with conn:
                conn.settimeout(5)
                _read_exact(conn, _read_varint(conn))  # handshake
                _read_exact(conn, _read_varint(conn))  # status request
                import json

                body = json.dumps(self.payload).encode()
                packet = _varint(0) + _varint(len(body)) + body
                conn.sendall(_varint(len(packet)) + packet)
        except Exception as exc:  # noqa: BLE001 - reported in the test
            self.error = exc
        finally:
            self.sock.close()


class FakeRconServer(threading.Thread):
    def __init__(self, password: str, reply: str = "Stopping the server") -> None:
        super().__init__(daemon=True)
        self.password = password
        self.reply = reply
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.commands: list[str] = []
        self.error: Exception | None = None

    @staticmethod
    def _packet(request_id: int, kind: int, payload: str) -> bytes:
        body = struct.pack("<ii", request_id, kind) + payload.encode() + b"\x00\x00"
        return struct.pack("<i", len(body)) + body

    def run(self) -> None:  # pragma: no cover - thread body
        try:
            conn, _ = self.sock.accept()
            with conn:
                conn.settimeout(5)
                while True:
                    try:
                        length = struct.unpack("<i", _read_exact(conn, 4))[0]
                    except (ConnectionError, struct.error):
                        break
                    body = _read_exact(conn, length)
                    request_id, kind = struct.unpack("<ii", body[:8])
                    payload = body[8:-2].decode("utf-8", "replace")
                    if kind == 3:
                        if payload == self.password:
                            conn.sendall(self._packet(request_id, 2, ""))
                        else:
                            conn.sendall(self._packet(-1, 2, ""))
                    elif kind == 2:
                        self.commands.append(payload)
                        conn.sendall(self._packet(request_id, 0, self.reply))
        except Exception as exc:  # noqa: BLE001
            self.error = exc
        finally:
            self.sock.close()


def _settings_with(**overrides):
    return replace(get_settings(), **overrides)


# --------------------------------------------------------------------------- ping
def test_server_list_ping_parses_version_players_and_motd():
    payload = {
        "version": {"name": "1.21.1", "protocol": 767},
        "players": {
            "max": 20,
            "online": 2,
            "sample": [{"id": "a", "name": "ecoeric"}, {"id": "b", "name": "PorscheLegend23"}],
        },
        "description": "sussy pussy",
    }
    server = FakePingServer(payload)
    server.start()
    result = asyncio.run(minecraft.ping("127.0.0.1", server.port, timeout=3))
    server.join(timeout=5)
    assert server.error is None
    assert result is not None
    assert result["version"]["name"] == "1.21.1"
    assert result["version"]["protocol"] == 767
    assert result["players"]["online"] == 2
    assert [entry["name"] for entry in result["players"]["sample"]] == ["ecoeric", "PorscheLegend23"]
    assert result["description"] == "sussy pussy"


def test_ping_returns_none_when_nothing_listens():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    assert asyncio.run(minecraft.ping("127.0.0.1", free_port, timeout=0.5)) is None


# --------------------------------------------------------------------------- rcon
def test_rcon_command_authenticates_and_returns_reply(tmp_path):
    server = FakeRconServer(password="s3cret")
    server.start()
    settings = _settings_with(minecraft_host="127.0.0.1", minecraft_port=server.port)
    reply = minecraft.rcon_command(settings, "s3cret", "stop")
    server.join(timeout=5)
    assert server.error is None
    assert reply == "Stopping the server"
    assert server.commands == ["stop"]


def test_rcon_rejects_wrong_password():
    server = FakeRconServer(password="right")
    server.start()
    settings = _settings_with(minecraft_host="127.0.0.1", minecraft_port=server.port)
    with pytest.raises(minecraft.MinecraftError) as excinfo:
        minecraft.rcon_command(settings, "wrong", "stop")
    server.join(timeout=5)
    assert excinfo.value.code == "rcon_auth_failed"


def test_rcon_requires_a_password(tmp_path):
    settings = _settings_with(minecraft_rcon_password_file=tmp_path / "absent")
    with pytest.raises(minecraft.MinecraftError) as excinfo:
        minecraft.rcon_command(settings, "", "stop")
    assert excinfo.value.code == "rcon_no_password"


# ----------------------------------------------------------------- supervised pty
def test_supervisor_console_start_and_stop(tmp_path):
    server_dir = tmp_path / "minecraft"
    server_dir.mkdir()
    script = server_dir / "run.sh"
    script.write_text(
        "#!/bin/sh\n"
        "echo \"arg:$1\"\n"
        "echo 'fake server ready'\n"
        "while read line; do\n"
        "  case \"$line\" in\n"
        "    stop) echo 'Stopping server'; exit 0 ;;\n"
        "  esac\n"
        "done\n"
    )
    script.chmod(0o755)
    settings = _settings_with(minecraft_dir=server_dir, data_dir=tmp_path / "data")

    try:
        info = minecraft.supervisor.start(settings)
        assert info["pid"] > 0
        assert minecraft.supervisor.running()
        assert minecraft.supervisor.stop(timeout=10) is True
        assert not minecraft.supervisor.running()
        log = (settings.logs_dir / "minecraft-console.log").read_text(encoding="utf-8", errors="replace")
        assert "arg:nogui" in log
        assert "fake server ready" in log
        assert "Stopping server" in log
    finally:
        minecraft.supervisor.reset()


def test_start_refuses_when_another_instance_is_running(tmp_path, monkeypatch):
    server_dir = tmp_path / "minecraft"
    server_dir.mkdir()
    (server_dir / "run.sh").write_text("#!/bin/sh\nexit 0\n")
    (server_dir / "run.sh").chmod(0o755)
    settings = _settings_with(minecraft_dir=server_dir, data_dir=tmp_path / "data")
    monkeypatch.setattr(minecraft, "find_process", lambda _settings: 4242)
    with pytest.raises(minecraft.MinecraftError) as excinfo:
        minecraft.supervisor.start(settings)
    assert excinfo.value.code == "instance_already_running"


# ------------------------------------------------------- SIGINT fallback / refusal
def _fake_java_process(directory: Path) -> subprocess.Popen:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "java-neoforge"
    shutil.copy("/bin/sleep", binary)
    binary.chmod(0o755)
    proc = subprocess.Popen([str(binary), "30"], cwd=str(directory))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if minecraft.find_process(replace(get_settings(), minecraft_dir=directory)) == proc.pid:
            break
        time.sleep(0.05)
    return proc


def test_stop_falls_back_to_sigint_when_hook_is_present(tmp_path, monkeypatch):
    server_dir = tmp_path / "minecraft"
    proc = _fake_java_process(server_dir)
    settings = _settings_with(
        minecraft_dir=server_dir,
        data_dir=tmp_path / "data",
        minecraft_stop_timeout_seconds=5,
    )
    monkeypatch.setattr(minecraft, "graceful_signal_supported", lambda _settings: (True, "test hook"))
    monkeypatch.setattr(minecraft, "_players_from_log", lambda _settings: [])

    try:
        result = minecraft.stop(settings)
        assert result["method"] == "sigint"
        assert result["pid"] == proc.pid
        assert result["stopped"] is True
        assert proc.wait(timeout=5) is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_stop_refuses_without_a_safe_channel(tmp_path, monkeypatch):
    server_dir = tmp_path / "minecraft"
    proc = _fake_java_process(server_dir)
    settings = _settings_with(minecraft_dir=server_dir, data_dir=tmp_path / "data")
    monkeypatch.setattr(minecraft, "graceful_signal_supported", lambda _settings: (False, "no hook"))
    monkeypatch.setattr(minecraft, "_players_from_log", lambda _settings: [])

    try:
        with pytest.raises(minecraft.MinecraftError) as excinfo:
            minecraft.stop(settings)
        assert excinfo.value.code == "no_safe_channel"
        assert proc.poll() is None, "the server must not be terminated when no safe channel exists"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_stop_requires_force_when_players_are_online(tmp_path, monkeypatch):
    settings = _settings_with(minecraft_dir=tmp_path / "minecraft", data_dir=tmp_path / "data")
    (tmp_path / "minecraft").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(minecraft, "_players_from_log", lambda _settings: ["ecoeric"])
    with pytest.raises(minecraft.MinecraftError) as excinfo:
        minecraft.stop(settings, force=False)
    assert excinfo.value.code == "players_online"
    assert excinfo.value.detail["players"] == ["ecoeric"]


def test_stop_refuses_when_target_changes(tmp_path, monkeypatch):
    server_dir = tmp_path / "minecraft"
    proc = _fake_java_process(server_dir)
    settings = _settings_with(minecraft_dir=server_dir, data_dir=tmp_path / "data")
    monkeypatch.setattr(minecraft, "graceful_signal_supported", lambda _settings: (True, "hook"))
    monkeypatch.setattr(minecraft, "_players_from_log", lambda _settings: [])
    real_find = minecraft.find_process
    calls = {"count": 0}

    def flaky(settings_value):
        calls["count"] += 1
        return real_find(settings_value) if calls["count"] == 1 else None

    monkeypatch.setattr(minecraft, "find_process", flaky)
    try:
        with pytest.raises(minecraft.MinecraftError) as excinfo:
            minecraft.stop(settings)
        assert excinfo.value.code == "target_changed"
        assert proc.poll() is None, "the server must not be signalled after re-verification fails"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
