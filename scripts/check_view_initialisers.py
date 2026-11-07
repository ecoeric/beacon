#!/usr/bin/env python3
"""Heuristic check of memberwise initialiser call sites for this project's SwiftUI views.

The SwiftUI layer cannot be typechecked on Linux (no SwiftUI module), but the most common
compile error in hand-written view code is a call site that omits a stored property which has no
default. This script extracts every `struct X: View` in `ios/Beacon`, records its stored
properties (and whether they have a default value), skips structs with a custom `init`, and then
checks every `X(...)` call site for missing required labels.

It is intentionally conservative: it reports only *missing* labels for properties declared
without defaults, and ignores dynamic member lookups, string interpolations and calls with
trailing-closure-only arguments. Exit code 1 means a real problem was found.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
IOS = ROOT / "ios" / "Beacon"

STRUCT_RE = re.compile(r"^struct\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*View\s*\{", re.MULTILINE)
PROPERTY_RE = re.compile(
    r"^\s{4}(?:(?:public|private|internal|fileprivate)\s+)?(?:private\(set\)\s+)?"
    r"(?P<kind>let|var)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<rest>[^\n]*)$"
)
WRAPPER_RE = re.compile(r"^\s*@(State|Binding|Environment|EnvironmentObject|FocusState|ObservedObject|StateObject)")


def find_struct_bodies(text: str) -> dict[str, tuple[str, bool]]:
    bodies: dict[str, tuple[str, bool]] = {}
    for match in STRUCT_RE.finditer(text):
        name = match.group(1)
        start = match.end()
        depth = 1
        index = start
        while index < len(text) and depth > 0:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        bodies[name] = (text[start:index], "init(" in text[start:index])
    return bodies


def stored_properties(body: str) -> list[tuple[str, bool]]:
    """Return [(name, has_default)] for stored properties declared before the first func/body."""
    properties: list[tuple[str, bool]] = []
    lines = body.splitlines()
    skipping_wrapper = False
    for index, line in enumerate(lines):
        if re.match(r"^\s{4}(var body|func |init\()", line):
            break
        if WRAPPER_RE.match(line):
            skipping_wrapper = True
            continue
        match = PROPERTY_RE.match(line)
        if match:
            rest = match.group("rest")
            name = match.group("name")
            if name == "body":
                continue
            if skipping_wrapper:
                skipping_wrapper = False
                continue
            if "{" in rest.split("=")[0] and not rest.lstrip().startswith("="):
                # computed property
                continue
            has_default = "=" in rest
            properties.append((name, has_default))
            skipping_wrapper = False
        elif line.strip():
            skipping_wrapper = False
    return properties


def call_labels(text: str, name: str) -> list[set[str]]:
    """Labels used in each `Name(` call site (only label-form arguments count)."""
    results: list[set[str]] = []
    for match in re.finditer(rf"(?<![\w.]){re.escape(name)}\s*\(", text):
        start = match.end()
        depth = 1
        index = start
        while index < len(text) and depth > 0:
            char = text[index]
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif char == '"':
                # skip string literal (handles escaped quotes and interpolation braces coarsely)
                index += 1
                while index < len(text) and text[index] != '"':
                    if text[index] == "\\":
                        index += 1
                    index += 1
            index += 1
        args = text[start : index - 1]
        labels: set[str] = set()
        depth = 0
        current = ""
        for char in args:
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            if char == "," and depth == 0:
                part = current.strip()
                if ":" in part:
                    label = part.split(":", 1)[0].strip()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
                        labels.add(label)
                current = ""
            else:
                current += char
        part = current.strip()
        if ":" in part:
            label = part.split(":", 1)[0].strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
                labels.add(label)
        results.append(labels)
    return results


def main() -> int:
    files = sorted(IOS.rglob("*.swift"))
    texts = {path: path.read_text(encoding="utf-8") for path in files}

    views: dict[str, tuple[pathlib.Path, list[tuple[str, bool]]]] = {}
    for path, text in texts.items():
        for name, (body, has_custom_init) in find_struct_bodies(text).items():
            if has_custom_init:
                continue
            properties = stored_properties(body)
            required = [prop for prop, has_default in properties if not has_default]
            if required:
                views[name] = (path, required)

    problems = 0
    checked = 0
    for name, (declared_in, required) in sorted(views.items()):
        required_names = required
        for path, text in texts.items():
            for labels in call_labels(text, name):
                checked += 1
                # A call with no labels at all is likely a different symbol (e.g. type reference).
                if not labels:
                    continue
                missing = [prop for prop in required_names if prop not in labels]
                if missing:
                    problems += 1
                    print(f"✗ {name}(...) in {path.relative_to(ROOT)} missing: {', '.join(missing)}")
                    print(f"    required by {declared_in.relative_to(ROOT)}")

    print(f"\nchecked {checked} call site(s) across {len(views)} view(s)")
    if problems:
        print(f"{problems} problem(s) found")
        return 1
    print("no missing memberwise arguments detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
