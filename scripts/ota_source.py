#!/usr/bin/env python3
"""Build a SideStore/AltStore source JSON for a freshly built Beacon IPA.

This is intentionally dependency-free (Python standard library only) so it runs both on the
Linux development host and on the GitHub Actions publish runner.

It also validates the *actual* IPA before writing the feed:

* exactly one ``Payload/*.app/Info.plist``;
* ``CFBundleIdentifier`` is Beacon's unchanged bundle id;
* ``CFBundleShortVersionString`` and ``CFBundleVersion`` match the release;
* the executable and bundled CA are present;
* no ``_CodeSignature`` or ``embedded.mobileprovision`` (SideStore signs the IPA itself).

Usage example (the workflow passes these values from GitHub):

    python3 scripts/ota_source.py \
      --ipa Beacon-unsigned.ipa \
      --version 1.0.42 --build 42 \
      --source-url https://github.com/owner/repo/releases/download/beacon-source/apps.json \
      --download-url https://github.com/owner/repo/releases/download/v1.0.42/Beacon-unsigned.ipa \
      --icon-url https://github.com/owner/repo/releases/download/beacon-source/Beacon-AppIcon.png \
      --notes-file release-notes.md \
      --existing apps.json \
      --output apps.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BUNDLE_ID = "dev.ericserver.beacon"
SOURCE_ID = "dev.ericserver.beacon.source"
VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?)?$")
MIN_OS_RE = re.compile(r"^\d+(?:\.\d+){1,2}$")
DEFAULT_DESCRIPTION = (
    "Beacon is a native iPhone dashboard and control surface for ericserver: "
    "live host metrics, Pi-hole, Minecraft, KSP/Luna, milestones and the active AI agent."
)
DEFAULT_SUBTITLE = "Native dashboard for ericserver"


class SourceError(RuntimeError):
    """A validation or feed-generation failure with a user-actionable message."""


@dataclass(frozen=True)
class IPAInfo:
    path: Path
    size: int
    sha256: str
    bundle_id: str
    version: str
    build: str
    minimum_os: str | None
    executable: str
    app_path: str


def _url(value: str, label: str, *, allow_http: bool) -> str:
    parsed = urlparse(value)
    schemes = {"https"} if not allow_http else {"http", "https"}
    if parsed.scheme not in schemes or not parsed.netloc:
        raise SourceError(f"{label} must be an absolute {'/'.join(sorted(schemes))} URL: {value!r}")
    return value


def inspect_ipa(
    path: Path,
    *,
    expected_bundle_id: str = BUNDLE_ID,
    expected_version: str | None = None,
    expected_build: str | None = None,
    require_unsigned: bool = True,
) -> IPAInfo:
    """Validate the IPA's shape and return metadata used by the source feed."""
    path = Path(path)
    if not path.is_file():
        raise SourceError(f"IPA not found: {path}")
    if path.stat().st_size <= 0:
        raise SourceError(f"IPA is empty: {path}")

    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            info_names = [
                name
                for name in names
                if name.startswith("Payload/")
                and name.endswith(".app/Info.plist")
                and name.count("/") == 2
            ]
            if len(info_names) != 1:
                raise SourceError(
                    f"expected exactly one Payload/*.app/Info.plist, found {info_names or 'none'}"
                )
            info_name = info_names[0]
            app_prefix = info_name[: -len("Info.plist")]
            app_name = app_prefix.rstrip("/").split("/")[-1].removesuffix(".app")
            if app_name != "Beacon":
                raise SourceError(f"unexpected app bundle name {app_name!r}; expected 'Beacon'")
            try:
                info = plistlib.loads(archive.read(info_name))
            except (plistlib.InvalidFileException, ValueError) as exc:
                raise SourceError(f"could not parse {info_name}: {exc}") from exc

            required = ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion")
            missing = [key for key in required if not info.get(key)]
            if missing:
                raise SourceError(f"Info.plist is missing {', '.join(missing)}")
            bundle_id = str(info["CFBundleIdentifier"])
            version = str(info["CFBundleShortVersionString"])
            build = str(info["CFBundleVersion"])
            if bundle_id != expected_bundle_id:
                raise SourceError(
                    f"bundle identifier changed: {bundle_id!r} != {expected_bundle_id!r}; "
                    "SideStore updates require the existing identifier"
                )
            if expected_version is not None and version != expected_version:
                raise SourceError(
                    f"IPA version {version!r} does not match release version {expected_version!r}"
                )
            if expected_build is not None and build != expected_build:
                raise SourceError(
                    f"IPA build {build!r} does not match release build {expected_build!r}"
                )
            if not VERSION_RE.match(version):
                raise SourceError(f"CFBundleShortVersionString is not a usable version: {version!r}")

            executable = str(info.get("CFBundleExecutable") or "Beacon")
            executable_name = f"{app_prefix}{executable}"
            if executable_name not in names:
                raise SourceError(f"missing executable {executable_name}")
            ca_name = f"{app_prefix}ca.crt"
            if ca_name not in names:
                raise SourceError(f"missing bundled CA {ca_name}")

            if require_unsigned:
                signed = [
                    name
                    for name in names
                    if name.startswith(f"{app_prefix}_CodeSignature/")
                    or name == f"{app_prefix}embedded.mobileprovision"
                ]
                if signed:
                    raise SourceError(
                        "IPA contains signing material; SideStore must sign a clean unsigned IPA "
                        f"(found {signed[0]})"
                    )

            minimum_os = info.get("MinimumOSVersion") or info.get("LSMinimumSystemVersion")
            minimum_os = str(minimum_os) if minimum_os else None
            if minimum_os and not MIN_OS_RE.match(minimum_os):
                raise SourceError(f"unexpected MinimumOSVersion: {minimum_os!r}")
    except zipfile.BadZipFile as exc:
        raise SourceError(f"not a valid zip/IPA: {path}") from exc

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return IPAInfo(
        path=path,
        size=path.stat().st_size,
        sha256=digest,
        bundle_id=bundle_id,
        version=version,
        build=build,
        minimum_os=minimum_os,
        executable=executable,
        app_path=app_prefix,
    )


