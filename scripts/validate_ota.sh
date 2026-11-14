#!/bin/bash
# Validate the SideStore OTA pipeline without GitHub or macOS.
# This checks the feed generator, the generated icon, Info.plist version placeholders and the
# workflow structure. The real iOS build and a SideStore install still require the GitHub macOS
# runner and an iPhone.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== OTA source generator tests"
python3 scripts/test_ota_source.py

echo "== Icon reproducibility"
TMP_ICON="$(mktemp --suffix=.png)"
trap 'rm -f "$TMP_ICON"' EXIT
python3 scripts/make_app_icon.py "$TMP_ICON" >/dev/null
cmp -s "$TMP_ICON" ios/Beacon/Resources/AppIcon.png
echo "✓ committed AppIcon.png matches scripts/make_app_icon.py"

echo "== Info.plist version placeholders"
python3 - <<'PY'
import plistlib
from pathlib import Path
info = plistlib.loads(Path("ios/Beacon/Resources/Info.plist").read_bytes())
assert info["CFBundleShortVersionString"] == "$(MARKETING_VERSION)"
assert info["CFBundleVersion"] == "$(CURRENT_PROJECT_VERSION)"
print("✓ CFBundleShortVersionString and CFBundleVersion are build-setting driven")
PY

echo "== Workflow structure"
python3 - <<'PY'
from pathlib import Path
try:
    import yaml
except ImportError:
    print("! PyYAML not installed; structural YAML check skipped")
    raise SystemExit(0)
data = yaml.safe_load(Path(".github/workflows/ios-build.yml").read_text())
jobs = data["jobs"]
assert "unsigned-ipa" in jobs
assert "simulator-tests" in jobs
assert "publish" in jobs
assert set(jobs["publish"]["needs"]) == {"unsigned-ipa", "simulator-tests"}
assert jobs["publish"]["permissions"]["contents"] == "write"
assert "ota_source.py" in Path(".github/workflows/ios-build.yml").read_text()
print("✓ workflow has gated publish job")
PY

if command -v actionlint >/dev/null 2>&1; then
    echo "== actionlint"
    actionlint .github/workflows/ios-build.yml
else
    echo "! actionlint not installed; install it for full expression/shell validation"
fi

echo "✓ OTA pipeline local validation passed (real build and SideStore install are external)"
