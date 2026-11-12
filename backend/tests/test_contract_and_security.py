"""Contract drift and static security guardrails.

These are cheap tests that protect properties which are easy to lose in a refactor:
the committed OpenAPI snapshot must match the app, no shell execution may sneak in, and the
Docker helper must stay read-only.
"""

from __future__ import annotations

import json
import re

import pytest
from pathlib import Path

from beacon.main import create_app

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "beacon"


def _sources() -> list[tuple[Path, str]]:
    return [(path, path.read_text(encoding="utf-8")) for path in sorted(BACKEND.rglob("*.py"))]


def test_openapi_matches_committed_contract(env):
    spec = create_app().openapi()
    committed = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    assert spec == committed, (
        "docs/openapi.json is stale — run: "
        "backend/.venv/bin/python scripts/check_openapi_drift.py --write"
    )


def test_contract_has_no_shell_like_routes(env):
    paths = set(create_app().openapi()["paths"])
    for path in paths:
        assert "exec" not in path.lower(), path
        assert "shell" not in path.lower(), path
    assert "/api/v1/screenshots/capture" in paths


def test_no_shell_execution_in_backend():
    forbidden = ("shell=True", "os.system(", "os.popen(", "pickle.loads", "yaml.load(")
    for path, text in _sources():
        for pattern in forbidden:
            assert pattern not in text, f"{path.name} contains {pattern}"
        assert re.search(r"(?<![\w.])(eval|exec)\s*\(", text) is None, f"{path.name} uses eval/exec"


def test_subprocess_calls_pass_argument_lists():
    for path, text in _sources():
        for match in re.finditer(r"subprocess\.(run|Popen|call)\(", text):
            snippet = text[match.start() : match.start() + 500]
            assert "[" in snippet or "command" in snippet or "argv" in snippet, (
                f"{path.name}: subprocess call without an argument list near "
                + snippet.splitlines()[0][:80]
            )


def test_capture_allow_lists_are_fixed_and_simple():
    from beacon.services import capture

    assert capture.CAPTURE_COMMANDS, "the text capture allow-list must not be empty"
    for key, argv in capture.CAPTURE_COMMANDS.items():
        assert isinstance(argv, list) and argv, key
        for token in argv:
            assert re.fullmatch(r"[a-z0-9-]+", token), f"unexpected token {token!r} in {key}"
    for path in capture.API_PATHS:
        assert path.startswith("/api/v1/"), path
        assert ".." not in path


def test_docker_snapshot_script_is_fixed():
    script = (ROOT / "deploy" / "docker-snapshot").read_text(encoding="utf-8")
    assert '"ps"' in script and '"stats"' in script
    assert "subprocess.run" in script
    assert "[DOCKER, *args]" in script
    for forbidden in ('docker exec', 'docker rm', '"run"', 'shell=True'):
        assert forbidden not in script, f"docker snapshot must not support {forbidden!r}"


def test_systemd_units_do_not_run_the_api_as_root():
    for name in ("beacon-api.service", "beacon-retention.service"):
        unit = (ROOT / "deploy" / name).read_text(encoding="utf-8")
        assert "User=eric" in unit, name
        assert "User=root" not in unit, name
    assert "NoNewPrivileges=yes" in (ROOT / "deploy" / "beacon-api.service").read_text(encoding="utf-8")


def test_docker_timer_privileges_are_minimal():
    unit = (ROOT / "deploy" / "beacon-docker.service").read_text(encoding="utf-8")
    assert "User=root" in unit
    assert "NoNewPrivileges=yes" in unit
    assert "CapabilityBoundingSet=" in unit
    assert "ReadOnlyPaths=/var/run/docker.sock" in unit
    assert "ReadWritePaths=/run/beacon" in unit
    assert "ProtectSystem=strict" in unit


