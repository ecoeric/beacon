# Architecture

## 1. Overall shape

Two deployables plus an iOS client.

| Component | Technology | Location | Process |
|---|---|---|---|
| `Beacon` iOS app | Swift 5.9+, SwiftUI, iOS 17+, no third-party packages | `ios/Beacon/**` | iPhone |
| `beacon-api` | Python 3.13, FastAPI, SQLite (WAL), Uvicorn with TLS | `backend/beacon/**` | systemd unit `beacon-api.service`, `192.168.1.83:8091` |
| `beacon` CLI | Python (same venv), talks to the API | `backend/beacon/cli.py` | invoked by admin or by the AI agent at checkpoints |

The iOS app never talks to Docker, Cherry Studio, Minecraft, or Pi-hole directly. Every byte
it sees is produced by `beacon-api`, which is the only component with credentials.

## 2. Responsibilities (deliberately independent)

```
                       ┌──────────────────────────── beacon-api ────────────────────────────┐
iPhone ──HTTPS/token──►│ auth ─► routers ─► services                                        │
                       │   agent_status   ← agent snapshot store + Cherry Studio evidence    │
                       │   message_queue  ← SQLite queue, checkpoint delivery                │
                       │   interrupt      ← /proc runtime resolution → SIGINT (audited)      │
                       │   milestones     ← milestone + screenshot metadata                   │
                       │   screenshots    ← capture sources + retention sweep                 │
                       │   monitoring     ← /proc, sensors, nvidia-smi, docker (read-only)     │
                       │   pihole         ← Pi-hole v6 API client                             │
                       │   minecraft      ← ping, logs, process, guarded controls              │
                       │   notifications  ← activity feed, dedupe + transitions                │
                       └──────────────────────────────────────────────────────────────────────┘
```

* **Status service** (`services/agent_status.py`) only reads: the agent-pushed snapshot row,
  the Cherry Studio SQLite database (opened read-only), `/proc` for the runtime process, and
  queue counts. It never writes to Cherry Studio, never calls an LLM, never spawns the agent.
  The one-to-three-sentence Status text is composed deterministically in
  `services/status_summary.py` (`render_status_summary`), a pure function over the snapshot.
* **Message queue** (`services/message_queue.py`) stores messages with explicit lifecycle
  states and only hands them out at a checkpoint call made by the agent token. It never
  writes into a running turn.
* **Interrupt handler** (`services/interrupt.py`) is a separate path with its own scope
  (`admin`), confirmation header, rate limit and audit row. It bypasses the queue completely.
* **Monitoring** (`services/system_metrics.py`, `services/docker_monitor.py`,
  `services/pihole.py`, `services/minecraft.py`) reads only; it has no dependency on agent
  state and keeps working when the agent is gone.
* **Milestone service** (`services/milestones.py`, `services/screenshots.py`,
  `services/retention.py`) owns milestone metadata, screenshot files and the retention sweep.

## 3. Data flow

### Dashboard refresh (polling)

`GET /api/v1/summary` composes, in one request, the agent card, service health, latest
milestone with screenshot descriptors, unread activity count and `data_age_seconds`. The app
polls every 15 s in the foreground, on pull-to-refresh, and on foregrounding. Every payload
carries `generated_at` and per-section evidence timestamps so stale data is rendered as stale.

### Agent message lifecycle

```
iOS "Send suggestion"           POST /api/v1/agent/messages        → status pending
agent checkpoint (turn boundary) POST /api/v1/agent/checkpoint      → status delivered (attempt++,
                                                                      inbox.jsonl mirror written)
agent acknowledges               POST /api/v1/agent/messages/{id}/ack → status acknowledged
agent finishes the work          POST /api/v1/agent/messages/{id}/processed → status processed
```

Ordering is by `seq` (monotonic), never by timestamp. Cancellation is only allowed while
`pending`. There is no code path that mutates a delivered message.

### Continue

