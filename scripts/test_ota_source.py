#!/usr/bin/env python3
"""Focused tests for the SideStore source feed generator (stdlib unittest)."""

from __future__ import annotations

import contextlib
import io
import json
import plistlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ota_source  # noqa: E402


def _ipa(directory: Path, *, version: str = "1.0.42", build: str = "42", signed: bool = False) -> Path:
    path = directory / "Beacon-unsigned.ipa"
    info = {
        "CFBundleIdentifier": "dev.ericserver.beacon",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": build,
        "CFBundleExecutable": "Beacon",
        "MinimumOSVersion": "17.0",
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Payload/Beacon.app/Info.plist", plistlib.dumps(info))
        archive.writestr("Payload/Beacon.app/Beacon", b"arm64-test-binary")
        archive.writestr("Payload/Beacon.app/ca.crt", b"test certificate")
        if signed:
            archive.writestr("Payload/Beacon.app/_CodeSignature/CodeResources", b"not a real signature")
    return path


def _source(ipa: Path, version: str = "1.0.42", build: str = "42", existing=None):
    info = ota_source.inspect_ipa(ipa, expected_version=version, expected_build=build)
    return ota_source.build_source(
        info,
        version=version,
        build=build,
        source_url="https://example.test/releases/download/beacon-source/apps.json",
        download_url=f"https://example.test/releases/download/v{version}/Beacon-unsigned.ipa",
        icon_url="https://example.test/releases/download/beacon-source/Beacon-AppIcon.png",
        notes="Fixes and improvements.",
        date="2026-11-14",
        existing=existing,
    )


class OtaSourceTests(unittest.TestCase):
    def test_inspects_unsigned_ipa(self):
        with tempfile.TemporaryDirectory() as raw:
            ipa = _ipa(Path(raw))
            info = ota_source.inspect_ipa(ipa, expected_version="1.0.42", expected_build="42")
            self.assertEqual(info.bundle_id, "dev.ericserver.beacon")
            self.assertEqual(info.version, "1.0.42")
            self.assertEqual(info.build, "42")
            self.assertEqual(info.minimum_os, "17.0")
            self.assertEqual(info.app_path, "Payload/Beacon.app/")
            self.assertEqual(info.size, ipa.stat().st_size)
            self.assertEqual(len(info.sha256), 64)

    def test_signed_ipa_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(ota_source.SourceError, "signing material"):
                ota_source.inspect_ipa(_ipa(Path(raw), signed=True))

    def test_version_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(ota_source.SourceError, "does not match release version"):
                ota_source.inspect_ipa(_ipa(Path(raw)), expected_version="1.0.99")

    def test_source_has_required_sidestore_fields(self):
        with tempfile.TemporaryDirectory() as raw:
            source = _source(_ipa(Path(raw)))
        self.assertEqual(source["identifier"], "dev.ericserver.beacon.source")
        self.assertEqual(source["sourceURL"], "https://example.test/releases/download/beacon-source/apps.json")
        app = source["apps"][0]
        self.assertEqual(app["bundleIdentifier"], "dev.ericserver.beacon")
        self.assertEqual(app["versions"][0]["version"], "1.0.42")
        self.assertEqual(app["versions"][0]["buildVersion"], "42")
        self.assertEqual(len(app["versions"][0]["sha256"]), 64)
        self.assertEqual(app["versions"][0]["size"], app["size"])
        self.assertEqual(app["versions"][0]["minOSVersion"], "17.0")
        self.assertEqual(app["version"], "1.0.42")
        self.assertEqual(app["downloadURL"], app["versions"][0]["downloadURL"])
        self.assertEqual(app["iconURL"], "https://example.test/releases/download/beacon-source/Beacon-AppIcon.png")
        self.assertIn("versions", app)
        self.assertIn("localizedDescription", app)

    def test_merge_preserves_history_and_prepends_newest(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            old = _source(_ipa(directory, version="1.0.41", build="41"), version="1.0.41", build="41")
            new = _source(
                _ipa(directory, version="1.0.42", build="42"),
                version="1.0.42",
                build="42",
                existing=old,
            )
        versions = new["apps"][0]["versions"]
        self.assertEqual([item["version"] for item in versions], ["1.0.42", "1.0.41"])
        self.assertEqual(new["apps"][0]["version"], "1.0.42")

    def test_merge_replaces_same_version(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            old = _source(_ipa(directory, version="1.0.42", build="42"), version="1.0.42", build="42")
            new = _source(
                _ipa(directory, version="1.0.42", build="42"),
                version="1.0.42",
                build="42",
                existing=old,
            )
        self.assertEqual([item["version"] for item in new["apps"][0]["versions"]], ["1.0.42"])

    def test_rejects_non_https_download_url(self):
        with tempfile.TemporaryDirectory() as raw:
            info = ota_source.inspect_ipa(_ipa(Path(raw)))
            with self.assertRaisesRegex(ota_source.SourceError, "downloadURL"):
                ota_source.build_source(
                    info,
                    version="1.0.42",
                    build="42",
                    source_url="https://example.test/apps.json",
                    download_url="http://example.test/Beacon.ipa",
                    icon_url="https://example.test/icon.png",
                    notes="notes",
                    date="2026-11-14",
                )

    def test_cli_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            ipa = _ipa(directory)
            output = directory / "apps.json"
            with contextlib.redirect_stderr(io.StringIO()):
                code = ota_source.main(
                    [
                        "--ipa",
                        str(ipa),
                        "--version",
                        "1.0.42",
                        "--build",
                        "42",
                        "--source-url",
                        "https://example.test/apps.json",
                        "--download-url",
                        "https://example.test/Beacon.ipa",
                        "--icon-url",
                        "https://example.test/icon.png",
                        "--notes-file",
                        str(directory / "notes.md"),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(code, 2)  # missing notes file must fail closed
            (directory / "notes.md").write_text("Release notes\n", encoding="utf-8")
            code = ota_source.main(
                [
                    "--ipa",
                    str(ipa),
                    "--version",
                    "1.0.42",
                    "--build",
                    "42",
                    "--source-url",
                    "https://example.test/apps.json",
                    "--download-url",
                    "https://example.test/Beacon.ipa",
                    "--icon-url",
                    "https://example.test/icon.png",
                    "--notes-file",
                    str(directory / "notes.md"),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, 0)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["apps"][0]["versions"][0]["localizedDescription"], "Release notes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
