#!/bin/bash
# Idempotent deployment of the Beacon dashboard backend on this host.
#
#   sudo scripts/install.sh
#
# Steps: python deps -> read-only docker helper + sudoers -> TLS/tokens -> systemd units.
# Existing services (Pi-hole, Minecraft, Caddy, WinLab, Cherry Studio) are never touched.
set -euo pipefail

PROJECT="/home/eric/beacon"
BACKEND="$PROJECT/backend"
VENV="$BACKEND/.venv"
PY="$VENV/bin/python"
ENV_FILE="$PROJECT/deploy/beacon.env"

# The script runs under sudo; keep the operator's home for venv, tokens and the CLI link.
if [ "$(id -u)" -eq 0 ]; then
    USER_HOME="/home/eric"
else
    USER_HOME="$HOME"
fi
export HOME="$USER_HOME"
UV="$USER_HOME/.cherrystudio/bin/uv"

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

step "1/6 python environment"
if [ ! -x "$PY" ]; then
    "$UV" venv --python 3.13 "$VENV"
fi
"$UV" pip install --python "$PY" -q -r "$BACKEND/requirements.lock"
"$PY" -c "import fastapi, uvicorn, PIL, cryptography, httpx; print('deps ok')"

step "2/6 privileged docker snapshot timer"
sudo install -d -o root -g root -m 0755 /usr/local/lib/beacon
sudo install -o root -g root -m 0755 "$PROJECT/deploy/docker-snapshot" /usr/local/lib/beacon/docker-snapshot
# Remove the previous sudo-based helper: the API no longer has a privileged path.
sudo rm -f /usr/local/lib/beacon/docker-read /etc/sudoers.d/beacon-docker-read
sudo install -o root -g root -m 0644 "$PROJECT/deploy/beacon-docker.service" /etc/systemd/system/beacon-docker.service
sudo install -o root -g root -m 0644 "$PROJECT/deploy/beacon-docker.timer" /etc/systemd/system/beacon-docker.timer
sudo systemctl daemon-reload
sudo systemctl enable --now beacon-docker.timer
sudo systemctl start beacon-docker.service
for _ in $(seq 1 30); do
    if [ -f /run/beacon/docker.json ]; then break; fi
    sleep 0.5
done
if [ -f /run/beacon/docker.json ]; then
    echo "docker snapshot: $(python3 -c 'import json;print(len(json.load(open("/run/beacon/docker.json"))["containers"]))') container(s)"
else
    echo "docker snapshot not written yet (will catch up on the next timer run)" >&2
fi

step "3/6 systemd units"
sudo install -o root -g root -m 0644 "$PROJECT/deploy/beacon-api.service" /etc/systemd/system/beacon-api.service
sudo install -o root -g root -m 0644 "$PROJECT/deploy/beacon-retention.service" /etc/systemd/system/beacon-retention.service
sudo install -o root -g root -m 0644 "$PROJECT/deploy/beacon-retention.timer" /etc/systemd/system/beacon-retention.timer
sudo systemctl daemon-reload
sudo systemctl enable --now beacon-retention.timer
echo "retention timer: $(systemctl is-active beacon-retention.timer)"

step "4/6 TLS material and tokens"
chmod +x "$PROJECT/bin/beacon"
mkdir -p "$USER_HOME/.local/bin"
ln -sf "$PROJECT/bin/beacon" "$USER_HOME/.local/bin/beacon"
sudo ln -sf "$PROJECT/bin/beacon" /usr/local/bin/beacon
# Run the CLI as the operator, never as root: tokens, keys and the SQLite file must be
# owned by the account the service runs as.
if [ "$(id -u)" -eq 0 ]; then
    runuser -u eric -- "$PROJECT/bin/beacon" init
else
    "$PROJECT/bin/beacon" init
fi
sudo chown -R eric:eric "$PROJECT/data" "$PROJECT/ios/Beacon/Resources" 2>/dev/null || true

step "5/6 API service"
sudo systemctl enable beacon-api.service
sudo systemctl restart beacon-api.service
set -a; . "$ENV_FILE"; set +a
ready=0
for _ in $(seq 1 60); do
    if systemctl is-active --quiet beacon-api.service && \
       curl -s -o /dev/null --cacert "$BEACON_DATA_DIR/tls/ca.crt" \
            "https://$BEACON_BIND:$BEACON_PORT/api/v1/health"; then
        ready=1
        break
    fi
    sleep 0.5
done
if [ "$ready" -ne 1 ]; then
    echo "beacon-api did not become healthy:" >&2
    sudo journalctl -u beacon-api.service -n 40 --no-pager >&2
    exit 1
fi
sudo journalctl -u beacon-api.service -n 5 --no-pager || true

step "6/6 verification"
if [ "$(id -u)" -eq 0 ]; then
    runuser -u eric -- "$PROJECT/bin/beacon" doctor || {
        echo "doctor reported problems; see above" >&2
        exit 1
    }
else
    "$PROJECT/bin/beacon" doctor || {
        echo "doctor reported problems; see above" >&2
        exit 1
    }
fi

cat <<EOF

Beacon is deployed.
  API          https://$BEACON_BIND:$BEACON_PORT/api/v1/health
  data         $BEACON_DATA_DIR
  secrets      $BEACON_DATA_DIR/secrets  (ios.token, agent.token, cli.token — 0600)
  CA cert      $BEACON_DATA_DIR/tls/ca.crt (copied into ios/Beacon/Resources/ca.crt)
  CLI          beacon doctor | beacon summary | beacon agent status
  retention    systemctl list-timers beacon-retention.timer

Copy the contents of data/secrets/ios.token into the app at first launch (it is stored in the
iOS Keychain). Never commit token files.
EOF
