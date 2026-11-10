#!/bin/bash
# Restore drill: serve a Beacon backup from a throwaway data directory and verify it.
#
#   sudo -u eric scripts/restore_drill.sh /home/eric/beacon/data/backups/20261110T....
#
# Checks, over real TLS with the restored token:
#   1. /health returns ok and reports the database ok,
#   2. the milestone list is non-empty and screenshots are described,
#   3. one screenshot is served byte-for-byte from the restored store,
#   4. /whoami accepts the restored token.
#
# The live service is not touched: a second Uvicorn instance is started on a free loopback port
# and stopped on exit. Exit code 0 means the archive is restorable.
set -euo pipefail

PROJECT="/home/eric/beacon"
BACKEND="$PROJECT/backend"
PY="$BACKEND/.venv/bin/python"

if [ "$#" -lt 1 ]; then
    echo "usage: $0 <backup-directory>" >&2
    exit 2
fi
BACKUP="$1"
for required in beacon.sqlite secrets/cli.token tls/ca.crt tls/server.crt tls/server.key; do
    if [ ! -e "$BACKUP/$required" ]; then
        echo "backup is missing $required" >&2
        exit 2
    fi
done

TMP="$(mktemp -d /tmp/beacon-restore-XXXXXX)"
PORT="$("$PY" - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
PID=""
cleanup() {
    if [ -n "$PID" ]; then kill "$PID" 2>/dev/null || true; fi
    rm -rf "$TMP"
}
trap cleanup EXIT

cp -a "$BACKUP"/. "$TMP"/
TOKEN="$(cat "$TMP/secrets/cli.token")"
CA="$TMP/tls/ca.crt"

cd "$BACKEND"
env \
    BEACON_DATA_DIR="$TMP" \
    BEACON_BIND=127.0.0.1 \
    BEACON_PORT="$PORT" \
    BEACON_TLS_CERT="$TMP/tls/server.crt" \
    BEACON_TLS_KEY="$TMP/tls/server.key" \
    BEACON_PIHOLE_PASSWORD_FILE="$TMP/secrets/pihole.password" \
    BEACON_DOCKER_READ_HELPER=/nonexistent/docker-read \
    HOME=/home/eric \
    "$PY" -m uvicorn beacon.asgi:app \
        --host 127.0.0.1 --port "$PORT" \
        --ssl-certfile "$TMP/tls/server.crt" --ssl-keyfile "$TMP/tls/server.key" \
        --no-server-header >"$TMP/restore.log" 2>&1 &
PID=$!

BASE="https://127.0.0.1:$PORT/api/v1"
ready=0
for _ in $(seq 1 60); do
    if curl -s --cacert "$CA" -o "$TMP/health.json" "$BASE/health" 2>/dev/null; then ready=1; break; fi
    sleep 0.25
done
if [ "$ready" -ne 1 ]; then
    echo "restored instance did not become ready:" >&2
    tail -20 "$TMP/restore.log" >&2
    exit 1
fi

STATUS="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$TMP/health.json")"
DB_STATUS="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["database"])' "$TMP/health.json")"
[ "$STATUS" = "ok" ] || { echo "health status is $STATUS" >&2; exit 1; }
[ "$DB_STATUS" = "ok" ] || { echo "database status is $DB_STATUS" >&2; exit 1; }

curl -s --cacert "$CA" -H "Authorization: Bearer $TOKEN" -o "$TMP/milestones.json" "$BASE/milestones"
read -r MILESTONES SHOTS URL <<EOF
$("$PY" - "$TMP/milestones.json" <<'PY'
import json, sys
rows = json.load(open(sys.argv[1]))
shots = sum(len(row["screenshots"]) for row in rows)
url = next((row["screenshots"][0]["url"] for row in rows if row["screenshots"]), "")
print(len(rows), shots, url)
PY
)
EOF

[ "$MILESTONES" -ge 1 ] || { echo "no milestones in the restored database" >&2; exit 1; }
[ -n "$URL" ] || { echo "no live screenshots in the restored database" >&2; exit 1; }
BYTES="$(curl -s --cacert "$CA" -H "Authorization: Bearer $TOKEN" -o "$TMP/shot.png" -w '%{http_code} %{size_download}' "$BASE${URL#/api/v1}" 2>/dev/null || true)"
CODE="${BYTES%% *}"
SIZE="${BYTES##* }"
[ "$CODE" = "200" ] || { echo "screenshot fetch returned $CODE" >&2; exit 1; }
[ "$SIZE" -gt 1000 ] || { echo "screenshot is implausibly small ($SIZE bytes)" >&2; exit 1; }

WHOAMI="$(curl -s --cacert "$CA" -H "Authorization: Bearer $TOKEN" "$BASE/whoami" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
[ "$WHOAMI" = "cli" ] || { echo "restored token identity is $WHOAMI" >&2; exit 1; }

echo "✓ restore drill passed"
echo "  health: ok · database: ok"
echo "  milestones: $MILESTONES · live screenshots: $SHOTS"
echo "  screenshot served: $SIZE bytes"
echo "  token identity: $WHOAMI"
echo "  restored instance: 127.0.0.1:$PORT (stopped)"
