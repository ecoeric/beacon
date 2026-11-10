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
        ├── system metrics                              ──► /proc, sensors, nvidia-smi, read-only docker wrapper
        ├── Pi-hole                                     ──► http://192.168.1.83:8080/api (v6)
        └── Minecraft                                   ──► server-list ping :25565, logs, /proc, (rcon/systemd if enabled)
```

## Repository layout

| Path | Contents |
|---|---|
| `backend/beacon/` | FastAPI application (API, services, CLI) |
| `backend/tests/` | pytest suite (unit + live integration) |
| `ios/` | Xcode project, SwiftUI app sources, validation harness |
| `deploy/` | systemd units, env file, sudoers drop-in, docker read wrapper |
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

Documentation: `docs/ARCHITECTURE.md`, `docs/SETUP.md`, `docs/OPERATIONS.md`, `DASHBOARD_IMPLEMENTATION.md`.

## Building the iPhone app

Requires macOS with Xcode 16+ (`xcodebuild`). See `docs/SETUP.md` § iOS. Nothing in this
repository installs, signs, or distributes the app — deployment to a device is a separate step.

## Status vocabulary

Implemented / Partial / Planned / Unavailable are used consistently in the docs; every claim
in `DASHBOARD_IMPLEMENTATION.md` refers to code that exists and tests that were run.

## Verified state

| Check | Result |
|---|---|
| `pytest backend/tests` | 121 passed |
| `scripts/smoke_test.py` (live Pi-hole / Minecraft / Docker / agent) | 58 checks passed |
| `cd ios && swift test` (Linux Swift 6, live-captured fixtures) | 13 passed |
| `swiftc -parse` on iOS sources | 22 files parsed |
| `scripts/validate_ios_project.py` | 18 checks passed |
| `scripts/check_openapi_drift.py` | contract up to date |
| backup restore drill | restored DB, token and image served by the API |
| crash recovery (`SIGKILL`) | systemd restart, API back in 3.8 s, data intact |
| `beacon doctor` | all checks passed |
| Retention drill through `beacon-retention.service` | aged screenshot deleted, 410 confirmed, milestone text kept |

Milestone records with four real screenshots each are stored on the server and shown in the app;
screenshots expire automatically after seven days while milestone summaries remain.

## Status of the iPhone build

The native project (Xcode project, SwiftUI app, pinned-TLS client, tests) is complete and
version-controlled here. Building it requires Xcode on macOS; see `docs/SETUP.md` §5. No
installation, signing or distribution to a phone was performed — that is a separate project.
