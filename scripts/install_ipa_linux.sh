#!/usr/bin/env bash
# Sign and install Beacon on a physical iPhone from Linux, using AltServer-Linux-NG.
#
# The IPA itself is built by GitHub Actions (unsigned). This script downloads a pinned,
# checksum-verified AltServer binary, asks for a free Apple ID, signs the app with a
# development profile and installs it over USB.
#
# It never stores the Apple ID password. It is passed to AltServer as an argument (visible
# briefly in the process list) because AltServer has no stdin-password option.
#
#   ./scripts/install_ipa_linux.sh --ipa Beacon-unsigned.ipa
#
# Target device: iPhone 16e, iOS 26.2. AltServer-Linux-NG is the maintained fork that fixes
# iOS 26.4+/27 signing and the 2026 Apple ID sign-in changes; older AltServer-Linux v0.0.5 does
# not work on modern iOS.

set -euo pipefail
umask 077

VERSION="ng-2026-11-05"
BASE_URL="https://github.com/jaakkopalvaila/AltServer-Linux/releases/download/${VERSION}"
TOOLS_DIR="${BEACON_TOOLS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/beacon/tools}"
IPA=""
UDID=""
APPLE_ID=""
ALTSERVER=""

usage() {
    cat <<'EOF'
Usage: install_ipa_linux.sh [options]

  --ipa PATH          Unsigned IPA from the GitHub Actions artifact
                      (default: ./Beacon-unsigned.ipa)
  --udid UDID         Device UDID; detected automatically if exactly one iPhone is connected
  --apple-id EMAIL    Apple ID; prompted if omitted
  --altserver PATH    Use an existing AltServer-Linux-NG binary instead of downloading it
  -h, --help          Show this help

Environment:
  BEACON_TOOLS_DIR            Where to cache AltServer (default ~/.local/share/beacon/tools)
  ALTSERVER_ANISETTE_SERVER   Default https://new.ani.sidestore.io
  ALTSERVER_2FA               auto | sms | trusteddevice (default auto)

Requires: usbmuxd, libimobiledevice-utils (idevice_id/ideviceinfo), curl, unzip, sha256sum.
EOF
}

die() { echo "error: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --ipa) IPA="${2:-}"; shift 2 ;;
        --udid) UDID="${2:-}"; shift 2 ;;
        --apple-id) APPLE_ID="${2:-}"; shift 2 ;;
        --altserver) ALTSERVER="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        -*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
        *) IPA="$1"; shift ;;
    esac
done

[ -n "$IPA" ] || IPA="Beacon-unsigned.ipa"
[ -f "$IPA" ] || die "IPA not found: $IPA"
command -v unzip >/dev/null || die "unzip is required"
unzip -l "$IPA" | grep -q 'Payload/Beacon.app/Beacon' \
    || die "$IPA does not contain Payload/Beacon.app/Beacon"
unzip -l "$IPA" | grep -q 'Payload/Beacon.app/ca.crt' \
    || die "$IPA is missing the bundled CA (Payload/Beacon.app/ca.crt)"

command -v idevice_id >/dev/null \
    || die "idevice_id is missing. Install: sudo apt install usbmuxd libimobiledevice-utils"
command -v ideviceinfo >/dev/null \
    || die "ideviceinfo is missing. Install: sudo apt install usbmuxd libimobiledevice-utils"

if ! pgrep -x usbmuxd >/dev/null 2>&1 && ! systemctl is-active --quiet usbmuxd 2>/dev/null; then
    echo "warning: usbmuxd does not appear active; trying the device connection anyway." >&2
    echo "         If detection fails: sudo systemctl enable --now usbmuxd" >&2
fi

# Pick the device. Prefer an explicit UDID, otherwise require exactly one connected iPhone.
if [ -z "$UDID" ]; then
    mapfile -t DEVICES < <(idevice_id -l | sort -u)
    [ "${#DEVICES[@]}" -gt 0 ] || die "no iPhone detected. Unlock it, connect USB, tap Trust, then retry."
    if [ "${#DEVICES[@]}" -gt 1 ]; then
        echo "Multiple devices detected; pass --udid explicitly:" >&2
        printf '  %s\n' "${DEVICES[@]}" >&2
        exit 1
    fi
    UDID="${DEVICES[0]}"
