#!/bin/bash
# Validate as much of the iOS project as is possible without macOS.
#
#   1. Parse every Swift file with a real Swift compiler (catches syntax errors).
#   2. Compile and test the Foundation-only subset (models, formatting, configuration, API
#      client) and run the decoding tests against fixtures captured from the live backend.
#   3. Typecheck every app and Xcode test source against mock SwiftUI/UIKit/Combine/XCTest
#      modules (see scripts/typecheck_ios_views.sh) — real compiler, mock signatures.
#   4. Check view initialiser call sites.
#   5. Parse and structurally validate the generated Xcode project.
#
# An actual iOS-SDK build requires Xcode on macOS. The GitHub Actions workflow in
# .github/workflows/ios-build.yml performs that real build; it is not claimed here.
set -euo pipefail

PROJECT="/home/eric/beacon"
SWIFT_IMAGE="${SWIFT_IMAGE:-swift:6.0}"

heading() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

USER_FLAGS=(--user "$(id -u):$(id -g)" -e HOME=/tmp)
heading "1/5 swiftc -parse (all sources)"
sudo docker run --rm "${USER_FLAGS[@]}" -v "$PROJECT/ios:/work" -w /work "$SWIFT_IMAGE" bash -lc '
set -e
files=$(find Beacon BeaconTests SharedTests -name "*.swift" | sort)
echo "parsing $(echo "$files" | wc -l) files"
for file in $files; do
    swiftc -parse "$file" >/dev/null
done
echo "all sources parsed"
'

heading "2/5 Foundation-only compile + tests (SwiftPM)"
sudo docker run --rm "${USER_FLAGS[@]}" -v "$PROJECT/ios:/work" -w /work "$SWIFT_IMAGE" swift test 2>&1 | tail -n 12

heading "3/5 app + test typecheck (mock frameworks, real compiler)"
bash "$PROJECT/scripts/typecheck_ios_views.sh"

heading "4/5 view initialiser call sites"
cd "$PROJECT"
python3 scripts/check_view_initialisers.py

heading "5/5 Xcode project structure"
if command -v uv >/dev/null 2>&1; then
    uv run --with pbxproj python scripts/validate_ios_project.py
else
    python3 scripts/validate_ios_project.py
fi

printf '\n\033[32m✓\033[0m iOS validation passed (mock-framework typecheck; real Xcode build is CI-only)\n'
