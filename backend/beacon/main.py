"""FastAPI application factory.

Routers are mounted under ``/api/v1``. Documentation endpoints are disabled unless
``BEACON_ENABLE_DOCS=1`` — the API surface is not something to broadcast on a LAN by default.
Custom service exceptions are mapped to stable JSON error bodies::

    HTTP <status>  {"error": "<code>", "message": "<human sentence>"}

The lifespan starts the metrics sampler, runs one retention sweep at boot and schedules an
hourly sweep in addition to the daily systemd timer (belt and braces for screenshot cleanup).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .config import get_settings
from .db import get_db
from .routers import agent, milestones, monitoring, system
from .services import capture, interrupts, message_queue, minecraft, pihole, retention, screenshots
from .services import system_metrics

logger = logging.getLogger("beacon")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

SERVICE_ERRORS = (
    message_queue.QueueError,
    interrupts.InterruptError,
    minecraft.MinecraftError,
    screenshots.ScreenshotError,
    capture.CaptureError,
    pihole.PiholeError,
)


class BodySizeLimitMiddleware:
    """Reject oversized request bodies before FastAPI parses them.

    A declared ``Content-Length`` is checked first; bodies without one (chunked) are read up to
    the limit + 1 byte and rejected, so a chunked upload cannot bypass the ceiling or be spooled
    to disk in full. Accepted bodies are replayed to the application unchanged.
    """

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        declared = headers.get(b"content-length")
        chunked = b"transfer-encoding" in headers
        if declared is None and not chunked:
            # No body is expected at all (GET/HEAD, or a bodyless request). Passing the original
            # receive through keeps streaming responses and disconnect listeners working.
            await self.app(scope, receive, send)
            return
        if declared is not None:
            try:
                size = int(declared)
            except ValueError:
                size = None
            if size is not None and size > self.max_bytes:
                await self._reject(send)
                return
        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if chunk:
                body.extend(chunk)
                if len(body) > self.max_bytes:
                    await self._reject(send)
                    return
            if not message.get("more_body", False):
                break
        delivered = False
        response_finished = asyncio.Event()

        async def guarded_send(message):
            await send(message)
            if message.get("type") == "http.response.body" and not message.get("more_body", False):
                response_finished.set()

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            # Mirror a real server: after the body, receive() waits for the exchange to finish
            # rather than returning immediately (Starlette's disconnect listener awaits this).
            await response_finished.wait()
            return {"type": "http.disconnect"}

        await self.app(scope, replay, guarded_send)

    async def _reject(self, send) -> None:
        payload = json.dumps(
            {"error": "payload_too_large", "message": "request body exceeds the configured limit"}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


def _error_handler(exc: Exception) -> JSONResponse:
    code = getattr(exc, "code", "error")
    message = getattr(exc, "message", str(exc))
    status_code = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", None)
    body = {"error": code, "message": message}
    if detail:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


async def _retention_loop(settings) -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            db = get_db(settings)
            result = await asyncio.to_thread(retention.run, settings, db, actor="retention-loop")
            if result.deleted_screenshots or result.orphan_files_removed:
                logger.info(
                    "retention sweep: %s screenshots, %s files, %s orphans removed",
                    result.deleted_screenshots,
                    result.deleted_files,
                    result.orphan_files_removed,
                )
        except Exception:  # pragma: no cover - loop must survive
            logger.exception("retention sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for directory in (settings.screenshots_dir, settings.capture_dir, settings.agent_dir, settings.logs_dir):
        directory.mkdir(parents=True, exist_ok=True)
    db = get_db(settings)
    system_metrics.get_sampler().start()
    task = asyncio.create_task(_retention_loop(settings), name="beacon-retention")
    try:
        await asyncio.to_thread(retention.run, settings, db, actor="startup")
    except Exception:
        logger.exception("startup retention sweep failed (continuing)")
    logger.info(
        "beacon %s ready on %s:%s (data=%s)", __version__, settings.bind, settings.port, settings.data_dir
    )
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        system_metrics.get_sampler().stop()
        await pihole.close_client()


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.enable_docs
    app = FastAPI(
        title="Beacon API",
        version=__version__,
        description="Server and AI-agent dashboard backend for the Beacon iOS app.",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
        swagger_ui_parameters={"persistAuthorization": True},
    )

    app.include_router(system.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(milestones.router, prefix="/api/v1")
    app.include_router(monitoring.router, prefix="/api/v1")

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)

    for error_type in SERVICE_ERRORS:
        app.add_exception_handler(error_type, lambda request, exc: _error_handler(exc))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Unexpected server error"},
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Beacon-Elapsed-Ms"] = f"{(time.monotonic() - started) * 1000:.1f}"
        return response

    return app


app = create_app()
