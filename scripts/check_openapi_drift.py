#!/usr/bin/env python3
"""Check (or rewrite) the committed OpenAPI contract snapshot.

    backend/.venv/bin/python scripts/check_openapi_drift.py          # check, exit 1 on drift
    backend/.venv/bin/python scripts/check_openapi_drift.py --write  # regenerate docs/openapi.json

Runs against a temporary data directory so the production database and TLS material are never
touched.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CONTRACT = ROOT / "docs" / "openapi.json"


def build_spec() -> dict:
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("BEACON_DATA_DIR", tempfile.mkdtemp(prefix="beacon-contract-"))
    from beacon.main import create_app  # imported after the env is set on purpose

    return create_app().openapi()


def diff_summary(current: dict, committed: dict) -> list[str]:
    lines: list[str] = []
    current_paths = set(current.get("paths", {}))
    committed_paths = set(committed.get("paths", {}))
    for added in sorted(current_paths - committed_paths):
        lines.append(f"+ path {added}")
    for removed in sorted(committed_paths - current_paths):
        lines.append(f"- path {removed}")
    for path in sorted(current_paths & committed_paths):
        current_methods = {method for method in current["paths"][path] if method != "parameters"}
        committed_methods = {method for method in committed["paths"][path] if method != "parameters"}
        for method in sorted(current_methods - committed_methods):
            lines.append(f"+ {method.upper()} {path}")
        for method in sorted(committed_methods - current_methods):
            lines.append(f"- {method.upper()} {path}")
            continue
        for method in sorted(current_methods & committed_methods):
            if current["paths"][path][method] != committed["paths"][path][method]:
                lines.append(f"~ {method.upper()} {path}")
    for key in ("components", "info", "tags"):
        if current.get(key) != committed.get(key):
            lines.append(f"~ {key}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="rewrite the committed snapshot")
    args = parser.parse_args()

    spec = build_spec()
    if args.write:
        CONTRACT.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {CONTRACT.relative_to(ROOT)} ({len(spec['paths'])} paths)")
        return 0

    if not CONTRACT.exists():
        print(f"missing {CONTRACT.relative_to(ROOT)}; run with --write", file=sys.stderr)
        return 1
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if spec == committed:
        print(f"OpenAPI contract is up to date ({len(spec['paths'])} paths)")
        return 0
    print("OpenAPI contract drift detected:", file=sys.stderr)
    for line in diff_summary(spec, committed)[:60]:
        print(f"  {line}", file=sys.stderr)
    print("run scripts/check_openapi_drift.py --write to update", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
