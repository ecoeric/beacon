# Changelog

All meaningful implementation changes, bug fixes, architectural changes and decisions.
Newest first. Dates are UTC.

## [0.1.12] — 2026-11-14

SideStore OTA release pipeline.

### Added
* `.github/workflows/ios-build.yml` now has a gated `publish` job. It runs only on the default
  branch after both the unsigned device build and simulator tests pass, creates an immutable
  `v1.0.<run_number>` GitHub Release, and updates a fixed `beacon-source` prerelease containing
  `apps.json` and `Beacon-AppIcon.png`.
* `scripts/ota_source.py`: dependency-free SideStore/AltStore source generator. It inspects the
  real IPA (bundle id, version/build, CA, executable, unsigned), merges up to 25 previous versions
  newest-first, writes modern `versions` (including `buildVersion` and IPA `sha256`) plus legacy flat
  fields, and fails closed on invalid URLs/versions.
* `scripts/test_ota_source.py` (8 tests) and `scripts/validate_ota.sh`.
* `scripts/make_app_icon.py` and a reproducible 1024×1024 `AppIcon.png` asset, used both by Xcode
  and the SideStore source.
* Automatic versioning: `CFBundleShortVersionString = 1.0.<run_number>` and
  `CFBundleVersion = <run_number>`, wired through `$(MARKETING_VERSION)` /
  `$(CURRENT_PROJECT_VERSION)` and verified after the Xcode build.
* `docs/OTA.md`: audit, architecture, public-repo and private-source/public-mirror setup,
  SideStore instructions, routine commands, failure handling, security and unverified limits.
* `scripts/install_sidestore_linux.sh`: one-time Linux/USB SideStore bootstrap using the pinned,
  checksum-verified official `0.7.0-alpha` IPA and the existing AltServer-Linux-NG cache.

### Changed
* Release builds are no longer cancelled by a newer push; PR builds still use cancellation to
  save runners.
* `docs/CI.md` and `README.md` describe the SideStore path; USB/AltServer remains a fallback.

### Security
* No Apple ID, certificate, provisioning profile or backend token is stored in GitHub. The IPA
  remains unsigned and SideStore signs it on-device.
* The optional public release mirror uses a fine-grained PAT in `BEACON_RELEASE_TOKEN`; the
  publish job refuses a private target repository.
* Bundle identifier remains `dev.ericserver.beacon`, so SideStore updates preserve app data.

### Verified locally
* 8 source-generator tests, icon reproducibility, version placeholders and workflow structure.
* `actionlint` 1.7.12 and `shellcheck` 0.11.0 pass on the workflow.
* The generator accepts the existing real `artifacts/Beacon-unsigned.ipa` (arm64, unsigned,
  bundle id, CA) and emits a valid feed.
* **Not verified:** no GitHub push/dispatch (no credentials on this host), no macOS/Xcode run, no
  published release/feed, and no SideStore install/update on an iPhone.

## [0.1.11] — 2026-11-14

Writeable Chats, real queue delivery, and bug-fix pass from phone use.

### Added
* **Writeable Chats.** `POST /agent/sessions/{id}/messages` writes one accepted user-delivery row
  into Cherry Studio's own durable delivery queue; Cherry runs the turn normally and the reply
  appears in the transcript. `BEACON_CHAT_WRITE=1` enables it; `=0` keeps Cherry strictly
  read-only and falls back to the Beacon queue. `BEACON_CHAT_WRITE` is off by default in code and
  on in `deploy/beacon.env`. The write is transactionally one row, validates the session/agent,
  uses UUIDv7 ids (or a deterministic UUIDv5 for retries), and never writes model output.
* **Legacy queue messages now actually send.** New `/agent/messages` and `/agent/continue` rows
  are forwarded to Cherry immediately; a 20-second API sweep forwards pre-existing pending rows.
  Forwarding is idempotent (`client_message_id=queue:<id>`) and leaves the row pending if Cherry is
  closed, busy or changed its schema.
* `chat_write` capability flag in `/capabilities`; Chats composer now uses the writeable endpoint
  and refreshes the transcript after sending.
