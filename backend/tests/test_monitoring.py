"""Host, Pi-hole, Minecraft and Docker monitoring behaviour (no real services touched)."""

from __future__ import annotations

import time

from beacon.db import get_db
from beacon.services import notifications, system_metrics


def test_server_overview_reads_real_host_metrics(client, auth):
    response = client.get("/api/v1/server/overview", headers=auth())
    assert response.status_code == 200
    payload = response.json()
    assert payload["cpu"]["model"]
    assert payload["cpu"]["cores"] >= 1
    assert payload["memory"]["total_bytes"] > 0
    assert payload["memory"]["percent"] >= 0
    assert payload["disks"], "at least the root filesystem should be reported"
    root = [disk for disk in payload["disks"] if disk["mount"] == "/"]
    assert root and root[0]["total_bytes"] > 0
    assert payload["docker_available"] is False
    assert payload["docker_error"]
    assert payload["gpu"]["available"] in (True, False)
    if not payload["gpu"]["available"]:
        assert payload["gpu"]["error"]


def test_minecraft_status_reports_stopped_with_start_available(client, auth):
    payload = client.get("/api/v1/minecraft/status", headers=auth()).json()
    assert payload["state"] == "stopped"
    assert payload["online"] is False
    assert payload["players_online"] is None
    assert payload["tps"] is None and payload["mspt"] is None
    assert payload["tick_metrics_note"]
    assert "start" in payload["controls"]["actions"]
    assert "stop" not in payload["controls"]["actions"]


def test_minecraft_control_requires_confirmation(client, auth):
    response = client.post(
        "/api/v1/minecraft/control", json={"action": "start"}, headers=auth("admin")
    )
    assert response.status_code == 428


def test_minecraft_control_errors_are_structured(client, auth):
    response = client.post(
        "/api/v1/minecraft/control",
        json={"action": "start"},
        headers=auth("admin", **{"X-Beacon-Confirm": "minecraft-start"}),
    )
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "no_launch_script"
    assert "launch script" in body["message"]


def test_minecraft_stop_refuses_when_not_running(client, auth):
    response = client.post(
        "/api/v1/minecraft/control",
        json={"action": "stop"},
        headers=auth("admin", **{"X-Beacon-Confirm": "minecraft-stop"}),
    )
    assert response.status_code == 409
    assert response.json()["error"] == "not_running"


def test_minecraft_logs_missing_file(client, auth):
    response = client.get("/api/v1/minecraft/logs", headers=auth())
    assert response.status_code == 404


def test_pihole_status_reports_unreachable_without_faking_numbers(client, auth):
    payload = client.get("/api/v1/pihole/status", headers=auth()).json()
    assert payload["available"] is False
    assert payload["online"] is False
    assert payload["queries_total"] is None
    assert payload["error"]


def test_pihole_blocking_requires_confirmation(client, auth):
    response = client.post(
        "/api/v1/pihole/blocking", json={"enabled": False}, headers=auth("admin")
    )
    assert response.status_code == 428


def test_pihole_blocking_reports_unreachable(client, auth, env):
    env.pihole_password_file.parent.mkdir(parents=True, exist_ok=True)
    env.pihole_password_file.write_text("dummy-password\n", encoding="utf-8")
    response = client.post(
        "/api/v1/pihole/blocking",
        json={"enabled": False},
        headers=auth("admin", **{"X-Beacon-Confirm": "pihole-blocking"}),
    )
    assert response.status_code == 503
    assert response.json()["error"] == "unreachable"


def test_docker_endpoint_reports_503_without_helper(client, auth):
    response = client.get("/api/v1/docker/containers", headers=auth())
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "docker_unavailable"


def test_dashboard_summary_composes_everything(client, auth):
    payload = client.get("/api/v1/summary", headers=auth()).json()
    assert payload["agent"]["state"] in {
        "idle",
        "working",
        "waiting_for_input",
        "waiting_for_messages",
        "completed",
        "interrupted",
        "failed",
        "disconnected",
        "unknown",
    }
    keys = {service["key"] for service in payload["services"]}
    assert {"api", "agent", "pihole", "minecraft", "server", "docker"} <= keys
    pihole_service = next(service for service in payload["services"] if service["key"] == "pihole")
    assert pihole_service["state"] == "down"
    minecraft_service = next(service for service in payload["services"] if service["key"] == "minecraft")
    assert minecraft_service["state"] == "down"
    assert payload["activity"]["unread"] == 0


def test_transitions_emit_one_notification_per_edge(env):
    db = get_db(env)
    first = notifications.transition(
        db,
        key="pihole",
        online=False,
        offline_notification=("pihole_offline", "Pi-hole down", "unreachable"),
        online_notification=("pihole_online", "Pi-hole up", "responding"),
    )
    assert first is None  # first observation only records state
    second = notifications.transition(
        db,
        key="pihole",
        online=True,
        offline_notification=("pihole_offline", "Pi-hole down", "unreachable"),
        online_notification=("pihole_online", "Pi-hole up", "responding"),
    )
    assert second is not None
    feed = notifications.feed(db)
    assert feed.unread == 1
    assert feed.items[0].title == "Pi-hole up"
    again = notifications.transition(
        db,
        key="pihole",
        online=True,
        offline_notification=("pihole_offline", "Pi-hole down", "unreachable"),
        online_notification=("pihole_online", "Pi-hole up", "responding"),
    )
    assert again is None


def test_activity_can_be_marked_read(client, auth, env):
    db = get_db(env)
    notification_id = notifications.notify(
        db, kind="test", severity="info", title="hello", body="world"
    )
    feed = client.get("/api/v1/activity", headers=auth()).json()
    assert feed["unread"] == 1
    assert client.post(f"/api/v1/activity/{notification_id}/read", headers=auth()).json() == {"read": True}
    assert client.get("/api/v1/activity", headers=auth()).json()["unread"] == 0
    assert client.post("/api/v1/activity/read-all", headers=auth()).json()["read"] == 0


def test_sampler_produces_cpu_delta():
    sampler = system_metrics.Sampler(interval=0.2)
    sampler.sample()
    time.sleep(0.35)
    sampler.sample()
    state = sampler.state()
    assert state["cpu_percent"] is None or state["cpu_percent"] >= 0
    sampler.stop()
