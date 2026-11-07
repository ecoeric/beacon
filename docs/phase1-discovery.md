# Phase 1 — Environment discovery (verified 2026-11-07)

All facts below were verified directly on the host (`ericserver`) with shell/file inspection.
Nothing here is assumed from documentation.

## Host

| Item | Verified value | How |
|---|---|---|
| OS | Debian 13.6 (trixie), kernel 6.12.101+deb13-amd64, x86_64 | `/etc/os-release`, `uname -a` |
| CPU | Intel i5-9300H, 4c/8t, VT-x | `lscpu` |
| RAM / swap | 15.5 GiB / 12 GiB (≈2.5 GiB available at inspection) | `free -h` |
| Disk | `/` 220 G (156 G free), `/mnt/storage_hdd` 916 G (907 G free) | `df -hT` |
| GPU | NVIDIA TU117M GTX 1650 Mobile, driver exposes util/temp/VRAM/power | `lspci`, `nvidia-smi --query-gpu=...` |
| Temperature | `coretemp` package sensor (~39 °C idle), NVMe + ACPI sensors | `sensors` |
| LAN | `enp3s0` 192.168.1.83/24, gateway 192.168.1.254 | `ip -4 -o addr`, `ss` |
| Display server | X11 socket `:0` exists, `$DISPLAY` unset in tool shells | `ls /tmp/.X11-unix` |

Tooling: `python3 3.13.5`, `uv`, `bun`, `node` (mise shim — broken symlink chain for some
uses), `git`, `ffmpeg`, `openssl`, `zstd`, `xwd`, **no** Swift toolchain, **no** Xcode,
**no** macOS, **no** `sqlite3` CLI (Python `sqlite3` module used instead), **no** tmux/screen,
**no** RCON client.

## Already-running services that must not be disturbed

| Service | Facts |
|---|---|
| Pi-hole | Docker container `pihole`, image `pihole/pihole:2026.10.1`, healthy, DNS on `192.168.1.83:53` (TCP+UDP), web/API on `192.168.1.83:8080`; container env contains `FTLCONF_webserver_api_password`; volume `/opt/pihole/etc-pihole`; DHCP disabled |
| Minecraft | NeoForge 21.1.252 (MC 1.21.1), `~/Desktop/NeoForgeServer`, Java 21, `run.sh` → `user_jvm_args.txt` (`-Xmx8G -Xms2G`), ~9.7 GiB RSS, started manually in terminal `pts/1` (pid observed 34408), `enable-status=true`, `enable-rcon=false`, `enable-query=false`, 90 mods, no spark/TPS mod |
| Caddy | owns `:80`/`:443` |
| WinLab backend | `winlab-backend.service` on `192.168.1.83:8090` (FastAPI/SQLite, prior project — **reuse patterns, do not touch**) |
| Others | Immich `:2283` + internal Express `127.0.0.1:38967`, PostgreSQL `:5432`, Redis `:6379`, Ollama `:11434`, Samba `445/139`, CUPS `631`, playit.gg |

Free ports verified: **8091**, 8092, 8093, 8443, 9443. No firewall (INPUT ACCEPT).

## Agent runtime (the "active AI agent")

Cherry Studio 2.0.14 desktop app spawns a per-session **DSH runtime** child process:

```
/opt/Cherry Studio/CherryStudio \
  .../dsh-bridge/dist/runtime/bin.mjs \
  ~/.config/CherryStudio/Data/Agents/.dsh/compositions/<session-id>.<composition-id>.yml
```

Verified consequences:

1. **Runtime ↔ session mapping is deterministic** — the composition file name contains the
   session id, so a session's live runtime PID can be resolved from `/proc`.
2. **Persistent state lives in SQLite** `~/.config/CherryStudio/Data/cherrystudio.sqlite`
   (WAL). Relevant tables: `agent`, `agent_session`, `agent_session_message`
   (`role`, `data` JSON, `status in {pending,success,error,paused}`,
   `delivery_status in {accepted,delivering,consumed,failed}`, timestamps in ms).
   The currently running agent turn appears as an **assistant message with `status='pending'`** —
   a real, live busy signal, not a guess.