* `BEACON_CHAT_WRITE`, `services/chat_write.py`, `services/chat_delivery.py`, and
  `tests/test_chat_write.py` (12 tests).
* Queue schema v2 adds `agent_message.forward` (default 1) so smoke tests and checkpoint-only
  callers can opt out of automatic chat forwarding; existing databases migrate on startup.

### Fixed
* Minecraft CPU tile now shows **percent of total host CPU** (`cpu_percent_of_total`) with the
  one-core process percentage as detail, instead of comparing a 100%+ process figure with a 7%
  host figure. Live example: 104% of one core = 8.7% of the host.
* Swift decoding: `cpuPercentOfTotal` and `luna` were declared with `= nil`, so `Decodable`
  silently ignored both backend fields. Removed the defaults and added the missing Minecraft
  `CodingKeys` entry.
* Chat transcript now filters raw `{"parts":...}` payloads and reasoning/tool-only parts at both
  the backend and UI layers.
* Chats list refreshes every 10 s and the transcript every 5 s; sending refreshes after the write.
* Chats layout no longer uses `safeAreaInset`/`overlay(alignment:)` (both were unsupported by the
  mock SwiftUI harness), fixing the last typecheck failure; composer sits below the scroll view.
* Luna / KSP card is live again: server name, Career mode, players, vessels, UDP 8800, uptime,
  memory, password and mod-control flags.

### Verified
* 164 backend tests, 20 app + 2 test Swift files typecheck, 21 app sources in the Xcode project,
  39 OpenAPI paths, `beacon doctor` green.
* Live endpoint returned `mode=cherry` for a real message row; Luna summary reports
  `state=running`, `game_mode=Career`, `udp_listening=true`.

### Not implemented
* **Creating a brand-new chat** from the phone. Sending into existing chats is now writeable;
  creating the session still belongs to Cherry Studio.
* True real-time push: the app polls (10 s chats / 5 s transcript / 15 s dashboard).

## [0.1.10] — 2026-11-13

Read-only KSP / Luna Multiplayer monitoring.

### Added
* `LunaStatus` in the dashboard summary, populated from the LMP status JSON on
  `http://127.0.0.1:8900` plus `/proc` process/UDP checks.
* Server tab card: running/stopped, server name, online/max players, current player names,
  vessel count, game mode, password/mod-control flags, warp mode, UDP 8800 listening, PID,
  uptime and process memory.
* Activity notifications for Luna online/offline edges.
* `BEACON_LUNA_STATUS_URL` and `BEACON_LUNA_PROCESS_MARKER` configuration; read-only by design.

### Not implemented
* Start/stop/restart of `luna-server.service`: it is a root-owned system service, and Beacon
  deliberately has no sudo path. Manage the service from the server.
* `new chat` creation in the iOS app; Cherry Studio's database remains read-only.

### Verified
* Live summary returned `state=running`, `players 0/10`, `udp_listening=true` for
  “Eric's Kerbin Station”.
* 152 backend tests, 39 OpenAPI paths.

## [0.1.9] — 2026-11-13

Read-only agent chat browser.

### Added
* `GET /api/v1/agent/sessions` and `GET /api/v1/agent/sessions/{id}/messages` expose the
  configured Cherry Studio agent's sessions and visible transcript text. The database is opened
  read-only; reasoning parts and empty/tool-only messages are not shown.
* Agent tab toolbar → **Chats**: session list plus transcript viewer. The current session is
  marked, and the footer states that new chats must be created in Cherry Studio.
* OpenAPI snapshot is now 39 paths.
* The Agent tab's status snapshot was refreshed after the successful build; the old macOS blocker
  was cleared.

### Not implemented
* **Creating a new chat.** Beacon has no write path into Cherry Studio and no agent-session API to
  create one. New chats remain a Cherry Studio action.

## [0.1.8] — 2026-11-13

iPhone app is installed; fixes from the first real use.

