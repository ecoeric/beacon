#!/usr/bin/env python3
"""Generate Beacon's 1024x1024 app icon without external image libraries.

The icon is intentionally simple: a dark rounded-square field, an indigo beacon signal and a
small white tower.  It is rasterised at 2x and box-filtered down so curves stay smooth.  Run:

    python3 scripts/make_app_icon.py ios/Beacon/Resources/AppIcon.png

Keeping the generator in the repository makes the binary reproducible on Linux and avoids
committing an opaque design asset with no provenance.
"""

from __future__ import annotations

import argparse
import math
import struct
import zlib
from pathlib import Path

SIZE = 1024
SS = 2  # supersampling factor


def _blend(dst: bytearray, offset: int, r: float, g: float, b: float, a: float) -> None:
    """Alpha-composite one straight-alpha colour over an RGBA bytearray pixel."""
    if a <= 0:
        return
    da = dst[offset + 3] / 255.0
    out_a = a + da * (1.0 - a)
    if out_a <= 0:
        return
    for index, value in enumerate((r, g, b)):
        src = value * 255.0 * a
        base = dst[offset + index] * da * (1.0 - a)
        dst[offset + index] = max(0, min(255, round((src + base) / out_a)))
    dst[offset + 3] = max(0, min(255, round(out_a * 255)))


def _inside_round_rect(x: float, y: float, size: float, radius: float) -> bool:
    if radius <= 0:
        return True
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius


def _disc(dst: bytearray, width: int, cx: float, cy: float, radius: float, color: tuple[float, float, float], alpha: float = 1.0) -> None:
    r, g, b = color
    x0 = max(0, int(cx - radius - 1))
    x1 = min(width - 1, int(cx + radius + 1))
    y0 = max(0, int(cy - radius - 1))
    y1 = min(width - 1, int(cy + radius + 1))
    for y in range(y0, y1 + 1):
        dy = y + 0.5 - cy
        for x in range(x0, x1 + 1):
            dx = x + 0.5 - cx
            if dx * dx + dy * dy <= radius * radius:
                _blend(dst, (y * width + x) * 4, r, g, b, alpha)


def _arc(dst: bytearray, width: int, cx: float, cy: float, radius: float, thickness: float, start: float, end: float, color: tuple[float, float, float]) -> None:
    r, g, b = color
    outer = radius + thickness / 2
    inner = radius - thickness / 2
    x0 = max(0, int(cx - outer - 1))
    x1 = min(width - 1, int(cx + outer + 1))
    y0 = max(0, int(cy - outer - 1))
    y1 = min(width - 1, int(cy + outer + 1))
    for y in range(y0, y1 + 1):
        dy = y + 0.5 - cy
        for x in range(x0, x1 + 1):
            dx = x + 0.5 - cx
            distance = math.hypot(dx, dy)
            if inner <= distance <= outer:
                angle = math.degrees(math.atan2(dy, dx))
                if start <= angle <= end:
                    _blend(dst, (y * width + x) * 4, r, g, b, 1.0)


def render() -> bytes:
    size = SIZE * SS
    pixels = bytearray(size * size * 4)
    # Opaque dark field.  iOS/SideStore applies its own rounded mask; keeping the source square
    # avoids transparent corners and the App Store's "icon contains transparency" warning.
    for y in range(size):
        for x in range(size):
            offset = (y * size + x) * 4
            pixels[offset] = 14
            pixels[offset + 1] = 15
            pixels[offset + 2] = 24
            pixels[offset + 3] = 255

    accent = (102 / 255, 127 / 255, 250 / 255)  # Theme.accent
    white = (238 / 255, 241 / 255, 255 / 255)
    muted = (153 / 255, 166 / 255, 238 / 255)
    cx, cy = size / 2, size * 0.40
    # Soft glow behind the emitter.
    _disc(pixels, size, cx, cy, 110 * SS, accent, 0.10)
    _disc(pixels, size, cx, cy, 72 * SS, accent, 0.16)
    # Three signal arcs.
    _arc(pixels, size, cx, cy, 128 * SS, 15 * SS, -160, -20, accent)
    _arc(pixels, size, cx, cy, 198 * SS, 13 * SS, -160, -20, muted)
    _arc(pixels, size, cx, cy, 268 * SS, 11 * SS, -160, -20, accent)
    # Emitter.
    _disc(pixels, size, cx, cy, 24 * SS, white)
    _disc(pixels, size, cx, cy, 10 * SS, accent)
    # Tower mast and base.
    _disc(pixels, size, cx, size * 0.61, 16 * SS, white)
    _disc(pixels, size, cx, size * 0.70, 16 * SS, white)
    for y in range(int(size * 0.60), int(size * 0.78)):
        for x in range(int(cx - 13 * SS), int(cx + 13 * SS)):
            _blend(pixels, (y * size + x) * 4, *white, 1.0)
    # A simple triangular plinth.
    apex_y = size * 0.74
    base_y = size * 0.84
    half_base = 92 * SS
    for y in range(int(apex_y), int(base_y)):
        t = (y - apex_y) / max(1.0, base_y - apex_y)
        half = 12 * SS + (half_base - 12 * SS) * t
        for x in range(int(cx - half), int(cx + half)):
            _blend(pixels, (y * size + x) * 4, *white, 1.0)

    # Box-filter 2x2 into the final RGBA image.
    out = bytearray(SIZE * SIZE * 4)
    for y in range(SIZE):
        for x in range(SIZE):
            r = g = b = a = 0
            for dy in range(SS):
                for dx in range(SS):
                    offset = ((y * SS + dy) * size + x * SS + dx) * 4
                    r += pixels[offset]
                    g += pixels[offset + 1]
                    b += pixels[offset + 2]
                    a += pixels[offset + 3]
            o = (y * SIZE + x) * 4
            out[o] = r // (SS * SS)
            out[o + 1] = g // (SS * SS)
            out[o + 2] = b // (SS * SS)
            out[o + 3] = a // (SS * SS)
    return _png(out, SIZE, SIZE)


def _png(rgba: bytes, width: int, height: int) -> bytes:
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter type: none
        raw.extend(rgba[y * stride : (y + 1) * stride])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", default="ios/Beacon/Resources/AppIcon.png")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(render())
    print(f"wrote {output} ({output.stat().st_size} bytes, {SIZE}x{SIZE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
