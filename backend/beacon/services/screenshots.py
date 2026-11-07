"""Screenshot storage, validation, retrieval and expiry rules.

Files live under ``data/screenshots/<milestone-id>/`` and are content-addressed in the
database. Retention is 7 days by default (``BEACON_SCREENSHOT_RETENTION_DAYS``); expired rows
keep their metadata (so milestone history survives) but the file is removed and reads return
410. Only files referenced by the ``screenshot`` table inside the screenshots directory can
ever be deleted — `services/retention.py` enforces that.
"""

from __future__ import annotations

import hashlib
import io
import re
import time
from pathlib import Path

from ..config import Settings
from ..db import Database, new_id, now
from ..schemas import ScreenshotMeta

ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


class ScreenshotError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _detect_type(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _dimensions(content: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as image:
            return image.width, image.height
    except Exception:
        return None, None


def sanitise_name(name: str) -> str:
    """Flatten a display name into a safe file name component.

    Path separators become dashes instead of being dropped, so a capture titled
    "GET /api/v1/retention/status" keeps its context ("GET-api-v1-retention-status.png")
    and can never introduce a directory.
    """
    flattened = str(name).replace("/", " ").replace("\\", " ")
    cleaned = SAFE_NAME.sub("-", flattened)
    cleaned = re.sub(r"-{2,}", "-", cleaned)[:80].strip("-.")
    return cleaned or "screenshot"


def store(
    settings: Settings,
    db: Database,
    *,
    milestone_id: str,
    content: bytes,
    caption: str = "",
    source: str = "upload",
    filename: str = "screenshot.png",
) -> ScreenshotMeta:
    if len(content) > settings.screenshot_max_bytes:
        raise ScreenshotError(
            "too_large",
            f"image is larger than {settings.screenshot_max_bytes // (1024 * 1024)} MiB",
            status_code=413,
        )
    content_type = _detect_type(content)
    if content_type is None:
        raise ScreenshotError("unsupported_type", "only PNG, JPEG and WebP images are accepted", status_code=415)
    width, height = _dimensions(content)
    screenshot_id = new_id()
    digest = hashlib.sha256(content).hexdigest()
    created = now()
    expires = created + settings.screenshot_retention_days * 86400
    relative = Path("screenshots") / milestone_id / f"{int(created)}-{screenshot_id[:8]}-{sanitise_name(filename)}"
    if Path(relative).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        relative = relative.with_suffix(EXTENSIONS.get(content_type, ".png"))
    target = settings.data_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    try:
        target.chmod(0o640)
    except OSError:
        pass
    db.execute(
        """
        INSERT INTO screenshot(id, milestone_id, rel_path, caption, source, content_type, bytes,
                               sha256, width, height, created_at, expires_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            screenshot_id,
            milestone_id,
            str(relative),
            caption[:300],
            source[:40],
            content_type,
            len(content),
            digest,
            width,
            height,
            created,
            expires,
        ),
    )
    row = db.query_one("SELECT * FROM screenshot WHERE id=?", (screenshot_id,))
    return meta(row)


def meta(row) -> ScreenshotMeta:
    expired = bool(row["deleted_at"]) or row["expires_at"] <= now()
    return ScreenshotMeta(
        id=row["id"],
        caption=row["caption"] or "",
        source=row["source"] or "",
        content_type=row["content_type"],
        bytes=int(row["bytes"]),
        width=row["width"],
        height=row["height"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        url=f"/api/v1/screenshots/{row['id']}",
        sha256=row["sha256"],
        expired=expired,
    )


def meta_for_milestone(db: Database, milestone_id: str) -> tuple[list[ScreenshotMeta], int]:
    rows = db.query(
        "SELECT * FROM screenshot WHERE milestone_id=? AND deleted_at IS NULL ORDER BY created_at",
        (milestone_id,),
    )
    live: list[ScreenshotMeta] = []
    expired = 0
    for row in rows:
        item = meta(row)
        if item.expired:
            expired += 1
        else:
            live.append(item)
    # Only images that actually reached the retention deadline count as "expired"; images an
    # operator deleted early are gone but are not retention casualties.
    swept_by_retention = db.scalar(
        "SELECT COUNT(*) FROM screenshot WHERE milestone_id=? AND deleted_at IS NOT NULL "
        "AND expires_at <= ?",
        (milestone_id, now()),
    )
    return live, expired + int(swept_by_retention or 0)


def get_row(db: Database, screenshot_id: str):
    return db.query_one("SELECT * FROM screenshot WHERE id=?", (screenshot_id,))


def resolve_path(settings: Settings, row) -> Path:
    """Resolve a screenshot path and prove it stays inside the screenshots directory."""
    base = settings.screenshots_dir.resolve()
    candidate = (settings.data_dir / row["rel_path"]).resolve()
    if not str(candidate).startswith(str(base) + "/"):
        raise ScreenshotError("invalid_path", "stored path escapes the screenshot directory", status_code=500)
    return candidate


def read(settings: Settings, db: Database, screenshot_id: str) -> tuple[Path, str, ScreenshotMeta]:
    row = get_row(db, screenshot_id)
    if row is None:
        raise ScreenshotError("not_found", "screenshot not found", status_code=404)
    item = meta(row)
    if item.expired:
        if row["deleted_at"] is not None and row["expires_at"] > now():
            raise ScreenshotError(
                "deleted",
                "this screenshot was deleted from the dashboard",
                status_code=410,
            )
        raise ScreenshotError(
            "expired",
            "this screenshot has passed its 7-day retention window and was removed",
            status_code=410,
        )
    path = resolve_path(settings, row)
    if not path.exists():
        raise ScreenshotError("missing_file", "screenshot file is missing on disk", status_code=404)
    return path, row["content_type"], item


def for_milestone(db: Database, milestone_id: str) -> list[ScreenshotMeta]:
    metas, _ = meta_for_milestone(db, milestone_id)
    return metas


def delete(settings: Settings, db: Database, screenshot_id: str) -> ScreenshotMeta:
    row = get_row(db, screenshot_id)
    if row is None:
        raise ScreenshotError("not_found", "screenshot not found", status_code=404)
    path = resolve_path(settings, row)
    removed = delete_file(settings, path)
    db.execute(
        "UPDATE screenshot SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
        (now(), screenshot_id),
    )
    item = meta(get_row(db, screenshot_id))
    item.expired = True
    return item if removed is not None else item


def delete_file(settings: Settings, path: Path) -> bool | None:
    base = settings.screenshots_dir.resolve()
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if not str(resolved).startswith(str(base) + "/"):
        return None
    try:
        resolved.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return None


def sweep_expired(settings: Settings, db: Database, *, now_ts: float | None = None) -> tuple[int, int]:
    """Delete files whose retention window passed. Keeps metadata for history."""
    now_ts = now_ts or now()
    rows = db.query(
        "SELECT * FROM screenshot WHERE deleted_at IS NULL AND expires_at <= ?", (now_ts,)
    )
    deleted_rows = 0
    deleted_files = 0
    for row in rows:
        path = None
        try:
            path = resolve_path(settings, row)
        except ScreenshotError:
            path = None
        if path is not None:
            outcome = delete_file(settings, path)
            if outcome:
                deleted_files += 1
        db.execute(
            "UPDATE screenshot SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (now_ts, row["id"])
        )
        deleted_rows += 1
    return deleted_rows, deleted_files


def summary_counts(settings: Settings, db: Database) -> dict[str, int]:
    live = int(
        db.scalar(
            "SELECT COUNT(*) FROM screenshot WHERE deleted_at IS NULL AND expires_at > ?", (now(),)
        )
        or 0
    )
    # Retention-expired only: an early operator delete is not a retention casualty.
    expired = int(
        db.scalar("SELECT COUNT(*) FROM screenshot WHERE expires_at <= ?", (now(),)) or 0
    )
    return {"live": live, "expired": expired, "retention_days": settings.screenshot_retention_days}


def bytes_on_disk(settings: Settings) -> int:
    total = 0
    base = settings.screenshots_dir
    if not base.exists():
        return 0
    for path in base.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def retention_deadline(settings: Settings, created_at: float) -> float:
    return created_at + settings.screenshot_retention_days * 86400


def sweep_capture_staging(settings: Settings, *, older_than_hours: float = 48) -> int:
    """Remove stale capture staging files (not user images) older than the window."""
    removed = 0
    cutoff = time.time() - older_than_hours * 3600
    for path in settings.capture_dir.glob("*") if settings.capture_dir.exists() else []:
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
