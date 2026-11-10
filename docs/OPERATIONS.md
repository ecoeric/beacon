# Operations runbook

Practical procedures for the deployed Beacon service on `ericserver`. Everything here was
executed on this host unless marked otherwise.

---

## 1. Service lifecycle

```bash
systemctl status beacon-api.service
systemctl is-active beacon-api.service        # active
systemctl is-enabled beacon-api.service       # enabled (starts at boot)
sudo systemctl restart beacon-api.service
sudo journalctl -u beacon-api.service -n 100 --no-pager
beacon service logs                           # same, wrapped
```

`beacon-api.service` has `Restart=always` with `RestartSec=3`. **Crash recovery drill
(verified):** `systemctl kill -s KILL beacon-api.service` → systemd restarted the process and the
API answered again in **3.8 s**; milestones, queue and screenshots were intact.

The service writes only to `data/` and (when controls are used) the Minecraft folder; it never
writes to Cherry Studio's database.

---

## 2. Health checks

| Check | Command | Expectation |
|---|---|---|
| Full deployment | `beacon doctor` | all checks ✓ |
| End-to-end live | `backend/.venv/bin/python scripts/smoke_test.py` | “all N checks passed” |
| Liveness | `curl --cacert data/tls/ca.crt https://192.168.1.83:8091/api/v1/health` | `{"status":"ok",...}` |
| Agent evidence | `beacon agent status` | state + evidence with ages |
| Contract | `backend/.venv/bin/python scripts/check_openapi_drift.py` | “up to date” |
| Unit tests | `cd backend && .venv/bin/python -m pytest tests -q` | 121 passed |
| iOS sources | `scripts/validate_ios.sh` | parse + Swift tests + project checks |

If `doctor` says “API reachable” failed: check `systemctl status`, then the TLS file permissions
(`data/tls` 0700, keys 0600), then `ss -tlnp | grep 8091`.

---

## 3. Backup and restore

### Create

```bash
beacon backup                       # → data/backups/<UTC timestamp>/
beacon backup --to /mnt/storage_hdd/beacon-backups/$(date +%F)
```

Contents: `beacon.sqlite` (via `VACUUM INTO`, integrity-checked), `secrets/`, `tls/`,
`screenshots/`.

### Restore procedure

1. `sudo systemctl stop beacon-api.service`
2. Copy back `beacon.sqlite`, `secrets/`, `tls/`, `screenshots/` into `data/` (keep ownership
   `eric:eric`; keys 0600, `data/` 0700).
3. `sudo systemctl start beacon-api.service`
4. `beacon doctor` and `beacon summary`.

### Restore drill (verified on the live archive)

The production backup was restored into a temporary data directory and a second API instance was
started on `127.0.0.1:8093` with the restored TLS material:

* `/api/v1/health` → 200, `database: ok`, `tls: true`
* `/api/v1/milestones` → the same four milestones with the same live/expired counts
* a screenshot fetched with the **restored** token → 200, 22 989 bytes

The temporary instance was stopped afterwards; the live service was not affected.
*(A unit test performs the same drill automatically:
`test_backup_can_be_restored_and_served`.)*

---

## 4. Credentials

### Token rotation

```bash
beacon token create ios2 --scopes read,action,admin   # prints the value once
beacon token revoke ios                               # old token stops working immediately
# update the app: Settings → Disconnect → reconnect with the new token
```

Tokens are hashed in SQLite; plaintext lives only in `data/secrets/<name>.token` (0600). The
`agent` token is required for runtime endpoints and must be updated in the agent's workspace
instructions if rotated.

### TLS rotation

```bash
beacon tls init --force        # new CA + leaf, re-copies ca.crt into ios/Beacon/Resources
beacon tls show                # SANs + new SPKI pin
sudo systemctl restart beacon-api.service
```

Then rebuild the iOS app (new bundled CA) and update the pin in Settings if one is used.
Leaf validity is 397 days; calendar a reminder before then.

---

## 5. Screenshots and retention

```bash
beacon retention status                 # window, live/expired, bytes, next expiry
beacon retention run --dry-run
beacon retention run --local            # exactly what the timer runs
systemctl list-timers beacon-retention.timer
sudo systemctl start beacon-retention.service   # run now
```

Semantics: after 7 days the file is deleted and reads return `410 {"error":"expired"}`; milestones
keep their text. Screenshots deleted by an operator return `410 {"error":"deleted"}` and are **not**
counted as retention expiry. The sweep only touches files under `data/screenshots` that are
recorded in the database (plus generated orphans older than 24 h and capture staging older than
48 h); unrelated files are reported and left alone.

**Live retention drill (verified):** one screenshot's `expires_at` was moved into the past; the
shipped `beacon-retention.service` deleted the file, kept the milestone text, returned 410, and
wrote an audit row `{"deleted_screenshots":1,"deleted_files":1,"kept":4}`.

---

## 6. Agent operations

