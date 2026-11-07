#!/usr/bin/env python3
"""Generate `ios/Beacon.xcodeproj` deterministically.

Xcode is not available on this Linux host, so the project file is produced from this script
and committed. IDs are derived from paths, which keeps regeneration stable and reviewable.

    python3 scripts/gen_xcodeproj.py

Validated by `scripts/validate_ios_project.py` (parses the pbxproj and cross-checks that every
Swift file on disk is referenced exactly once by the right target).
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
IOS = ROOT / "ios"

APP_SOURCES = [
    "Beacon/App/BeaconApp.swift",
    "Beacon/App/RootView.swift",
    "Beacon/App/AppModel.swift",
    "Beacon/Design/Theme.swift",
    "Beacon/Design/Components.swift",
    "Beacon/Models/Models.swift",
    "Beacon/Models/Formatting.swift",
    "Beacon/Networking/ServerConfiguration.swift",
    "Beacon/Networking/APIClient.swift",
    "Beacon/Networking/PinnedSession.swift",
    "Beacon/Networking/Keychain.swift",
    "Beacon/Networking/AppSettings.swift",
    "Beacon/Features/Setup/OnboardingView.swift",
    "Beacon/Features/Dashboard/DashboardView.swift",
    "Beacon/Features/Agent/AgentView.swift",
    "Beacon/Features/Milestones/MilestonesView.swift",
    "Beacon/Features/Milestones/ScreenshotViewer.swift",
    "Beacon/Features/Server/ServerView.swift",
    "Beacon/Features/Settings/SettingsView.swift",
    "Beacon/Fixtures.swift",
]

APP_RESOURCES = [
    "Beacon/Resources/Assets.xcassets",
    "Beacon/Resources/ca.crt",
]

TEST_SOURCES = [
    "BeaconTests/SnapshotTests.swift",
    "SharedTests/ModelDecodingTests.swift",
]

INFO_PLIST = "Beacon/Resources/Info.plist"

PROJECT_NAME = "Beacon"
APPS_GROUP = "Beacon"
TESTS_GROUP_NAME = "BeaconTests"

APP_BUNDLE_ID = "dev.ericserver.beacon"
TEST_BUNDLE_ID = "dev.ericserver.beacon.tests"

DEPLOYMENT_TARGET = "17.0"
SWIFT_VERSION = "5.9"


def oid(key: str) -> str:
    """Deterministic 24-character hex identifier (Xcode-style)."""
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:24].upper()


def file_type(path: str) -> str:
    if path.endswith(".swift"):
        return "sourcecode.swift"
    if path.endswith(".plist"):
        return "text.plist.xml"
    if path.endswith(".xcassets"):
        return "folder.assetcatalog"
    if path.endswith(".crt"):
        return "file"
    return "file"


class ProjectBuilder:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.phase_entries: dict[str, list[str]] = {}
        self.groups: dict[str, list[str]] = {}
        self.target_dependencies: list[str] = []
        self.config_ids: dict[str, str] = {}

    # -- primitives ---------------------------------------------------------
    def open(self, comment: str = "") -> None:
        self.lines.append("{")

    def section(self, name: str) -> None:
        self.lines.append(f"\n/* Begin {name} section */")

    def end_section(self, name: str) -> None:
        self.lines.append(f"/* End {name} section */\n")

    def render(self) -> str:
        return "\n".join(self.lines) + "\n"


def build() -> str:
    lines: list[str] = []
    add = lines.append

    add("// !$*UTF8*$!")
    add("{")
    add("\tarchiveVersion = 1;")
    add("\tclasses = {")
    add("\t};")
    add("\tobjectVersion = 56;")
    add("\tobjects = {")
    add("")

    # ---- PBXBuildFile
    add("/* Begin PBXBuildFile section */")
    for path in APP_SOURCES + TEST_SOURCES + APP_RESOURCES:
        name = pathlib.Path(path).name
        add(
            f"\t\t{oid('buildfile:' + path)} /* {name} in "
            f"{'Resources' if path in APP_RESOURCES else 'Sources'} */ = {{isa = PBXBuildFile; "
            f"fileRef = {oid('fileref:' + path)} /* {name} */; }};"
        )
    add("/* End PBXBuildFile section */")
    add("")

    # ---- PBXFileReference
    add("/* Begin PBXFileReference section */")
    add(
        f"\t\t{oid('product:app')} /* {PROJECT_NAME}.app */ = {{isa = PBXFileReference; "
        f"explicitFileType = wrapper.application; includeInIndex = 0; path = {PROJECT_NAME}.app; "
        "sourceTree = BUILT_PRODUCTS_DIR; };"
    )
    add(
        f"\t\t{oid('product:tests')} /* {PROJECT_NAME}Tests.xctest */ = {{isa = PBXFileReference; "
        f"explicitFileType = wrapper.cfbundle; includeInIndex = 0; path = {PROJECT_NAME}Tests.xctest; "
        "sourceTree = BUILT_PRODUCTS_DIR; };"
    )
    for path in APP_SOURCES + TEST_SOURCES + APP_RESOURCES + [INFO_PLIST]:
        name = pathlib.Path(path).name
        add(
            f"\t\t{oid('fileref:' + path)} /* {name} */ = {{isa = PBXFileReference; "
            f"lastKnownFileType = {file_type(path)}; path = {path}; sourceTree = \"<group>\"; }};"
        )
    add("/* End PBXFileReference section */")
    add("")

    # ---- PBXFrameworksBuildPhase
    add("/* Begin PBXFrameworksBuildPhase section */")
    for key in ("app", "tests"):
        add(
            f"\t\t{oid('phase:frameworks:' + key)} /* Frameworks */ = {{isa = PBXFrameworksBuildPhase; "
            "buildActionMask = 2147483647; files = ("
            "); runOnlyForDeploymentPostprocessing = 0; };"
        )
    add("/* End PBXFrameworksBuildPhase section */")
    add("")

    # ---- PBXGroup
    add("/* Begin PBXGroup section */")
    add(
        f"\t\t{oid('group:main')} = {{isa = PBXGroup; children = ("
        f"{oid('group:app')} /* {APPS_GROUP} */, {oid('group:tests')} /* {TESTS_GROUP_NAME} */, "
        f"{oid('group:shared')} /* SharedTests */, {oid('group:products')} /* Products */, "
        "); sourceTree = \"<group>\"; };"
    )
    # App group: mirror the directories so Xcode shows the same structure as the filesystem.
    app_groups: dict[str, list[str]] = {
        "Beacon/App": [],
        "Beacon/Design": [],
        "Beacon/Models": [],
        "Beacon/Networking": [],
        "Beacon/Features/Setup": [],
        "Beacon/Features/Dashboard": [],
        "Beacon/Features/Agent": [],
        "Beacon/Features/Milestones": [],
        "Beacon/Features/Server": [],
        "Beacon/Features/Settings": [],
        "Beacon/Resources": [],
    }
    app_root_files: list[str] = []
    for path in APP_SOURCES + APP_RESOURCES + [INFO_PLIST]:
        parent = str(pathlib.Path(path).parent)
        if parent == "Beacon":
            app_root_files.append(path)
        elif parent in app_groups:
            app_groups[parent].append(path)
        else:
            app_root_files.append(path)

    feature_children: list[str] = []
    for directory in sorted(app_groups):
        children = app_groups[directory]
        if not children:
            continue
        group_id = oid("group:dir:" + directory)
        if directory.startswith("Beacon/Features/"):
            feature_children.append(group_id)
        child_refs = " ".join(
            f"{oid('fileref:' + child)} /* {pathlib.Path(child).name} */," for child in children
        )
        add(
            f"\t\t{group_id} /* {pathlib.Path(directory).name} */ = {{isa = PBXGroup; children = ("
            f"{child_refs} ); path = {directory}; sourceTree = \"<group>\"; }};"
        )
    if feature_children:
        add(
            f"\t\t{oid('group:features')} /* Features */ = {{isa = PBXGroup; children = ("
            + " ".join(f"{child}," for child in feature_children)
            + " ); path = Beacon/Features; sourceTree = \"<group>\"; };"
        )
    app_root_refs = " ".join(
        f"{oid('fileref:' + child)} /* {pathlib.Path(child).name} */," for child in app_root_files
    )
    app_group_children = (
        f"{oid('group:dir:Beacon/App')}, {oid('group:dir:Beacon/Design')}, "
        f"{oid('group:dir:Beacon/Models')}, {oid('group:dir:Beacon/Networking')}, "
        f"{oid('group:features')}, {oid('group:dir:Beacon/Resources')}, {app_root_refs}"
    )
    add(
        f"\t\t{oid('group:app')} /* {APPS_GROUP} */ = {{isa = PBXGroup; children = ("
        f"{app_group_children} ); path = {APPS_GROUP}; sourceTree = \"<group>\"; }};"
    )
    test_refs = " ".join(
        f"{oid('fileref:' + child)} /* {pathlib.Path(child).name} */," for child in TEST_SOURCES if child.startswith("BeaconTests/")
    )
    shared_refs = " ".join(
        f"{oid('fileref:' + child)} /* {pathlib.Path(child).name} */," for child in TEST_SOURCES if child.startswith("SharedTests/")
    )
    add(
        f"\t\t{oid('group:tests')} /* {TESTS_GROUP_NAME} */ = {{isa = PBXGroup; children = ("
        f"{test_refs} ); path = {TESTS_GROUP_NAME}; sourceTree = \"<group>\"; }};"
    )
    add(
        f"\t\t{oid('group:shared')} /* SharedTests */ = {{isa = PBXGroup; children = ("
        f"{shared_refs} ); path = SharedTests; sourceTree = \"<group>\"; }};"
    )
    add(
        f"\t\t{oid('group:products')} /* Products */ = {{isa = PBXGroup; children = ("
        f"{oid('product:app')} /* {PROJECT_NAME}.app */, {oid('product:tests')} /* {PROJECT_NAME}Tests.xctest */, "
        "); name = Products; sourceTree = \"<group>\"; };"
    )
    add("/* End PBXGroup section */")
    add("")

    # ---- PBXNativeTarget
    add("/* Begin PBXNativeTarget section */")
    add(
        f"\t\t{oid('target:app')} /* {PROJECT_NAME} */ = {{isa = PBXNativeTarget; "
        f"buildConfigurationList = {oid('configlist:app')} /* Build configuration list for PBXNativeTarget \"{PROJECT_NAME}\" */; "
        "buildPhases = ("
        f"{oid('phase:sources:app')} /* Sources */, {oid('phase:frameworks:app')} /* Frameworks */, "
        f"{oid('phase:resources:app')} /* Resources */, ); buildRules = ( ); dependencies = ( ); "
        f"name = {PROJECT_NAME}; productName = {PROJECT_NAME}; "
        f"productReference = {oid('product:app')} /* {PROJECT_NAME}.app */; productType = \"com.apple.product-type.application\"; }};"
    )
    add(
        f"\t\t{oid('target:tests')} /* {PROJECT_NAME}Tests */ = {{isa = PBXNativeTarget; "
        f"buildConfigurationList = {oid('configlist:tests')} /* Build configuration list for PBXNativeTarget \"{PROJECT_NAME}Tests\" */; "
        "buildPhases = ("
        f"{oid('phase:sources:tests')} /* Sources */, {oid('phase:frameworks:tests')} /* Frameworks */, ); "
        "buildRules = ( ); dependencies = ("
        f"{oid('dependency:tests')} /* PBXTargetDependency */, ); name = {PROJECT_NAME}Tests; "
        f"productName = {PROJECT_NAME}Tests; productReference = {oid('product:tests')} /* {PROJECT_NAME}Tests.xctest */; "
        "productType = \"com.apple.product-type.bundle.unit-test\"; };"
    )
    add("/* End PBXNativeTarget section */")
    add("")

    # ---- PBXProject
    add("/* Begin PBXProject section */")
    add(
        f"\t\t{oid('project')} /* Project object */ = {{isa = PBXProject; attributes = {{"
        "BuildIndependentTargetsInParallel = 1; LastSwiftUpdateCheck = 1600; LastUpgradeCheck = 1600; "
        "TargetAttributes = {"
        f"{oid('target:app')} = {{CreatedOnToolsVersion = 16.0; }}; "
        f"{oid('target:tests')} = {{CreatedOnToolsVersion = 16.0; TestTargetID = {oid('target:app')}; }}; "
        "}; }; buildConfigurationList = "
        f"{oid('configlist:project')} /* Build configuration list for PBXProject \"{PROJECT_NAME}\" */; "
        "compatibilityVersion = \"Xcode 14.0\"; developmentRegion = en; hasScannedForEncodings = 0; "
        "knownRegions = ( en, Base, ); mainGroup = "
        f"{oid('group:main')}; productRefGroup = {oid('group:products')} /* Products */; "
        "projectDirPath = \"\"; projectRoot = \"\"; targets = ("
        f"{oid('target:app')} /* {PROJECT_NAME} */, {oid('target:tests')} /* {PROJECT_NAME}Tests */, ); }};"
    )
    add("/* End PBXProject section */")
    add("")

    # ---- Resources
    add("/* Begin PBXResourcesBuildPhase section */")
    resource_refs = " ".join(
        f"{oid('buildfile:' + path)} /* {pathlib.Path(path).name} in Resources */," for path in APP_RESOURCES
    )
    add(
        f"\t\t{oid('phase:resources:app')} /* Resources */ = {{isa = PBXResourcesBuildPhase; "
        f"buildActionMask = 2147483647; files = ( {resource_refs} ); runOnlyForDeploymentPostprocessing = 0; }};"
    )
    add("/* End PBXResourcesBuildPhase section */")
    add("")

    # ---- Sources
    add("/* Begin PBXSourcesBuildPhase section */")
    app_source_refs = " ".join(
        f"{oid('buildfile:' + path)} /* {pathlib.Path(path).name} in Sources */," for path in APP_SOURCES
    )
    test_source_refs = " ".join(
        f"{oid('buildfile:' + path)} /* {pathlib.Path(path).name} in Sources */," for path in TEST_SOURCES
    )
    add(
        f"\t\t{oid('phase:sources:app')} /* Sources */ = {{isa = PBXSourcesBuildPhase; "
        f"buildActionMask = 2147483647; files = ( {app_source_refs} ); runOnlyForDeploymentPostprocessing = 0; }};"
    )
    add(
        f"\t\t{oid('phase:sources:tests')} /* Sources */ = {{isa = PBXSourcesBuildPhase; "
        f"buildActionMask = 2147483647; files = ( {test_source_refs} ); runOnlyForDeploymentPostprocessing = 0; }};"
    )
    add("/* End PBXSourcesBuildPhase section */")
    add("")

    # ---- Dependency
    add("/* Begin PBXTargetDependency section */")
    add(
        f"\t\t{oid('dependency:tests')} /* PBXTargetDependency */ = {{isa = PBXTargetDependency; "
        f"target = {oid('target:app')} /* {PROJECT_NAME} */; targetProxy = {oid('proxy:tests')} /* PBXContainerItemProxy */; }};"
    )
    add("/* End PBXTargetDependency section */")
    add("")

    add("/* Begin PBXContainerItemProxy section */")
    add(
        f"\t\t{oid('proxy:tests')} /* PBXContainerItemProxy */ = {{isa = PBXContainerItemProxy; "
        f"containerPortal = {oid('project')} /* Project object */; proxyType = 1; "
        f"remoteGlobalIDString = {oid('target:app')}; remoteInfo = {PROJECT_NAME}; }};"
    )
    add("/* End PBXContainerItemProxy section */")
    add("")

    # ---- Build configurations
    def configuration(config_id: str, key: str, name: str, settings: dict[str, str]) -> None:
        add(f"\t\t{config_id} /* {name} */ = {{isa = XCBuildConfiguration; buildSettings = {{")
        for setting, value in settings.items():
            add(f"\t\t\t{setting} = {value};")
        add("\t\t}; name = " + name + "; };")

    common_project = {
        "ALWAYS_SEARCH_USER_PATHS": "NO",
        "CLANG_ANALYZER_NONNULL": "YES",
        "CLANG_ENABLE_MODULES": "YES",
        "CLANG_ENABLE_OBJC_ARC": "YES",
        "ENABLE_STRICT_OBJC_MSGSEND": "YES",
        "GCC_C_LANGUAGE_STANDARD": "gnu17",
        "IPHONEOS_DEPLOYMENT_TARGET": DEPLOYMENT_TARGET,
        "SDKROOT": "iphoneos",
        "SWIFT_VERSION": SWIFT_VERSION,
    }
    project_debug = dict(common_project)
    project_debug.update(
        {
            "DEBUG_INFORMATION_FORMAT": "dwarf",
            "ENABLE_TESTABILITY": "YES",
            "GCC_OPTIMIZATION_LEVEL": "0",
            "ONLY_ACTIVE_ARCH": "YES",
            "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "DEBUG",
            "SWIFT_OPTIMIZATION_LEVEL": "\"-Onone\"",
        }
    )
    project_release = dict(common_project)
    project_release.update(
        {
            "DEBUG_INFORMATION_FORMAT": "\"dwarf-with-dsym\"",
            "ENABLE_NS_ASSERTIONS": "NO",
            "SWIFT_COMPILATION_MODE": "wholemodule",
            "VALIDATE_PRODUCT": "YES",
        }
    )

    app_common = {
        "ASSETCATALOG_COMPILER_APPICON_NAME": "AppIcon",
        "ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME": "AccentColor",
        "CODE_SIGN_STYLE": "Automatic",
        "CURRENT_PROJECT_VERSION": "1",
        "DEVELOPMENT_TEAM": "\"\"",
        "ENABLE_PREVIEWS": "YES",
        "GENERATE_INFOPLIST_FILE": "NO",
        "INFOPLIST_FILE": INFO_PLIST,
        "MARKETING_VERSION": "1.0",
        "PRODUCT_BUNDLE_IDENTIFIER": APP_BUNDLE_ID,
        "PRODUCT_NAME": "\"$(TARGET_NAME)\"",
        "SUPPORTED_PLATFORMS": "\"iphoneos iphonesimulator\"",
        "SUPPORTS_MACCATALYST": "NO",
        "SWIFT_EMIT_LOC_STRINGS": "YES",
        "SWIFT_STRICT_CONCURRENCY": "minimal",
        "SWIFT_VERSION": SWIFT_VERSION,
        "TARGETED_DEVICE_FAMILY": "1",
    }
    app_debug = dict(app_common)
    app_debug["SWIFT_ACTIVE_COMPILATION_CONDITIONS"] = "DEBUG"
    app_release = dict(app_common)

    test_common = {
        "BUNDLE_LOADER": "\"$(TEST_HOST)\"",
        "CODE_SIGN_STYLE": "Automatic",
        "CURRENT_PROJECT_VERSION": "1",
        "DEVELOPMENT_TEAM": "\"\"",
        "GENERATE_INFOPLIST_FILE": "YES",
        "MARKETING_VERSION": "1.0",
        "PRODUCT_BUNDLE_IDENTIFIER": TEST_BUNDLE_ID,
        "PRODUCT_NAME": "\"$(TARGET_NAME)\"",
        "SUPPORTED_PLATFORMS": "\"iphoneos iphonesimulator\"",
        "SWIFT_STRICT_CONCURRENCY": "minimal",
        "SWIFT_VERSION": SWIFT_VERSION,
        "TARGETED_DEVICE_FAMILY": "1",
        "TEST_HOST": "\"$(BUILT_PRODUCTS_DIR)/Beacon.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/Beacon\"",
    }

    add("/* Begin XCBuildConfiguration section */")
    configuration(oid("config:project:debug"), "project", "Debug", project_debug)
    configuration(oid("config:project:release"), "project", "Release", project_release)
    configuration(oid("config:app:debug"), "app", "Debug", app_debug)
    configuration(oid("config:app:release"), "app", "Release", app_release)
    configuration(oid("config:tests:debug"), "tests", "Debug", test_common)
    configuration(oid("config:tests:release"), "tests", "Release", test_common)
    add("/* End XCBuildConfiguration section */")
    add("")

    add("/* Begin XCConfigurationList section */")
    for key, label in (
        ("project", f"PBXProject \"{PROJECT_NAME}\""),
        ("app", f"PBXNativeTarget \"{PROJECT_NAME}\""),
        ("tests", f"PBXNativeTarget \"{PROJECT_NAME}Tests\""),
    ):
        add(
            f"\t\t{oid('configlist:' + key)} /* Build configuration list for {label} */ = {{"
            "isa = XCConfigurationList; buildConfigurations = ("
            f"{oid(f'config:{key}:debug')} /* Debug */, {oid(f'config:{key}:release')} /* Release */, "
            "); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release; };"
        )
    add("/* End XCConfigurationList section */")
    add("")

    add("\t};")
    add(f"\trootObject = {oid('project')} /* Project object */;")
    add("}")
    return "\n".join(lines) + "\n"


SCHEME = """<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="1600" version="1.7">
   <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">
            <BuildableReference
               BuildableIdentifier="primary"
               BlueprintIdentifier="{APP_TARGET}"
               BuildableName="Beacon.app"
               BlueprintName="Beacon"
               ReferencedContainer="container:Beacon.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES">
      <Testables>
         <TestableReference skipped="NO">
            <BuildableReference
               BuildableIdentifier="primary"
               BlueprintIdentifier="{TEST_TARGET}"
               BuildableName="BeaconTests.xctest"
               BlueprintName="BeaconTests"
               ReferencedContainer="container:Beacon.xcodeproj">
            </BuildableReference>
         </TestableReference>
      </Testables>
   </TestAction>
   <LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" debugServiceExtension="internal" allowLocationSimulation="YES">
      <BuildableProductRunnable runnableDebuggingMode="0">
         <BuildableReference
            BuildableIdentifier="primary"
            BlueprintIdentifier="{APP_TARGET}"
            BuildableName="Beacon.app"
            BlueprintName="Beacon"
            ReferencedContainer="container:Beacon.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </LaunchAction>
   <ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES">
      <BuildableProductRunnable runnableDebuggingMode="0">
         <BuildableReference
            BuildableIdentifier="primary"
            BlueprintIdentifier="{APP_TARGET}"
            BuildableName="Beacon.app"
            BlueprintName="Beacon"
            ReferencedContainer="container:Beacon.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </ProfileAction>
   <AnalyzeAction buildConfiguration="Debug"/>
   <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
