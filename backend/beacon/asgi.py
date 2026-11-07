"""ASGI entrypoint used by uvicorn (``beacon.asgi:app``)."""

from .main import app

__all__ = ["app"]