fi

IOS_VERSION="$(ideviceinfo -u "$UDID" -k ProductVersion 2>/dev/null || true)"
PRODUCT_TYPE="$(ideviceinfo -u "$UDID" -k ProductType 2>/dev/null || true)"
echo "Device: ${PRODUCT_TYPE:-unknown} · iOS ${IOS_VERSION:-unknown} · UDID ${UDID:0:8}…"
case "${IOS_VERSION%%.*}" in
    1[7-9]|2[0-9]) ;;
    ''|*) echo "warning: could not confirm iOS 17+; Beacon requires iOS 17 or newer" >&2 ;;
esac

if [ -n "$ALTSERVER" ]; then
    [ -x "$ALTSERVER" ] || die "--altserver is not executable: $ALTSERVER"
else
    case "$(uname -m)" in
        x86_64)
            ASSET="AltServer-x86_64"
            SHA256="8d34e45ce68801ef93be25d304efb424a2325341be5235d651c36d118151a29a"
            ;;
        aarch64|arm64)
            ASSET="AltServer-aarch64"
            SHA256="f6651711241685809ba01c24c893a2fb3061e8973c81ceb6605f91050ae2cbd2"
            ;;
        *) die "unsupported CPU architecture: $(uname -m) (x86_64 or aarch64 required)" ;;
    esac
    ALTSERVER="$TOOLS_DIR/$ASSET"
    if [ ! -x "$ALTSERVER" ]; then
        mkdir -p "$TOOLS_DIR"
        TMP="$ALTSERVER.part"
        echo "Downloading AltServer-Linux-NG ${VERSION} ($ASSET)…"
        curl -fL --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 20 \
            -o "$TMP" "$BASE_URL/$ASSET"
        echo "$SHA256  $TMP" | sha256sum -c - >/dev/null \
            || { rm -f "$TMP"; die "AltServer checksum verification failed"; }
        chmod 0755 "$TMP"
        mv "$TMP" "$ALTSERVER"
    fi
    echo "$SHA256  $ALTSERVER" | sha256sum -c - >/dev/null \
        || die "cached AltServer checksum mismatch; remove $ALTSERVER and retry"
fi

if [ -z "$APPLE_ID" ]; then
    read -r -p "Apple ID (use a dedicated free account): " APPLE_ID
fi
[ -n "$APPLE_ID" ] || die "Apple ID is required"

if [ ! -t 0 ]; then
    die "a terminal is required for the Apple ID password and two-factor prompt"
fi
read -r -s -p "Apple ID password: " PASSWORD
echo
[ -n "$PASSWORD" ] || die "password is empty"
trap 'unset PASSWORD' EXIT

cat <<EOF

About to sign and install:
  IPA:      $IPA
  Device:   $UDID
  Apple ID: $APPLE_ID
  AltServer: $ALTSERVER

Free Apple ID provisioning expires after 7 days. The app can be renewed by running this
script again. Use a dedicated free Apple ID; repeated failed sign-ins can lock the account.

EOF
read -r -p "Continue? [y/N] " ANSWER
case "$ANSWER" in y|Y|yes|YES) ;; *) echo "cancelled"; exit 0 ;; esac

# No password is written to a file or log. AltServer reads the 2FA code from the terminal.
ALTSERVER_ANISETTE_SERVER="${ALTSERVER_ANISETTE_SERVER:-https://new.ani.sidestore.io}" \
ALTSERVER_ANISETTE_PROTOCOL="${ALTSERVER_ANISETTE_PROTOCOL:-v3}" \
ALTSERVER_2FA="${ALTSERVER_2FA:-auto}" \
"$ALTSERVER" -u "$UDID" -a "$APPLE_ID" -p "$PASSWORD" "$IPA"

echo
echo "Install command finished. If Beacon is on the Home Screen, open it and allow Local Network."
echo "The free profile expires in ~7 days; rerun this script to renew."
