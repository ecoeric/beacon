#!/usr/bin/env python3
"""``beacon`` command line interface.

Used by the operator (setup, diagnostics, service control) and by the AI agent itself at safe
checkpoints (``beacon agent checkpoint`` / ``ack`` / ``processed`` / ``status-set``). It only
talks to the local API over HTTPS with a token from ``data/secrets``; it never opens the
Cherry Studio database for writing and never spawns a shell.

Exit codes: 0 ok, 1 request/validation failure, 2 usage error, 3 unreachable API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .config import Settings, get_settings
from .db import get_db

TOKEN_ROLES = {
    "cli": ("read,action,admin", "operator command line"),
    "ios": ("read,action,admin", "Beacon iOS app"),
    "agent": ("agent,read", "AI agent runtime checkpoints"),
}


# --------------------------------------------------------------------------- helpers
def _colour(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def ok(text: str) -> None:
    print(f"{_colour('✓', '32')} {text}")


def fail(text: str) -> None:
    print(f"{_colour('✗', '31')} {text}")


def info(text: str) -> None:
    print(f"  {text}")


def heading(text: str) -> None:
    print(f"\n{_colour(text, '1')}")


def token_path(settings: Settings, role: str) -> Path:
    return settings.secrets_dir / f"{role}.token"


def read_token(settings: Settings, role: str) -> str:
    path = token_path(settings, role)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise SystemExit(
            f"missing {role} token at {path}\nrun: beacon init   (or: beacon token create {role})"
        )
    if not value:
        raise SystemExit(f"empty token file {path}")
    return value


class Api:
    def __init__(self, role: str = "cli") -> None:
        self.settings = get_settings()
        base = os.environ.get("BEACON_API_URL") or f"https://{self.settings.bind}:{self.settings.port}"
        ca = self.settings.tls_cert.parent / "ca.crt"
        verify: Any = str(ca) if ca.exists() else True
        self.client = httpx.Client(
            base_url=base.rstrip("/"),
            verify=verify,
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {read_token(self.settings, role)}",
                "Accept": "application/json",
            },
        )
        self.role = role

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.ConnectError as exc:
            raise SystemExit(f"cannot reach Beacon API at {self.client.base_url}: {exc}")
        except httpx.HTTPError as exc:
            raise SystemExit(f"request failed: {exc}")
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"error": "http_error", "message": response.text[:300]}
            message = payload.get("message") or payload.get("detail") or response.reason_phrase
            print(f"HTTP {response.status_code} {payload.get('error', '')}: {message}", file=sys.stderr)
            if payload.get("detail") and not isinstance(payload.get("detail"), str):
                print(json.dumps(payload["detail"], indent=2)[:2000], file=sys.stderr)
            raise SystemExit(1)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text[:4000]}

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)


def _confirm(prompt: str, assume_yes: bool) -> None:
    if assume_yes:
        return
    if not sys.stdin.isatty():
        raise SystemExit(f"refusing: {prompt} — pass --yes to confirm")
    answer = input(f"{prompt} [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise SystemExit("aborted")


def _systemctl(*args: str) -> int:
    return subprocess.call(["sudo", "-n", "systemctl", *args])


def _ago(timestamp: float | None) -> str:
    if not timestamp:
        return "n/a"
    delta = max(0, int(time.time() - timestamp))
    if delta < 90:
        return f"{delta}s ago"
    if delta < 5400:
        return f"{delta // 60}m ago"
    if delta < 172800:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


# --------------------------------------------------------------------------- commands
def cmd_init(args: argparse.Namespace) -> int:
    from . import tls as tls_module
    from .security import create_token, list_tokens

    settings = get_settings()
    heading("Beacon initialisation")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(settings.data_dir, 0o700)
    for directory in (settings.secrets_dir, settings.screenshots_dir, settings.capture_dir, settings.agent_dir, settings.logs_dir):
        directory.mkdir(parents=True, exist_ok=True)
    os.chmod(settings.secrets_dir, 0o700)
    db = get_db(settings)
    ok(f"data directory {settings.data_dir}")
    ok(f"database {settings.db_path} (schema {db.get_meta('schema_version', '?')})")

    try:
        material = tls_module.generate(settings, force=args.force_tls)
        ok(f"TLS certificate issued for {', '.join(material.ip_addresses + material.dns_names)}")
        info(f"SPKI pin: {material.pin}")
    except FileExistsError as exc:
        ok(f"TLS material present ({exc})")
        material = None

    existing = {row["name"] for row in list_tokens(db)}
    for role, (scopes, description) in TOKEN_ROLES.items():
        if role in existing:
            info(f"token '{role}' already exists ({description})")
            continue
        raw, token_info = create_token(db, settings.secrets_dir, role, scopes)
        ok(f"token '{role}' created for {description} — scopes {scopes}")
        info(f"written to {token_path(settings, role)} (0600); copy into the app, never commit it")

    pihole_file = settings.pihole_password_file
    if not pihole_file.exists():
        try:
            raw = subprocess.run(
                ["sudo", "-n", "docker", "exec", "pihole", "printenv", "FTLCONF_webserver_api_password"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            raw = ""
        if raw:
            pihole_file.parent.mkdir(parents=True, exist_ok=True)
            pihole_file.write_text(raw + "\n", encoding="utf-8")
            os.chmod(pihole_file, 0o600)
            ok("Pi-hole API password imported from the running container")
        else:
            fail("Pi-hole API password not found — set BEACON_PIHOLE_PASSWORD_FILE manually")

    ca = settings.tls_cert.parent / tls_module.CA_FILENAME
    project_ios = Path(__file__).resolve().parents[2] / "ios" / "Beacon" / "Resources" / "ca.crt"
    if ca.exists():
        project_ios.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ca, project_ios)
        ok(f"CA certificate copied into the app bundle at {project_ios}")

    heading("Next steps")
    info("deploy the service: sudo scripts/install.sh")
    info("check everything: beacon doctor")
    return 0


def cmd_tls(args: argparse.Namespace) -> int:
    from . import tls as tls_module

    settings = get_settings()
    if args.tls_action == "init":
        material = tls_module.generate(
            settings, force=args.force, extra_dns=args.dns or [], extra_ips=args.ip or []
        )
        ok(f"CA: {material.ca_cert}")
        ok(f"server certificate: {material.server_cert} (valid until {material.not_valid_after})")
        ok(f"SAN: {', '.join(material.dns_names + material.ip_addresses)}")
        ok(f"SPKI pin: {material.pin}")
        return 0
    if not settings.tls_cert.exists():
        fail("no server certificate; run beacon tls init")
        return 1
    details = tls_module.certificate_info(settings.tls_cert)
    heading("Server certificate")
    for key, value in details.items():
        info(f"{key}: {value}")
    ca = settings.tls_cert.parent / tls_module.CA_FILENAME
    if ca.exists():
        info(f"ca_fingerprint_sha256: {tls_module.ca_fingerprint(settings)}")
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    from .security import create_token, list_tokens, revoke_token

    settings = get_settings()
    db = get_db(settings)
    if args.token_action == "create":
        try:
            raw, token_info = create_token(db, settings.secrets_dir, args.name, args.scopes)
        except Exception as exc:
            fail(f"could not create token: {exc}")
            return 1
        ok(f"token '{token_info.name}' created with scopes {', '.join(sorted(token_info.scopes))}")
        info(f"file: {token_path(settings, token_info.name)}")
        info(f"value: {raw}")
        return 0
    if args.token_action == "revoke":
        if revoke_token(db, args.name):
            ok(f"token '{args.name}' revoked")
            return 0
        fail(f"no token named '{args.name}'")
        return 1
    rows = list_tokens(db)
    if not rows:
        info("no tokens yet — run beacon init")
        return 0
    heading(f"{len(rows)} token(s)")
    for row in rows:
        state = "revoked" if row["revoked_at"] else "active"
        info(
            f"{row['name']:<8} {state:<8} scopes={row['scopes']:<18} "
            f"created={_ago(row['created_at'])} last_used={_ago(row['last_used_at'])}"
        )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import tls as tls_module
    from .services import agent_runtime, minecraft

    settings = get_settings()
    heading("Beacon doctor")
    problems = 0

    def check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal problems
        if condition:
            ok(f"{label}{(' — ' + detail) if detail else ''}")
        else:
            problems += 1
            fail(f"{label}{(' — ' + detail) if detail else ''}")

    check("data directory writable", os.access(settings.data_dir, os.W_OK), str(settings.data_dir))
    db = get_db(settings)
    check("database schema", db.get_meta("schema_version") == "1", f"schema {db.get_meta('schema_version')}")
    def readable(path) -> bool:
        try:
            return path.exists() and os.access(path, os.R_OK)
        except OSError:
            return False

    check("TLS certificate", readable(settings.tls_cert) and readable(settings.tls_key), str(settings.tls_cert))
    if readable(settings.tls_cert):
        try:
            info(f"SPKI pin: {tls_module.spki_pin(settings.tls_cert)}")
        except OSError as exc:
            info(f"SPKI pin unavailable: {exc}")

    try:
        api = Api("cli")
        health = api.get("/api/v1/health")
        check("API reachable", health.get("status") == "ok", f"v{health.get('version')} tls={health.get('tls')}")
        identity = api.get("/api/v1/whoami")
        info(f"token: {identity.get('name')} scopes={','.join(identity.get('scopes', []))}")
    except SystemExit as exc:
        check("API reachable", False, str(exc))
        api = None

    active = subprocess.run(
        ["systemctl", "is-active", "beacon-api.service"], capture_output=True, text=True
    ).stdout.strip()
    check("beacon-api.service active", active == "active", active or "unknown")
    timer = subprocess.run(
        ["systemctl", "is-active", "beacon-retention.timer"], capture_output=True, text=True
    ).stdout.strip()
    check("beacon-retention.timer active", timer == "active", timer or "unknown")

    sessions = agent_runtime.list_sessions(settings)
    check("Cherry Studio database readable", bool(sessions), f"{len(sessions)} agent sessions")
    if sessions:
        latest = sessions[0]
        runtime = agent_runtime.resolve_runtime(settings, latest.id)
        check("active agent runtime process", runtime is not None, f"session {latest.id[:8]}")
        info(f"agent: {latest.agent_name or 'unknown'} · session: {latest.name[:60]}")
        status = None
        if api is not None:
            status = api.get("/api/v1/agent/status")
            info(
                f"agent state: {status['state']} · snapshot {_ago(status.get('updated_at'))} · "
                f"queue pending={status['queue']['pending']}"
            )

    docker_helper = settings.docker_read_helper
    check("docker read helper installed", docker_helper.exists(), str(docker_helper))
    if docker_helper.exists():
        probe = subprocess.run(
            ["sudo", "-n", str(docker_helper), "ps"], capture_output=True, text=True, timeout=15
        )
        check("docker read helper usable", probe.returncode == 0, probe.stderr.strip()[:120])

    if api is not None:
        pihole_status = api.get("/api/v1/pihole/status")
        check(
            "Pi-hole API",
            bool(pihole_status.get("available")),
            pihole_status.get("error") or f"blocking={pihole_status.get('blocking')}",
        )
        minecraft_status = api.get("/api/v1/minecraft/status")
        check(
            "Minecraft status probe",
            minecraft_status.get("available", False),
            f"state={minecraft_status.get('state')} version={minecraft_status.get('version')}",
        )
        retention_status = api.get("/api/v1/retention/status")
        info(
            f"screenshots: {retention_status.get('live')} live / {retention_status.get('expired')} expired · "
            f"retention {retention_status.get('retention_days')} days"
        )

    graceful, hint = minecraft.graceful_signal_supported(settings)
    info(f"minecraft graceful stop channel: {'available' if graceful else 'unavailable'} ({hint})")

    heading("Result")
    if problems:
        fail(f"{problems} check(s) failed")
        return 1
    ok("all checks passed")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    api = Api()
    data = api.get("/api/v1/summary")
    agent = data["agent"]
    heading(f"Beacon · {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"agent      {agent['state_label']}  ({agent['state']})")
    print(f"project    {agent.get('project') or '—'} · {agent.get('stage') or '—'}")
    print(f"activity   {(agent.get('activity') or '—')[:90]}")
    print(f"milestone  {(agent.get('last_milestone') or '—')[:90]}")
    print(f"next       {(agent.get('next_action') or '—')[:90]}")
    print(f"queue      pending={agent['queue']['pending']} delivered={agent['queue']['delivered']} "
          f"acknowledged={agent['queue']['acknowledged']}")
    print(f"updated    {_ago(agent.get('updated_at'))}")
    heading("services")
    for service in data["services"]:
        print(f"{service['key']:<10} {service['state']:<12} {service['summary'][:80]}")
    server = data["server"]
    if server.get("memory"):
        print(
            f"\nhost       cpu {server['cpu'].get('percent')}% · "
            f"ram {server['memory']['percent']}% · gpu {server['gpu'].get('utilization_percent')}°C "
            f"{server['gpu'].get('temperature_c')}"
        )
    milestone = data.get("latest_milestone")
    if milestone:
        print(f"milestone  #{milestone['seq']} {milestone['title']} "
              f"({len(milestone['screenshots'])} screenshots, {_ago(milestone['created_at'])})")
    activity = data.get("activity") or {}
    print(f"activity   {activity.get('unread', 0)} unread")
    return 0


def cmd_system(args: argparse.Namespace) -> int:
    api = Api()
    data = api.get("/api/v1/server/overview")
    heading("Host")
    cpu = data["cpu"]
    print(f"cpu        {cpu.get('percent')}%  load {cpu.get('load')}  temp {cpu.get('temperature_c')}°C")
    per_core = " ".join(f"{value:.0f}" for value in cpu.get("per_core", [])[:8])
    if per_core:
        print(f"per-core   {per_core}%")
    memory = data.get("memory")
    if memory:
        print(
            f"memory     {memory['used_bytes'] / 1024**3:.1f}/{memory['total_bytes'] / 1024**3:.1f} GiB "
            f"({memory['percent']}%) swap {memory['swap_percent']}%"
        )
    gpu = data["gpu"]
    if gpu.get("available"):
        print(
            f"gpu        {gpu['name']} util {gpu['utilization_percent']}% "
            f"{gpu['temperature_c']}°C vram {gpu['memory_used_bytes'] / 1024**2:.0f}/"
            f"{gpu['memory_total_bytes'] / 1024**2:.0f} MiB power {gpu['power_w']}W"
        )
    else:
        print(f"gpu        unavailable: {gpu.get('error')}")
    for disk in data.get("disks", []):
        print(
            f"disk       {disk['mount']:<20} {disk['used_bytes'] / 1024**3:6.1f} GiB used "
            f"{disk['percent']:5.1f}%  free {disk['free_bytes'] / 1024**3:6.1f} GiB"
        )
    network = data.get("network")
    if network:
        print(
            f"network    {network['interface']} ↓{network['rx_bytes_per_second'] / 1024:.0f} KiB/s "
            f"↑{network['tx_bytes_per_second'] / 1024:.0f} KiB/s"
        )
    if data.get("uptime_seconds"):
        print(f"uptime     {data['uptime_seconds'] / 86400:.1f} days")
    if data.get("docker_available"):
        heading("Containers")
        for container in data.get("docker", []):
            print(
                f"{container['name']:<16} {container['state']:<8} {container.get('health') or '-':<10} "
                f"cpu {container.get('cpu_percent') or 0:.2f}% mem {(container.get('memory_bytes') or 0) / 1024**2:.0f} MiB"
            )
    else:
        info(f"docker: {data.get('docker_error')}")
    if data.get("unavailable"):
        info("unavailable: " + "; ".join(data["unavailable"]))
    return 0


def cmd_pihole(args: argparse.Namespace) -> int:
    api = Api()
    if args.pihole_action == "block":
        enabled = args.value == "on"
        _confirm(f"turn Pi-hole blocking {args.value}", args.yes)
        result = api.post(
            "/api/v1/pihole/blocking", json={"enabled": enabled}, headers={"X-Beacon-Confirm": "pihole-blocking"}
        )
        ok(f"blocking is now {result.get('blocking')}")
        return 0
    data = api.get("/api/v1/pihole/status")
    heading("Pi-hole")
    if not data.get("available"):
        fail(f"unavailable: {data.get('error')}")
        return 1
    print(f"blocking   {data.get('blocking')}")
    print(
        f"queries    {data.get('queries_total')} total · {data.get('queries_blocked')} blocked "
        f"({data.get('percent_blocked')}%)"
    )
    container = data.get("container")
    if container:
        print(f"container  {container['name']} {container['state']} {container.get('health') or ''}")
    if data.get("top_blocked_domains"):
        heading("Top blocked")
        for entry in data["top_blocked_domains"]:
            print(f"{entry['count']:>7}  {entry['name']}")
    if data.get("top_clients"):
        heading("Top clients")
        for entry in data["top_clients"]:
            print(f"{entry['count']:>7}  {entry['name']}")
    return 0


def cmd_minecraft(args: argparse.Namespace) -> int:
    api = Api()
    action = args.minecraft_action
    if action in {"start", "stop", "restart"}:
        _confirm(f"{action} the Minecraft server", args.yes)
        payload: dict[str, Any] = {"action": action, "force": bool(getattr(args, "force", False))}
        result = api.post(
            "/api/v1/minecraft/control",
            json=payload,
            headers={"X-Beacon-Confirm": f"minecraft-{action}"},
        )
        ok(f"{action}: {json.dumps(result)[:300]}")
        return 0
    data = api.get("/api/v1/minecraft/status")
    heading("Minecraft")
    print(f"state      {data.get('state')}  online={data.get('online')}")
    print(f"version    {data.get('version')} (protocol {data.get('protocol')})")
    print(f"players    {data.get('players_online')}/{data.get('players_max')} {', '.join(data.get('players') or [])}")
    if data.get("uptime_seconds"):
        print(f"uptime     {data['uptime_seconds'] / 3600:.1f} h · pid {data.get('pid')}")
    print(f"cpu/mem    {data.get('cpu_percent')}% · {(data.get('memory_bytes') or 0) / 1024**3:.1f} GiB")
    print(f"tick       tps={data.get('tps')} mspt={data.get('mspt')} — {data.get('tick_metrics_note')}")
    controls = data.get("controls") or {}
    print(f"controls   {', '.join(controls.get('actions') or []) or 'none'} (stop via {controls.get('stop_method')})")
    if data.get("backup_note"):
        info(f"backup: {data['backup_note']}")
    elif data.get("last_backup_at"):
        info(f"last backup {_ago(data['last_backup_at'])}")
    for line in data.get("recent_errors") or []:
        info(f"error: {line[:140]}")
    return 0


AGENT_RUNTIME_ACTIONS = {"status-set", "checkpoint", "inbox", "ack", "processed", "interrupt-ack"}


def cmd_agent(args: argparse.Namespace) -> int:
    action = args.agent_action
    # Runtime actions require the agent-scope token; the operator token cannot consume the
    # queue or publish a snapshot, by design.
    api = Api("agent" if action in AGENT_RUNTIME_ACTIONS else "cli")
    if action == "status":
        data = api.get("/api/v1/agent/status")
        heading("Agent status")
        print(f"state      {data['state']} ({data['state_label']})")
        print(f"project    {data.get('project') or '—'} · {data.get('stage') or '—'}")
        print(f"activity   {data.get('activity') or '—'}")
        print(f"milestone  {data.get('last_milestone') or '—'}")
        print(f"next       {data.get('next_action') or '—'}")
        print(f"blockers   {', '.join(data.get('blockers') or []) or '—'}")
        session = data["session"]
        print(
            f"session    {session.get('id', '—')[:8]} runtime={session.get('runtime_pid')} "
            f"alive={session.get('runtime_alive')} turn={session.get('turn_running')}"
        )
        print(f"queue      pending={data['queue']['pending']} delivered={data['queue']['delivered']}")
        print(f"updated    {_ago(data.get('updated_at'))}  stale={data.get('is_stale')}")
        for item in data.get("evidence", []):
            info(f"evidence {item['source']}: {item['detail'][:90]} ({_ago(None) if item.get('age_seconds') is None else str(int(item['age_seconds'])) + 's'})")
        for note in data.get("notes", []):
            info(f"note: {note}")
        return 0
    if action == "summary":
        data = api.get("/api/v1/agent/status/summary")
        print(data["summary"])
        return 0
    if action == "status-set":
        payload: dict[str, Any] = {}
        if args.project is not None:
            payload["project"] = args.project
        if args.stage is not None:
            payload["stage"] = args.stage
        if args.activity is not None:
            payload["activity"] = args.activity
        if args.last_milestone is not None:
            payload["last_milestone"] = args.last_milestone
        if args.next_action is not None:
            payload["next_action"] = args.next_action
        if args.blocker:
            payload["blockers"] = args.blocker
        if args.awaiting_input:
            payload["awaiting_input"] = True
        if args.not_awaiting_input:
            payload["awaiting_input"] = False
        if args.state:
            payload["state_override"] = args.state
        if args.progress is not None:
            payload["progress"] = args.progress
        if args.session:
            payload["session_id"] = args.session
        data = api.put("/api/v1/agent/status", json=payload)
        ok(f"status updated: {data['state']} · {data.get('activity') or data.get('project')}")
        return 0
    if action == "checkpoint":
        data = api.post("/api/v1/agent/checkpoint")
        delivered = data.get("delivered") or []
        interrupts = data.get("interrupts") or []
        print(f"checkpoint {time.strftime('%Y-%m-%d %H:%M:%S')} · {len(delivered)} message(s), "
              f"{len(interrupts)} interrupt(s), {data.get('pending_remaining', 0)} still queued")
        for message in delivered:
            heading(f"#{message['seq']} {message['kind']} · {message['id'][:8]} · {_ago(message['created_at'])}")
            print(message["body"])
            info(f"ack: beacon agent ack {message['id']}   processed: beacon agent processed {message['id']}")
        for interrupt in interrupts:
            heading(f"interrupt {interrupt['mode']} · {interrupt['id'][:8]} · {interrupt['status']}")
            info(interrupt.get("reason") or "no reason given")
            info(f"ack: beacon agent interrupt-ack {interrupt['id']}")
        if not delivered and not interrupts:
            info("nothing to deliver")
        return 0
    if action == "inbox":
        args.agent_action = "checkpoint"
        return cmd_agent(args)
    if action in {"ack", "processed"}:
        endpoint = "ack" if action == "ack" else "processed"
        data = api.post(f"/api/v1/agent/messages/{args.message_id}/{endpoint}", json={"note": args.note})
        ok(f"message {data['id'][:8]} is now {data['status']}")
        return 0
    if action == "interrupt":
        _confirm(f"interrupt the agent ({args.mode})", args.yes)
        data = api.post(
            "/api/v1/agent/interrupt",
            json={"mode": args.mode, "reason": args.reason or ""},
            headers={"X-Beacon-Confirm": "agent-interrupt"},
        )
        ok(f"interrupt {data['status']} · mode={data['mode']} pid={data.get('pid')}")
        for item in data.get("evidence") or []:
            info(item)
        return 0
    if action == "interrupt-ack":
        data = api.post(f"/api/v1/agent/interrupts/{args.interrupt_id}/ack", json={"note": args.note})
        ok(f"interrupt {data['id'][:8]} acknowledged ({data['status']})")
        return 0
    if action == "interrupts":
        rows = api.get("/api/v1/agent/interrupts")
        if not rows:
            info("no interrupts recorded")
            return 0
        for row in rows:
            print(
                f"{time.strftime('%m-%d %H:%M', time.localtime(row['requested_at']))} "
                f"{row['mode']:<10} {row['status']:<12} pid={row.get('pid')} {row.get('error') or ''}"
            )
        return 0
    raise SystemExit(f"unknown agent action {action}")


def cmd_queue(args: argparse.Namespace) -> int:
    api = Api()
    if args.queue_action == "cancel":
        data = api.delete(f"/api/v1/agent/messages/{args.message_id}")
        ok(f"message {data['id'][:8]} cancelled")
        return 0
    if args.queue_action == "stats":
        data = api.get("/api/v1/agent/queue")
        print(json.dumps(data, indent=2))
        return 0
    rows = api.get("/api/v1/agent/messages", params={"limit": args.limit})
    if not rows:
        info("queue is empty")
        return 0
    for row in rows:
        stamp = time.strftime("%m-%d %H:%M", time.localtime(row["created_at"]))
        print(
            f"#{row['seq']:<3} {stamp}  {row['kind']:<10} {row['status']:<13} "
            f"{row['id'][:8]}  {row['body'][:80].replace(chr(10), ' ')}"
        )
    return 0


def cmd_milestones(args: argparse.Namespace) -> int:
    api = Api()
    if args.milestones_action == "add":
        attach = args.attach or []
        for capture_id in attach:
            if not re.fullmatch(r"[0-9a-f]{32}", capture_id):
                fail(f"'{capture_id}' is not a valid capture id (expected 32 hex characters)")
                info("copy it from the id printed by: beacon screenshot capture --source …")
                return 1
        payload = {
            "title": args.title,
            "summary": args.summary or "",
            "changes": args.change or [],
            "phase": args.phase or "",
            "screenshots": attach,
        }
        data = api.post("/api/v1/milestones", json=payload)
        ok(f"milestone #{data['seq']} recorded: {data['title']} ({len(data['screenshots'])} screenshots)")
        return 0
    rows = api.get("/api/v1/milestones", params={"limit": args.limit})
    if not rows:
        info("no milestones yet")
        return 0
    for row in rows:
        stamp = time.strftime("%m-%d %H:%M", time.localtime(row["created_at"]))
        expired = f" expired={row['expired_screenshots']}" if row.get("expired_screenshots") else ""
        print(
            f"#{row['seq']:<2} {stamp}  {row['title'][:60]:<60} "
            f"shots={len(row['screenshots'])}{expired}"
        )
    return 0


def cmd_screenshot(args: argparse.Namespace) -> int:
    api = Api()
    if args.screenshot_action == "capture":
        payload = {
            "source": args.source,
            "title": args.title or "",
            "command": args.command,
            "path": args.path,
            "caption": args.caption or "",
        }
        data = api.post("/api/v1/screenshots/capture", json=payload)
        ok(f"captured {data['source']} → {data['capture_id']} ({data['bytes']} bytes, preview {data['preview_url']})")
        info(f"attach with: beacon milestones add --title '…' --attach {data['capture_id']}")
        return 0
    if args.screenshot_action == "delete":
        data = api.delete(f"/api/v1/screenshots/{args.screenshot_id}")
        ok(f"screenshot {data['id'][:8]} deleted (expired={data['expired']})")
        return 0
    if args.screenshot_action == "retention":
        if args.run_sweep:
            data = api.post("/api/v1/retention/run", params={"dry_run": bool(args.dry_run)})
            ok(
                f"retention: deleted {data['deleted_screenshots']} rows / {data['deleted_files']} files, "
                f"orphans {data['orphan_files_removed']}, kept {data['kept']}"
            )
            for error in data.get("errors") or []:
                info(f"note: {error}")
            return 0
        data = api.get("/api/v1/retention/status")
        print(json.dumps(data, indent=2))
        return 0
    raise SystemExit("unknown screenshot action")


def cmd_retention(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.retention_action == "status":
        from .services import retention

        db = get_db(settings)
        print(json.dumps(retention.storage_summary(settings, db), indent=2))
        return 0
    from .services import retention

    db = get_db(settings)
    result = retention.run(
        settings, db, dry_run=bool(args.dry_run), actor="cli-retention"
    )
    ok(
        f"retention: deleted {result.deleted_screenshots} rows / {result.deleted_files} files · "
        f"orphans {result.orphan_files_removed} · kept {result.kept}"
    )
    for error in result.errors:
        info(f"note: {error}")
    return 0


def cmd_api_get(args: argparse.Namespace) -> int:
    api = Api()
    data = api.get(args.path)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def cmd_service(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.service_action == "status":
        print("beacon-api.service:")
        _systemctl("status", "beacon-api.service", "--no-pager", "--lines=12")
        print("\nbeacon-retention.timer:")
        _systemctl("status", "beacon-retention.timer", "--no-pager", "--lines=6")
        return 0
    if args.service_action == "start":
        return _systemctl("start", "beacon-api.service", "beacon-retention.timer")
    if args.service_action == "stop":
        return _systemctl("stop", "beacon-api.service")
    if args.service_action == "restart":
        return _systemctl("restart", "beacon-api.service")
    if args.service_action == "logs":
        return subprocess.call(
            ["sudo", "-n", "journalctl", "-u", "beacon-api.service", "-n", str(args.lines), "--no-pager"]
        )
    raise SystemExit(f"unknown service action; settings port {settings.port}")


def cmd_backup(args: argparse.Namespace) -> int:
    settings = get_settings()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = Path(args.to).expanduser() if args.to else settings.data_dir / "backups" / stamp
    target.mkdir(parents=True, exist_ok=True)
    import sqlite3

    db = get_db(settings)
    destination = target / "beacon.sqlite"
    with sqlite3.connect(settings.db_path) as source, sqlite3.connect(destination) as copy:
        source.backup(copy)
    for name in ("secrets", "tls"):
        source_dir = settings.data_dir / name
        if source_dir.exists():
            shutil.copytree(source_dir, target / name, dirs_exist_ok=True)
    if settings.screenshots_dir.exists():
        shutil.copytree(settings.screenshots_dir, target / "screenshots", dirs_exist_ok=True)
    ok(f"backup written to {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="beacon", description="Beacon server dashboard CLI")
    parser.add_argument("--version", action="version", version=f"beacon {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialise data directory, TLS material and tokens")
    init.add_argument("--force-tls", action="store_true")
    init.set_defaults(func=cmd_init)

    doctor = sub.add_parser("doctor", help="check the whole deployment")
    doctor.set_defaults(func=cmd_doctor)

    tls_parser = sub.add_parser("tls", help="TLS material")
    tls_sub = tls_parser.add_subparsers(dest="tls_action", required=True)
    tls_init = tls_sub.add_parser("init")
    tls_init.add_argument("--force", action="store_true")
    tls_init.add_argument("--dns", action="append")
    tls_init.add_argument("--ip", action="append")
    tls_show = tls_sub.add_parser("show", help="show certificate details and pin")
    tls_init.set_defaults(func=cmd_tls)
    tls_show.set_defaults(func=cmd_tls, tls_action="show")

    token_parser = sub.add_parser("token", help="manage API tokens")
    token_sub = token_parser.add_subparsers(dest="token_action", required=True)
    token_create = token_sub.add_parser("create")
    token_create.add_argument("name")
    token_create.add_argument("--scopes", default="read")
    token_list = token_sub.add_parser("list")
    token_revoke = token_sub.add_parser("revoke")
    token_revoke.add_argument("name")
    token_create.set_defaults(func=cmd_token)
    token_list.set_defaults(func=cmd_token, token_action="list")
    token_revoke.set_defaults(func=cmd_token)

    summary = sub.add_parser("summary", help="compact dashboard from the API")
    summary.set_defaults(func=cmd_summary)

    system_cmd = sub.add_parser("system", help="host metrics")
    system_sub = system_cmd.add_subparsers(dest="system_action", required=True)
    system_show = system_sub.add_parser("show")
    system_show.set_defaults(func=cmd_system)

    pihole_cmd = sub.add_parser("pihole", help="Pi-hole status and blocking")
    pihole_sub = pihole_cmd.add_subparsers(dest="pihole_action", required=True)
    pihole_status = pihole_sub.add_parser("status")
    pihole_block = pihole_sub.add_parser("block")
    pihole_block.add_argument("value", choices=["on", "off"])
    pihole_block.add_argument("--yes", action="store_true")
    pihole_status.set_defaults(func=cmd_pihole)
    pihole_block.set_defaults(func=cmd_pihole)

    minecraft_cmd = sub.add_parser("minecraft", help="Minecraft status and controls")
    minecraft_sub = minecraft_cmd.add_subparsers(dest="minecraft_action", required=True)
    for name in ("status", "start", "stop", "restart"):
        entry = minecraft_sub.add_parser(name)
        entry.add_argument("--yes", action="store_true")
        entry.add_argument("--force", action="store_true")
        entry.set_defaults(func=cmd_minecraft)

    agent_cmd = sub.add_parser("agent", help="agent status, queue checkpoints, interrupt")
    agent_sub = agent_cmd.add_subparsers(dest="agent_action", required=True)
    agent_sub.add_parser("status").set_defaults(func=cmd_agent)
    agent_sub.add_parser("summary").set_defaults(func=cmd_agent)
    agent_sub.add_parser("inbox").set_defaults(func=cmd_agent)
    agent_sub.add_parser("checkpoint").set_defaults(func=cmd_agent)
    agent_sub.add_parser("interrupts").set_defaults(func=cmd_agent)
    status_set = agent_sub.add_parser("status-set")
    status_set.add_argument("--project")
    status_set.add_argument("--stage")
    status_set.add_argument("--activity")
    status_set.add_argument("--last-milestone")
    status_set.add_argument("--next-action")
    status_set.add_argument("--blocker", action="append")
    status_set.add_argument("--awaiting-input", action="store_true")
    status_set.add_argument("--not-awaiting-input", action="store_true")
    status_set.add_argument("--state", choices=["idle", "working", "completed", "failed"])
    status_set.add_argument("--progress", type=float)
    status_set.add_argument("--session")
    status_set.set_defaults(func=cmd_agent)
    ack = agent_sub.add_parser("ack")
    ack.add_argument("message_id")
    ack.add_argument("--note")
    ack.set_defaults(func=cmd_agent)
    processed = agent_sub.add_parser("processed")
    processed.add_argument("message_id")
    processed.add_argument("--note")
    processed.set_defaults(func=cmd_agent)
    interrupt = agent_sub.add_parser("interrupt")
    interrupt.add_argument("--mode", choices=["signal", "checkpoint"], default="signal")
    interrupt.add_argument("--reason")
    interrupt.add_argument("--yes", action="store_true")
    interrupt.set_defaults(func=cmd_agent)
    interrupt_ack = agent_sub.add_parser("interrupt-ack")
    interrupt_ack.add_argument("interrupt_id")
    interrupt_ack.add_argument("--note")
    interrupt_ack.set_defaults(func=cmd_agent)

    queue_cmd = sub.add_parser("queue", help="message queue")
    queue_sub = queue_cmd.add_subparsers(dest="queue_action", required=True)
    queue_list = queue_sub.add_parser("list")
    queue_list.add_argument("--limit", type=int, default=20)
    queue_cancel = queue_sub.add_parser("cancel")
    queue_cancel.add_argument("message_id")
    queue_stats = queue_sub.add_parser("stats")
    queue_list.set_defaults(func=cmd_queue)
    queue_cancel.set_defaults(func=cmd_queue)
    queue_stats.set_defaults(func=cmd_queue)

    milestones_cmd = sub.add_parser("milestones", help="milestone history")
    milestones_sub = milestones_cmd.add_subparsers(dest="milestones_action", required=True)
    milestones_list = milestones_sub.add_parser("list")
    milestones_list.add_argument("--limit", type=int, default=20)
    milestones_add = milestones_sub.add_parser("add")
    milestones_add.add_argument("--title", required=True)
    milestones_add.add_argument("--summary")
    milestones_add.add_argument("--change", action="append")
    milestones_add.add_argument("--phase")
    milestones_add.add_argument("--attach", action="append")
    milestones_list.set_defaults(func=cmd_milestones)
    milestones_add.set_defaults(func=cmd_milestones)

    shot_cmd = sub.add_parser("screenshot", help="capture and retention")
    shot_sub = shot_cmd.add_subparsers(dest="screenshot_action", required=True)
    shot_capture = shot_sub.add_parser("capture")
    shot_capture.add_argument("--source", choices=["text", "api", "window", "file"], default="text")
    shot_capture.add_argument("--command")
    shot_capture.add_argument("--path")
    shot_capture.add_argument("--title")
    shot_capture.add_argument("--caption")
    shot_delete = shot_sub.add_parser("delete")
    shot_delete.add_argument("screenshot_id")
    shot_retention = shot_sub.add_parser("retention")
    shot_retention.add_argument("--run-sweep", action="store_true")
    shot_retention.add_argument("--dry-run", action="store_true")
    shot_capture.set_defaults(func=cmd_screenshot)
    shot_delete.set_defaults(func=cmd_screenshot)
    shot_retention.set_defaults(func=cmd_screenshot)

    retention_cmd = sub.add_parser("retention", help="screenshot retention sweep")
    retention_sub = retention_cmd.add_subparsers(dest="retention_action", required=True)
    retention_run = retention_sub.add_parser("run")
    retention_run.add_argument("--dry-run", action="store_true")
    retention_run.add_argument("--local", action="store_true", help="run in-process (no API needed)")
    retention_status = retention_sub.add_parser("status")
    retention_run.set_defaults(func=cmd_retention)
    retention_status.set_defaults(func=cmd_retention)

    api_get = sub.add_parser("api-get", help="GET an allowed API path and print JSON")
    api_get.add_argument("path")
    api_get.set_defaults(func=cmd_api_get)

    service_cmd = sub.add_parser("service", help="systemd service and logs")
    service_sub = service_cmd.add_subparsers(dest="service_action", required=True)
    for name in ("status", "start", "stop", "restart"):
        service_sub.add_parser(name).set_defaults(func=cmd_service)
    logs = service_sub.add_parser("logs")
    logs.add_argument("--lines", type=int, default=60)
    logs.set_defaults(func=cmd_service)

    backup = sub.add_parser("backup", help="backup database, secrets, TLS and screenshots")
    backup.add_argument("--to")
    backup.set_defaults(func=cmd_backup)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except UnicodeEncodeError:
        fail("the request contained characters that cannot be encoded; check the arguments")
        return 1


if __name__ == "__main__":
    sys.exit(main())
