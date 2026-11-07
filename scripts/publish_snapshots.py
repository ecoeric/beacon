#!/usr/bin/env python3
"""Attach snapshot-test PNGs (rendered on macOS) to a Beacon milestone.

Usage (on the Mac that ran `BeaconTests/SnapshotTests`):

    python3 scripts/publish_snapshots.py \
        --dir ~/beacon/artifacts/snapshots \
        --title "Native UI screens" \
        --summary "Rendered on the iPhone 16 Pro simulator against the live server" \
        --change "Home dashboard with live agent state" \
        --change "Agent panel with queued instruction"

The directory must contain the PNGs plus `manifest.json` (written by the snapshot test) or files
named 01-*.png … 04-*.png. Requires `data/secrets/cli.token` and `data/tls/ca.crt` from this
repository — run it on the server after copying the images there, or point --token/--ca at files.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CA = ROOT / "data" / "tls" / "ca.crt"
DEFAULT_TOKEN = ROOT / "data" / "secrets" / "cli.token"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="directory with PNGs and manifest.json")
    parser.add_argument("--base-url", default="https://192.168.1.83:8091")
    parser.add_argument("--token-file", default=str(DEFAULT_TOKEN))
    parser.add_argument("--ca", default=str(DEFAULT_CA))
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--change", action="append")
    parser.add_argument("--phase", default="UI")
    args = parser.parse_args()

    directory = pathlib.Path(args.dir).expanduser()
    if not directory.is_dir():
        print(f"not a directory: {directory}", file=sys.stderr)
        return 2

    manifest_path = directory / "manifest.json"
    captions: dict[str, str] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest.get("screens", []):
            captions[entry["file"]] = entry.get("caption", "")

    files = sorted(path for path in directory.glob("*.png"))
    if not files:
        print("no PNG files found", file=sys.stderr)
        return 2
    if len(files) > 4:
        print(f"{len(files)} images found; a milestone keeps four — using the first four")
        files = files[:4]

    token = pathlib.Path(args.token_file).read_text(encoding="utf-8").strip()
    client = httpx.Client(
        base_url=args.base_url.rstrip("/"),
        verify=args.ca,
        timeout=60,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )

    milestone = client.post(
        "/api/v1/milestones",
        json={
            "title": args.title,
            "summary": args.summary,
            "changes": args.change or [],
            "phase": args.phase,
        },
    )
    milestone.raise_for_status()
    milestone_body = milestone.json()
    print(f"milestone #{milestone_body['seq']} created ({milestone_body['id'][:8]})")

    upload_files = []
    for path in files:
        caption = captions.get(path.name) or path.stem.replace("-", " ")
        upload_files.append(("files", (path.name, path.read_bytes(), "image/png")))
        print(f"  attaching {path.name}: {caption}")
    response = client.post(
        f"/api/v1/milestones/{milestone_body['id']}/screenshots",
        files=upload_files,
        data={"captions": "|".join(captions.get(path.name, path.stem) for path in files)},
    )
    if response.status_code >= 400:
        print(f"upload failed: HTTP {response.status_code} {response.text[:300]}", file=sys.stderr)
        return 1
    print(f"attached {len(response.json())} screenshot(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