def test_no_secret_values_are_committed():
    secrets = ROOT / "data" / "secrets"
    tracked_candidates = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and ".venv" not in path.parts
        and ".build" not in path.parts
    ]
    if not secrets.exists():
        return
    for secret_file in secrets.glob("*"):
        if not secret_file.is_file():
            continue
        value = secret_file.read_text(encoding="utf-8", errors="ignore").strip()
        if len(value) < 12:
            continue
        for candidate in tracked_candidates:
            if candidate == secret_file or ".sqlite" in candidate.name:
                continue
            try:
                if value in candidate.read_text(encoding="utf-8", errors="ignore"):
                    raise AssertionError(f"secret from {secret_file.name} appears in {candidate}")
            except (UnicodeDecodeError, OSError):
                continue


def test_oversized_request_body_is_rejected_before_parsing(client, auth):
    oversized = b"x" * (3 * 1024 * 1024)  # env fixture caps requests at 2 MiB
    response = client.post(
        "/api/v1/agent/messages",
        content=oversized,
        headers={**auth("admin"), "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


def test_screenshot_store_enforces_byte_limit(env):
    from dataclasses import replace

    import pytest as _pytest

    from beacon.db import get_db
    from beacon.services import screenshots

    small = replace(env, screenshot_max_bytes=512)
    with _pytest.raises(screenshots.ScreenshotError) as excinfo:
        screenshots.store(
            small,
            get_db(env),
            milestone_id="m",
            content=b"\x89PNG\r\n\x1a\n" + b"0" * 4096,
            caption="too big",
        )
    assert excinfo.value.code == "too_large"


def test_chunked_body_limit_is_enforced(client, auth):
    def oversized_chunks():
        for _ in range(3):
            yield b"x" * (1024 * 1024)  # env fixture limit is 2 MiB, no Content-Length

    response = client.post(
        "/api/v1/agent/messages",
        content=oversized_chunks(),
        headers={**auth("admin"), "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


def test_health_does_not_leak_database_errors(env, monkeypatch):
    import beacon.db as db_module

    def boom(_settings):
        raise RuntimeError("unable to open /home/eric/beacon/data/beacon.sqlite: secret detail")

    monkeypatch.setattr(db_module, "get_db", boom)
    from fastapi.testclient import TestClient

    from beacon.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["database"] == "error"
        assert body["status"] == "degraded"
        text = response.text
        assert "secret detail" not in text
        assert "/home/eric" not in text


def test_capture_file_has_no_existence_oracle():
    from beacon.config import get_settings
    from beacon.services import capture

    settings = get_settings()
    with pytest.raises(capture.CaptureError) as existing:
        capture.capture_file(settings, path="/etc/passwd")
    with pytest.raises(capture.CaptureError) as missing:
        capture.capture_file(settings, path="/tmp/definitely-not-a-beacon-file-92837.png")
    assert existing.value.status_code == 404
    assert missing.value.status_code == 404
    assert existing.value.message == missing.value.message == "file not found"


def test_request_path_has_no_privilege_escalation():
    """Only the operator CLI may invoke sudo; request-handling code must not."""
    offenders = []
    for directory in ("services", "routers"):
        for path in (BACKEND / directory).glob("*.py"):
            text = path.read_text(encoding="utf-8")
            # String literals, not prose: `["sudo", ...]`, `'sudo'`, f"sudo …"
            if '"sudo"' in text or "'sudo'" in text or "sudo -n" in text:
                offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == [], offenders


def test_api_unit_has_no_privileged_dependency():
    unit = (ROOT / "deploy" / "beacon-api.service").read_text(encoding="utf-8")
    assert "NoNewPrivileges=yes" in unit
    assert "InaccessiblePaths=" in unit
    assert "sudoers" not in unit.lower()
    # The sudo-based helper must not exist in the repository any more.
    assert not (ROOT / "deploy" / "sudoers-beacon").exists()
    assert not (ROOT / "deploy" / "docker-read").exists()