"""

WORKSPACE = """<?xml version="1.0" encoding="UTF-8"?>
<Workspace version = "1.0">
   <FileRef location = "self:">
   </FileRef>
</Workspace>
"""


def main() -> int:
    missing = [path for path in APP_SOURCES + TEST_SOURCES + APP_RESOURCES + [INFO_PLIST] if not (IOS / path).exists()]
    if missing:
        print("missing files:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1
    project_dir = IOS / "Beacon.xcodeproj"
    (project_dir / "project.xcworkspace").mkdir(parents=True, exist_ok=True)
    (project_dir / "xcshareddata" / "xcschemes").mkdir(parents=True, exist_ok=True)
    (project_dir / "project.pbxproj").write_text(build(), encoding="utf-8")
    (project_dir / "project.xcworkspace" / "contents.xcworkspacedata").write_text(WORKSPACE, encoding="utf-8")
    (project_dir / "xcshareddata" / "xcschemes" / "Beacon.xcscheme").write_text(
        SCHEME.replace("{APP_TARGET}", oid("target:app")).replace("{TEST_TARGET}", oid("target:tests")),
        encoding="utf-8",
    )
    print(f"wrote {project_dir.relative_to(ROOT)} ({len(APP_SOURCES)} app sources, {len(TEST_SOURCES)} test sources)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
