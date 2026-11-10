# Setup

Everything is reproducible on `ericserver`. Nothing in this repository installs or signs the iOS
app — deployment to a device is a separate project.

---

## 1. Requirements

### Server (already satisfied on this host)

| Requirement | Version used |
|---|---|
| Debian | 13.6 (trixie) |
| Python | 3.13 (`uv` manages the venv) |
| `uv` | `/home/eric/.cherrystudio/bin/uv` |
| systemd | host init |
| Tools | `openssl` (not required — `cryptography` builds the cert), `ffmpeg` (X11 captures), `sensors`, `nvidia-smi`, `docker` (read-only helper) |
| Optional | Docker image `swift:6.0` for Linux-side Swift validation |

### iOS build machine (required to build/run the app)

| Requirement | Notes |
|---|---|
| macOS | 14 Sonoma or newer |
| Xcode | 16.0+ with an iOS 17+ simulator runtime |
| Apple ID in Xcode | free personal team is enough for simulator; a device build needs signing, which is a separate project |

The app has **zero** third-party dependencies (SwiftUI, Security, CryptoKit, Foundation only).

---

## 2. Backend installation

```bash
cd ~/beacon
sudo scripts/install.sh
```

What it does, in order:

1. creates `backend/.venv` and installs `backend/requirements.lock` (exact pinned versions);
2. installs the read-only Docker helper at `/usr/local/lib/beacon/docker-read` plus
   `/etc/sudoers.d/beacon-docker-read` (validated with `visudo -c`);
3. installs and enables `beacon-api.service` + `beacon-retention.timer`;
4. runs `beacon init` **as `eric`**: data directory, SQLite schema, TLS material, tokens
   (`ios`, `agent`, `cli`), Pi-hole password import, copies `ca.crt` into the iOS bundle;
5. restarts the API and runs `beacon doctor`.

If the script is re-run it is idempotent: existing tokens, certificates and the database are kept.

### Tokens

| Role | Scopes | Used by |
|---|---|---|
| `ios` | `read,action,admin` | the iPhone app (Keychain) |
| `agent` | `agent,read` | the AI agent at checkpoints (`beacon agent checkpoint`, `status-set`, `ack`) |
| `cli` | `read,action,admin` | operator CLI on the server |

Plaintext exists only in `data/secrets/<role>.token` (0600). Losing a token means creating a new
one: `beacon token create ios2 --scopes read,action,admin` and revoking the old:
`beacon token revoke ios`.

### TLS

```bash
beacon tls show                 # SANs, validity, SPKI pin
beacon tls init --force         # rotation (also re-copies ca.crt into the app bundle)
```

After rotation, rebuild the app so the new `ios/Beacon/Resources/ca.crt` is bundled, and re-run
`beacon doctor`.

### Pi-hole

`beacon init` imports the app password from the running container
(`sudo docker exec pihole printenv FTLCONF_webserver_api_password`) into
`data/secrets/pihole.password` (0600). The existing Pi-hole container is not modified.

### Minecraft controls

Read-only monitoring works with no configuration. Controls use the first available channel:

| Channel | How to enable | Notes |
|---|---|---|
| Supervised console (safest) | stop the current instance once, then start it from Beacon (`beacon minecraft start` or the app) | Beacon owns a pty and can send `stop` |
| RCON | add `enable-rcon=true`, `rcon.password=…` to `server.properties` (one restart), write the password to `data/secrets/minecraft.rcon` | typed console commands |
| SIGINT | nothing — enabled only if the installed server jar contains the `Server Shutdown Thread` hook (verified automatically) | equivalent to Ctrl+C; never force-killed |

The currently running instance was started manually in a terminal, so Beacon can monitor it and
can stop it via SIGINT but cannot type into its console until it is restarted once.

### Genuine window screenshots (optional)

`deploy/beacon.env` already sets `BEACON_X11_DISPLAY=:0` and
`BEACON_X11_AUTHORITY=/home/eric/.Xauthority`. Verify:

```bash
beacon screenshot capture --source window --title "desktop" --caption "test"
```

If no X session is available the API answers `503 no_display` instead of inventing an image.

---

## 3. Running

```bash
beacon service status            # systemd state + last log lines
beacon doctor                    # full deployment check
beacon summary                   # compact dashboard in the terminal
beacon agent status              # structured agent state + evidence
sudo journalctl -u beacon-api -f # live logs
```

Endpoints: `https://192.168.1.83:8091/api/v1/health` (health is the only unauthenticated route).
API docs are disabled by default; `docs/openapi.json` is the committed contract.

### Daily retention

```bash
systemctl list-timers beacon-retention.timer
beacon retention status          # window, counts, storage, next expiry
beacon retention run --dry-run
beacon retention run --local     # same command the timer runs
```

---

## 4. Testing

```bash
# 1. backend unit + integration tests (125; no live services needed)
cd ~/beacon/backend && .venv/bin/python -m pytest tests -q

# 1b. OpenAPI snapshot must match the code
cd ~/beacon && backend/.venv/bin/python scripts/check_openapi_drift.py

# 2. live end-to-end checks (real Pi-hole, Minecraft, Docker, agent runtime)
~/beacon/backend/.venv/bin/python ~/beacon/scripts/smoke_test.py

# 3. iOS: parse every source, compile+test the Foundation subset, check view call sites,
#    validate the Xcode project
cd ~/beacon && scripts/validate_ios.sh

# 4. deployment health
beacon doctor
```

