"""Pi-hole v6 API integration.

Uses the existing Pi-hole container (no changes to it): the web password is read from a
0600 secrets file, exchanged for a session id at ``POST /api/auth``, and reused until it
expires (Pi-hole default 300 s; re-authenticated on 401). Every field is optional: when the
API is unreachable the payload says so instead of showing zeros.
"""

from __future__ import annotations

import time

import httpx

from ..config import Settings
from ..schemas import (
    DockerContainerInfo,
    DomainCount,
    PiholeStatus,
    UpstreamInfo,
)

SESSION_TTL = 240.0


class PiholeError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class PiholeClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._sid: str | None = None
        self._sid_at: float = 0.0
        self._client = httpx.AsyncClient(
            base_url=settings.pihole_url.rstrip("/"),
            timeout=settings.pihole_timeout_seconds,
            verify=True,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _authenticate(self) -> str:
        password = self.settings.pihole_password
        if not password:
            raise PiholeError(
                "no_password",
                "The Pi-hole API password is not configured on the server",
                status_code=503,
            )
        try:
            response = await self._client.post("/api/auth", json={"password": password})
        except httpx.HTTPError as exc:
            raise PiholeError("unreachable", f"Pi-hole API unreachable: {exc}", status_code=503) from exc
        if response.status_code != 200:
            raise PiholeError(
                "auth_failed",
                f"Pi-hole authentication failed ({response.status_code})",
                status_code=502,
            )
        data = response.json()
        session = data.get("session") or {}
        sid = session.get("sid")
        if not sid:
            raise PiholeError("auth_failed", "Pi-hole returned no session id", status_code=502)
        self._sid = sid
        self._sid_at = time.monotonic()
        return sid

    async def _sid_value(self, *, force: bool = False) -> str:
        if force or self._sid is None or time.monotonic() - self._sid_at > SESSION_TTL:
            return await self._authenticate()
        return self._sid

    async def _get(self, path: str, params: dict | None = None) -> dict:
        for attempt in (0, 1):
            sid = await self._sid_value(force=attempt == 1)
            try:
                response = await self._client.get(path, params=params, headers={"sid": sid})
            except httpx.HTTPError as exc:
                raise PiholeError("unreachable", f"Pi-hole request failed: {exc}", status_code=503) from exc
            if response.status_code == 401 and attempt == 0:
                continue
            if response.status_code != 200:
                raise PiholeError(
                    "api_error",
                    f"Pi-hole {path} returned HTTP {response.status_code}",
                    status_code=502,
                )
            return response.json()
        raise PiholeError("api_error", "Pi-hole request failed after re-authentication", status_code=502)

    async def status(self, container: DockerContainerInfo | None = None) -> PiholeStatus:
        generated = time.time()
        try:
            blocking = await self._get("/api/dns/blocking")
        except PiholeError as exc:
            return PiholeStatus(
                available=False,
                online=False,
                blocking=None,
                container=container,
                generated_at=generated,
                error=exc.message,
            )
        result = PiholeStatus(
            available=True,
            online=True,
            blocking=str(blocking.get("blocking", "unknown")),
            container=container,
            generated_at=generated,
        )
        try:
            summary = await self._get("/api/stats/summary")
            queries = summary.get("queries") or {}
            result.queries_total = queries.get("total")
            result.queries_blocked = queries.get("blocked")
            result.percent_blocked = (
                round(float(queries.get("percent_blocked")), 2)
                if queries.get("percent_blocked") is not None
                else None
            )
            result.unique_domains = queries.get("unique_domains")
            result.queries_forwarded = queries.get("forwarded")
            result.queries_cached = queries.get("cached")
        except PiholeError as exc:
            result.error = f"stats summary unavailable: {exc.message}"
        try:
            domains = await self._get("/api/stats/top_domains", {"blocked": "true", "count": 5})
            result.top_blocked_domains = [
                DomainCount(name=str(item.get("domain", "")), count=int(item.get("count", 0)))
                for item in (domains.get("domains") or [])
                if item.get("domain")
            ]
        except PiholeError as exc:
            result.error = (result.error + "; " if result.error else "") + f"top domains unavailable: {exc.message}"
        try:
            clients = await self._get("/api/stats/top_clients", {"count": 5})
            result.top_clients = [
                DomainCount(
                    name=str(item.get("name") or item.get("ip") or ""),
                    count=int(item.get("count", 0)),
                )
                for item in (clients.get("clients") or [])
                if item.get("ip") or item.get("name")
            ]
        except PiholeError as exc:
            result.error = (result.error + "; " if result.error else "") + f"top clients unavailable: {exc.message}"
        try:
            upstreams = await self._get("/api/stats/upstreams")
            items: list[UpstreamInfo] = []
            for item in upstreams.get("upstreams") or []:
                count = int(item.get("count", 0) or 0)
                statistics = item.get("statistics") or {}
                response_avg = statistics.get("response")
                items.append(
                    UpstreamInfo(
                        name=str(item.get("name") or item.get("ip") or ""),
                        address=f"{item.get('ip', '')}:{item.get('port', '')}",
                        count=count,
                        response_avg_ms=(
                            round(float(response_avg) * 1000, 1)
                            if isinstance(response_avg, (int, float)) and response_avg
                            else None
                        ),
                    )
                )
            items.sort(key=lambda entry: entry.count, reverse=True)
            result.upstreams = items[:6]
        except PiholeError as exc:
            result.error = (result.error + "; " if result.error else "") + f"upstreams unavailable: {exc.message}"
        return result

    async def set_blocking(self, enabled: bool) -> dict:
        for attempt in (0, 1):
            sid = await self._sid_value(force=attempt == 1)
            try:
                response = await self._client.post(
                    "/api/dns/blocking",
                    json={"blocking": "enabled" if enabled else "disabled"},
                    headers={"sid": sid},
                )
            except httpx.HTTPError as exc:
                raise PiholeError("unreachable", f"Pi-hole request failed: {exc}", status_code=503) from exc
            if response.status_code == 401 and attempt == 0:
                continue
            if response.status_code != 200:
                raise PiholeError(
                    "api_error",
                    f"Pi-hole blocking update failed (HTTP {response.status_code})",
                    status_code=502,
                )
            data = response.json()
            return {
                "blocking": data.get("blocking"),
                "timer": data.get("timer"),
            }
        raise PiholeError("api_error", "Pi-hole blocking update failed", status_code=502)


_client: PiholeClient | None = None


def get_client(settings: Settings) -> PiholeClient:
    global _client
    if _client is None or _client.settings.pihole_url != settings.pihole_url:
        _client = PiholeClient(settings)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
