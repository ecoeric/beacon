# iOS build, tests and IPA CI (no Mac required)

Beacon is developed on a Linux host with **no Xcode, iOS SDK or simulator**. Three independent
layers cover the gap; they are deliberately not conflated:

| Layer | Where | What it proves |
|---|---|---|
| Swift typecheck | this host, Docker `swift:6.0` | Every app source and both Xcode test files typecheck with the real Swift compiler against mock SwiftUI/UIKit/Combine/XCTest modules. Catches type, generic, result-builder, property-wrapper and concurrency errors. **Not an iOS build.** |
| Xcode build + IPA | GitHub Actions `macos-26`, Xcode 26.2 | A real iOS-SDK device build of the generated project, packaged as an **unsigned arm64 IPA**, plus a separate simulator test job. This is the authoritative compile confirmation. |
| Sign + install | SideStore on the iPhone (preferred) or AltServer-Linux-NG over USB (fallback) | The unsigned IPA is signed with a free Apple ID. SideStore installs it without USB; see [`OTA.md`](OTA.md). The fallback is [`LINUX_IPA_INSTALL.md`](LINUX_IPA_INSTALL.md). |

`scripts/validate_ios.sh` runs the first layer plus parsing, Foundation tests, call-site checks and
project validation.

## The workflow

`.github/workflows/ios-build.yml` has two `macos-26` build/test jobs plus a gated publish job:

### `unsigned-ipa` — the artifact you install

1. Regenerates `ios/Beacon.xcodeproj` and fails if the committed project differs.
2. Selects **Xcode 26.2** explicitly (`/Applications/Xcode_26.2.app`) and verifies an iOS 26 SDK.
3. Builds **Release, `-sdk iphoneos`, arm64** with signing completely disabled.
4. Packages `Payload/Beacon.app` as `Beacon-unsigned.ipa`.
5. Verifies the executable is arm64 and the bundled `ca.crt` is present.
6. Uploads `Beacon-unsigned.ipa`, its SHA-256, `build-info.txt` and `build.log` as artifact
   **`Beacon-unsigned-ipa`** (30-day retention).

The app is **unsigned on purpose**: no Apple developer account, certificate or provisioning
profile is needed for CI. Signing happens locally with a free Apple ID before installation.

### `simulator-tests` — compile and test the views

Builds and runs `BeaconTests` on an iPhone simulator with Xcode 26.2 and uploads `test.log` plus
`TestResults.xcresult`. A test failure does not block the build artifact, but it **does** block the
`publish` job.

### `publish` — immutable release and SideStore feed

Runs on `ubuntu-latest` only for a push to the default branch, and only when both jobs above pass.
It verifies the IPA, creates a versioned GitHub Release, merges the SideStore `apps.json` into the
fixed `beacon-source` prerelease, and fetches the published feed back to verify it. See
[`OTA.md`](OTA.md) for the source URL, one-time setup and failure model.

## Running it

1. Push this repository to GitHub.
2. For SideStore, the target release repository must be public (or use a public mirror — see
   [`OTA.md`](OTA.md)); private GitHub assets cannot be fetched by SideStore.
3. Open **Actions → iOS build, tests & SideStore release → Run workflow**.
4. Wait roughly 5–10 minutes for the build and tests, then the publish job.
5. Add the source URL printed in the run summary in SideStore, install Beacon, and use
   **Updates → Update** for later builds.

You do **not** need a paid Apple Developer account to compile the app or to produce the IPA.
A free Apple ID is enough for personal installation, but the profile expires after 7 days.

### Cost

GitHub Actions is free for public repositories. Private repositories consume included macOS
minutes (macOS runners have a multiplier). The workflow timeout is 45 minutes for the IPA job and
40 minutes for tests.

## What CI can and cannot see

* **Can** compile against the real iOS SDK, package a device IPA, run the test target, render the
  four screens with `ImageRenderer`, and surface real Xcode errors.
* **Cannot** reach `192.168.1.83` — a GitHub runner is outside the LAN. Snapshot tests run in
  **layout mode** with DEBUG fixtures; screenshot tiles show "Unavailable" and no image is
  fabricated. Live screenshots must be produced on a machine on the LAN.
* **Does not** sign or install the IPA. The artifact is intentionally unsigned; SideStore signs
  it on-device, or the fallback AltServer script signs it over USB.
* **Cannot publish to a private repository.** The publish job checks visibility and fails closed
  with instructions to make the repo public or configure a public mirror.

## Live screenshots on a Mac

Set the variables in the Xcode scheme (**Product → Scheme → Edit Scheme → Test → Arguments →
Environment Variables**) or pass them with the simulator's `SIMCTL_CHILD_` passthrough:

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
the PNGs to a milestone.

## Status

The original build workflow was implemented and locally linted with `actionlint` 1.7.12; its
embedded shell also passes ShellCheck 0.11.0. The **first real CI run executed** on `macos-26` with Xcode 26.2
and found two blockers:

- duplicated Xcode resource paths (`ios/Beacon/Beacon/Resources/...`) caused
  `CpResource … ca.crt` to fail;
- the simulator destination used `iPhone 16e` with an implicit latest OS, but that model only
  exists on iOS 26.2.

Both are fixed. The rerun **succeeded**: Xcode 26.2 produced `Beacon-unsigned.ipa` (arm64,
unsigned, 706 KB) and the simulator test job is green. The Linux-side typecheck has also run and
passes; it previously found a real compile blocker (a `Section` with more than ten direct
children), which was fixed.

The OTA release job and SideStore source feed are newer than that first build. They have been
locally validated with `scripts/validate_ota.sh`, `actionlint` and the existing real IPA, but the
new publish path has **not** executed on GitHub yet; this host has no GitHub credentials. See
[`OTA.md`](OTA.md#limits-and-unverified-parts).

If a build fails, download `Beacon-unsigned-ipa` (which contains `build.log`) and fix the reported
error. No release or source-feed update occurs for a failed build.
