#!/bin/bash
# Validate as much of the iOS project as is possible without macOS.
#
#   1. Parse every Swift file with a real Swift compiler (catches syntax errors).
#   2. Compile and test the Foundation-only subset (models, formatting, configuration, API
#      client) and run the decoding tests against fixtures captured from the live backend.
#   3. Parse and structurally validate the generated Xcode project.
#
# Full typechecking of the SwiftUI layer and an actual app build require Xcode on macOS;
# that is documented in docs/SETUP.md and is not claimed here.
set -euo pipefail

PROJECT="/home/eric/beacon"
SWIFT_IMAGE="${SWIFT_IMAGE:-swift:6.0}"

heading() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

heading "1/3 swiftc -parse (all sources)"
docker run --rm -v "$PROJECT/ios:/work" -w /work "$SWIFT_IMAGE" bash -lc '
set -e
files=$(find Beacon BeaconTests SharedTests -name "*.swift" | sort)
echo "parsing $(echo "$files" | wc -l) files"
for file in $files; do
    swiftc -parse "$file" >/dev/null
done
echo "all sources parsed"
'

heading "2/3 Foundation-only compile + tests (SwiftPM)"
docker run --rm -v "$PROJECT/ios:/work" -w /work "$SWIFT_IMAGE" swift test 2>&1 | tail -n 12

heading "3/3 Xcode project structure"
cd "$PROJECT"
if command -v uv >/dev/null 2>&1; then
    uv run --with pbxproj python scripts/validate_ios_project.py
else
    python3 scripts/validate_ios_project.py
fi

printf '\n\033[32m✓\033[0m iOS validation passed (Xcode build remains macOS-only)\n'
