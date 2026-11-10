# Changelog

All meaningful implementation changes, bug fixes, architectural changes and decisions.
Newest first. Dates are UTC.

## [0.1.2] — 2026-11-10

Operational validation on the live deployment plus a small hardening increment.

### Added
* `docs/OPERATIONS.md`: runbook for service lifecycle, health checks, backup/restore, token and TLS
  rotation, retention, agent operations, Minecraft/Pi-hole procedures, incident checklist,
  hardening posture and upgrades.

### Verified on the live host
* **Production backup**: `VACUUM INTO` copy with `PRAGMA integrity_check = ok`; 4 milestones,
  16 screenshot rows, 12 live image files, 3 tokens, TLS material and secrets included (1.3 MB).
* **Restore drill**: the archive was restored into a temporary data directory and served by a
  second TLS instance on `127.0.0.1:8093` using the restored CA and token — health `ok`, the same
  four milestones, and a screenshot served byte-for-byte (22 989 bytes). The temporary instance
  was then stopped; the live service was untouched.
* **Crash recovery**: `SIGKILL` of the main process → systemd restarted it and the API answered in
  **3.8 s** with all data intact.
* **Hardening score**: `systemd-analyze security` improved from 6.9 to **6.5 MEDIUM** by adding
  `SystemCallArchitectures=native` and `ProtectProc=invisible`.

### Tried and reverted
* `IPAddressDeny=any` + `IPAddressAllow=127.0.0.0/8 192.168.1.0/24` on the service: with the BPF
  egress allow-list active the service could no longer reach Pi-hole on the same host, so the
  control was removed. The unit file and the runbook record why; exposure remains limited by
  binding to the LAN address only.

### Operational note
* The Minecraft server was stopped externally around 2026-11-10 13:29 (clean world save in
  `latest.log`); Beacon's audit log contains no Minecraft control actions. The dashboard correctly
  reports it as stopped.

## [0.1.1] — 2026-11-07

Hardening pass: the control paths that could not be exercised against the live services were
covered with offline protocol tests, plus contract, security and backup guardrails.

### Added
* `tests/test_minecraft_protocols.py` (10 tests): server-list ping parsing against a fake server,
  the RCON client against a fake RCON server (success, rejected password, missing password,
  command reply), the supervised pty console (start -> `stop` -> exit -> console log), the graceful
  SIGINT fallback, the refusal when no safe channel exists (the process must keep running) and the
  player-online `force` gate.
* `tests/test_pihole_parsing.py` (6 tests): recorded Pi-hole v6 payload shapes through
  `httpx.MockTransport` — statistics, blocking, top domains/clients, upstream average conversion,
  one-shot re-authentication after 401, missing password, partial statistics failure, unreachable
  API.
* `tests/test_integration_edges.py` (11 tests): Docker `ps`/`stats` parsers and cache, helper
  failures, agent-runtime edge cases (missing/corrupt Cherry Studio DB, agent-id filtering,
  transcript mtime, unknown runtime), and a backup **restore drill** that serves the API from the
  restored database with the restored token and image bytes.
* `tests/test_contract_and_security.py` (8 tests): OpenAPI snapshot equality, no shell-execution
  primitives, argument-list subprocess calls, capture allow-list shape, Docker helper read-only
  checks, non-root systemd units, best-effort committed-secret scan.
* `scripts/check_openapi_drift.py` (check/`--write`) and `scripts/check_view_initialisers.py`
  (heuristic SwiftUI memberwise call-site check, wired into `scripts/validate_ios.sh`).

### Changed
* `PiholeClient` accepts an optional HTTP transport (tests replay recorded payloads; production
  behaviour unchanged).
* `minecraft.Supervisor` gained `reset()` for deterministic test teardown.

### Fixed
* Hardened SwiftUI view memberwise call sites (missing optional defaults for `StatusPill`,
  `MetaText`, `SectionHeader`, `MetricTile`, `KeyValueRow`, `ErrorBanner`, `EmptyState`) and
  replaced `.secondary.opacity(...)` with `Color.secondary.opacity(...)`, the only form that
  type-checks; found by the new heuristic call-site checker and manual review.