`POST /api/v1/agent/continue` (`{note?: string}`) is sugar over the same queue with
`kind="continue"`; it requires no text.

### Interrupt

```
POST /api/v1/agent/interrupt  {mode:"signal"|"checkpoint", reason?}
  → resolve runtime pid for the bound session (composition file ↔ /proc cmdline, uid checked)
  → signal:     write interrupt row, SIGINT pid, poll for exit ≤ 5 s, record evidence
  → checkpoint: write interrupt row consumed by the agent at its next safe point
```

`mode=signal` is the default and is the only implementation that stops an actively running
turn. Both modes bypass the queue. If the runtime cannot be resolved the request returns
`409` with a machine-readable reason instead of pretending an interrupt happened.

### Milestones and screenshots

Milestones are created through `POST /api/v1/milestones` (admin or agent scope) with summary
and change list. Screenshot bytes are uploaded to the same endpoint as multipart files (or
captured server-side by `beacon screenshot capture`). Each file gets `expires_at =
created_at + 7 days`; reads of expired images return `410`; the retention sweep deletes only
rows and files recorded in the `screenshot` table, confined to the screenshots directory.

## 4. Storage

All state is in `data/` (mode 0700): `beacon.sqlite` (WAL), `secrets/*.token` (0600),
`screenshots/<milestone-id>/<sha256-prefix>-<name>.<ext>`, `agent/inbox.jsonl`,
`captures/` (transient render inputs), `logs/`. Backups are a filesystem copy of `data/`
(SQLite in WAL mode is copied with `VACUUM INTO` by `beacon backup`).

## 5. Security model

* Transport: TLS 1.2+ only, ECDSA P-256 certificate issued by `beacon tls init`.
  The app performs SHA-256 **SPKI pinning**; there is no "ignore certificate errors" switch.
* Process containment: the API runs with `NoNewPrivileges=yes` (so a compromised process cannot
  exec setuid `sudo` even though the interactive account has a NOPASSWD rule), `ProtectSystem=strict`,
  `ProtectHome=read-only` plus `ReadWritePaths` for `data/` and the Minecraft folder,
  `ProtectProc=invisible`, `SystemCallArchitectures=native`, and `InaccessiblePaths` masking
  `~/.ssh`, `~/.gnupg`, `~/.mozilla` and Cherry Studio's `Credentials` directory. Residual risk:
  the process still runs as `eric` and can read the Cherry Studio database (needed for agent
  evidence) and other non-masked files owned by that account; it cannot gain root.
* Authentication: opaque bearer tokens (32 random bytes, base64url) accepted **only** in the
  `Authorization` header. Only SHA-256 hashes are stored in SQLite; plaintext is written once to
  `data/secrets/<name>.token` (0600). `last_used_at` is flushed at most once per minute.
  Scopes: `read` < `action` < `admin`, plus a dedicated `agent` scope for the runtime CLI.
* Authorisation: every route declares a required scope; destructive service controls require
  `admin` **and** a confirmation header (`X-Beacon-Confirm: <action>`), are rate limited,
  and write an audit row.
* Input validation: strict Pydantic models, bounded message lengths, enumerated states,
  a chunked-safe request-body ceiling, per-file and total screenshot quotas, per-token throttles,
  and no user-controlled paths or shell strings anywhere in the request path. The API spawns only
  `nvidia-smi`, `sensors`, `ffmpeg` (x11grab), the allow-listed `beacon` capture commands and the
  Minecraft rcon client (host/port from config, command from a fixed enum); it never runs `sudo`
  and never touches the Docker socket.
* The systemd unit runs as `eric` with `ProtectSystem=strict`, `ProtectHome=read-only`,
  and `ReadWritePaths` limited to `~/beacon/data` and the Minecraft folder. Docker visibility is
  provided by a separate root timer; see 8.5.
* No arbitrary shell execution endpoint exists.

## 6. Agent state machine

Derived in `services/agent_status.py::derive_state`, first match wins:

| State | Evidence |
|---|---|
| `disconnected` | snapshot older than `STALE_DISCONNECT` (24 h) and no live runtime for the session |
| `failed` | last assistant message `status='error'`, or snapshot `state_override='failed'`, fresher than 10 min |
| `interrupted` | latest interrupt row `status='signalled'` without a later snapshot/heartbeat |
| `working` | live runtime **and** (an assistant message with `status='pending'` **or** session activity < 90 s) |
| `waiting_for_messages` | queue has `pending` messages |
| `waiting_for_input` | snapshot `awaiting_input=true` |
| `completed` | snapshot `state_override='completed'` |
| `idle` | live runtime, no pending assistant turn, snapshot fresh |
| `unknown` | none of the above / insufficient evidence |

Every response carries the evidence used (`evidence[]`) and `data_age_seconds`, so the app can
distinguish "idle" from "we cannot tell".

## 7. Dependencies

Backend: `fastapi`, `uvicorn`, `pydantic`, `httpx`, `cryptography` (TLS + SPKI), `python-multipart`,
`pytest` (dev). Deliberately no ORM, no task queue, no Redis, no monitoring stack — the host
already runs enough services. iOS: Foundation, SwiftUI, Charts, Security, QuickLook — all
system frameworks, zero packages.

## 8. Implementation map (as built)

### 8.1 Backend modules

| Module | Responsibility |
|---|---|
| `main.py` | app factory, routers, error mapping, lifespan (sampler, retention loop), security headers |
| `config.py` | environment-driven settings (single source) |
| `db.py` | SQLite WAL connections, schema v1, transactions with retry |
| `security.py` | token hashing/creation/verification, scopes, audit, rate limiter |
| `deps.py` | FastAPI dependencies, confirmation header, throttling |
| `tls.py` | private CA + leaf generation, SPKI pin, certificate inspection |
| `services/agent_runtime.py` | read-only Cherry Studio evidence + `/proc` runtime resolution |
| `services/agent_status.py` | state machine, snapshot loading, status payload |
| `services/status_summary.py` | deterministic 1–3 sentence status text (pure) |
| `services/message_queue.py` | queue lifecycle, checkpoint delivery, inbox mirror |
| `services/interrupts.py` | signal/checkpoint interrupts, resolution, evidence, audit |
| `services/milestones.py` | milestone records and joins |
| `services/screenshots.py` | validation, storage, serving rules, expiry |
| `services/capture.py` | real capture sources (text/api/window/file) + PNG renderer |
| `services/retention.py` | confined deletion sweep, storage summary |
| `services/summary.py` | dashboard composition + service edge detection |
| `services/system_metrics.py` | sampler and host metrics |
| `services/docker_monitor.py` | reads the root-written Docker snapshot file (no sudo, no socket) |
| `services/pihole.py` | Pi-hole v6 client (session cache, stats, blocking) |
| `services/minecraft.py` | ping, process, logs, backups, supervisor, guarded controls |
| `services/notifications.py` | activity feed, dedupe, transitions |
| `cli.py` | operator and agent CLI |

### 8.2 Database schema (v1)

`token`, `agent_status` (one row per agent id), `agent_message` (seq-ordered queue),
`interrupt`, `milestone`, `screenshot` (metadata kept after expiry), `notification`, `audit`,
`service_state` (edge detection), `meta` (schema version, checkpoint timestamp).

### 8.3 API surface

40 routes under `/api/v1` in five groups (system, agent, milestones/screenshots, monitoring,
retention). Full table in `docs/API.md`; machine-readable contract in `docs/openapi.json`.
Documentation endpoints are disabled in production (`BEACON_ENABLE_DOCS=0`).

### 8.4 iOS implementation

* `ios/Beacon/Models` — Codable mirrors of the API, Foundation only.
* `ios/Beacon/Networking` — `APIClient`, `PinnedSession` (CA anchor + SPKI pin, DER parser),
  `Keychain`, `AppSettings`, `ServerConfiguration`.
