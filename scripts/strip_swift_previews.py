#!/usr/bin/env python3
"""Remove `#Preview { ... }` blocks from Swift sources copied for Linux typechecking.

The preview macro is an Xcode macro that the Linux toolchain does not provide; the preview
bodies are not part of the shipped app logic. Brace matching keeps nested closures intact.
"""

from __future__ import annotations

import pathlib
import sys


def strip_previews(text: str) -> str:
    pieces: list[str] = []
    cursor = 0
    while True:
        start = text.find("#Preview", cursor)
        if start < 0:
            pieces.append(text[cursor:])
            return "".join(pieces)
        pieces.append(text[cursor:start])
        brace = text.find("{", start)
        if brace < 0:
            return "".join(pieces)
        depth = 0
        end = brace
        for end in range(brace, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    break
        cursor = end + 1


def main(argv: list[str]) -> int:
    for name in argv[1:]:
        path = pathlib.Path(name)
        original = path.read_text(encoding="utf-8")
        stripped = strip_previews(original)
        if stripped != original:
            path.write_text(stripped, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