* Fixtures moved out of `#if DEBUG` so `#Preview` blocks cannot break a Release build.
* The smoke test and Swift fixture test counted sentences by naive dot-splitting, so a status
  mentioning `docs/SETUP.md` was reported as four sentences; both now use a terminator regex
  (and a pytest regression test covers abbreviations), matching the backend's own rule.
* Operator-deleted screenshots were counted as "expired by retention" in milestone and retention
  summaries, and reads said "passed its 7-day window" for a manual delete. Both now distinguish
  the two cases (`{"error":"deleted"}` for manual deletes, retention only counts rows that reached
  `expires_at`).
* Screenshot file names lost their context because `Path(name).name` was applied first
  (`GET /api/v1/retention/status` became `status.png`); path separators are now flattened to
  dashes and runs collapsed, verified live (`GET-api-v1-retention-status.png`).

### Verified
* 121 pytest tests (three consecutive clean runs), 58 live smoke checks, 13 Swift tests,
  22 Swift files parsed, 18 Xcode-project checks, 109 view call sites checked, OpenAPI drift
  check clean.

## [0.1.0] — 2026-11-07

First complete implementation: backend, agent integration, milestone/screenshot pipeline,
monitoring integrations, native iOS app source, tests and documentation.

### Added — backend

* `beacon-api` FastAPI service (`192.168.1.83:8091`, HTTPS, systemd `beacon-api.service`) with
  SQLite WAL storage, schema versioning, security headers and JSON error bodies.
* Scoped bearer tokens (`read`/`action`/`admin`/`agent`), SHA-256 at rest, one-time plaintext files
  (0600), revocation, per-route authorisation and a rate limiter.
* Private ECDSA CA + leaf certificate (`backend/beacon/tls.py`), SAN for the LAN IP/hostname,
  397-day leaf (Apple limit), SPKI pin tooling, CA copied into the iOS bundle.
* Agent evidence collector (`services/agent_runtime.py`): read-only Cherry Studio SQLite,
  transcript mtime, `/proc` mapping of the DSH runtime via the composition file name.
* Agent state machine (`services/agent_status.py`) with nine states, evidence list and data age.
* Deterministic Status action (`services/status_summary.py`), pure function, 1–3 sentences,
  no network/LLM.
* Durable message queue (`services/message_queue.py`): monotonic `seq`, idempotency keys,
  `pending→delivered→acknowledged→processed`, cancel-before-delivery, JSONL inbox mirror.
* Checkpoint endpoint returning queued messages + pending interrupts; separate agent-only scope.
* Interrupt handler (`services/interrupts.py`): SIGINT to the resolved runtime pid with uid/cmdline
  verification, 5 s exit observation (zombies treated as exited), evidence and audit; cooperative
  `checkpoint` mode.
* Milestones (`services/milestones.py`), screenshot storage/serving (`services/screenshots.py`),
  capture pipeline with four real sources (`services/capture.py`), 7-day retention with read
  guard, daily timer, hourly sweep and path-confined deletion (`services/retention.py`).
* Monitoring: `/proc`-based CPU/RAM/net/uptime sampler, `sensors` temperature, `nvidia-smi` GPU,
  `statvfs` disks, read-only Docker helper (`deploy/docker-read` + sudoers), Pi-hole v6 client with
  blocking control, Minecraft ping/process/log/backup monitoring with guarded controls
  (pty supervisor → RCON → verified SIGINT, never force-kill).
* Activity feed with edge detection and dedupe; audit table for all privileged actions.
* `beacon` CLI: init/doctor, tokens, TLS, service control, summary, agent status/status-set/
  checkpoint/ack/processed/interrupt/interrupt-ack, queue, milestones, screenshots, retention,
  api-get, backup.
* Deployment: `deploy/beacon.env`, hardened systemd units, retention timer, sudoers drop-in,
  idempotent `scripts/install.sh`.

