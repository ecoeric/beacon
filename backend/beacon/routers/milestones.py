"""Milestones, screenshot capture/upload, retrieval and retention endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse

from ..config import get_settings
from ..deps import AdminDep, DbDep, ElevatedDep, ReadDep, client_ip, throttle
from ..schemas import (
    CaptureRequest,
    CaptureResult,
    MilestoneCreate,
    MilestoneModel,
    RetentionResult,
    ScreenshotMeta,
)
from ..security import audit
from ..services import capture, milestones, notifications, retention, screenshots

router = APIRouter(tags=["milestones"])


@router.get("/milestones", response_model=list[MilestoneModel], summary="Milestone history")
def list_milestones(
    db: DbDep,
    token: ReadDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[MilestoneModel]:
    return milestones.list_milestones(db, limit=limit, offset=offset)


@router.get("/milestones/{milestone_id}", response_model=MilestoneModel, summary="One milestone")
def get_milestone(milestone_id: str, db: DbDep, token: ReadDep) -> MilestoneModel:
    milestone = milestones.get(db, milestone_id)
    if milestone is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "milestone not found"})
    return milestone


@router.post(
    "/milestones",
    response_model=MilestoneModel,
    status_code=status.HTTP_201_CREATED,
    summary="Record a milestone (optionally attaching staged captures)",
)
def create_milestone(
    payload: MilestoneCreate, request: Request, db: DbDep, token: ElevatedDep
) -> MilestoneModel:
    settings = get_settings()
    if len(payload.screenshots) > 4:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail={"code": "too_many_screenshots", "message": "a milestone keeps at most four screenshots"},
        )
    stage: list[tuple[str, bytes, dict]] = []
    for capture_id in payload.screenshots:
        content, meta = capture.load_staging(settings, capture_id)
        stage.append((capture_id, content, meta))

    milestone = milestones.create(
        db,
        title=payload.title,
        summary=payload.summary,
        changes=payload.changes,
        phase=payload.phase,
        agent_id=token.name,
        session_id=None,
    )
    for capture_id, content, meta in stage:
        screenshots.store(
            settings,
            db,
            milestone_id=milestone.id,
            content=content,
            caption=meta.get("caption") or payload.title,
            source=meta.get("source", "capture"),
            filename=f"{meta.get('title', capture_id)}.png",
        )
        capture.consume_staging(settings, capture_id)

    notifications.notify(
        db,
        kind="milestone_completed",
        severity="success",
        title=f"Milestone {milestone.seq}: {milestone.title}",
        body=milestone.summary[:300],
        dedupe_key=f"milestone:{milestone.id}",
        payload={"milestone_id": milestone.id, "seq": milestone.seq, "phase": milestone.phase},
    )
    audit(
        db,
        actor=token.name,
        action="milestone.create",
        target=milestone.id,
        detail={"title": milestone.title, "screenshots": len(stage)},
        ip=client_ip(request),
    )
    refreshed = milestones.get(db, milestone.id)
    return refreshed if refreshed is not None else milestone


@router.post(
    "/milestones/{milestone_id}/screenshots",
    response_model=list[ScreenshotMeta],
    summary="Upload real screenshot files to a milestone",
)
async def upload_screenshots(
    milestone_id: str,
    db: DbDep,
    token: ElevatedDep,
    files: Annotated[list[UploadFile], File()] = None,
    captions: Annotated[str | None, Form()] = None,
) -> list[ScreenshotMeta]:
    settings = get_settings()
    if milestones.get(db, milestone_id) is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "milestone not found"})
    uploads = files or []
    if not uploads:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail={"code": "no_files", "message": "no files uploaded"})
    existing = len(screenshots.for_milestone(db, milestone_id))
    if existing + len(uploads) > 4:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail={"code": "too_many_screenshots", "message": f"milestone already has {existing} screenshots (max 4)"},
        )
    caption_list = [part.strip() for part in (captions or "").split("|") if part.strip()]
    stored: list[ScreenshotMeta] = []
    for index, upload in enumerate(uploads):
        content = await upload.read()
        meta = screenshots.store(
            settings,
            db,
            milestone_id=milestone_id,
            content=content,
            caption=caption_list[index] if index < len(caption_list) else (upload.filename or ""),
            source="upload",
            filename=upload.filename or "upload.png",
        )
        stored.append(meta)
    audit(
        db,
        actor=token.name,
        action="screenshot.upload",
        target=milestone_id,
        detail={"count": len(stored)},
    )
    return stored


@router.get("/screenshots/{screenshot_id}", summary="Fetch screenshot bytes", response_class=FileResponse)
def get_screenshot(screenshot_id: str, db: DbDep, token: ReadDep) -> Response:
    settings = get_settings()
    path, content_type, meta = screenshots.read(settings, db, screenshot_id)
    return FileResponse(
        path,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": f'inline; filename="{meta.id}.png"',
        },
    )


@router.delete("/screenshots/{screenshot_id}", response_model=ScreenshotMeta, summary="Delete one screenshot")
def delete_screenshot(screenshot_id: str, db: DbDep, token: AdminDep, request: Request) -> ScreenshotMeta:
    settings = get_settings()
    meta = screenshots.delete(settings, db, screenshot_id)
    audit(
        db,
        actor=token.name,
        action="screenshot.delete",
        target=screenshot_id,
        ip=client_ip(request),
    )
    return meta


@router.post("/screenshots/capture", response_model=CaptureResult, summary="Capture a real artefact as a PNG")
def capture_screenshot(
    payload: CaptureRequest, db: DbDep, token: ElevatedDep, request: Request
) -> CaptureResult:
    throttle(f"{token.name}:capture", limit=8, window_seconds=60)
    settings = get_settings()
    result = capture.capture(
        settings,
        source=payload.source,
        title=payload.title,
        command=payload.command,
        path=payload.path,
        caption=payload.caption,
    )
    audit(
        db,
        actor=token.name,
        action="screenshot.capture",
        target=result.capture_id,
        detail={"source": payload.source, "command": payload.command, "path": payload.path},
        ip=client_ip(request),
    )
    return result


@router.get("/captures/{capture_id}", summary="Preview a staged capture", response_class=FileResponse)
def preview_capture(capture_id: str, token: ReadDep) -> Response:
    settings = get_settings()
    content = capture.preview_bytes(settings, capture_id)
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=600"},
    )


@router.post("/retention/run", response_model=RetentionResult, summary="Run the screenshot retention sweep")
def run_retention(
    db: DbDep,
    token: AdminDep,
    request: Request,
    dry_run: bool = Query(default=False),
) -> RetentionResult:
    settings = get_settings()
    result = retention.run(settings, db, dry_run=dry_run, actor=token.name)
    audit(
        db,
        actor=token.name,
        action="retention.run",
        target="screenshots",
        detail={"dry_run": dry_run, "deleted": result.deleted_screenshots},
        ip=client_ip(request),
    )
    return result


@router.get("/retention/status", summary="Retention configuration and storage usage")
def retention_status(db: DbDep, token: ReadDep) -> dict:
    settings = get_settings()
    return {
        "retention_days": settings.screenshot_retention_days,
        "timer_hint": retention.run_time_of_day_hint(),
        **retention.storage_summary(settings, db),
        "warnings": retention.clock_skew_guard(settings, db),
    }
