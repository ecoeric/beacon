"""Persistence across restarts and TLS material generation (with a real HTTPS handshake)."""

from __future__ import annotations

import datetime as dt
import socket
import threading
import time

import httpx
import pytest
from cryptography import x509

from beacon import tls as tls_module
from beacon.db import get_db


def test_state_survives_an_app_restart(env, tokens, auth):
    from fastapi.testclient import TestClient

    from beacon.main import create_app

    with TestClient(create_app()) as first:
        status_response = first.put(
            "/api/v1/agent/status",
            json={"project": "Beacon", "stage": "phase 4", "activity": "persisting"},
            headers=auth("agent"),
        )
        assert status_response.status_code == 200
        message = first.post("/api/v1/agent/messages", json={"text": "remember me"}, headers=auth("admin")).json()
        milestone = first.post(
            "/api/v1/milestones", json={"title": "persisted"}, headers=auth("agent")
        ).json()

    with TestClient(create_app()) as second:
        status_value = second.get("/api/v1/agent/status", headers=auth()).json()
        assert status_value["project"] == "Beacon"
        messages = second.get("/api/v1/agent/messages", headers=auth()).json()
        assert any(row["id"] == message["id"] for row in messages)
        milestones = second.get("/api/v1/milestones", headers=auth()).json()
        assert any(row["id"] == milestone["id"] for row in milestones)


def test_tls_material_is_valid_for_ios(env):
    material = tls_module.generate(env)
    assert material.server_cert.exists()
    assert material.server_key.exists()
    assert material.ca_cert.exists()
    certificate = x509.load_pem_x509_certificate(material.server_cert.read_bytes())
    lifetime = certificate.not_valid_after_utc - certificate.not_valid_before_utc
    assert lifetime <= dt.timedelta(days=398), "Apple rejects longer-lived TLS leaf certificates"
    san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "127.0.0.1" in [str(value) for value in san.get_values_for_type(x509.IPAddress)]
    assert material.pin and len(material.pin) == 43
    again = tls_module.spki_pin(material.server_cert)
    assert again == material.pin
    with pytest.raises(FileExistsError):
        tls_module.generate(env)

    ca = x509.load_pem_x509_certificate(material.ca_cert.read_bytes())
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_https_server_serves_the_api_with_the_generated_ca(env, tokens, auth):
    import uvicorn

    from beacon.main import create_app

    material = tls_module.generate(env)
    port = _free_port()
    config = uvicorn.Config(
        create_app(),
        host="127.0.0.1",
        port=port,
        ssl_certfile=str(material.server_cert),
        ssl_keyfile=str(material.server_key),
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                response = httpx.get(
                    f"https://127.0.0.1:{port}/api/v1/health",
                    verify=str(material.ca_cert),
                    timeout=2,
                )
                break
            except Exception as exc:  # noqa: BLE001 - retry until the server is up
                last_error = exc
                time.sleep(0.2)
        else:  # pragma: no cover
            raise AssertionError(f"HTTPS server never became ready: {last_error}")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Authenticated call over TLS.
        whoami = httpx.get(
            f"https://127.0.0.1:{port}/api/v1/whoami",
            verify=str(material.ca_cert),
            headers=auth("read"),
            timeout=5,
        )
        assert whoami.status_code == 200

        # The same certificate must not be trusted by a default CA store.
        with pytest.raises(httpx.HTTPError):
            httpx.get(f"https://127.0.0.1:{port}/api/v1/health", verify=True, timeout=5)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_spki_pin_changes_when_the_key_rotates(env):
    first = tls_module.generate(env)
    second = tls_module.generate(env, force=True)
    assert first.pin != second.pin


def test_db_schema_version_is_recorded(env):
    db = get_db(env)
    assert db.get_meta("schema_version") == "2"
