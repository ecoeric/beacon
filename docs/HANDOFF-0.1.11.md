# Beacon 0.1.11 handoff — writeable Chats + fixes

Commit: `5fcabed` (feature commit `11f9b30`) · 2026-11-14

## What changed

- **Chats are writeable.** The transcript composer posts to
  `POST /api/v1/agent/sessions/{id}/messages`. The backend writes one accepted user row into
  Cherry Studio's own durable delivery queue, so Cherry runs a normal turn and the reply appears
  in the same transcript. `BEACON_CHAT_WRITE=1` in `deploy/beacon.env` enables it; `0` keeps
  Cherry strictly read-only and falls back to Beacon's queue.
- **Old queued messages now send.** `POST /agent/messages` and `/agent/continue` forward to
  Cherry immediately; a 20-second API sweep forwards pre-existing pending rows. Forwarding is
  idempotent per queue id and leaves the row pending when Cherry is closed/busy.
- **Minecraft CPU is honest.** The card shows `cpu_percent_of_total` (host-wide) and the detail
  shows the process figure with `100% = 1 core` (for example 66.7% process = 5.6% host).
- **KSP / Luna details are live.** Name, Career mode, players, vessels, UDP 8800, uptime,
  memory, password/mod-control and warp are read from `http://127.0.0.1:8900`. The stale
  "sandbox" description was corrected to Career.
- **Decoding fix.** `cpuPercentOfTotal` and `luna` no longer have `= nil` defaults, so `Decodable`
  actually reads them; the Minecraft `CodingKeys` entry was added.
- **Chat freshness.** Session list refreshes every 10 s, transcript every 5 s, and immediately
  after a send. Reasoning/tool-only/raw `{"parts":...}` rows are filtered.
- **Composer layout fix.** Removed `safeAreaInset` / `overlay(alignment:)`; the composer is a
  normal child below the scroll view, which also fixed the Swift mock-typecheck failure.
- **Queue schema v2** adds `agent_message.forward` (default 1), so smoke tests and checkpoint-only
  callers can opt out (`"forward": false`); existing databases migrate on startup.

## Verification

| Check | Result |
|---|---|
| `cd backend && .venv/bin/python -m pytest -q` | **164 passed** |
| `backend/.venv/bin/python scripts/smoke_test.py` | **58 checks passed** |
| `scripts/validate_ios.sh` | **passed**; 20 app + 2 test Swift files typecheck, 21 app sources, project structure |
| `backend/.venv/bin/python scripts/check_openapi_drift.py` | **39 paths, up to date** |
| `beacon doctor` | **all checks passed**, schema 2 |
| live summary | MC `running/online`, CPU total 5.6% at 66.7% process; Luna `running`, Career, UDP listening |
| live chat endpoint | returned `delivered=true, mode=cherry`; the row was visible to Cherry and locked as an in-flight Session delivery |

## Not done / caveats

- **The new IPA has not been built.** GitHub push is blocked on this host: HTTPS has no
  credentials and no SSH key is configured. The last built IPA is still `a7a8021`.
- **New chat creation** from the phone is still not implemented; sending to existing chats is.
- The app still polls rather than using push.
- Chat writes depend on Cherry Studio's schema (one compatibility integration). Failures fall
  back to Beacon's queue instead of losing the message. Set `BEACON_CHAT_WRITE=0` to roll back.

## Finish on a machine with GitHub credentials

```bash
cd ~/beacon
git push origin master                 # triggers .github/workflows/ios-build.yml
# download Beacon-unsigned-ipa artifact, then:
scripts/install_ipa_linux.sh --ipa ~/Downloads/Beacon-unsigned.ipa --check
scripts/install_ipa_linux.sh --ipa ~/Downloads/Beacon-unsigned.ipa
```
