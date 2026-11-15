#!/usr/bin/env bash
# One-time SideStore bootstrap from Linux over USB, using AltServer-Linux-NG.
#
# SideStore is not on the App Store. This installs the official unsigned SideStore IPA from
# GitHub with a free Apple ID, exactly like the Beacon fallback installer. It never writes the
# password to disk; AltServer needs it as an argv value, so it is briefly visible in the process
# list (same limitation as scripts/install_ipa_linux.sh).
#
#   ./scripts/install_sidestore_linux.sh
#   ./scripts/install_sidestore_linux.sh --check
#
# After this finishes, on the iPhone:
#   Settings -> General -> VPN & Device Management -> trust your Apple ID developer app
#   Settings -> Privacy & Security -> Developer Mode -> on -> restart
#   Open LocalDevVPN -> Connect -> open SideStore -> sign in -> refresh SideStore
set -euo pipefail
umask 077

SIDESTORE_VERSION="0.7.0-alpha"
SIDESTORE_URL="https://github.com/SideStore/SideStore/releases/download/${SIDESTORE_VERSION}/SideStore.ipa"
SIDESTORE_SHA256="e334f86e6ceeab2e0d886c07611246533f474bb18838cf13ebc09ed1f0d622b5"
ALTSERVER_VERSION="ng-2026-11-05"
ALTSERVER_BASE="https://github.com/jaakkopalvaila/AltServer-Linux/releases/download/${ALTSERVER_VERSION}"
TOOLS_DIR="${BEACON_TOOLS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/beacon/tools}"
IPA=""
UDID=""
APPLE_ID=""
ALTSERVER=""
CHECK_ONLY=0

usage() {
    cat <<'EOF'
Usage: install_sidestore_linux.sh [options]

  --ipa PATH          Existing SideStore.ipa (default: cached download)
  --udid UDID         Device UDID; detected automatically if exactly one iPhone is connected
  --apple-id EMAIL    Apple ID; prompted if omitted
  --altserver PATH    Existing AltServer-Linux-NG binary
  --check             Verify IPA, device and tools, then exit before the password prompt
  -h, --help          Show help

Environment:
  BEACON_TOOLS_DIR              Cache directory (default ~/.local/share/beacon/tools)
  ALTSERVER_ANISETTE_SERVER     Default https://new.ani.sidestore.io
  ALTSERVER_2FA                 auto | sms | trusteddevice (default auto)
EOF
}

die() { echo "error: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --ipa) IPA="${2:-}"; shift 2 ;;
        --udid) UDID="${2:-}"; shift 2 ;;
        --apple-id) APPLE_ID="${2:-}"; shift 2 ;;
        --altserver) ALTSERVER="${2:-}"; shift 2 ;;
        --check) CHECK_ONLY=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

mkdir -p "$TOOLS_DIR"
if [ -z "$IPA" ]; then
    IPA="$TOOLS_DIR/SideStore-${SIDESTORE_VERSION}.ipa"
    if [ ! -f "$IPA" ]; then
        echo "Downloading SideStore ${SIDESTORE_VERSION}…"
        curl -fL --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 20 -o "$IPA.part" "$SIDESTORE_URL"
        echo "$SIDESTORE_SHA256  $IPA.part" | sha256sum -c - >/dev/null \
            || { rm -f "$IPA.part"; die "SideStore IPA checksum verification failed"; }
        mv "$IPA.part" "$IPA"
    fi
fi
[ -f "$IPA" ] || die "SideStore IPA not found: $IPA"
echo "$SIDESTORE_SHA256  $IPA" | sha256sum -c - >/dev/null \
    || die "SideStore IPA checksum mismatch: $IPA"
IPA_LIST="$(mktemp)"
trap 'rm -f "$IPA_LIST"' EXIT
unzip -Z1 "$IPA" > "$IPA_LIST"
grep -qx 'Payload/SideStore.app/SideStore' "$IPA_LIST" \
    || die "$IPA does not contain Payload/SideStore.app/SideStore"
rm -f "$IPA_LIST"
trap - EXIT

command -v idevice_id >/dev/null || die "idevice_id is missing (install libimobiledevice-utils)"
command -v ideviceinfo >/dev/null || die "ideviceinfo is missing (install libimobiledevice-utils)"
command -v idevicepair >/dev/null || die "idevicepair is missing (install libimobiledevice-utils)"

