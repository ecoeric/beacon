"""Screenshot retention sweep.

Deletion rules (all checked, in this order):

1. Only rows in the ``screenshot`` table are candidates; the file must resolve **inside**
   ``data/screenshots``.
2. A file is deleted when its row passed ``expires_at`` (default: created + 7 days), or when
   an operator deletes it explicitly. Rows are kept with ``deleted_at`` so milestone history
   survives.
3. Orphan scans only touch files inside ``data/screenshots`` that match the generated naming
   pattern (``<epoch>-``), are unreferenced, and are older than 24 h. Source images, project
   artefacts and user files are never scanned.
4. Capture staging files older than 48 h are removed (they are temporary by definition).
5. Empty milestone directories are pruned; anything unexpected is reported, not deleted.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from ..config import Settings
from ..db import Database, now
from ..schemas import RetentionResult
from ..security import audit
from . import screenshots

GENERATED_NAME = re.compile(r"^\d{10}-[0-9a-f]{8}-")
ORPHAN_MIN_AGE_SECONDS = 24 * 3600
CAPTURE_MAX_AGE_HOURS = 48


def run(
    settings: Settings,
    db: Database,
    *,
    now_ts: float | None = None,
    dry_run: bool = False,
    actor: str = "retention",
) -> RetentionResult:
    stamp = now_ts or now()
    errors: list[str] = []

    if dry_run:
        rows = db.query(
            "SELECT COUNT(*) AS n FROM screenshot WHERE deleted_at IS NULL AND expires_at <= ?",
            (stamp,),
        )
        expired = int(rows[0]["n"]) if rows else 0
        return RetentionResult(
            deleted_screenshots=0,
            deleted_files=0,
            orphan_files_removed=0,
            kept=expired,
            ran_at=stamp,
            errors=["dry run: nothing was deleted"] if expired else [],
        )

    deleted_rows, deleted_files = screenshots.sweep_expired(settings, db, now_ts=stamp)

    referenced: set[str] = set()
    for row in db.query("SELECT rel_path FROM screenshot"):
        referenced.add(str(row["rel_path"]))

    orphans = 0
    base = settings.screenshots_dir.resolve() if settings.screenshots_dir.exists() else None
    if base is not None:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            try:
                relative = str(path.resolve().relative_to(settings.data_dir.resolve()))
            except (OSError, ValueError):
                errors.append(f"unexpected path outside the data directory: {path.name}")
                continue
            if relative in referenced:
                continue
            if not GENERATED_NAME.match(path.name):
                errors.append(f"unrecognised file left untouched: {relative}")
                continue
            try:
                age = stamp - path.stat().st_mtime
            except OSError:
                continue
            if age < ORPHAN_MIN_AGE_SECONDS:
                continue
            if not str(path.resolve()).startswith(str(base) + "/"):
                continue
            try:
                path.unlink()
                orphans += 1
            except OSError as exc:
                errors.append(f"could not remove orphan {path.name}: {exc}")

    captures_removed = 0
    try:
        captures_removed = screenshots.sweep_capture_staging(
            settings, older_than_hours=CAPTURE_MAX_AGE_HOURS
        )
    except OSError as exc:
        errors.append(f"capture staging cleanup failed: {exc}")

    if base is not None:
        for directory in sorted(base.rglob("*"), reverse=True):
            if directory.is_dir():
                try:
                    next(directory.iterdir())
                except StopIteration:
                    try:
                        directory.rmdir()
                    except OSError as exc:
                        errors.append(f"could not prune {directory.name}: {exc}")
                except OSError:
                    continue

    kept = int(
        db.scalar(
            "SELECT COUNT(*) FROM screenshot WHERE deleted_at IS NULL AND expires_at > ?", (stamp,)
        )
        or 0
    )
    result = RetentionResult(
        deleted_screenshots=deleted_rows,
        deleted_files=deleted_files,
        orphan_files_removed=orphans + captures_removed,
        kept=kept,
        ran_at=stamp,
        errors=errors,
    )
    audit(
        db,
        actor=actor,
        action="screenshots.retention",
        target="screenshots",
        detail={
            "deleted_screenshots": result.deleted_screenshots,
            "deleted_files": result.deleted_files,
            "orphans_removed": result.orphan_files_removed,
            "kept": result.kept,
            "errors": result.errors[:10],
        },
    )
    return result


def next_expiry(settings: Settings, db: Database) -> float | None:
    value = db.scalar("SELECT MIN(expires_at) FROM screenshot WHERE deleted_at IS NULL")
    return float(value) if value is not None else None


def storage_summary(settings: Settings, db: Database) -> dict:
    return {
        **screenshots.summary_counts(settings, db),
        "bytes_on_disk": screenshots.bytes_on_disk(settings),
        "next_expiry": next_expiry(settings, db),
        "captures_staged": len(list(settings.capture_dir.glob("*.png")))
        if settings.capture_dir.exists()
        else 0,
    }


def clock_skew_guard(settings: Settings, db: Database) -> list[str]:
    """Detect rows whose expires_at is implausibly far in the future."""
    warnings: list[str] = []
    threshold = now() + settings.screenshot_retention_days * 86400 + 3600
    rows = db.query(
        "SELECT id, expires_at FROM screenshot WHERE deleted_at IS NULL AND expires_at > ?",
        (threshold,),
    )
    if rows:
        warnings.append(f"{len(rows)} screenshot row(s) expire later than the configured retention window")
    return warnings


def sweepable_file_count(settings: Settings) -> int:
    base: Path = settings.screenshots_dir
    if not base.exists():
        return 0
    return sum(1 for path in base.rglob("*") if path.is_file())


def run_time_of_day_hint() -> str:
    return f"daily at 03:41 local time (systemd timer beacon-retention.timer), last run {time.strftime('%Y-%m-%d %H:%M')}"
