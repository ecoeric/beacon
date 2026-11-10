"""Contract drift and static security guardrails.

These are cheap tests that protect properties which are easy to lose in a refactor:
the committed OpenAPI snapshot must match the app, no shell execution may sneak in, and the
Docker helper must stay read-only.
"""

from __future__ import annotations

import json
import re
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


def test_docker_helper_is_read_only():
    script = (ROOT / "deploy" / "docker-read").read_text(encoding="utf-8")
    assert "ps)" in script and "stats)" in script
    for mutation in ("docker rm", "docker stop", "docker start", "docker restart", "docker exec", "docker run"):
        assert mutation not in script, f"docker-read should not reference {mutation!r}"
    assert "exec \"$DOCKER\" ps" in script
    assert "exec \"$DOCKER\" stats" in script


def test_systemd_units_do_not_run_as_root():
    for name in ("beacon-api.service", "beacon-retention.service"):
        unit = (ROOT / "deploy" / name).read_text(encoding="utf-8")
        assert "User=eric" in unit, name
        assert "User=root" not in unit, name


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