* `ios/Beacon/App` — `BeaconApp`, `RootView` (four tabs + onboarding gate), `AppModel`.
* `ios/Beacon/Design` — `Theme`, reusable components.
* `ios/Beacon/Features` — Setup, Dashboard, Agent, Milestones (+ viewer), Server, Settings.
* `ios/SharedTests` — decoding/formatting tests shared with the Linux SwiftPM package.
* `ios/BeaconTests/SnapshotTests` — renders four screens to PNG on macOS (live or fixture mode)
  and attaches them to the `.xcresult`.
* `ios/Shim` — mock SwiftUI/UIKit/Combine modules used only by the Linux typecheck; never
  compiled into the app.
* `.github/workflows/ios-build.yml` — real Xcode build + simulator tests on a macOS runner.

### 8.5 Deployment topology (actual)

Operational procedures: `docs/OPERATIONS.md`.

```
systemd
├── beacon-api.service      eric, 192.168.1.83:8091 TLS, ProtectSystem=strict
│                           ProtectHome=read-only + ReadWritePaths data + Minecraft folder
│                           NoNewPrivileges=yes, PrivateTmp=off (X11), credential dirs masked
├── beacon-retention.timer  daily 03:41 (Persistent), oneshot beacon-retention.service
├── beacon-docker.timer     every 15 s, oneshot beacon-docker.service as root
│                           two fixed docker commands → /run/beacon/docker.json (0644)
└── (existing) pihole container, NeoForge java process, Caddy, WinLab, Cherry Studio
```

### 8.6 Deliberate deviations from the Phase 1 sketch

| Sketch | Built | Why |
|---|---|---|
| Single retention trigger | read guard + hourly in-process sweep + daily systemd timer | cleanup must survive restarts and API downtime |
| Interrupt only as SIGINT | SIGINT **and** cooperative checkpoint mode | signal is impossible when the runtime is gone; both bypass the queue |
| Docker via socket | root timer writes a read-only snapshot file | avoids root-equivalent Docker access *and* lets the API run with NoNewPrivileges |
| Screenshots from the app only | four server-side capture sources + upload endpoint | the UI cannot be rendered on this host; real artifacts are still capturable |
| iOS build “on the server” | source + Linux Foundation tests + mock-framework SwiftUI typecheck + CI Xcode workflow | Xcode requires macOS; CI supplies the real iOS-SDK build |

## 9. Testing strategy

| Layer | Method | Result (last run) |
|---|---|---|
| API/service logic | 149 pytest tests with synthetic Cherry Studio DB, fake Minecraft/RCON servers, mocked Pi-hole transport and controlled processes | 149 passed |
| Transport/auth | real Uvicorn TLS server + generated CA in tests | verified trust and rejection |
| Live system | `scripts/smoke_test.py` against real Pi-hole/Minecraft/Docker/agent | 58 checks passed |
| iOS logic | Swift 6 on Linux: compile + 13 decoding/formatting tests against live-captured fixtures | 13 passed |
| iOS syntax | `swiftc -parse` on all 22 Swift files | parsed |
| iOS SwiftUI typecheck | real Swift 6 compiler against mock SwiftUI/UIKit/Combine modules (`scripts/typecheck_ios_views.sh`) | 19 app files + 2 test files, 0 errors |
| iOS SDK build | GitHub Actions `macos-15` runner (`docs/CI.md`) | workflow committed, not yet run |
| Xcode project | `pbxproj` parser + cross-checks | 18 checks passed |
| Retention | live drill via the systemd unit (aged screenshot) | deleted, 410 confirmed, history kept |
| Backup / restore | `beacon backup` then serve the API from the restored data directory | milestone, token and image intact |
| Contract & security | OpenAPI snapshot equality, static no-shell checks, snapshot-timer privilege checks | clean |
| Agent messaging | live queue + checkpoint + ack + processed; interrupt signal path against a controlled process | verified |