### Added — iOS

* Hand-generated `ios/Beacon.xcodeproj` (app + hosted unit-test target, shared scheme) produced by
  `scripts/gen_xcodeproj.py`, structurally validated with the `pbxproj` library.
* SwiftUI app (iOS 17, zero packages): design system, Home dashboard, Agent panel, Progress
  milestone screens, Server screen, Settings, onboarding; 22 Swift files.
* Networking: `APIClient` (async/await, typed errors), private-CA anchored trust + optional SPKI
  pinning with a hand-written DER/SPKI parser, Keychain token storage, `AppModel` with
  scene-aware 15 s polling.
* App-bound `ca.crt`, ATS configuration, local-network usage description.
* `BeaconTests/SnapshotTests` renders the four screens with `ImageRenderer` (live or fixture mode).

### Added — tests and tooling

* 82 pytest tests (auth, queue, status, interrupt against a controlled process, milestones,
  retention safety, TLS handshake against a real Uvicorn TLS server, persistence).
* 57-check live smoke test (`scripts/smoke_test.py`) against the real services.
* 13 Swift decoding/formatting tests compiled and run on Linux with SwiftPM.
* `scripts/validate_ios.sh` (parse all Swift, run Swift tests, validate the Xcode project) and
  `scripts/publish_snapshots.py` (attach macOS-rendered screenshots to a milestone).

### Verified live

* `beacon doctor`: all checks (API, TLS, systemd, retention timer, Cherry Studio DB, runtime pid,
  docker helper, Pi-hole, Minecraft) pass.
* Pi-hole: 36 170 queries / blocking enabled / container healthy / upstreams reported.
* Minecraft: NeoForge 1.21.1 running, players reported through server-list ping, process metrics.
* Agent: resolved runtime pid 415932; state `working` derived from a pending assistant turn.
* Screenshot retention drill: aged screenshot deleted by `beacon-retention.service`, milestone text
  preserved, read returns 410, audit row written.

### Fixed

* `uvicorn --http httptools` required an uninstalled extra → removed (default h11).
* Zombie runtime processes were treated as alive → `/proc/<pid>/stat` state is now checked.
* Foundation's `.convertFromSnakeCase` maps `processed_last_24h` to `processedLast24H`; the Swift
  model now spells the key explicitly (found by the Linux Swift tests).
* Status summary could exceed three sentences by appending a freshness note → now flattened and
  capped; freshness lives in `data_age_seconds`/`is_stale`.
* UI tokens could call the checkpoint endpoint → runtime endpoints now require the `agent` scope.
* The installer ran `beacon init` as root, leaving the data directory unreadable for the service →
  CLI now runs as the operator and ownership is normalised.
* CLI could crash with a traceback on a malformed capture id → ids are validated and encoding
  errors reported cleanly.

### Decisions

* **Agent integration**: read-only Cherry Studio evidence + a pushed status snapshot, with
  checkpoint-pulled message delivery. Writing into the live Cherry Studio database was rejected
  (two writers on a WAL database owned by the UI).
* **Interrupt**: SIGINT to the resolved DSH runtime (`bin.mjs` disposes its fiber tree and exits,
  journal preserved) rather than a chat message; cooperative checkpoint mode as the fallback.
* **TLS/pinning**: private CA + SPKI pin instead of a public certificate or a self-signed
  "accept everything" client.
* **No iOS build on this host**: Xcode cannot run on this Debian machine, so the project ships as
  complete source with Foundation-only logic compiled and tested on Linux, all sources parsed,
  and the Xcode project structurally validated; a macOS build remains a documented requirement.
* **Minecraft controls**: preference for a supervised pty, then RCON, then the verified JVM
  shutdown hook; the running instance was intentionally not restarted during development.
* **Milestone screenshots**: real artifacts only. For this phase that means live command/API
  output and a genuine X11 capture of the agent UI, because the iOS UI cannot be rendered without
  Xcode. The snapshot test target produces true UI screenshots once run on a Mac.
