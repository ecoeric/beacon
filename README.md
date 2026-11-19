# Beacon — native iOS dashboard for this server

Beacon is a genuinely native SwiftUI iPhone app plus a small, hardened FastAPI service that
runs on `ericserver`. It shows what the active AI agent is doing, lets you read and send chat
messages (and interrupt it safely), tracks development milestones with short-lived
screenshots, and monitors the host, Pi-hole, Minecraft and the KSP Luna Multiplayer server.

```
iPhone (SwiftUI, no web views)
        │  HTTPS + bearer token + certificate pinning
        ▼
beacon-api  (FastAPI, 192.168.1.83:8091, systemd, SQLite WAL)
        ├── agent status / chat / interrupt          ──► Cherry Studio DSH runtime + SQLite (read-mostly)
        ├── milestones + screenshots + 7-day retention ──► data/screenshots
        ├── system metrics                              ──► /proc, sensors, nvidia-smi, root-written Docker snapshot
        ├── Pi-hole                                     ──► http://192.168.1.83:8080/api (v6)
        ├── Minecraft                                   ──► server-list ping :25565, logs, /proc, (rcon/systemd if enabled)
        └── KSP / Luna Multiplayer                      ──► read-only status JSON http://127.0.0.1:8900
```

## Repository layout

| Path | Contents |
|---|---|
| `backend/beacon/` | FastAPI application (API, services, CLI) |
| `backend/tests/` | pytest suite (unit + live integration) |
| `ios/` | Xcode project, SwiftUI app sources, validation harness |
| `deploy/` | systemd units, env file, root Docker snapshot timer |
| `docs/` | architecture, setup, API reference, phase discovery notes |
| `DASHBOARD_IMPLEMENTATION.md` | feature registry: every feature, files, endpoints, tests, limits |
| `CHANGELOG.md` | implementation history and decisions |

## Quick start (server)

```bash
cd ~/beacon
scripts/install.sh          # venv, TLS cert, tokens, systemd units, CLI link
systemctl status beacon-api
beacon doctor
```

Documentation: `docs/ARCHITECTURE.md`, `docs/SETUP.md`, `docs/OPERATIONS.md`,
`docs/SECURITY_REVIEW.md`, `docs/CI.md`, `docs/OTA.md`, `DASHBOARD_IMPLEMENTATION.md`.

## Building the iPhone app

Three routes, in order of convenience:

- **Linux-only USB (current routine on this phone):** GitHub Actions builds an unsigned IPA
  (`.github/workflows/ios-build.yml`), and `scripts/install_ipa_linux.sh` signs and installs it
  with a free Apple ID (see `docs/LINUX_IPA_INSTALL.md`).
- **SideStore OTA (works at the feed level; blocked on this phone):** GitHub Actions publishes the
  unsigned IPA and a stable SideStore source feed. Once both apps have unsuffixed bundle IDs,
  add the source and tap **Update** in SideStore. The current AltServer-installed copies carry a
  team-ID suffix that SideStore cannot match; see `docs/OTA.md`.
- **Borrowed Mac:** open `ios/Beacon.xcodeproj` and Run (see `docs/INSTALL_IPHONE.md`).

`docs/CI.md` covers the workflow and its artifacts. CI publishes the unsigned IPA and SideStore
feed automatically; signing and installation on the phone remain explicit user actions.

## Status vocabulary

Implemented / Partial / Planned / Unavailable are used consistently in the docs; every claim
in `DASHBOARD_IMPLEMENTATION.md` refers to code that exists and tests that were run.

## Verified state

| Check | Result |
|---|---|
| `pytest backend/tests` | 164 passed |
| `scripts/smoke_test.py` (live Pi-hole / Minecraft / Docker / agent) | 58 checks passed |
| `cd ios && swift test` (Linux Swift 6, live-captured fixtures) | 13 passed |
| `swiftc -parse` on iOS sources | 24 files parsed |
| `scripts/typecheck_ios_views.sh` (real Swift 6 compiler, mock SwiftUI/UIKit/Combine/XCTest) | 21 app files + 2 test files typecheck, 0 errors |
| `.github/workflows/ios-build.yml` (Xcode 26.2 unsigned IPA + simulator tests + publish) | **succeeded** through run 6 (`aa9a794`); unsigned arm64 IPA (815 KB) published as release `v1.0.6`, SideStore feed public and verified |
| `scripts/install_ipa_linux.sh` + `docs/LINUX_IPA_INSTALL.md` | executed: Beacon 1.0 installed on the iPhone over USB. AltServer appended its team ID to the installed bundle identifier; no iPhone is attached to this host right now |
| `scripts/validate_ios_project.py` | project structure + version placeholders + 1024px app icon checks pass |
| `scripts/validate_ota.sh` | 8 source-generator tests pass; icon reproducible; workflow structure valid |
| `actionlint` + `shellcheck` | workflow expressions and embedded shell pass |
| `scripts/check_openapi_drift.py` | contract up to date (39 paths) |
| backup restore drill | restored DB, token and image served by the API |
| crash recovery (`SIGKILL`) | systemd restart, API back in 3.8 s, data intact |
| privilege boundary | API runs with `NoNewPrivileges=yes`; Docker reads via a fixed root timer |
| `beacon doctor` | all checks passed |
| Retention drill through `beacon-retention.service` | aged screenshot deleted, 410 confirmed, milestone text kept |

Milestone records with four real screenshots each are stored on the server and shown in the app;
screenshots expire automatically after seven days while milestone summaries remain.

## Status of the iPhone build

The native project (Xcode project, SwiftUI app, pinned-TLS client, tests) is complete and
version-controlled here. Every app source typechecks with the real Swift compiler against mock
SwiftUI/UIKit modules; that is compiler validation, **not** an iOS build. The GitHub Actions
workflow builds an unsigned arm64 IPA with Xcode 26.2, runs simulator tests, and publishes the
versioned GitHub Release plus the SideStore feed. Run 6 built and published `v1.0.6`; the feed at
`https://github.com/ecoeric/beacon/releases/download/beacon-source/apps.json` returns a valid
source with a checksum-verified IPA.

The Linux USB script has also been exercised: Beacon 1.0 is installed on the iPhone, signed with a
free Apple ID through AltServer-Linux-NG. That path remains the working routine update method on
this phone. The SideStore feed is public and valid, but SideStore cannot update or resign the
installed apps because their bundle identifiers carry an AltServer-appended team suffix
(`dev.ericserver.beacon.CS7ALNH4T4`, `com.SideStore.SideStore.CS7ALNH4T4`) while SideStore looks
for the unsuffixed identifiers. Fixing that needs a one-time clean reinstall of both apps with
unsuffixed IDs; retrying SideStore's resign action cannot fix it.

The full Chat tab is newer than the installed 1.0 build and will arrive in the next CI build.
