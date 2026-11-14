#!/usr/bin/env python3
"""Live integration smoke test for a deployed Beacon instance.

Runs against the real server, the real Pi-hole and the real Minecraft installation. It never
stops a service, never changes Pi-hole blocking and never signals the agent runtime (only the
cooperative "checkpoint" interrupt mode is exercised, and it is acknowledged immediately).

    python3 scripts/smoke_test.py [--base-url https://192.168.1.83:8091]

Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import ssl
import subprocess
import sys
import time
import uuid

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CA = DATA / "tls" / "ca.crt"

PASS = 0
FAIL = 0
NOTES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"✓ {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"✗ {name}" + (f" — {detail}" if detail else ""))


def token(name: str) -> str:
    return (DATA / "secrets" / f"{name}.token").read_text(encoding="utf-8").strip()


def client(base_url: str, role: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        verify=str(CA),
        timeout=30.0,
        headers={"Authorization": f"Bearer {token(role)}", "Accept": "application/json"},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://192.168.1.83:8091")
    args = parser.parse_args()
    base = args.base_url

    print(f"Beacon smoke test against {base}\n")

    # --- transport & auth ------------------------------------------------
    with httpx.Client(base_url=base, verify=str(CA), timeout=10) as anon:
        health = anon.get("/api/v1/health")
        check("TLS handshake with the private CA", health.status_code == 200, health.status_code == 200 and health.text[:60] or "")
        check("health reports ok", health.json().get("status") == "ok")
        check("health reports TLS enabled", health.json().get("tls") is True)
        check("unauthenticated read is rejected", anon.get("/api/v1/summary").status_code == 401)
        check("docs are not exposed", anon.get("/docs").status_code == 404)

    admin = client(base, "ios")
    cli = client(base, "cli")
    agent = client(base, "agent")

    identity = cli.get("/api/v1/whoami").json()
    check("token identity resolves", identity.get("name") == "cli", json.dumps(identity.get("scopes")))

    # --- dashboard -------------------------------------------------------
    summary_response = cli.get("/api/v1/summary")
    check("summary returns 200", summary_response.status_code == 200)
    summary = summary_response.json()
    check("agent card present", bool(summary["agent"]["state"]), summary["agent"]["state"])
    check("services list complete", {s["key"] for s in summary["services"]} >= {"pihole", "minecraft", "server"})
    check("host metrics present", summary["server"]["memory"]["total_bytes"] > 0)
    cli_token = token("cli")
    check("no secret token value in the payload", cli_token not in json.dumps(summary))
    check("data age is reported", summary["data_age_seconds"] is not None, f"{summary['data_age_seconds']}s")

    # --- Status action (read-only) --------------------------------------
    status_before = cli.get("/api/v1/agent/status").json()
    first = cli.get("/api/v1/agent/status/summary").json()
    second = cli.get("/api/v1/agent/status/summary").json()
    status_after = cli.get("/api/v1/agent/status").json()
    sentences = re.findall(r"[.!?](?=\s|$)", first["summary"])
    check("status summary is deterministic", first["summary"] == second["summary"])
    check("status summary is 1-3 sentences", 1 <= len(sentences) <= 3, f"{len(sentences)} sentences")
    check("status says it is deterministic", first.get("deterministic") is True)
    check("status did not mutate the snapshot", status_before["updated_at"] == status_after["updated_at"])
    check("status did not consume queue messages", status_before["queue"]["pending"] == status_after["queue"]["pending"])
    check("status did not start a turn", status_after["session"]["turn_running"] == status_before["session"]["turn_running"])

    # --- message queue ---------------------------------------------------
    unique = uuid.uuid4().hex[:10]
    queued = cli.post(
        "/api/v1/agent/messages",
        json={
            "text": "Beacon smoke test — no action required.",
            "idempotency_key": f"smoke-{unique}",
            "forward": False,
        },
    )
    duplicate = cli.post(
        "/api/v1/agent/messages",
        json={
            "text": "Beacon smoke test — no action required.",
            "idempotency_key": f"smoke-{unique}",
            "forward": False,
        },
    )
    check("message queued", queued.status_code == 201, queued.json().get("id", "")[:8])
    check("idempotency prevents duplicates", duplicate.json()["id"] == queued.json()["id"])
    message_id = queued.json()["id"]
    pending = cli.get("/api/v1/agent/status").json()["queue"]["pending"]
    check("queue reports the pending message", pending >= 1, f"pending={pending}")

    checkpoint = agent.post("/api/v1/agent/checkpoint").json()
    delivered_ids = [item["id"] for item in checkpoint["delivered"]]
    check("checkpoint delivers the queued message", message_id in delivered_ids)
    acknowledged = agent.post(f"/api/v1/agent/messages/{message_id}/ack", json={"note": "smoke test"}).json()
    check("agent can acknowledge", acknowledged["status"] == "acknowledged")
    processed = agent.post(f"/api/v1/agent/messages/{message_id}/processed", json={"note": "smoke test done"}).json()
    check("agent can mark processed", processed["status"] == "processed")
    check(
        "UI token cannot consume the queue",
        admin.post("/api/v1/agent/checkpoint").status_code == 403,
    )

    continue_message = cli.post(
        "/api/v1/agent/continue", json={"note": "smoke test", "forward": False}
    ).json()
    cancelled = cli.delete(f"/api/v1/agent/messages/{continue_message['id']}")
    check("Continue works without text and can be cancelled", cancelled.json()["status"] == "cancelled")

    # --- interrupt (safe, cooperative) ----------------------------------
    interrupt = admin.post(
        "/api/v1/agent/interrupt",
        json={"mode": "checkpoint", "reason": "smoke test"},
        headers={"X-Beacon-Confirm": "agent-interrupt"},
    )
    if interrupt.status_code == 429:
        check("interrupt rate limiter active (repeat within 15s)", True, "skipping delivery check")
    else:
        check("checkpoint interrupt accepted", interrupt.status_code == 200, interrupt.text[:80])
        interrupt_body = interrupt.json()
        pending_interrupts = agent.get("/api/v1/agent/interrupts/pending").json()
        check(
            "checkpoint interrupt reaches the agent",
            any(item["id"] == interrupt_body["id"] for item in pending_interrupts),
        )
        acked = agent.post(
            f"/api/v1/agent/interrupts/{interrupt_body['id']}/ack", json={"note": "smoke test"}
        ).json()
        check("interrupt can be acknowledged", acked["status"] == "acknowledged")
    check(
        "interrupt requires confirmation header",
        admin.post("/api/v1/agent/interrupt", json={"mode": "checkpoint"}).status_code == 428,
    )

    # --- screenshots -----------------------------------------------------
    capture = cli.post(
        "/api/v1/screenshots/capture",
        json={"source": "text", "command": "doctor", "caption": "smoke test capture"},
    )
    check("text capture produces a PNG", capture.status_code == 200, capture.text[:100])
    capture_body = capture.json()
    preview = cli.get(capture_body["preview_url"])
    check("capture preview is a PNG", preview.status_code == 200 and preview.content[:4] == b"\x89PNG")
    forbidden = cli.post(
        "/api/v1/screenshots/capture", json={"source": "text", "command": "rm -rf /"}
    )
    check("arbitrary commands are rejected", forbidden.status_code == 422)

    milestones = cli.get("/api/v1/milestones").json()
    check("milestone history is readable", isinstance(milestones, list), f"{len(milestones)} milestone(s)")
    if milestones:
        latest = milestones[0]
        check(
            "milestones carry screenshot metadata",
            "screenshots" in latest and "expired_screenshots" in latest,
            f"{len(latest['screenshots'])} live",
        )

    retention = cli.get("/api/v1/retention/status").json()
    check("retention window is 7 days", retention.get("retention_days") == 7)
    check("retention timer is scheduled", "03:41" in retention.get("timer_hint", ""))
    dry_run = cli.post("/api/v1/retention/run", params={"dry_run": "true"})
    check("retention dry run works", dry_run.status_code == 200)

    # --- Pi-hole ---------------------------------------------------------
    pihole = cli.get("/api/v1/pihole/status").json()
    check("Pi-hole API reachable", pihole["available"], pihole.get("error") or "")
    if pihole["available"]:
        check("Pi-hole blocking state reported", pihole["blocking"] in {"enabled", "disabled"}, pihole["blocking"])
        check("Pi-hole query counts reported", isinstance(pihole["queries_total"], int), f"{pihole['queries_total']} queries")
        check("Pi-hole container health reported", pihole["container"] is not None and pihole["container"].get("health") == "healthy")
        check("top blocked domains present", len(pihole["top_blocked_domains"]) > 0)
        check("upstream DNS reported", len(pihole["upstreams"]) > 0)
    check(
        "blocking change requires confirmation",
        admin.post("/api/v1/pihole/blocking", json={"enabled": False}).status_code == 428,
    )

    # --- Minecraft -------------------------------------------------------
    minecraft = cli.get("/api/v1/minecraft/status").json()
    check("Minecraft status available", minecraft["available"])
    check("Minecraft online state detected", minecraft["state"] in {"running", "stopped", "unreachable"}, minecraft["state"])
    running = minecraft["state"] == "running"
    check(
        "Minecraft version via server-list ping",
        (not running) or bool(minecraft["version"]),
        minecraft["version"] or "server stopped",
    )
    check(
        "Minecraft player count reported",
        (not running) or minecraft["players_online"] is not None,
        f"{minecraft['players_online']} online" if running else "server stopped",
    )
    check(
        "Minecraft process metrics reported",
        (not running) or (minecraft["pid"] is not None and minecraft["memory_bytes"] is not None),
        f"pid {minecraft['pid']}" if running else "server stopped",
    )
    check("tick metrics are not fabricated", minecraft["tps"] is None and bool(minecraft["tick_metrics_note"]), minecraft["tick_metrics_note"][:60])
    logs = cli.get("/api/v1/minecraft/logs", params={"lines": 20})
    check("Minecraft logs are readable", logs.status_code == 200 and len(logs.json()["lines"]) == 20)
    check(
        "Minecraft control requires confirmation",
        admin.post("/api/v1/minecraft/control", json={"action": "start"}).status_code == 428,
    )

    # --- Docker ----------------------------------------------------------
    containers = cli.get("/api/v1/docker/containers")
    check("Docker monitor works read-only", containers.status_code == 200, f"{len(containers.json())} containers")
    if containers.status_code == 200:
        check("Pi-hole container listed", any(c["name"] == "pihole" for c in containers.json()))

    # --- capabilities ----------------------------------------------------
    capabilities = cli.get("/api/v1/capabilities").json()
    check("capabilities describe delivery mode", capabilities["message_delivery"]["mode"] == "checkpoint")
    check("capabilities describe interrupt modes", "signal" in capabilities["interrupt"]["modes"])
    check("push notifications reported as not implemented", capabilities["notifications"]["push"] is False)

    print()
    if FAIL:
        print(f"{FAIL} check(s) failed, {PASS} passed")
        return 1
    print(f"all {PASS} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
