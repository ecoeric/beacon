#!/usr/bin/env bash
# Typecheck every Beacon app and Xcode test source with the real Swift compiler on Linux.
#
# WHY: this host has no Xcode or iOS SDK, so a genuine iOS build is impossible here. This script
# compiles small *mock* modules that reproduce the SwiftUI/UIKit/Combine/XCTest API surface Beacon
# uses, then typechecks the app and test sources against them. It catches real Swift errors (types, generics,
# property wrappers, result builders, isolation) but it is NOT an iOS build: mock signatures and
# no iOS SDK are involved. A real Xcode build runs in CI (see docs/CI.md).
#
# It uses the swift:6.0 Docker image, never installs anything on the host, and does not touch the
# running Beacon service.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${BEACON_SWIFT_IMAGE:-swift:6.0}"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    DOCKER=(docker)
elif command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
    DOCKER=(sudo -n docker)
else
    echo "typecheck: Docker is not available (need docker or passwordless sudo docker)." >&2
    exit 2
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/beacon-typecheck.XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

mkdir -p "$WORK/Sources" "$WORK/Tests" "$WORK/Shim" "$WORK/Modules" "$WORK/Logs"

# Copy app sources except the three files that need the iOS SDK (Security/CryptoKit) or are the
# @main entry point. PlatformStubs.swift supplies the two small surfaces those files expose.
while IFS= read -r file; do
    base="$(basename "$file")"
    case "$base" in
        BeaconApp.swift|Keychain.swift|PinnedSession.swift) continue ;;
    esac
    cp "$file" "$WORK/Sources/$base"
done < <(find "$ROOT/ios/Beacon" -name '*.swift' | sort)
cp "$ROOT/ios/Shim/"*.swift "$WORK/Shim/"
cp "$ROOT/ios/Shim/PlatformStubs.swift" "$WORK/Sources/"
cp "$ROOT/ios/SharedTests/"*.swift "$WORK/Tests/"
cp "$ROOT/ios/BeaconTests/"*.swift "$WORK/Tests/"
python3 "$ROOT/scripts/strip_swift_previews.py" "$WORK/Sources/"*.swift

cat > "$WORK/build.sh" <<'BUILD'
set -euo pipefail
cd /work
SWIFTC=(swiftc -swift-version 5)

# 1. Mock framework modules. UIKit and Combine come first; SwiftUI imports both.
"${SWIFTC[@]}" -emit-module -parse-as-library -module-name UIKit \
    -emit-module-path Modules/UIKit.swiftmodule Shim/UIKit.swift
"${SWIFTC[@]}" -emit-module -parse-as-library -module-name Combine \
    -emit-module-path Modules/Combine.swiftmodule Shim/Combine.swift
"${SWIFTC[@]}" -emit-module -parse-as-library -module-name XCTest \
    -emit-module-path Modules/XCTest.swiftmodule Shim/XCTest.swift
"${SWIFTC[@]}" -emit-module -parse-as-library -module-name SwiftUI -I Modules \
    -emit-module-path Modules/SwiftUI.swiftmodule Shim/SwiftUI.swift Shim/SwiftUIModifiers.swift

# 2. Typecheck the app and emit a testable module for the test-source pass.
#    -warnings-as-errors would flag mock-only concurrency notes, so only hard errors fail.
echo "typechecking $(find Sources -name '*.swift' | wc -l) app files"
"${SWIFTC[@]}" -emit-module -enable-testing -module-name Beacon -I Modules \
    -emit-module-path Modules/Beacon.swiftmodule $(find Sources -name '*.swift' | sort)

# 3. Typecheck the Xcode test sources (@testable import Beacon) against the mock XCTest module.
echo "typechecking $(find Tests -name '*.swift' | wc -l) test files"
"${SWIFTC[@]}" -typecheck -module-name BeaconTests -I Modules $(find Tests -name '*.swift' | sort)
BUILD

echo "typecheck: swift 6.0 in $IMAGE"
echo "typecheck: $(find "$WORK/Sources" -name '*.swift' | wc -l) app files + $(find "$WORK/Tests" -name '*.swift' | wc -l) test files + 6 stub files"

"${DOCKER[@]}" run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "$WORK:/work" \
    -w /work \
    "$IMAGE" \
    bash /work/build.sh

echo "typecheck: PASS — app and test sources typecheck against the mock frameworks"
echo "typecheck: note — this is compiler validation, not an iOS SDK build; CI does the real Xcode build"
