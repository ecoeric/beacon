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

Documentation: `docs/ARCHITECTURE.md`, `docs/SETUP.md`, `DASHBOARD_IMPLEMENTATION.md`.

## Building the iPhone app

Requires macOS with Xcode 16+ (`xcodebuild`). See `docs/SETUP.md` § iOS. Nothing in this
repository installs, signs, or distributes the app — deployment to a device is a separate step.

## Status vocabulary

Implemented / Partial / Planned / Unavailable are used consistently in the docs; every claim
in `DASHBOARD_IMPLEMENTATION.md` refers to code that exists and tests that were run.
