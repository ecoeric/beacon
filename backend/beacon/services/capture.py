"""Milestone screenshot capture.

Only real artefacts are captured — there is no image synthesis. Sources:

``text``   runs one allow-listed, read-only ``beacon`` CLI command and renders its actual
           stdout/stderr as a PNG (title bar + monospace body).
``api``    runs ``beacon api-get <path>`` for an allow-listed local API path and renders the
           real JSON response.
``window`` grabs the X11 display with ``ffmpeg -f x11grab`` (requires DISPLAY + XAUTHORITY);
           used for genuine screenshots of desktop applications such as Cherry Studio.
``file``   ingests a real image produced elsewhere (for example an Xcode simulator
           screenshot taken on a Mac) from a path inside this project.

Captures are staged in ``data/captures`` and attached to a milestone by id, at which point the
bytes move into the screenshot store and inherit the 7-day retention rule.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import Settings
from ..db import Database, new_id, now
from ..schemas import CaptureResult
from .screenshots import ScreenshotError, sanitise_name

# Allow-listed read-only CLI commands. Keys are what the API accepts; values are argv tails.
CAPTURE_COMMANDS: dict[str, list[str]] = {
    "doctor": ["doctor"],
    "summary": ["summary"],
    "agent-status": ["agent", "status"],
    "agent-queue": ["queue", "list"],
    "agent-interrupts": ["agent", "interrupts"],
    "milestones": ["milestones", "list"],
    "system": ["system", "show"],
    "pihole": ["pihole", "status"],
    "minecraft": ["minecraft", "status"],
    "retention-dry-run": ["retention", "run", "--dry-run"],
}

API_PATHS = {
    "/api/v1/summary",
    "/api/v1/agent/status",
    "/api/v1/agent/status/summary",
    "/api/v1/agent/messages",
    "/api/v1/milestones",
    "/api/v1/server/overview",
    "/api/v1/pihole/status",
    "/api/v1/minecraft/status",
    "/api/v1/activity",
    "/api/v1/health",
}

FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
COLOURS = {
    "bg": (10, 10, 13, 255),
    "bar": (22, 22, 28, 255),
    "title": (238, 238, 243, 255),
    "body": (214, 216, 224, 255),
    "dim": (130, 136, 150, 255),
    "accent": (129, 152, 255, 255),
}

MAX_PIXELS_WIDTH = 1600


class CaptureError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(path, size)
    except OSError:  # pragma: no cover - font is present on this host
        return ImageFont.load_default()


def render_text(title: str, body: str) -> bytes:
    """Render a terminal-style PNG from real captured text."""
    import io

    title = title.strip() or "beacon"
    lines: list[str] = []
    for raw_line in body.replace("\t", "    ").splitlines() or [""]:
        if not raw_line.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(raw_line, width=112) or [""])
    max_lines = 90
    truncated = len(lines) > max_lines
    lines = lines[:max_lines]
    if truncated:
        lines.append("… output truncated for the screenshot …")

    font = _font(15)
    title_font = _font(16, bold=True)
    line_height = 21
    pad = 26
    width = 1120
    header = 54
    height = header + pad * 2 + line_height * max(1, len(lines))

    image = Image.new("RGBA", (width, height), COLOURS["bg"])
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width, header], fill=COLOURS["bar"])
    draw.rectangle([0, header - 2, width, header], fill=COLOURS["accent"])
    for index, colour in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        draw.ellipse([20 + index * 22, 19, 32 + index * 22, 31], fill=colour)
    draw.text((pad + 70, 16), title[:90], font=title_font, fill=COLOURS["title"])
    y = header + pad
    for line in lines:
        colour = COLOURS["body"]
        if line.startswith(("✗", "ERROR", "error", "FAIL", "Fail")):
            colour = (255, 138, 138)
        elif line.startswith(("✓", "OK", "ok", "PASS", "Pass")):
            colour = (126, 226, 158)
        elif line.startswith("$"):
            colour = COLOURS["accent"]
        draw.text((pad, y), line, font=font, fill=colour)
        y += line_height
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _run_cli(settings: Settings, args: list[str], timeout: float = 20.0) -> tuple[int, str]:
    env = dict(os.environ)
    env.setdefault("BEACON_DATA_DIR", str(settings.data_dir))
    env.setdefault("PYTHONUNBUFFERED", "1")
    command = [sys.executable, "-m", "beacon.cli", *args]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CaptureError("command_failed", f"could not run beacon CLI: {exc}", status_code=500) from exc
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output.strip()


def _store_staging(settings: Settings, content: bytes, *, title: str, source: str, caption: str) -> CaptureResult:
    capture_id = new_id()
    settings.capture_dir.mkdir(parents=True, exist_ok=True)
    target = settings.capture_dir / f"{capture_id}.png"
    target.write_bytes(content)
    try:
        target.chmod(0o640)
    except OSError:
        pass
    width = height = None
    try:
        with Image.open(target) as image:
            width, height = image.width, image.height
    except Exception:
        pass
    meta = {
        "capture_id": capture_id,
        "title": title,
        "source": source,
        "caption": caption,
        "created_at": now(),
        "path": str(target),
        "width": width,
        "height": height,
    }
    (settings.capture_dir / f"{capture_id}.json").write_text(json.dumps(meta), encoding="utf-8")
    return CaptureResult(
        capture_id=capture_id,
        source=source,
        title=title,
        bytes=len(content),
        width=width,
        height=height,
        preview_url=f"/api/v1/captures/{capture_id}",
        expires_at=now() + 48 * 3600,
    )


def capture_text(settings: Settings, *, command_key: str, caption: str = "") -> CaptureResult:
    if command_key not in CAPTURE_COMMANDS:
        raise CaptureError(
            "command_not_allowed",
            f"allowed commands: {', '.join(sorted(CAPTURE_COMMANDS))}",
            status_code=422,
        )
    args = CAPTURE_COMMANDS[command_key]
    code, output = _run_cli(settings, args)
    if code != 0 and not output:
        raise CaptureError("command_failed", f"beacon {' '.join(args)} exited {code} with no output", status_code=500)
    title = f"beacon {' '.join(args)}"
    body = f"$ beacon {' '.join(args)}\n\n{output}"
    return _store_staging(settings, render_text(title, body), title=title, source="text", caption=caption)


def capture_api(settings: Settings, *, path: str, caption: str = "") -> CaptureResult:
    if path not in API_PATHS:
        raise CaptureError(
            "path_not_allowed",
            f"allowed paths: {', '.join(sorted(API_PATHS))}",
            status_code=422,
        )
    code, output = _run_cli(settings, ["api-get", path])
    title = f"GET {path}"
    body = f"$ beacon api-get {path}\n\n{output}"
    return _store_staging(settings, render_text(title, body), title=title, source="api", caption=caption)


def capture_window(settings: Settings, *, label: str = "", caption: str = "") -> CaptureResult:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CaptureError("ffmpeg_missing", "ffmpeg is not installed", status_code=503)
    display = os.environ.get("BEACON_X11_DISPLAY") or os.environ.get("DISPLAY")
    authority = os.environ.get("BEACON_X11_AUTHORITY") or os.environ.get("XAUTHORITY")
    if not display:
        raise CaptureError(
            "no_display",
            "No X11 display configured for the service (set BEACON_X11_DISPLAY=:0 in deploy/beacon.env)",
            status_code=503,
        )
    if authority and Path(authority).exists():
        os.environ.setdefault("XAUTHORITY", authority)
    settings.capture_dir.mkdir(parents=True, exist_ok=True)
    staging = settings.capture_dir / f"window-{int(time.time())}.png"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "x11grab",
        "-video_size",
        "1366x768",
        "-i",
        f"{display}.0+0,0",
        "-frames:v",
        "1",
        "-y",
        str(staging),
    ]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ},
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CaptureError("capture_failed", f"x11grab failed: {exc}", status_code=500) from exc
    if proc.returncode != 0 or not staging.exists():
        message = (proc.stderr or proc.stdout or "no output").strip().splitlines()
        raise CaptureError(
            "capture_failed",
            f"x11grab failed: {message[0][:200] if message else 'unknown error'}",
            status_code=502,
        )
    content = staging.read_bytes()
    staging.unlink(missing_ok=True)
    content = _downscale(content)
    return _store_staging(
        settings,
        content,
        title=label or "X11 display capture",
        source="window",
        caption=caption,
    )


def _downscale(content: bytes) -> bytes:
    import io

    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.width > MAX_PIXELS_WIDTH:
                ratio = MAX_PIXELS_WIDTH / image.width
                resized = image.resize((MAX_PIXELS_WIDTH, int(image.height * ratio)), Image.LANCZOS)
                buffer = io.BytesIO()
                resized.convert("RGB").save(buffer, format="PNG", optimize=True)
                return buffer.getvalue()
    except Exception:
        return content
    return content


def _allowed_file_roots(settings: Settings) -> list[Path]:
    roots = [settings.data_dir / "captures", settings.data_dir / "artifacts"]
    project = Path(__file__).resolve().parents[3]
    roots.append(project / "artifacts")
    return [root.resolve() for root in roots if root.exists()]


def capture_file(settings: Settings, *, path: str, caption: str = "") -> CaptureResult:
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise CaptureError("not_found", f"file not found: {path}", status_code=404) from exc
    roots = _allowed_file_roots(settings)
    if not any(str(resolved).startswith(str(root) + "/") for root in roots):
        raise CaptureError(
            "path_not_allowed",
            "file captures are limited to the project artifacts and capture directories",
            status_code=403,
        )
    content = resolved.read_bytes()
    if len(content) > settings.screenshot_max_bytes:
        raise ScreenshotError("too_large", "image is too large", status_code=413)
    if not (content.startswith(b"\x89PNG") or content.startswith(b"\xff\xd8\xff") or content[:4] == b"RIFF"):
        raise CaptureError("unsupported_type", "only PNG/JPEG/WebP files can be captured", status_code=415)
    return _store_staging(
        settings,
        content,
        title=sanitise_name(resolved.stem),
        source="file",
        caption=caption or resolved.name,
    )


def capture(
    settings: Settings,
    *,
    source: str,
    title: str = "",
    command: str | None = None,
    path: str | None = None,
    caption: str = "",
) -> CaptureResult:
    if source == "text":
        if not command:
            raise CaptureError("missing_command", "source=text requires a command key", status_code=422)
        return capture_text(settings, command_key=command, caption=caption)
    if source == "api":
        if not path:
            raise CaptureError("missing_path", "source=api requires a path", status_code=422)
        return capture_api(settings, path=path, caption=caption)
    if source == "window":
        return capture_window(settings, label=title, caption=caption)
    if source == "file":
        if not path:
            raise CaptureError("missing_path", "source=file requires a path", status_code=422)
        return capture_file(settings, path=path, caption=caption)
    raise CaptureError("invalid_source", "source must be text, api, window or file", status_code=422)


def load_staging(settings: Settings, capture_id: str) -> tuple[bytes, dict]:
    if not re.fullmatch(r"[0-9a-f]{32}", capture_id or ""):
        raise CaptureError("invalid_capture", "capture id is malformed", status_code=422)
    meta_path = settings.capture_dir / f"{capture_id}.json"
    image_path = settings.capture_dir / f"{capture_id}.png"
    if not meta_path.exists() or not image_path.exists():
        raise CaptureError("capture_not_found", "capture has expired or was already attached", status_code=404)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return image_path.read_bytes(), meta


def consume_staging(settings: Settings, capture_id: str) -> None:
    for name in (f"{capture_id}.png", f"{capture_id}.json"):
        (settings.capture_dir / name).unlink(missing_ok=True)


def preview_bytes(settings: Settings, capture_id: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{32}", capture_id or ""):
        raise CaptureError("invalid_capture", "capture id is malformed", status_code=422)
    path = settings.capture_dir / f"{capture_id}.png"
    if not path.exists():
        raise CaptureError("capture_not_found", "capture not found", status_code=404)
    return path.read_bytes()
