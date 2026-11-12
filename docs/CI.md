# iOS build & test CI (no Mac required)

Beacon is developed on a Linux host. That host has the real Swift compiler (via Docker) but **no
Xcode, no iOS SDK and no simulator**, so it cannot produce an iOS build. Two independent checks
cover the gap; they are deliberately not conflated:

| Check | Where | What it proves |
|---|---|---|
| `scripts/typecheck_ios_views.sh` | this host, Docker `swift:6.0` | Every app source and both Xcode test files typecheck with the real Swift compiler against mock SwiftUI/UIKit/Combine/XCTest modules. Catches type, generic, result-builder, property-wrapper and concurrency errors. **Not an iOS build** (mock signatures, no SDK). |
| `.github/workflows/ios-build.yml` | GitHub-hosted `macos-15` runner | A real Xcode build of the generated project plus `xcodebuild test` on an iPhone simulator. This is the authoritative compile/run confirmation. |

`scripts/validate_ios.sh` runs the first check along with parsing, Foundation tests, call-site
checks and project validation.

## Running the real build

The workflow runs on every push or pull request that touches `ios/`, and can be started manually.

1. Push this repository to GitHub (a private repository is fine).
2. Open **Actions → iOS build & tests → Run workflow** (or push a change).
3. Wait for the job; it takes roughly 5–10 minutes on a hosted runner.
4. Download the `ios-build-and-test` artifact. It contains:
   * `build.log` — full `xcodebuild` output;
   * `test.log` — test output;
   * `TestResults.xcresult` — open with Xcode's result browser. The four rendered screens are
     attached to `SnapshotTests` as PNG attachments.

No signing certificate, provisioning profile, Apple developer account or Mac is needed: the job
builds for the simulator with `CODE_SIGNING_ALLOWED=NO`. Device signing and installation remain
out of scope for this project.

### Cost

GitHub Actions is free for public repositories. Private repositories consume the account's
included macOS minutes (macOS runners are billed at a multiplier); a 30-minute timeout caps a run.

## What CI can and cannot see

* **Can** compile the app against the iOS SDK, run the test target, render the four screens with
  `ImageRenderer`, and surface real Xcode errors and warnings.
* **Cannot** reach `192.168.1.83` — a GitHub runner is outside the LAN. `SnapshotTests` therefore
  runs in **layout mode** with DEBUG fixtures; screenshot tiles show "Unavailable" and no image is
  fabricated. The live-data screenshots stored on the server are produced on a Mac on the LAN.
* **Does not** install, sign or distribute the app.

## Live screenshots on a Mac

Set the variables in the Xcode scheme (**Product → Scheme → Edit Scheme → Test → Arguments →
Environment Variables**) or pass them to `xcodebuild` with the simulator's `SIMCTL_CHILD_`
passthrough:

```bash
cd ios
mkdir -p ~/beacon/artifacts/snapshots
SIMCTL_CHILD_BEACON_SNAPSHOT_DIR="$HOME/beacon/artifacts/snapshots" \
SIMCTL_CHILD_BEACON_SNAPSHOT_BASE_URL="https://192.168.1.83:8091" \
SIMCTL_CHILD_BEACON_SNAPSHOT_TOKEN="$(cat ~/beacon/data/secrets/ios.token)" \
xcodebuild test -project Beacon.xcodeproj -scheme Beacon \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  -only-testing:BeaconTests/SnapshotTests
```

Without those variables the same test renders fixtures. `scripts/publish_snapshots.py` attaches
the resulting PNGs to a milestone.

## Status

The workflow file is committed and reviewed, but has **not been executed** — this repository has
no GitHub remote configured on this host. The first run is the remaining confirmation step. The
Linux-side typecheck *has* been executed and currently passes; it also found a genuine
compile-blocking bug (a `Section` with more than ten direct children) that was fixed.
