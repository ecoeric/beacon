"""Beacon backend configuration.

Every value comes from the environment (loaded by systemd from deploy/beacon.env) with a
conservative default. Nothing security-relevant is hardcoded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name)
    if value is None:
        if default is None:
            raise RuntimeError(f"missing required environment variable {name}")
        return default
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    bind: str
    port: int
    tls_cert: Path
    tls_key: Path

    cherry_db: Path
    cherry_agents_dir: Path
    agent_id: str
    session_id: str
    stale_working_seconds: int
    stale_disconnect_seconds: int
    message_lease_seconds: int
    message_max_attempts: int

    pihole_url: str
    pihole_password_file: Path
    pihole_timeout_seconds: float

    minecraft_dir: Path
    minecraft_host: str
    minecraft_port: int
    minecraft_launch_script: str
    minecraft_rcon_password_file: Path
    minecraft_stop_timeout_seconds: int

    docker_snapshot_file: Path
    screenshot_retention_days: int
    screenshot_max_bytes: int
    screenshot_max_total_bytes: int
    max_request_bytes: int
    enable_docs: bool = False
    minecraft_launch_args: list[str] = field(default_factory=lambda: ["nogui"])
    allowed_origins: list[str] = field(default_factory=list)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "beacon.sqlite"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_dir / "screenshots"

    @property
    def capture_dir(self) -> Path:
        return self.data_dir / "captures"

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def agent_dir(self) -> Path:
        return self.data_dir / "agent"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def pihole_password(self) -> str | None:
        try:
            text = self.pihole_password_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    @property
    def minecraft_rcon_password(self) -> str | None:
        try:
            text = self.minecraft_rcon_password_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None


def load_settings() -> Settings:
    data_dir = Path(_env("BEACON_DATA_DIR", str(Path.home() / "beacon" / "data"))).expanduser()
    settings = Settings(
        data_dir=data_dir,
        bind=_env("BEACON_BIND", "127.0.0.1"),
        port=_env_int("BEACON_PORT", 8091),
        tls_cert=Path(_env("BEACON_TLS_CERT", str(data_dir / "tls" / "server.crt"))).expanduser(),
        tls_key=Path(_env("BEACON_TLS_KEY", str(data_dir / "tls" / "server.key"))).expanduser(),
        cherry_db=Path(
            _env("BEACON_CHERRY_DB", str(Path.home() / ".config/CherryStudio/Data/cherrystudio.sqlite"))
        ).expanduser(),
        cherry_agents_dir=Path(
            _env("BEACON_CHERRY_AGENTS_DIR", str(Path.home() / ".config/CherryStudio/Data/Agents"))
        ).expanduser(),
        agent_id=_env("BEACON_AGENT_ID", ""),
        session_id=_env("BEACON_SESSION_ID", ""),
        stale_working_seconds=_env_int("BEACON_STALE_WORKING_SECONDS", 90),
        stale_disconnect_seconds=_env_int("BEACON_STALE_DISCONNECT_SECONDS", 86400),
        message_lease_seconds=_env_int("BEACON_MESSAGE_LEASE_SECONDS", 120),
        message_max_attempts=_env_int("BEACON_MESSAGE_MAX_ATTEMPTS", 5),
        pihole_url=_env("BEACON_PIHOLE_URL", "http://192.168.1.83:8080"),
        pihole_password_file=Path(
            _env("BEACON_PIHOLE_PASSWORD_FILE", str(data_dir / "secrets" / "pihole.password"))
        ).expanduser(),
        pihole_timeout_seconds=float(_env("BEACON_PIHOLE_TIMEOUT_SECONDS", "3")),
        minecraft_dir=Path(
            _env("BEACON_MINECRAFT_DIR", str(Path.home() / "Desktop" / "NeoForgeServer"))
        ).expanduser(),
        minecraft_host=_env("BEACON_MINECRAFT_HOST", "127.0.0.1"),
        minecraft_port=_env_int("BEACON_MINECRAFT_PORT", 25565),
        minecraft_launch_script=_env("BEACON_MINECRAFT_LAUNCH_SCRIPT", "run.sh"),
        minecraft_rcon_password_file=Path(
            _env("BEACON_MINECRAFT_RCON_PASSWORD_FILE", str(data_dir / "secrets" / "minecraft.rcon"))
        ).expanduser(),
        minecraft_stop_timeout_seconds=_env_int("BEACON_MINECRAFT_STOP_TIMEOUT_SECONDS", 120),
        docker_snapshot_file=Path(
            _env("BEACON_DOCKER_SNAPSHOT_FILE", "/run/beacon/docker.json")
        ),
        screenshot_retention_days=_env_int("BEACON_SCREENSHOT_RETENTION_DAYS", 7),
        screenshot_max_bytes=_env_int("BEACON_SCREENSHOT_MAX_BYTES", 12 * 1024 * 1024),
        screenshot_max_total_bytes=_env_int(
            "BEACON_SCREENSHOT_MAX_TOTAL_BYTES", 512 * 1024 * 1024
        ),
        max_request_bytes=_env_int("BEACON_MAX_REQUEST_BYTES", 64 * 1024 * 1024),
        enable_docs=_env_bool("BEACON_ENABLE_DOCS", False),
        minecraft_launch_args=_env_list("BEACON_MINECRAFT_LAUNCH_ARGS", ["nogui"]),
        allowed_origins=_env_list("BEACON_ALLOWED_ORIGINS", []),
    )
    return settings


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings_for_tests() -> None:
    global _settings
    _settings = None