### Fixed
* Minecraft launches through the existing `run.sh` with the configurable argument list
  `BEACON_MINECRAFT_LAUNCH_ARGS=nogui`; the supervised process is now
  `run.sh nogui` (verified live: server reached `Done (8.763s)` and `running/online=True`).
* Milestone screenshots use aspect-fit inside a fixed, clipped tile instead of aspect-fill. Whole
  images are visible with letterboxing instead of being cropped; the grid remains bounded.
* AltServer signing data (including its `.p12`) is kept outside the repository in
  `~/.local/share/beacon/tools/AltServerData/` and is git-ignored.

### Not changed
* The Agent screen is deliberately not a chat client: it shows status, queues instructions and
  offers interrupt. There is no transcript browser or “new chat” control in Beacon; those belong
  to Cherry Studio, not this dashboard.

## [0.1.7] — 2026-11-12

First real Xcode 26.2 CI run: fixed the two build blockers it exposed. The IPA itself has not been
produced yet; the workflow must be rerun after this commit.

### Fixed
* **Duplicated resource paths (compile blocker):** the generated Xcode project gave both the group
  and its file reference the full path (`Beacon/Resources/...` + `Beacon/Resources/...`), so Xcode
  resolved `ca.crt` and `Assets.xcassets` under `ios/Beacon/Beacon/Resources/...` and failed with
  `lstat(...): No such file or directory`. File references now use basenames and group paths are
  single components, matching Xcode's group-relative resolution model.
* **Simulator destination (test blocker):** the workflow selected `iPhone 16e` by name, and
  `xcodebuild` interpreted the missing OS as “latest” (iOS 26.5), where that model is unavailable.
  Tests now select an exact simulator UDID from `simctl` and pass `-destination id=...`; iPhone 16e
  on iOS 26.2 is preferred.

### Added
* `scripts/validate_ios_project.py` now resolves each `PBXFileReference` through its `PBXGroup`
  parents and fails if the resulting file is missing, or if a file/group path contains a slash.
  This would have caught the duplication before CI. Project validation is now **22 checks**.

### Verified
* Project validation passes; 22 checks. Workflow YAML and shell blocks still pass local linting.
* The rerun **succeeded** on GitHub Actions with Xcode 26.2. The unsigned arm64 IPA is 706 KB,
  contains `ca.crt`, and reports `minimum_os=17.0` and `signed=false`; the simulator test job is
  green. No signing or phone installation has been performed yet.

## [0.1.6] — 2026-11-12

iPhone distribution pipeline: a real Xcode 26.2 CI build that produces an unsigned IPA, plus a
Linux signing/install path. No IPA was produced on this host and no phone install was performed.

### Added
* Reworked `.github/workflows/ios-build.yml` for `macos-26` with Xcode **26.2** selected explicitly.
  Two independent jobs:
  * **Unsigned IPA** — Release device build (`-sdk iphoneos`, arm64), signing disabled, packaged as
    `Payload/Beacon.app` and uploaded as `Beacon-unsigned-ipa` with checksum, `build-info.txt` and
    `build.log`. The job verifies the arm64 executable and the bundled `ca.crt`.
  * **Simulator tests** — the existing test target on an iPhone simulator, with `test.log` and
    `TestResults.xcresult` artifacts. Test failures do not block the IPA job.
* `scripts/install_ipa_linux.sh` — downloads the pinned **AltServer-Linux-NG** release
  (`ng-2026-11-05`, SHA-256 verified), detects the iPhone over usbmuxd, prompts for a free Apple
  ID, signs and installs the IPA. No password is written to disk; it is passed to AltServer as an
  argument (briefly visible to `ps`).
* `docs/LINUX_IPA_INSTALL.md` — Linux-only signing/installation guide, including the free-Apple-ID
  7-day limit, 2FA/SMS handling, iOS 26.2 compatibility notes, USB vs netmuxd and troubleshooting.

### Notes
* The IPA is intentionally **unsigned**: CI needs no Apple account, certificate or provisioning
  profile. Signing happens locally with a free Apple ID.
* AltServer-Linux v0.0.5 is not used: it fails on modern iOS. The maintained NG fork fixes the
  iOS 26.4+/27 signature rejection and the 2026 Apple sign-in changes.
