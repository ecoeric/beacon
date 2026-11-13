# API reference

Base URL: `https://192.168.1.83:8091/api/v1` · TLS with the private Beacon CA · JSON only.
The machine-readable contract is `docs/openapi.json` (regenerate: see below).

## Authentication

```
Authorization: Bearer <token>
```

| Scope | Grants |
|---|---|
| `read` | all status/monitoring GETs, screenshots, activity, capabilities, whoami |
| `action` | `read` + queue a suggestion / Continue / cancel a pending message |
| `admin` | `action` + interrupt, Pi-hole blocking, Minecraft controls, milestone creation, screenshot capture/delete, retention run, audit |
| `agent` | runtime-only endpoints (status publishing, checkpoint delivery, acknowledgements) |

Scopes are hierarchical for human clients (`admin ⊃ action ⊃ read`); `agent` is separate.
The agent token additionally gets `read` so it can see its own status.

Tokens are accepted **only** in the `Authorization` header. Query-string tokens are not
supported (they would be written to access logs); image requests carry the header as well.

## Errors

```json
{"error": "rate_limited", "message": "Too many requests, slow down"}
```

| Status | Meaning |
|---|---|
| 401 | missing/invalid token |
| 403 | token lacks the scope |
| 409 | state conflict (e.g. no runtime to interrupt, invalid queue transition) |
| 410 | screenshot expired (7-day retention) |
| 422 | validation error (Pydantic message shape: `{"detail": [...]}`) |
| 428 | missing `X-Beacon-Confirm` header |
| 429 | rate limited (`Retry-After`) |
| 500/502/503/504 | server-side failure, upstream unavailable, timeout |

Confirmation headers: `agent-interrupt`, `pihole-blocking`, `minecraft-start`,
`minecraft-stop`, `minecraft-restart`.

## Endpoints

### System

| Method | Path | Scope | Notes |
|---|---|---|---|
| GET | `/health` | none | liveness, version, TLS flag |
| GET | `/whoami` | read | token id, name, scopes |
| GET | `/summary` | read | everything the home screen needs |
| GET | `/activity` | read | activity feed (`?limit=`) |
| POST | `/activity/{id}/read` | action | mark one read |
| POST | `/activity/read-all` | action | mark all read |
| GET | `/capabilities` | read | what this deployment can read/control |
| GET | `/audit` | admin | last 200 audit rows |

### Agent

| Method | Path | Scope | Notes |
|---|---|---|---|
| GET | `/agent/status` | read | structured state + evidence + queue counts |
| GET | `/agent/status/summary` | read | deterministic 1–3 sentence status (no LLM) |
| GET | `/agent/sessions` | read | read-only Cherry Studio session list (`?limit=`) |
| GET | `/agent/sessions/{session_id}/messages` | read | read-only visible transcript (`?limit=`) |
| PUT | `/agent/status` | agent | publish snapshot (project/stage/activity/… ) |
| GET | `/agent/messages` | read | recent messages (`?limit=`) |
| POST | `/agent/messages` | action | queue a suggestion (`text`, `kind`, `idempotency_key`) |
| POST | `/agent/continue` | action | Continue (optional `note`) |
| DELETE | `/agent/messages/{id}` | action | cancel while pending |
| GET | `/agent/queue` | read | queue stats + last checkpoint age |
| POST | `/agent/interrupt` | admin | `{mode, reason?, session_id?}` + confirm header; target comes from Cherry Studio sessions, never the status snapshot |
| GET | `/agent/interrupts` | read | interrupt history |
| POST | `/agent/checkpoint` | agent | deliver pending/lease-expired messages + interrupts |
| POST | `/agent/messages/{id}/ack` | agent | acknowledge delivery |
| POST | `/agent/messages/{id}/nack` | agent | return a delivered message to the queue |
| POST | `/agent/messages/{id}/processed` | agent | mark processed |
| GET | `/agent/interrupts/pending` | agent | checkpoint interrupts awaiting ack |
| POST | `/agent/interrupts/{id}/ack` | agent | acknowledge an interrupt |

### Milestones & screenshots

| Method | Path | Scope | Notes |
|---|---|---|---|
| GET | `/milestones` | read | history (`?limit=&offset=`) |
| GET | `/milestones/{id}` | read | one milestone with screenshot metadata |
| POST | `/milestones` | admin/agent | create, optionally attach staged capture ids |
| POST | `/milestones/{id}/screenshots` | admin/agent | multipart upload (png/jpeg/webp, max 4 total) |
| GET | `/screenshots/{id}` | read | image bytes (410 when expired) |
| DELETE | `/screenshots/{id}` | admin | delete one (audited) |
| POST | `/screenshots/capture` | admin/agent | `source: text|api|window|file` |
| GET | `/captures/{id}` | read | staged capture preview |
| POST | `/retention/run` | admin | run the sweep (`?dry_run=true`) |
| GET | `/retention/status` | read | window, counts, storage, next expiry |

### Monitoring and controls

| Method | Path | Scope | Notes |
|---|---|---|---|
| GET | `/server/overview` | read | CPU/RAM/GPU/disks/network/uptime/docker |
| GET | `/docker/containers` | read | 503 when the helper is unavailable |
| GET | `/pihole/status` | read | stats, blocking, container health, upstreams |
| POST | `/pihole/blocking` | admin | `{enabled: bool}` + confirm |
| GET | `/minecraft/status` | read | ping, players, process metrics, logs summary |
| GET | `/minecraft/logs` | read | `?lines=10..300` |
| POST | `/minecraft/control` | admin | `{action:"start"|"stop"|"restart", force}` + confirm |

## Regenerating or checking the contract snapshot

```bash
# check (exit 1 on drift) — also enforced by pytest
backend/.venv/bin/python scripts/check_openapi_drift.py

# regenerate after an intentional API change
backend/.venv/bin/python scripts/check_openapi_drift.py --write
```

`ios/Fixtures/*.json` are captured from the live service and decoded by the Swift tests, so
contract drift fails the iOS validation too.
