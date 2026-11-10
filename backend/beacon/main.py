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
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > settings.max_request_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": "payload_too_large",
                    "message": f"request body exceeds {settings.max_request_bytes} bytes",
                },
            )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Beacon-Elapsed-Ms"] = f"{(time.monotonic() - started) * 1000:.1f}"
        return response

    return app


app = create_app()
