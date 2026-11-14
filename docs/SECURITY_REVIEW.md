# Security review record

An independent read-only review of the backend (authentication, authorisation, injection,
process handling, retention, deployment privileges) and of the SwiftUI layer (compile risks) was
performed on 2026-11-12. This file records what was found and what was done, with the evidence used
to confirm it. It is not a certification — it is an audit trail.

## 1. Findings and resolution

| # | Severity | Finding | Status | Evidence |
|---|---|---|---|---|
| 1 | HIGH | The API ran as `eric`, who has passwordless root, with `NoNewPrivileges=off`. The "read-only Docker wrapper" was therefore not a privilege boundary. | **Fixed** — API no longer runs `sudo`; Docker reads moved to a root timer writing a snapshot file; `NoNewPrivileges=yes`; credential directories masked. | `systemctl show … NoNewPrivileges` → `yes`; `sudo` inside an NNP unit fails; `systemctl-analyze security` 6.3; no `sudo` literals in `services/` or `routers/` |
| 2 | MEDIUM | Message delivery was at-most-once: rows became `delivered` before the agent received them, with no redelivery or nack. | **Fixed** — leases (120 s), redelivery up to 5 attempts, agent `nack`; tests age a delivery and assert redelivery. | `tests/test_queue.py` |
| 3 | MEDIUM | Interrupt target came from the agent-writable status snapshot. | **Fixed** — targets come only from read-only Cherry Studio sessions (or `BEACON_SESSION_ID`); explicit `session_id` validated; pidfd + pre-signal re-resolution. | `tests/test_interrupt.py::test_agent_cannot_redirect_interrupt_via_status_snapshot` |
| 4 | MEDIUM | Uploads buffered whole bodies; the `Content-Length` check was bypassable with chunked encoding; no total quota. | **Fixed** — chunked-safe ASGI body limit, pre-read per-file check, 512 MiB store quota, upload throttles. | `tests/test_contract_and_security.py::test_chunked_body_limit_is_enforced` |
| 5 | MEDIUM | A read-scoped token could mutate the activity feed; every request wrote `last_used_at`; `service_state` rewrote unchanged rows. | **Fixed** — activity mutations require `action`; token flush ≤1/min; no-op state updates skipped. | `tests/test_monitoring.py`, `tests/test_auth.py` |
| 6 | MEDIUM | `?token=` on screenshot GETs leaked bearer tokens into access logs. | **Fixed** — header-only authentication; query-token path removed. | `tests/test_interrupt.py::test_query_token_is_not_accepted` |
| 7 | LOW | PID-reuse window between `/proc` resolution and `kill`. | **Fixed** — pidfd signalling where available; both callers re-verify before signalling. | `procs.send_signal`; fallback test |
| 8 | LOW | Window-capture staging file was time-derived and force-overwritten. | **Fixed** — `mkstemp` + `finally` cleanup. | code review + parse/tests |
| 9 | LOW | File-capture existence oracle and absolute paths in error messages. | **Fixed** — one generic 404 for missing/disallowed; paths removed from Pi-hole/Docker/Minecraft messages. | `tests/test_contract_and_security.py::test_capture_file_has_no_existence_oracle` |
| 10 | LOW | Unbounded log read; DB error leaked on unauthenticated `/health`; idempotency race returned a 500. | **Fixed** — bounded tail (512 KiB), generic health error, `ON CONFLICT DO NOTHING` with per-client keys. | `tests/test_monitoring.py`, `test_queue.py`, `test_contract_and_security.py` |

A cross-test flake was also found during this work: SQLite reader connections were cached in a
module-level thread-local keyed by `id(Database)`, so a freed database's address could be reused
and hand back a connection to the wrong file. Connections are now owned per `Database` instance and
closed on reset.

## 2. The privilege split (why this shape)

`eric` has `NOPASSWD: ALL` for interactive convenience, which makes any process running as `eric`
root-capable unless something prevents it. Two options were considered:

1. **Dedicated service account** — the textbook fix, but it needs ACLs across `/home/eric`
   (which is 0700), the Cherry Studio database and WAL/SHM files, the Minecraft folder (read *and*
   write for controls), `~/.Xauthority` for genuine window captures, plus split ownership of
   `data/` between operator CLI and service. That is a large, risky change on a live host.
2. **Remove the privileged path from the API** — chosen. The only root action was Docker
   inspection, so it moved into a fixed, root-owned oneshot timer
   (`beacon-docker.timer` → `docker ps` + `docker stats` → `/run/beacon/docker.json`), and the API
   was given `NoNewPrivileges=yes`. The sudo helper and its sudoers rule were deleted.

Result: `sudo` inside the unit fails (verified with `systemd-run`), while an interactive shell is
unaffected. The API still runs as `eric`; that residual risk is listed below.

## 3. Verification commands

```bash
# the boundary
systemctl show beacon-api.service -p NoNewPrivileges -p InaccessiblePaths
sudo systemd-run --wait --pipe --property=NoNewPrivileges=yes --property=User=eric \
     /usr/bin/sudo -n /usr/bin/id      # → "the 'no new privileges' flag is set", exit non-zero

# the privileged read is a fixed timer, not a generalised API capability
systemctl status beacon-docker.service
sudo cat /run/beacon/docker.json

# static and behavioural checks
cd backend && .venv/bin/python -m pytest tests -q          # 164 tests
python3 scripts/check_openapi_drift.py
backend/.venv/bin/python scripts/smoke_test.py             # live, 58 checks
beacon doctor
```

## 4. Residual risks (accepted, documented)

* The API process runs as `eric`. It can read the Cherry Studio database (required for agent
  evidence) and, because `BEACON_CHAT_WRITE=1`, write one narrowly-shaped user message row into
  Cherry's durable delivery table so Chats is writeable from the phone. That requires
  `ReadWritePaths` for `~/.config/CherryStudio/Data` and is the main new privilege of this feature.
  The API still cannot gain root, cannot execute arbitrary shell commands, and can write only to
  `data/`, the Minecraft folder, and that Cherry data directory. The write path is transactionally
  one row, validates the session/agent, and falls back to the Beacon queue on any schema or lock
  error. Set `BEACON_CHAT_WRITE=0` to return to a strictly read-only Cherry integration.
* The Docker snapshot timer is root and runs a fixed Python script; compromises of that script
  would grant Docker-socket-level access. It is short, dependency-free and only shells out with a
  fixed argv.
* LAN-only deployment: no port forward, no public listener; TLS with a private CA and SPKI pinning.
* The iOS layer could not be compiled on this host; its risk is mitigated by parsing all sources,
  compiling/testing the Foundation subset, and a call-site checker, but an Xcode build is still the
  first real compile.
