# Changelog

All meaningful implementation changes, bug fixes, architectural changes and decisions.
Newest first. Dates are UTC.

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