3. **Session transcript** is appended as `session.jsonl.zstd` per session
   (`Data/Agents/.dsh/sessions/<slug>/<session-id>/`), mtime = last activity.
4. **No local HTTP API** for Cherry Studio: probing `127.0.0.1:38967` proved it belongs to
   Immich (NestJS), not Cherry Studio; no Express routes exist for the app.
   There is no supported endpoint to inject a message into a conversation from outside.
5. **SIGINT/SIGTERM handling** in `bin.mjs` disposes the runtime fiber tree and exits
   (130/0). This is the direct, out-of-band way to stop the active execution system; the
   session journal on disk preserves work and the session is resumable.
6. `agent_session_message.delivery_*` columns exist for Cherry Studio's own cross-session
   messaging (`cherry-tools session_send`), but writing rows into the live app database from
   an external service was rejected: two writers on a WAL database owned by the UI is a
   correctness and data-integrity risk, and the app caches session state in memory.
7. No hook system (`hooks`, `SessionStart`, `AGENTS.md` loader) was found in the unpacked
   runtime modules → message delivery into the conversation must be **cooperative**
   (agent pulls at a safe checkpoint).

## Native iOS build environment

No Swift, Xcode, or macOS anywhere on this host, and Xcode cannot legally/practically run on
this Debian laptop. Therefore:

* The **complete Xcode project + Swift/SwiftUI sources** are authored and version controlled
  here; the build is performed later on a Mac (documented in `SETUP.md`).
* To avoid "untested source", the project is structured so that all pure logic
  (models, decoding, queue/status formatting, TLS pin computation inputs) lives in
  Foundation-only files that **do compile and run on Linux** with a Swift toolchain, and are
  exercised against the live backend.
* An Xcode **snapshot test target** renders the four key screens to PNG on a Mac, feeding the
  same milestone screenshot pipeline.

## Architecture decisions taken from these facts

| Decision | Rationale |
|---|---|
| New FastAPI service `beacon-api`, systemd, port **8091**, SQLite WAL, venv + pinned deps | Same proven shape as the existing WinLab backend; no new runtime dependencies; isolated from it |
| HTTPS with a locally generated ECDSA cert + **SPKI pinning** in the app | LAN-only server, no public CA; encrypted transport with explicit trust, no blind trust |
| Bearer tokens, SHA-256 at rest, scopes `read/action/admin/agent` | No secrets in the app; per-client revocation; agent-only endpoints separated from UI actions |
| Agent status = **snapshot pushed by the agent** + **read-only Cherry Studio DB/runtime evidence** | Single structured source of truth; no LLM calls, no fabrication; honest staleness |
| Message delivery = durable queue + **checkpoint pull** by the agent CLI | The runtime offers no injection API; queue semantics and ordering are enforced server-side |
| Interrupt = admin-scoped `SIGINT` to the resolved runtime PID (audited, rate-limited) + cooperative interrupt flag fallback | Direct signal to the execution system, bypasses the queue; journal preserves work |
| Milestone screenshots captured by a server-side capture service (text/API/X11/file sources), 7-day retention by dedicated systemd timer | Real artifacts only; automatic and path-confined deletion |
| Monitoring from `/proc`, `sensors`, `nvidia-smi`, read-only Docker wrapper, Pi-hole v6 API, Minecraft server-list ping + logs | Reuse existing facilities; no new monitoring stack |

## Verified integration contracts (used by the implementation)

* Pi-hole v6: `POST /api/auth {password}` → `session.sid`; then `GET /api/stats/summary`,
  `/api/dns/blocking`, `/api/stats/top_domains?blocked=true`, `/api/stats/top_clients`,
  `/api/info/system`; `POST /api/dns/blocking {blocking:"enabled"|"disabled"}`.
  Verified values at inspection: 35 933 queries, 5 186 blocked (14.43 %), blocking enabled.
* Minecraft server-list ping on `127.0.0.1:25565` returns version `1.21.1`, protocol 767,
  `players.online = 2` with sample names, MOTD `sussy pussy`, `enforcesSecureChat: true`.
* Cherry Studio DB read must be `file:...?mode=ro` (WAL-aware, no `immutable=1`), no writes.