* The workflow and install script are prepared but **not executed**: this repository has no
  GitHub remote, and no iPhone is attached to this Linux host. The first CI run is the remaining
  compile confirmation.

## [0.1.5] — 2026-11-12

Real compiler validation for the SwiftUI layer, plus a prepared macOS CI build. No iOS build was
run on this host (it has no Xcode or iOS SDK).

### Added
* `ios/Shim/` — mock SwiftUI, UIKit and Combine modules that reproduce the API surface Beacon uses
  (result builders, property wrappers, modifiers, styles, shapes). They exist **only** for
  typechecking and are excluded from the Xcode project and the app target.
* `scripts/typecheck_ios_views.sh` — builds the mock modules in Docker `swift:6.0` and typechecks
  every app source and both Xcode test files with the real Swift compiler. It now includes
  `BeaconApp.swift` via mock `App`/`Scene`/`WindowGroup` declarations (19 app files + 2 test files,
  0 errors) and is step 3 of `scripts/validate_ios.sh`.
* `.github/workflows/ios-build.yml` and `docs/CI.md` — a real Xcode build and simulator test run,
  with logs and the `.xcresult` uploaded as artifacts. The workflow is committed but has not been
  executed: no GitHub remote is configured on this host.
* Snapshot tests now attach each rendered PNG to the `.xcresult`, so a CI runner can retrieve the
  four screens without access to the simulator's filesystem.
* `docs/INSTALL_IPHONE.md` — beginner guide for the first physical install with a free Apple ID,
  including Developer Mode, bundle identifiers, signing limits and troubleshooting.

### Fixed
* **Compile-blocking SwiftUI bug found by the typecheck:** the Settings "Backend" `Section` had 13
  direct children, above SwiftUI's ten-child `ViewBuilder` limit. It is split into "Agent" and
  "Monitoring" sections. This would have failed the first real Xcode build.
* `AppModel.swift` now conditionally imports `FoundationNetworking` so `URLSession` resolves under
  the Linux typecheck; iOS is unaffected (`canImport` is false there).
* `scripts/validate_ios_project.py` ignores `ios/Shim/` when checking for unreferenced Swift files.

### Verified
* `scripts/typecheck_ios_views.sh`: 18 app files + 2 test files + 6 stub files, exit 0.
* The real iOS-SDK build remains the one unexecuted verification step; it is now reproducible in CI
  without a Mac.

## [0.1.4] — 2026-11-12

Verification pass for the security work and installer robustness.

### Added
* `docs/SECURITY_REVIEW.md`: findings/resolution matrix, the privilege-split rationale, verification
  commands and the accepted residual risks.
* Static guardrail tests that request-handling code contains no `sudo` capability and that the API
  unit has no privileged dependency (149 pytest tests total).

### Fixed
* `scripts/install.sh` now waits for the TLS health endpoint (not merely `systemctl is-active`)
  before running `beacon doctor`; a re-run is fully idempotent and exits 0.
* The installer removes the obsolete Docker helper/sudoers rule on upgrade.

### Verified
* `sudo` inside a `NoNewPrivileges=yes` unit is refused (control: the interactive account can still
  use it), the Docker snapshot refreshes every ~15 s, the production backup restores and serves
  5 milestones / 16 screenshots, 149 pytest tests pass, `doctor` is green and the OpenAPI contract
  is current.

## [0.1.3] — 2026-11-12

Independent security review of the backend, with fixes for the two structural findings and the
smaller issues.

### Security
* **Privilege boundary (HIGH):** the API no longer calls `sudo` and no longer uses a
  sudo-allow-listed Docker wrapper. Docker metrics are produced by a root-owned oneshot timer
  (`beacon-docker.timer`, 15 s) that runs exactly `docker ps` and `docker stats` and writes
  `/run/beacon/docker.json` (0644, atomic); the API only reads that file. `NoNewPrivileges=yes` is
  enabled on the API unit, so a compromised API process cannot exec setuid `sudo` even though the
  interactive `eric` account has a NOPASSWD rule. Unrelated credential directories (`~/.ssh`,
  `~/.gnupg`, `~/.mozilla`, Cherry Studio `Credentials`) are masked with `InaccessiblePaths`.
  `systemd-analyze security` improves to **6.3 MEDIUM**. Residual risk documented: the API still
  runs as `eric` and can read the Cherry Studio database (needed for agent evidence) and other
  non-masked files owned by that account.
