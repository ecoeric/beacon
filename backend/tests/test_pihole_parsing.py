"""Pi-hole v6 client parsing and control tests against recorded API shapes.

The live API was used to capture these payload shapes during development; the tests replay them
through `httpx.MockTransport`, so parsing regressions are caught without the container.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from beacon.config import get_settings
from beacon.services.pihole import PiholeClient, PiholeError

SUMMARY = {
    "queries": {
        "total": 35933,
        "blocked": 5186,
        "percent_blocked": 14.432415962219238,
        "unique_domains": 5232,
        "forwarded": 2576,
        "cached": 28076,
    },
    "took": 0.0002,
}
BLOCKING = {"blocking": "enabled", "timer": None}
TOP_DOMAINS = {
    "domains": [
        {"domain": "scribe.logs.roku.com", "count": 3526},
        {"domain": "logs.netflix.com", "count": 601},
    ],
    "total_queries": 35933,
    "blocked_queries": 5186,
}
TOP_CLIENTS = {
    "clients": [
        {"name": "", "ip": "192.168.1.83", "count": 12030},
        {"name": "laptop", "ip": "192.168.1.75", "count": 7087},
    ],
    "total_queries": 35933,
    "blocked_queries": 5186,
}
UPSTREAMS = {
    "upstreams": [
        {"ip": "blocklist", "name": "blocklist", "port": -1, "count": 5192, "statistics": {"response": 0, "variance": 0}},
        {"ip": "1.0.0.1", "name": "one.one.one.one", "port": 53, "count": 1664, "statistics": {"response": 0.0221, "variance": 0.001}},
        {"ip": "1.1.1.1", "name": "one.one.one.one", "port": 53, "count": 912, "statistics": {"response": 0.0145, "variance": 0.0006}},
    ]
}


def _client(handler, settings=None) -> PiholeClient:
    settings = settings or get_settings()
    return PiholeClient(settings, transport=httpx.MockTransport(handler))


def _happy_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path != "/api/auth":
        assert request.headers.get("sid", "").startswith("sid-"), "every data call must carry a session id"
    if path == "/api/auth":
        return httpx.Response(200, json={"session": {"valid": True, "sid": "sid-123", "validity": 300}})
    if path == "/api/dns/blocking":
        return httpx.Response(200, json=BLOCKING)
    if path == "/api/stats/summary":
        return httpx.Response(200, json=SUMMARY)
    if path == "/api/stats/top_domains":
        assert request.url.params["blocked"] == "true"
        return httpx.Response(200, json=TOP_DOMAINS)
    if path == "/api/stats/top_clients":
        return httpx.Response(200, json=TOP_CLIENTS)
    if path == "/api/stats/upstreams":
        return httpx.Response(200, json=UPSTREAMS)
    return httpx.Response(404, json={"error": "not found"})


def test_status_parses_live_api_shapes(env):
    env.pihole_password_file.parent.mkdir(parents=True, exist_ok=True)
    env.pihole_password_file.write_text("pw\n", encoding="utf-8")
    client = _client(_happy_handler, env)

    async def run():
        status = await client.status()
        await client.close()
        return status

    status = asyncio.run(run())
    assert status.available and status.online
    assert status.blocking == "enabled"
    assert status.queries_total == 35933
    assert status.queries_blocked == 5186
    assert status.percent_blocked == pytest.approx(14.43)
    assert status.unique_domains == 5232
    assert [domain.name for domain in status.top_blocked_domains] == [
        "scribe.logs.roku.com",
        "logs.netflix.com",
    ]
    assert status.top_clients[0].name == "192.168.1.83"
    assert status.top_clients[1].name == "laptop"
    upstream = {item.address: item for item in status.upstreams}
    assert upstream["1.0.0.1:53"].response_avg_ms == pytest.approx(22.1, abs=0.1)
    assert status.upstreams[0].count >= status.upstreams[-1].count
    assert status.error is None


def test_reauth_once_after_401(env):
    env.pihole_password_file.parent.mkdir(parents=True, exist_ok=True)
    env.pihole_password_file.write_text("pw\n", encoding="utf-8")
    calls = {"auth": 0, "blocking": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth":
            calls["auth"] += 1
            return httpx.Response(200, json={"session": {"sid": f"sid-{calls['auth']}"}})
        if request.url.path == "/api/dns/blocking":
            calls["blocking"] += 1
            if calls["blocking"] == 1:
                return httpx.Response(401, json={"error": "unauthorized"})
        return _happy_handler(request)

    client = _client(handler, env)

    async def run():
        status = await client.status()
        await client.close()
        return status

    status = asyncio.run(run())
    assert status.available is True
    assert calls["auth"] == 2
    assert calls["blocking"] == 2  # first attempt answered 401, the retry succeeded


def test_set_blocking_posts_enabled_or_disabled(env):
    env.pihole_password_file.parent.mkdir(parents=True, exist_ok=True)
    env.pihole_password_file.write_text("pw\n", encoding="utf-8")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth":
            return httpx.Response(200, json={"session": {"sid": "sid-123"}})
        if request.url.path == "/api/dns/blocking":
            body = json.loads(request.content)
            seen.append(body)
            return httpx.Response(200, json={"blocking": body["blocking"], "timer": None})
        return httpx.Response(404)

    client = _client(handler, env)

    async def run():
        first = await client.set_blocking(False)
        second = await client.set_blocking(True)
        await client.close()
        return first, second

    first, second = asyncio.run(run())
    assert first["blocking"] == "disabled"
    assert second["blocking"] == "enabled"
    assert seen == [{"blocking": "disabled"}, {"blocking": "enabled"}]


def test_missing_password_is_reported_not_faked(env, tmp_path):
    settings = replace(env, pihole_password_file=tmp_path / "missing.password")
    client = _client(_happy_handler, settings)

    async def run():
        status = await client.status()
        await client.close()
        return status

    status = asyncio.run(run())
    assert status.available is False
    assert "password" in (status.error or "").lower()
    assert status.queries_total is None


def test_partial_statistics_failure_is_reported(env):
    env.pihole_password_file.parent.mkdir(parents=True, exist_ok=True)
    env.pihole_password_file.write_text("pw\n", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/stats/top_domains":
            return httpx.Response(500, json={"error": "boom"})
        return _happy_handler(request)

    client = _client(handler, env)

    async def run():
        status = await client.status()
        await client.close()
        return status

    status = asyncio.run(run())
    assert status.available is True
    assert status.top_blocked_domains == []
    assert "top domains" in (status.error or "").lower()
    assert status.queries_total == 35933


def test_unreachable_api_reports_available_false(env):
    env.pihole_password_file.parent.mkdir(parents=True, exist_ok=True)
    env.pihole_password_file.write_text("pw\n", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _client(handler, env)

    async def run():
        status = await client.status()
        await client.close()
        return status

    status = asyncio.run(run())
    assert status.available is False
    assert status.online is False
    assert status.blocking is None
    assert status.error