def _notes(path: Path | None) -> str:
    if path is None:
        return "Beacon update."
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SourceError(f"could not read release notes {path}: {exc}") from exc
    if not text:
        return "Beacon update."
    # SideStore renders this as text; keep it useful but bounded.
    return text[:4000]


def _load_existing(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceError(f"existing source feed is not valid JSON ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise SourceError(f"existing source feed must be a JSON object: {path}")
    return data


def _validate_version_entry(entry: Any, *, label: str) -> None:
    if not isinstance(entry, dict):
        raise SourceError(f"{label} must be an object")
    for key in ("version", "date", "downloadURL", "size"):
        if key not in entry:
            raise SourceError(f"{label} is missing {key}")
    if not isinstance(entry["version"], str) or not VERSION_RE.match(entry["version"]):
        raise SourceError(f"{label}.version is invalid: {entry['version']!r}")
    if not isinstance(entry["date"], str) or not DATE_RE.match(entry["date"]):
        raise SourceError(f"{label}.date is invalid: {entry['date']!r}")
    if not isinstance(entry["downloadURL"], str) or urlparse(entry["downloadURL"]).scheme != "https":
        raise SourceError(f"{label}.downloadURL must be an https URL")
    if not isinstance(entry["size"], int) or entry["size"] <= 0:
        raise SourceError(f"{label}.size must be a positive integer")
    if "buildVersion" in entry and not isinstance(entry["buildVersion"], str):
        raise SourceError(f"{label}.buildVersion must be a string")
    if "sha256" in entry and (
        not isinstance(entry["sha256"], str)
        or len(entry["sha256"]) != 64
        or any(ch not in "0123456789abcdef" for ch in entry["sha256"].lower())
    ):
        raise SourceError(f"{label}.sha256 must be a 64-character hex digest")


def validate_source(data: dict[str, Any], *, bundle_id: str = BUNDLE_ID) -> None:
    """Fail closed on the AltStore/SideStore fields SideStore actually consumes."""
    for key in ("name", "identifier", "sourceURL", "apps"):
        if key not in data:
            raise SourceError(f"source feed is missing {key}")
    if not isinstance(data["name"], str) or not data["name"].strip():
        raise SourceError("source name is empty")
    if not isinstance(data["identifier"], str) or not data["identifier"].strip():
        raise SourceError("source identifier is empty")
    if not isinstance(data["sourceURL"], str) or urlparse(data["sourceURL"]).scheme != "https":
        raise SourceError("sourceURL must be an https URL")
    apps = data["apps"]
    if not isinstance(apps, list) or not apps:
        raise SourceError("source feed has no apps")
    app = next(
        (item for item in apps if isinstance(item, dict) and item.get("bundleIdentifier") == bundle_id),
        None,
    )
    if app is None:
        raise SourceError(f"source feed has no app with bundleIdentifier {bundle_id}")
    for key in ("name", "bundleIdentifier", "developerName", "localizedDescription", "iconURL", "versions"):
        if key not in app:
            raise SourceError(f"app is missing {key}")
    if not isinstance(app["iconURL"], str) or urlparse(app["iconURL"]).scheme != "https":
        raise SourceError("app.iconURL must be an https URL")
    versions = app["versions"]
    if not isinstance(versions, list) or not versions:
        raise SourceError("app.versions is empty")
    seen: set[str] = set()
    for index, entry in enumerate(versions):
        _validate_version_entry(entry, label=f"versions[{index}]")
        key = entry["version"]
        if key in seen:
            raise SourceError(f"duplicate version in source feed: {key}")
        seen.add(key)
        if "minOSVersion" in entry and (
            not isinstance(entry["minOSVersion"], str) or not MIN_OS_RE.match(entry["minOSVersion"])
        ):
            raise SourceError(f"versions[{index}].minOSVersion is invalid")
    # Deprecated flat fields are still consumed by older AltStore builds. Keep them truthful.
    latest = versions[0]
    for flat, nested in (
        ("version", "version"),
        ("versionDate", "date"),
        ("versionDescription", "localizedDescription"),
        ("downloadURL", "downloadURL"),
        ("size", "size"),
    ):
        if flat in app and app[flat] != latest.get(nested):
            raise SourceError(f"legacy app field {flat} does not match versions[0]")
    if app.get("version") is not None and app["version"] != latest["version"]:
        raise SourceError("app.version does not match versions[0].version")


def build_source(
    info: IPAInfo,
    *,
    version: str,
    build: str,
    source_url: str,
    download_url: str,
    icon_url: str,
    notes: str,
    date: str,
    existing: dict[str, Any] | None = None,
    bundle_id: str = BUNDLE_ID,
    source_identifier: str = SOURCE_ID,
    developer_name: str = "Eric",
    app_name: str = "Beacon",
    subtitle: str = DEFAULT_SUBTITLE,
    description: str = DEFAULT_DESCRIPTION,
    min_os: str | None = None,
    max_versions: int = 25,
    allow_http: bool = False,
) -> dict[str, Any]:
    if version != info.version:
        raise SourceError(f"release version {version!r} does not match IPA version {info.version!r}")
    if build != info.build:
        raise SourceError(f"release build {build!r} does not match IPA build {info.build!r}")
    if not VERSION_RE.match(version):
        raise SourceError(f"invalid release version: {version!r}")
    source_url = _url(source_url, "sourceURL", allow_http=allow_http)
    download_url = _url(download_url, "downloadURL", allow_http=allow_http)
    icon_url = _url(icon_url, "iconURL", allow_http=allow_http)
    if not DATE_RE.match(date):
        raise SourceError(f"invalid release date: {date!r}")
    if not (1 <= max_versions <= 100):
        raise SourceError("max_versions must be between 1 and 100")

    app_versions: list[dict[str, Any]] = []
    source: dict[str, Any]
    if existing:
        if not isinstance(existing.get("apps"), list):
            raise SourceError("existing source feed has no apps array")
        source = {
            **existing,
            "name": existing.get("name") or app_name,
            "identifier": existing.get("identifier") or source_identifier,
            "sourceURL": source_url,
        }
        app = next(
            (
                item
                for item in existing["apps"]
                if isinstance(item, dict) and item.get("bundleIdentifier") == bundle_id
            ),
            None,
        )
        if app:
            source["apps"] = [item for item in existing["apps"] if item is not app]
            app_versions = [item for item in app.get("versions", []) if isinstance(item, dict)]
        else:
            source["apps"] = list(existing["apps"])
        # Keep older versions after the new one, dropping a previous build of the same version.
        app_versions = [item for item in app_versions if item.get("version") != version]
    else:
        source = {
            "name": app_name,
            "identifier": source_identifier,
            "sourceURL": source_url,
            "apps": [],
        }

    entry: dict[str, Any] = {
        "version": version,
        "buildVersion": build,
        "date": date,
        "localizedDescription": notes,
        "sha256": info.sha256,
        "downloadURL": download_url,
        "size": info.size,
    }
    effective_min = min_os or info.minimum_os
    if effective_min:
        if not MIN_OS_RE.match(effective_min):
            raise SourceError(f"invalid minimum OS version: {effective_min!r}")
        entry["minOSVersion"] = effective_min

    versions = [entry, *app_versions][:max_versions]
    app_payload: dict[str, Any] = {
        "name": app_name,
        "bundleIdentifier": bundle_id,
        "developerName": developer_name,
        "subtitle": subtitle,
        "localizedDescription": description,
        "iconURL": icon_url,
        "tintColor": "667FFA",
        "versions": versions,
        # AltStore Classic compatibility: keep flat fields in sync with versions[0].
        "version": version,
        "versionDate": date,
        "versionDescription": notes,
        "downloadURL": download_url,
        "size": info.size,
    }
    source["apps"] = [app_payload, *source["apps"]]
    validate_source(source, bundle_id=bundle_id)
    return source


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ipa", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--download-url", required=True)
    parser.add_argument("--icon-url", required=True)
    parser.add_argument("--notes-file", type=Path)
    parser.add_argument("--existing", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--min-os")
    parser.add_argument("--bundle-id", default=BUNDLE_ID)
    parser.add_argument("--source-identifier", default=SOURCE_ID)
    parser.add_argument("--developer-name", default="Eric")
    parser.add_argument("--app-name", default="Beacon")
    parser.add_argument("--subtitle", default=DEFAULT_SUBTITLE)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--max-versions", type=int, default=25)
    parser.add_argument("--allow-http", action="store_true", help="for local testing only")
    args = parser.parse_args(argv)

    try:
        info = inspect_ipa(
            args.ipa,
            expected_bundle_id=args.bundle_id,
            expected_version=args.version,
            expected_build=args.build,
        )
        source = build_source(
            info,
            version=args.version,
            build=args.build,
            source_url=args.source_url,
            download_url=args.download_url,
            icon_url=args.icon_url,
            notes=_notes(args.notes_file),
            date=args.date,
            existing=_load_existing(args.existing),
            bundle_id=args.bundle_id,
            source_identifier=args.source_identifier,
            developer_name=args.developer_name,
            app_name=args.app_name,
            subtitle=args.subtitle,
            description=args.description,
            min_os=args.min_os,
            max_versions=args.max_versions,
            allow_http=args.allow_http,
        )
        serialized = json.dumps(source, indent=2, ensure_ascii=False) + "\n"
        _atomic_write(args.output, serialized)
    except SourceError as exc:
        print(f"ota-source: {exc}", file=sys.stderr)
        return 2

    app = next(item for item in source["apps"] if item["bundleIdentifier"] == args.bundle_id)
    print(
        f"ota-source: wrote {args.output} "
        f"(Beacon {info.version} build {info.build}, {info.size} bytes, "
        f"sha256 {info.sha256[:16]}…, {len(app['versions'])} version(s))"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