* **Interrupt targeting (MEDIUM):** the signalling target comes only from the read-only Cherry
  Studio session list (or `BEACON_SESSION_ID`), never from the agent-writable status snapshot; an
  optional explicit `session_id` must exist in that list, and the runtime is re-resolved immediately
  before the signal (`409 target_changed`). Signals use a **pidfd** where available.
* **Message delivery (MEDIUM):** deliveries are leased and re-delivered after 120 s without an
  acknowledgement (max 5 attempts), with a new agent `nack` endpoint, so an interrupted runtime can
  no longer silently swallow an instruction. Idempotency keys are namespaced per client and use
  `ON CONFLICT ... DO NOTHING` to survive concurrent retries.
* **Abuse limits (MEDIUM):** chunked-safe request-body ceiling in an ASGI middleware (the previous
  `Content-Length` check was bypassable), per-file and total screenshot quotas, throttles on
  milestone/upload writes, and rate-limit keys based on the token id.
* **Information leaks (LOW):** query-string bearer tokens removed (they were written to access
  logs); `/health` no longer echoes database errors; file captures return one generic 404 for
  missing vs disallowed paths; Docker/Pi-hole/Minecraft error messages no longer contain absolute
  paths.
* **Write amplification (MEDIUM):** activity mutations now require `action` scope (a read-only
  token can no longer clear the operator's feed), `last_used_at` is flushed at most once per minute,
  and `service_state` rows are only updated when their detail changes.
* **Log reads:** `/minecraft/logs` tails the last 512 KiB with `seek` instead of reading the whole
  file into memory.

### Fixed
* SQLite reader connections are cached per `Database` instance instead of in a module-level
  thread-local keyed by `id(self)`; the previous scheme could hand back a connection to a freed
  test database after CPython reused an address (flaky test failures).
* Window-capture staging uses `mkstemp` and is always cleaned up.
* Swift: added the missing `UIKit` import in the snapshot test, corrected `SWIFT_VERSION` to `5.0`
  (the valid `-swift-version` value), and the foreground polling loop now starts on launch and after
  sign-in rather than only on a later scene-phase change.

### Verified
* 147 pytest tests, 58 live smoke checks, `beacon doctor` green, OpenAPI contract up to date,
  iOS validation unchanged (22 files parsed, 13 Swift tests, 109 call sites, project valid), live
  Docker metrics served from the snapshot, X11 capture working with `NoNewPrivileges=yes`.

## [0.1.2] — 2026-11-10

Operational validation on the live deployment plus a small hardening increment.

### Added
* `docs/OPERATIONS.md`: runbook for service lifecycle, health checks, backup/restore, token and TLS
  rotation, retention, agent operations, Minecraft/Pi-hole procedures, incident checklist,
  hardening posture and upgrades.

### Security hardening
* Configurable request-body ceiling (`BEACON_MAX_REQUEST_BYTES`, default 64 MiB) enforced in
  middleware before parsing, plus a pre-read size check on multipart screenshot uploads, so an
  oversized body cannot be buffered into memory.
* The agent interrupt handler re-resolves the DSH runtime immediately before `SIGINT` and refuses
  (`409 target_changed`) if the process changed or disappeared; the Minecraft stop path re-checks
  `find_process` before signalling. Both are covered by tests where the second lookup fails and the
  process must survive.
* Writing to the supervised Minecraft console now maps `OSError` to a structured
  `console_write_failed` error instead of an unhandled 500.
* Window capture builds a subprocess environment instead of mutating the service's `os.environ`.
* `verify_token` now compares the digest it actually selected (constant-time) and no longer reads a
  column it did not fetch.

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
