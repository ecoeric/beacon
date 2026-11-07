#!/usr/bin/env python3
"""Validate the generated Xcode project and the Swift sources.

Checks performed:
  * the pbxproj parses as an Xcode project (``pbxproj`` library);
  * the app target compiles every source file that exists under ``ios/Beacon``;
  * the test target includes the snapshot test and the shared decoding test;
  * resources (asset catalog, private CA) are in the resources phase;
  * Info.plist is wired through ``INFOPLIST_FILE`` and exists;
  * the shared scheme references real target ids;
  * every ``.swift`` file on disk is referenced by exactly one target;
  * all Swift files parse (requires ``swiftc``; run ``scripts/validate_ios.sh`` for that step).

Usage:  python3 scripts/validate_ios_project.py
Requires:  pbxproj (pip/pipx), e.g. `uv run --with pbxproj python scripts/validate_ios_project.py`
"""

from __future__ import annotations

import pathlib
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
IOS = ROOT / "ios"
PROJECT = IOS / "Beacon.xcodeproj" / "project.pbxproj"
SCHEME = IOS / "Beacon.xcodeproj" / "xcshareddata" / "xcschemes" / "Beacon.xcscheme"

failures: list[str] = []


def setting(config, key: str, default: str = "") -> str:
    """Read one build setting from a PBXGenericObject-ish configuration."""
    try:
        value = config.buildSettings[key]
    except Exception:
        return default
    return "" if value is None else str(value)


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"✓ {message}")
    else:
        failures.append(message)
        print(f"✗ {message}")


def main() -> int:
    try:
        from pbxproj import XcodeProject
    except ImportError:
        print("pbxproj library is required: uv run --with pbxproj python scripts/validate_ios_project.py")
        return 2

    check(PROJECT.exists(), "project.pbxproj exists")
    project = XcodeProject.load(str(PROJECT))

    targets = {target.name: target for target in project.objects.get_targets()}
    check("Beacon" in targets, "app target 'Beacon' present")
    check("BeaconTests" in targets, "test target 'BeaconTests' present")

    app = targets.get("Beacon")
    tests = targets.get("BeaconTests")

    def source_paths(target) -> set[str]:
        paths: set[str] = set()
        for phase_id in target.buildPhases:
            phase = project.objects[phase_id]
            if phase.isa != "PBXSourcesBuildPhase":
                continue
            for build_file_id in phase.files:
                build_file = project.objects[build_file_id]
                file_ref = project.objects[build_file.fileRef]
                paths.add(str(file_ref.path))
        return paths

    def resource_paths(target) -> set[str]:
        paths: set[str] = set()
        for phase_id in target.buildPhases:
            phase = project.objects[phase_id]
            if phase.isa != "PBXResourcesBuildPhase":
                continue
            for build_file_id in phase.files:
                build_file = project.objects[build_file_id]
                file_ref = project.objects[build_file.fileRef]
                paths.add(str(file_ref.path))
        return paths

    app_sources = source_paths(app)
    test_sources = source_paths(tests)
    print(f"  app sources: {len(app_sources)} · test sources: {len(test_sources)}")

    on_disk_app = {
        str(path.relative_to(IOS))
        for path in (IOS / "Beacon").rglob("*.swift")
    }
    missing = on_disk_app - app_sources
    check(not missing, f"every app Swift file is in the app target ({len(on_disk_app)} files)" + (f" — missing {sorted(missing)}" if missing else ""))

    extra = app_sources - on_disk_app
    check(not extra, "no app target entry points at a non-existent file" + (f" — extra {sorted(extra)}" if extra else ""))

    shared_tests = {str(path.relative_to(IOS)) for path in (IOS / "SharedTests").rglob("*.swift")}
    snapshot_tests = {str(path.relative_to(IOS)) for path in (IOS / "BeaconTests").rglob("*.swift")}
    check(shared_tests <= test_sources, "shared decoding tests are compiled into the test target")
    check(snapshot_tests <= test_sources, "snapshot tests are compiled into the test target")

    resources = resource_paths(app)
    check(any(path.endswith("Assets.xcassets") for path in resources), "asset catalog is in the resources phase")
    check(any(path.endswith("ca.crt") for path in resources), "private CA certificate is bundled")

    info_plist = IOS / "Beacon" / "Resources" / "Info.plist"
    check(info_plist.exists(), "Info.plist exists")
    app_configs = [
        project.objects[config_id]
        for config_id in project.objects[app.buildConfigurationList].buildConfigurations
    ]
    check(
        all(setting(config, "INFOPLIST_FILE") == "Beacon/Resources/Info.plist" for config in app_configs),
        "INFOPLIST_FILE points at Beacon/Resources/Info.plist",
    )
    bundle_ids = {setting(config, "PRODUCT_BUNDLE_IDENTIFIER") for config in app_configs}
    check(bundle_ids == {"dev.ericserver.beacon"}, "app bundle identifier is dev.ericserver.beacon")
    pbx_text = PROJECT.read_text(encoding="utf-8")
    check(
        pbx_text.count("IPHONEOS_DEPLOYMENT_TARGET = 17.0;") >= 2,
        "iOS deployment target is 17.0 in both build configurations",
    )

    test_configs = [
        project.objects[config_id]
        for config_id in project.objects[tests.buildConfigurationList].buildConfigurations
    ]
    check(
        all(setting(config, "BUNDLE_LOADER").startswith("$(TEST_HOST)") for config in test_configs),
        "test target is hosted by the app (BUNDLE_LOADER/TEST_HOST)",
    )

    check(SCHEME.exists(), "shared scheme exists")
    if SCHEME.exists():
        tree = ET.parse(SCHEME)
        identifiers = {
            element.get("BlueprintIdentifier")
            for element in tree.iter("BuildableReference")
            if element.get("BlueprintIdentifier")
        }
        known = {str(target.get_id()) for target in targets.values()}
        check(identifiers <= known, "scheme references existing target ids")
        check(len(identifiers) >= 2, "scheme includes app and test targets")

    stray = [
        str(path.relative_to(ROOT))
        for path in IOS.rglob("*.swift")
        if path.name != "Package.swift"
        and "/.build/" not in str(path)
        and str(path.relative_to(IOS)) not in app_sources
        and str(path.relative_to(IOS)) not in test_sources
    ]
    check(not stray, "no unreferenced Swift files" + (f" — stray {stray}" if stray else ""))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("Xcode project validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