if [ -z "$UDID" ]; then
    mapfile -t DEVICES < <(idevice_id -l | sort -u)
    [ "${#DEVICES[@]}" -gt 0 ] || die "No iPhone detected. Unlock it, reconnect USB, tap Trust, then retry."
    [ "${#DEVICES[@]}" -eq 1 ] || { printf 'Multiple devices; pass --udid:\n'; printf '  %s\n' "${DEVICES[@]}"; exit 1; }
    UDID="${DEVICES[0]}"
fi
idevicepair -u "$UDID" validate >/dev/null 2>&1 \
    || die "The iPhone is not paired. Unlock it, reconnect USB, tap Trust, then retry."
PRODUCT="$(ideviceinfo -u "$UDID" -k ProductType 2>/dev/null || echo unknown)"
IOS="$(ideviceinfo -u "$UDID" -k ProductVersion 2>/dev/null || echo unknown)"
echo "Device: ${PRODUCT} · iOS ${IOS} · UDID ${UDID:0:8}…"

if [ -n "$ALTSERVER" ]; then
    [ -x "$ALTSERVER" ] || die "--altserver is not executable: $ALTSERVER"
else
    case "$(uname -m)" in
        x86_64) ASSET="AltServer-x86_64"; SHA="8d34e45ce68801ef93be25d304efb424a2325341be5235d651c36d118151a29a" ;;
        aarch64|arm64) ASSET="AltServer-aarch64"; SHA="f6651711241685809ba01c24c893a2fb3061e8973c81ceb6605f91050ae2cbd2" ;;
        *) die "unsupported CPU architecture: $(uname -m)" ;;
    esac
    ALTSERVER="$TOOLS_DIR/$ASSET"
    if [ ! -x "$ALTSERVER" ]; then
        echo "Downloading AltServer-Linux-NG ${ALTSERVER_VERSION}…"
        curl -fL --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 20 -o "$ALTSERVER.part" "$ALTSERVER_BASE/$ASSET"
        echo "$SHA  $ALTSERVER.part" | sha256sum -c - >/dev/null \
            || { rm -f "$ALTSERVER.part"; die "AltServer checksum verification failed"; }
        chmod 0755 "$ALTSERVER.part"; mv "$ALTSERVER.part" "$ALTSERVER"
    fi
    echo "$SHA  $ALTSERVER" | sha256sum -c - >/dev/null || die "cached AltServer checksum mismatch"
fi

if [ "$CHECK_ONLY" = 1 ]; then
    echo "preflight: SideStore IPA, device pairing and AltServer are OK."
    exit 0
fi

[ -n "$APPLE_ID" ] || read -r -p "Apple ID (use a dedicated free account): " APPLE_ID
[ -n "$APPLE_ID" ] || die "Apple ID is required"
[ -t 0 ] || die "run this in a terminal so the password and 2FA prompts work"
read -r -s -p "Apple ID password: " PASSWORD
echo
[ -n "$PASSWORD" ] || die "password is empty"
trap 'unset PASSWORD' EXIT

cat <<EOF

About to install SideStore:
  IPA:       $IPA
  Device:    $UDID
  Apple ID:  $APPLE_ID
  AltServer: $ALTSERVER

The free development profile expires after 7 days; SideStore refreshes its own apps.
EOF
read -r -p "Continue? [y/N] " ANSWER
case "$ANSWER" in y|Y|yes|YES) ;; *) echo "cancelled"; exit 0 ;; esac

cd "$TOOLS_DIR"
ALTSERVER_ANISETTE_SERVER="${ALTSERVER_ANISETTE_SERVER:-https://new.ani.sidestore.io}" \
ALTSERVER_ANISETTE_PROTOCOL="${ALTSERVER_ANISETTE_PROTOCOL:-v3}" \
ALTSERVER_2FA="${ALTSERVER_2FA:-auto}" \
"$ALTSERVER" -u "$UDID" -a "$APPLE_ID" -p "$PASSWORD" "$IPA"

cat <<'EOF'

Install command finished.

On the iPhone:
  1. Settings -> General -> VPN & Device Management -> trust your Apple ID developer app.
  2. Settings -> Privacy & Security -> Developer Mode -> on -> restart.
  3. Open LocalDevVPN -> Connect.
  4. Open SideStore -> sign in with the same Apple ID -> My Apps -> tap 7 DAYS to refresh.
  5. Then add the Beacon source and install Beacon.
EOF