`scripts/validate_ios.sh` needs Docker (image `swift:6.0`) and `uv` with the `pbxproj` package.
It does **not** build the UI — that requires Xcode.

---

## 5. Building the iPhone app (macOS)

```bash
git clone <this repo> beacon            # or copy ~/beacon/ios
cd beacon/ios
open Beacon.xcodeproj
```

1. Select the **Beacon** target → *Signing & Capabilities* → choose your team (or "None" for
   simulator-only runs). The bundle id is `dev.ericserver.beacon`; change it if it clashes.
2. Choose an iOS 17+ simulator (e.g. iPhone 16 Pro) and press Run.
3. First launch asks for: server address (`192.168.1.83:8091`), the contents of
   `data/secrets/ios.token`, and optionally the pin from `beacon tls show`.
   The token goes to the Keychain; nothing is stored until the server accepts it.
4. For a device build, accept the local-network permission prompt so the phone can reach the LAN
   address. (Installing on the phone is a separate project.)

### Regenerating the project file

Sources are added by `scripts/gen_xcodeproj.py` (the project is committed and reproducible):

```bash
python3 scripts/gen_xcodeproj.py
uv run --with pbxproj python scripts/validate_ios_project.py
```

### Unit tests and true UI screenshots (macOS)

```bash
cd ios
xcodebuild test -project Beacon.xcodeproj -scheme Beacon \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
  -only-testing:BeaconTests/ModelDecodingTests

# Four real screenshots of the running app against the live server:
mkdir -p ~/beacon/artifacts/snapshots
xcodebuild test -project Beacon.xcodeproj -scheme Beacon \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
  -only-testing:BeaconTests/SnapshotTests \
  BEACON_SNAPSHOT_DIR=$HOME/beacon/artifacts/snapshots \
  BEACON_SNAPSHOT_BASE_URL=https://192.168.1.83:8091 \
  BEACON_SNAPSHOT_TOKEN="$(cat ~/beacon/data/secrets/ios.token)"

# Attach those PNGs to a milestone on the server:
python3 ~/beacon/scripts/publish_snapshots.py --dir ~/beacon/artifacts/snapshots \
  --title "Native UI screens" --summary "Rendered on the iPhone 16 Pro simulator"
```

Without `BEACON_SNAPSHOT_BASE_URL/TOKEN` the test renders DEBUG fixture data (layout check only).
Screenshot tiles then show "Unavailable" — the test never fabricates images.

---

## 6. Updates, backup and restore

```bash
beacon backup                    # VACUUM INTO + secrets + TLS + screenshots under data/backups/<ts>
sudo scripts/install.sh          # idempotent redeploy after pulling changes
sudo systemctl restart beacon-api
```

Restore: stop the service, replace `data/beacon.sqlite` and the `secrets/`, `tls/`,
`screenshots/` directories from the backup, start the service, run `beacon doctor`.

---

## 7. Troubleshooting

For day-to-day procedures (backup/restore, token and TLS rotation, incidents, hardening posture)
see **`docs/OPERATIONS.md`**.

| Symptom | Fix |
|---|---|
| `beacon doctor` reports "API reachable" failed | `systemctl status beacon-api`; check port 8091 (`ss -tlnp`); certificate/key permissions (`data/tls` 0700, keys 0600) |
| App shows "The server certificate is not trusted" | Rebuild after `beacon tls init` so `ca.crt` is bundled; confirm the address matches a certificate SAN (`beacon tls show`) |
| 401 in the app | Token revoked or from another install: `beacon token create ios --scopes read,action,admin`, enter it again |
| Pi-hole "unreachable" | container running? `docker ps`; password file present? `beacon init` re-imports it |
| Agent "disconnected" | Cherry Studio not running, or the session ended; reopen it, then `beacon agent status` shows a live runtime pid |
| Interrupt answers 409 `no_runtime` | the session has no runtime process; use `mode=checkpoint` or resume the session |
| Docker metrics missing | `sudo -n /usr/local/lib/beacon/docker-read ps`; reinstall with `scripts/install.sh` |
| Screenshot returns 410 | older than 7 days — expected; the milestone text remains |
| `ffmpeg` capture fails | Service needs an active X session and read access to `~/.Xauthority`; `echo $DISPLAY` |
| Swift validation fails after editing sources | add the file to `scripts/gen_xcodeproj.py` lists, regenerate, re-run validation |

---

## 8. Security notes

* The API listens on the LAN address only; there is no port-forward and no reverse proxy.
* TLS 1.2+ with a private CA; the app pins the leaf SPKI when a pin is configured and fails
  closed if the CA bundle is missing.
* Tokens are hashed at rest, scoped, revocable, and never returned by any endpoint.
* The API process is not in the `docker` group and has no shell-execution endpoint. The only
  helpers it may run are the fixed-argv Docker reader, `sensors`, `nvidia-smi`, `ffmpeg` and the
  allow-listed `beacon` capture commands.
* Service controls require `admin` + a confirmation header, are rate limited, and are audited.
* Runtime endpoints (queue consumption, status publishing) require the `agent` token so UI tokens
  cannot consume instructions.
