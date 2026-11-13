# Beacon — native iOS dashboard for this server

Beacon is a genuinely native SwiftUI iPhone app plus a small, hardened FastAPI service that
runs on `ericserver`. It shows what the active AI agent is doing, lets you send it queued
instructions (and interrupt it safely), tracks development milestones with short-lived
screenshots, and monitors the host, Pi-hole and the Minecraft server.

```
iPhone (SwiftUI, no web views)
        │  HTTPS + bearer token + certificate pinning
        ▼
beacon-api  (FastAPI, 192.168.1.83:8091, systemd, SQLite WAL)
        ├── agent status / message queue / interrupt  ──► Cherry Studio DSH runtime + SQLite (read-only)
        ├── milestones + screenshots + 7-day retention ──► data/screenshots
        ├── system metrics                              ──► /proc, sensors, nvidia-smi, root-written Docker snapshot
        ├── Pi-hole                                     ──► http://192.168.1.83:8080/api (v6)
        └── Minecraft                                   ──► server-list ping :25565, logs, /proc, (rcon/systemd if enabled)
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

Documentation: `docs/ARCHITECTURE.md`, `docs/SETUP.md`, `docs/OPERATIONS.md`, `docs/SECURITY_REVIEW.md`, `docs/CI.md`, `DASHBOARD_IMPLEMENTATION.md`.

## Building the iPhone app

Two routes:

- **Borrowed Mac:** open `ios/Beacon.xcodeproj` and Run (see `docs/INSTALL_IPHONE.md`).
- **Linux-only:** GitHub Actions builds an unsigned IPA (`.github/workflows/ios-build.yml`), and
  `scripts/install_ipa_linux.sh` signs and installs it with a free Apple ID
  (see `docs/LINUX_IPA_INSTALL.md`).

`docs/CI.md` covers the workflow and its artifacts. Nothing in this repository pushes, signs or
distributes the app automatically; the final signing/install is an explicit user action.

## Status vocabulary

Implemented / Partial / Planned / Unavailable are used consistently in the docs; every claim
in `DASHBOARD_IMPLEMENTATION.md` refers to code that exists and tests that were run.

## Verified state

| Check | Result |
|---|---|
| `pytest backend/tests` | 149 passed |
| `scripts/smoke_test.py` (live Pi-hole / Minecraft / Docker / agent) | 58 checks passed |
| `cd ios && swift test` (Linux Swift 6, live-captured fixtures) | 13 passed |
| `swiftc -parse` on iOS sources | 22 files parsed |
| `scripts/typecheck_ios_views.sh` (real Swift 6 compiler, mock SwiftUI/UIKit/Combine/XCTest) | 19 app files + 2 test files typecheck, 0 errors |
| `.github/workflows/ios-build.yml` (Xcode 26.2 unsigned IPA + simulator tests) | **succeeded**; unsigned arm64 IPA produced (706 KB), both jobs green |
| `scripts/install_ipa_linux.sh` + `docs/LINUX_IPA_INSTALL.md` | prepared; not executed (no iPhone attached to this host) |
| `scripts/validate_ios_project.py` | 22 checks passed |
| `scripts/check_openapi_drift.py` | contract up to date |
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
workflow builds an unsigned arm64 IPA with Xcode 26.2 and runs simulator tests; the Linux install
script signs and installs that IPA with a free Apple ID. The first CI run found two blockers
(duplicated resource paths and an ambiguous simulator destination); after fixing them, the rerun
**succeeded** and produced `Beacon-unsigned.ipa` (arm64, unsigned, bundled CA present). No
installation, signing or distribution to a phone has been performed yet.
