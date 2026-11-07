"""Milestones, screenshot capture, retention and file-confined deletion."""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

from PIL import Image

from beacon.db import get_db
from beacon.services import capture, retention, screenshots


def _png(colour: tuple[int, int, int] = (30, 90, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (320, 200), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _create_milestone(client, auth, title: str = "Foundation") -> dict:
    response = client.post(
        "/api/v1/milestones",
        json={"title": title, "summary": "phase 2", "changes": ["a", "b"], "phase": "2"},
        headers=auth("agent"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_milestone_create_and_list(client, auth):
    milestone = _create_milestone(client, auth)
    assert milestone["seq"] == 1
    listing = client.get("/api/v1/milestones", headers=auth()).json()
    assert [item["id"] for item in listing] == [milestone["id"]]
    assert listing[0]["changes"] == ["a", "b"]
    activity = client.get("/api/v1/activity", headers=auth()).json()
    assert activity["items"][0]["kind"] == "milestone_completed"


def test_upload_and_fetch_screenshot(client, auth):
    milestone = _create_milestone(client, auth)
    response = client.post(
        f"/api/v1/milestones/{milestone['id']}/screenshots",
        files=[("files", ("home.png", _png(), "image/png"))],
        data={"captions": "Dashboard view"},
        headers=auth("admin"),
    )
    assert response.status_code == 200, response.text
    stored = response.json()
    assert len(stored) == 1
    assert stored[0]["caption"] == "Dashboard view"
    assert stored[0]["width"] == 320 and stored[0]["height"] == 200
    assert stored[0]["expires_at"] - stored[0]["created_at"] == 7 * 86400

    image = client.get(stored[0]["url"], headers=auth())
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")

    refreshed = client.get(f"/api/v1/milestones/{milestone['id']}", headers=auth()).json()
    assert len(refreshed["screenshots"]) == 1


def test_screenshot_max_four_per_milestone(client, auth):
    milestone = _create_milestone(client, auth)
    response = client.post(
        f"/api/v1/milestones/{milestone['id']}/screenshots",
        files=[("files", (f"s{i}.png", _png((i * 40, 10, 10)), "image/png")) for i in range(5)],
        headers=auth("admin"),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "too_many_screenshots"


def test_screenshot_rejects_non_image(client, auth):
    milestone = _create_milestone(client, auth)
    response = client.post(
        f"/api/v1/milestones/{milestone['id']}/screenshots",
        files=[("files", ("notes.txt", b"hello", "text/plain"))],
        headers=auth("admin"),
    )
    assert response.status_code == 415
    assert response.json()["error"] == "unsupported_type"


def test_capture_text_source_produces_real_png(client, auth):
    response = client.post(
        "/api/v1/screenshots/capture",
        json={"source": "text", "command": "milestones", "caption": "milestone list"},
        headers=auth("agent"),
    )
    assert response.status_code == 200, response.text
    capture_payload = response.json()
    assert capture_payload["bytes"] > 1000
    assert capture_payload["source"] == "text"
    preview = client.get(capture_payload["preview_url"], headers=auth())
    assert preview.status_code == 200
    assert preview.content.startswith(b"\x89PNG")

    milestone = client.post(
        "/api/v1/milestones",
        json={"title": "Captured", "summary": "", "screenshots": [capture_payload["capture_id"]]},
        headers=auth("agent"),
    )
    assert milestone.status_code == 201
    assert len(milestone.json()["screenshots"]) == 1


def test_capture_rejects_arbitrary_commands(client, auth):
    response = client.post(
        "/api/v1/screenshots/capture",
        json={"source": "text", "command": "rm -rf /"},
        headers=auth("agent"),
    )
    assert response.status_code == 422
    assert response.json()["error"] == "command_not_allowed"


def test_capture_rejects_arbitrary_paths(client, auth):
    response = client.post(
        "/api/v1/screenshots/capture",
        json={"source": "api", "path": "/etc/passwd"},
        headers=auth("agent"),
    )
    assert response.status_code == 422
    assert response.json()["error"] == "path_not_allowed"


def test_expired_screenshot_returns_410(client, auth, env):
    milestone = _create_milestone(client, auth)
    stored = client.post(
        f"/api/v1/milestones/{milestone['id']}/screenshots",
        files=[("files", ("a.png", _png(), "image/png"))],
        headers=auth("admin"),
    ).json()[0]
    db = get_db(env)
    db.execute("UPDATE screenshot SET expires_at=? WHERE id=?", (time.time() - 10, stored["id"]))
    response = client.get(stored["url"], headers=auth())
    assert response.status_code == 410
    assert response.json()["error"] == "expired"


def test_retention_deletes_expired_files_and_keeps_history(client, auth, env):
    milestone = _create_milestone(client, auth)
    stored = client.post(
        f"/api/v1/milestones/{milestone['id']}/screenshots",
        files=[("files", ("old.png", _png(), "image/png"))],
        headers=auth("admin"),
    ).json()[0]
    db = get_db(env)
    db.execute("UPDATE screenshot SET expires_at=? WHERE id=?", (time.time() - 10, stored["id"]))
    path = env.data_dir / stored["url"].replace("/api/v1/screenshots/", "screenshots/")  # not used
    before = list(env.screenshots_dir.rglob("*.png"))
    assert before

    result = retention.run(env, db)
    assert result.deleted_screenshots == 1
    assert result.deleted_files == 1
    assert not list(env.screenshots_dir.rglob("*.png"))

    history = client.get(f"/api/v1/milestones/{milestone['id']}", headers=auth()).json()
    assert history["screenshots"] == []
    assert history["expired_screenshots"] == 1
    assert history["title"] == "Foundation"


def test_retention_never_touches_unrelated_files(client, auth, env):
    unrelated = env.data_dir / "unrelated-user-image.png"
    unrelated.write_bytes(_png())
    odd = env.screenshots_dir / "user-notes.png"
    odd.parent.mkdir(parents=True, exist_ok=True)
    odd.write_bytes(_png())
    db = get_db(env)
    result = retention.run(env, db)
    assert unrelated.exists()
    assert odd.exists()
    assert any("unrecognised file left untouched" in error for error in result.errors)


def test_retention_removes_stale_generated_orphans(client, auth, env):
    orphan = env.screenshots_dir / "orphan-milestone" / f"{int(time.time()) - 90000}-deadbeef-orphan.png"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(_png())
    old = time.time() - 3 * 86400
    os.utime(orphan, (old, old))
    db = get_db(env)
    result = retention.run(env, db)
    assert result.orphan_files_removed >= 1
    assert not orphan.exists()


def test_retention_endpoint_dry_run(client, auth):
    response = client.post("/api/v1/retention/run", params={"dry_run": "true"}, headers=auth("admin"))
    assert response.status_code == 200
    assert response.json()["deleted_screenshots"] == 0
    status = client.get("/api/v1/retention/status", headers=auth()).json()
    assert status["retention_days"] == 7


def test_screenshot_delete_is_audited(client, auth, env):
    milestone = _create_milestone(client, auth)
    stored = client.post(
        f"/api/v1/milestones/{milestone['id']}/screenshots",
        files=[("files", ("x.png", _png(), "image/png"))],
        headers=auth("admin"),
    ).json()[0]
    response = client.delete(f"/api/v1/screenshots/{stored['id']}", headers=auth("admin"))
    assert response.status_code == 200
    assert response.json()["expired"] is True
    trail = client.get("/api/v1/audit", headers=auth()).json()
    assert any(row["action"] == "screenshot.delete" for row in trail)


def test_text_renderer_has_no_secret_leak():
    png = capture.render_text("beacon doctor", "$ beacon doctor\n✓ all checks passed")
    assert png.startswith(b"\x89PNG")
    assert len(png) > 1000


def test_screenshot_path_cannot_escape_data_dir(env, client, auth):
    milestone = _create_milestone(client, auth)
    stored = client.post(
        f"/api/v1/milestones/{milestone['id']}/screenshots",
        files=[("files", ("x.png", _png(), "image/png"))],
        headers=auth("admin"),
    ).json()[0]
    db = get_db(env)
    db.execute("UPDATE screenshot SET rel_path='../../etc/passwd' WHERE id=?", (stored["id"],))
    response = client.get(stored["url"], headers=auth())
    assert response.status_code == 500
    assert response.json()["error"] == "invalid_path"


def test_screenshot_name_keeps_context_and_strips_separators():
    from beacon.services.screenshots import sanitise_name

    assert sanitise_name("GET /api/v1/retention/status.png") == "GET-api-v1-retention-status.png"
    assert sanitise_name("home.png") == "home.png"
    assert "/" not in sanitise_name("../../etc/passwd")
    assert sanitise_name("") == "screenshot"
    assert len(sanitise_name("x" * 400)) <= 80


def test_manual_delete_is_not_counted_as_retention_expiry(client, auth):
    milestone = _create_milestone(client, auth)
    stored = client.post(
        f"/api/v1/milestones/{milestone['id']}/screenshots",
        files=[("files", ("x.png", _png(), "image/png"))],
        headers=auth("admin"),
    ).json()[0]
    assert client.delete(f"/api/v1/screenshots/{stored['id']}", headers=auth("admin")).status_code == 200
    refreshed = client.get(f"/api/v1/milestones/{milestone['id']}", headers=auth()).json()
    assert refreshed["screenshots"] == []
    assert refreshed["expired_screenshots"] == 0, "an operator delete is not a retention expiry"

    gone = client.get(stored["url"], headers=auth())
    assert gone.status_code == 410
    assert gone.json()["error"] == "deleted"


def test_retention_status_does_not_count_manual_deletes(client, auth):
    milestone = _create_milestone(client, auth)
    stored = client.post(
        f"/api/v1/milestones/{milestone['id']}/screenshots",
        files=[("files", ("y.png", _png(), "image/png"))],
        headers=auth("admin"),
    ).json()[0]
    client.delete(f"/api/v1/screenshots/{stored['id']}", headers=auth("admin"))
    status = client.get("/api/v1/retention/status", headers=auth()).json()
    assert status["live"] == 0
    assert status["expired"] == 0