```bash
beacon agent status                       # read-only state + evidence
beacon agent summary                      # the 1–3 sentence Status text
beacon agent checkpoint                   # agent: collect queued work (agent token)
beacon agent ack <id> --note "on it"      # agent: acknowledge a delivered message
beacon agent processed <id> --note "done" # agent: mark it processed
beacon agent interrupts                   # interrupt history
beacon agent interrupt --mode signal --reason "…" --yes   # admin; bypasses the queue
beacon agent interrupt-ack <id> --note "stopped cleanly"  # agent: acknowledge
beacon queue list / beacon queue stats
```

Safety rules:

* `--mode signal` sends `SIGINT` to the resolved DSH runtime PID (uid and cmdline are verified).
  It ends that runtime process; the session journal preserves work. **Never target the runtime that
  hosts your own session.**
* `--mode checkpoint` records a cooperative interrupt that the agent consumes at its next safe
  point — use it when the runtime is not resolvable.
* Interrupt requires the `admin` scope plus the confirmation header; the CLI adds it for you.
* Queued messages are only handed out by the agent token at a checkpoint; UI tokens cannot consume
  the queue.

---

## 7. Minecraft

Control channel priority: supervised pty console → RCON → SIGINT (only if the installed server jar
contains the `Server Shutdown Thread` hook). The server is never force-killed; a failed stop is
reported, not escalated.

```bash
beacon minecraft status
beacon minecraft start --yes
beacon minecraft stop --yes            # refuses with players online unless --force
beacon minecraft restart --yes --force
```

The running instance was originally started by hand in a terminal; to get full console control,
stop it once and start it from Beacon (`beacon minecraft start`). With RCON enabled
(`enable-rcon=true` + `data/secrets/minecraft.rcon`) typed commands are used instead.
TPS/MSPT remain unavailable on this install (no spark, RCON/query off) and the API says so.

---

## 8. Pi-hole

```bash
beacon pihole status
beacon pihole block off --yes          # admin + confirmation, audited
beacon pihole block on --yes
```

The dashboard uses the existing container's v6 API and never reconfigures it. The app password is
imported by `beacon init` from the container environment into `data/secrets/pihole.password`.

---

## 9. Incident checklist

| Symptom | First checks | Typical fix |
|---|---|---|
| App shows “Offline” | `beacon doctor`; `systemctl status beacon-api`; same LAN? | start/restart the service |
| App shows “token rejected” | `beacon token list`; revoke/rotate | new token in the app |
| Certificate warning in the app | `beacon tls show`; was the app rebuilt after rotation? | bundle the current `ca.crt`, re-enter pin |
| Agent “disconnected” | Cherry Studio running? `ps aux \| grep dsh-bridge`; `beacon agent status` | reopen the agent session |
| Messages never delivered | `beacon queue list`; `data/agent/inbox.jsonl` mtime | agent must call `beacon agent checkpoint` |
| Interrupt 409 `no_runtime` | `beacon agent status` session/runtime | use `--mode checkpoint`, or resume the session |
| Pi-hole unreachable | `docker ps`; `curl http://192.168.1.83:8080/api/auth` | restart container (outside Beacon) |
| Minecraft shows stopped | `ss -tlnp \| grep 25565`; server log | start it in its console or via Beacon |
| Docker metrics missing | `sudo -n /usr/local/lib/beacon/docker-read ps` | re-run `scripts/install.sh` |
| Disk pressure activity item | `df -h`; `beacon system show` | clean up; the item clears when below 92 % |
| Screenshot 410 | expected after 7 days (or manual delete) | milestone text remains |

---

## 10. Hardening posture

`systemd-analyze security beacon-api.service` → **6.5 MEDIUM** (was 6.9 before adding
`SystemCallArchitectures=native` and `ProtectProc=invisible`).

Deliberate trade-offs:

* `NoNewPrivileges=off` and `RestrictSUIDSGID` not set — the service calls the sudo-allow-listed,
  read-only Docker helper; that wrapper only accepts `ps` and `stats`.
* `PrivateTmp=off` — `ffmpeg -f x11grab` needs `/tmp/.X11-unix` for real window captures.
* `PrivateDevices=off` — `nvidia-smi` needs `/dev/nvidia*`.
* `ProtectHome=read-only` with `ReadWritePaths` for `data/` and the Minecraft folder.
* An `IPAddressDeny=any` egress allow-list was trialled and **reverted**: with it in place the
  service could not reach Pi-hole on the same host. The unit documents this. Exposure is instead
  limited by binding to `192.168.1.83` only (no port forward, no public listener).
* API docs are disabled (`BEACON_ENABLE_DOCS=0`); `docs/openapi.json` is the reviewed contract.

---

## 11. Upgrade procedure

```bash
cd ~/beacon
git pull                        # or apply the reviewed change set
sudo scripts/install.sh         # idempotent: deps, units, tokens/TLS if missing, restart, doctor
(cd backend && .venv/bin/python -m pytest tests -q)
backend/.venv/bin/python scripts/smoke_test.py
scripts/validate_ios.sh         # when iOS sources changed
```

`install.sh` never rewrites an existing token, certificate or database. If the OpenAPI contract
changed intentionally, update the snapshot and the iOS fixture tests:

```bash
backend/.venv/bin/python scripts/check_openapi_drift.py --write
```
