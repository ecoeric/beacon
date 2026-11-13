# Sign and install Beacon on iPhone from Linux

This is the Linux-only path: **GitHub Actions builds an unsigned IPA**, and this host signs and
installs it with a free Apple ID using **AltServer-Linux-NG**. No Windows and no Mac are required
for this step.

> The IPA from CI is **unsigned**. It cannot be installed directly. `scripts/install_ipa_linux.sh`
> signs it with a development profile and installs it over USB.

Target device: **iPhone 16e, iOS 26.2**. The app deployment target is iOS 17.0.

**Compatibility note:** the maintained NG fork documents iOS 26.4+/27 signing fixes and was tested
by its maintainer on iOS 27.0, not specifically 26.2. iOS 26.2 is expected to work, but this exact
combination has not been verified on this host (no iPhone is attached). If it fails, capture the
AltServer error and stop after one or two attempts rather than retrying repeatedly.

---

## 1. Prerequisites

On this Linux host:

```bash
sudo apt update
sudo apt install -y usbmuxd libimobiledevice-utils curl unzip
sudo systemctl restart usbmuxd
```

Check that the tools exist:

```bash
idevice_id --help
ideviceinfo --version
```

Install the `libimobiledevice-utils` package if either command is missing.

On the iPhone:

1. Unlock it.
2. Enable **Developer Mode**: **Settings → Privacy & Security → Developer Mode → On**, then
   restart and confirm. Free-provisioned apps will not launch without it.
3. Connect it by USB.
4. Tap **Trust** when the computer prompt appears.
5. Leave it unlocked until the install finishes.

Verify the device is visible:

```bash
idevice_id -l
ideviceinfo -k ProductVersion
```

You should see one UDID and an iOS version. If not, see Troubleshooting.

---

## 2. Get the IPA from GitHub Actions

The workflow is `.github/workflows/ios-build.yml`. Its **Unsigned IPA (device, arm64)** job uploads
an artifact named:

```
Beacon-unsigned-ipa
```

Download and unzip it. You need:

- `Beacon-unsigned.ipa`
- `Beacon-unsigned.ipa.sha256`
- `build-info.txt`
- `build.log` (if something went wrong)

Verify the checksum before signing:

```bash
sha256sum -c Beacon-unsigned.ipa.sha256
unzip -l Beacon-unsigned.ipa | grep -E 'Payload/Beacon.app/(Beacon|ca.crt)'
```

The IPA is built for **arm64 device**, not the simulator. It contains the app and the bundled
private CA (`ca.crt`); the workflow fails if the CA is missing.

---

## 3. Sign and install

From the repository root, first run the preflight (no password, no install):

```bash
./scripts/install_ipa_linux.sh --check --ipa /path/to/Beacon-unsigned.ipa
```

If that passes, sign and install:

```bash
./scripts/install_ipa_linux.sh --ipa /path/to/Beacon-unsigned.ipa
```

The script:

1. Downloads the pinned **AltServer-Linux-NG** release (`ng-2026-11-05`) and verifies its SHA-256.
2. Detects the connected iPhone (or accepts `--udid`).
3. Asks for your Apple ID and password.
4. Lets AltServer request the two-factor code.
5. Signs the app with a free development profile and installs it.

It never writes the password to disk or a log. The password is passed to AltServer as a command
argument, so it is briefly visible to `ps`; run this on a trusted host. Use a dedicated free Apple
ID, not your primary account.

### Two-factor codes

- If the account has a trusted Apple device, the code appears there.
- If it has no trusted device, AltServer can use SMS. If the automatic choice fails, run:

  ```bash
  ALTSERVER_2FA=sms ./scripts/install_ipa_linux.sh --ipa /path/to/Beacon-unsigned.ipa
  ```

If sign-in fails once or twice, **stop**. Repeated failures can lock the Apple ID. Read the error
and fix the cause before retrying; do not loop.

### First launch on the iPhone

Open Beacon and enter:

| Field | Value |
|---|---|
| Server | `192.168.1.83:8091` |
| Token | contents of `~/beacon/data/secrets/ios.token` on the server |
| Pin | blank first; optionally `beacon tls show` → `spki_pin` |

Allow the **Local Network** permission. The app contains the private CA, so do not install a CA
profile on the phone. The server certificate must be valid for `192.168.1.83`.

---

## 4. Free Apple ID limits

- The provisioning profile expires after **7 days**.
- The app then stops opening until it is re-signed.
- Renew by running the same install command again; the app data is preserved when the bundle id
  and signing identity are unchanged.
- Up to **3 apps** per device.
- No paid capabilities such as push notifications. Beacon does not use APNs.

For a permanent install, use a paid Apple Developer account and TestFlight (internal testing,
builds expire after 90 days). That still needs a signed build, but it removes the weekly renewal.

---

## 5. If USB does not work: Wi-Fi with netmuxd

AltServer-Linux-NG was tested by its maintainer over Wi-Fi with **netmuxd** on iOS 27. USB uses the
same libimobiledevice/usbmuxd path, but the fork’s release notes list USB as “not tested”. If USB
detection fails:

1. Install the latest `netmuxd` release (x86_64 Linux tarball).
2. Stop the system `usbmuxd` service.
3. Run `netmuxd` so it also advertises network devices.
4. Keep the iPhone on the same Wi-Fi and paired over USB at least once.
5. Point AltServer at netmuxd with `USBMUXD_SOCKET_ADDRESS` if needed, then rerun the install.

This is more moving parts. Try USB first; only switch if `idevice_id -l` cannot see the phone.

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `no iPhone detected` | Unlock, reconnect USB, tap Trust; check `idevice_id -l`; ensure `usbmuxd` is running |
| `usbmuxd is not running` | `sudo systemctl restart usbmuxd` |
| `idevice_id: command not found` | `sudo apt install libimobiledevice-utils` |
| `Unable to sign you in` / `-80043`, `-80045`, `-80046` | Use the pinned NG release; use the default `https://new.ani.sidestore.io`; stop after one or two failures to avoid an account lock |
| `Incorrect Apple ID or password` | Use the Apple ID password, not the device passcode; if AltServer asks for an app-specific password, create one at appleid.apple.com |
| `App installs but crashes on launch` | Check Developer Mode. If it is on, this is the iOS 26.4+ signing bug fixed in AltServer-Linux-NG; do not use old AltServer v0.0.5. Reinstall with the current script |
| `Developer Mode disabled` warning on first launch | Settings → Privacy & Security → Developer Mode, restart, confirm |
| `Failed to register bundle identifier` / bundle id unavailable | Change `APP_BUNDLE_ID` in `scripts/gen_xcodeproj.py`, regenerate the project, rebuild in CI, and rerun. Or choose a unique id in Xcode before building |
| `ApplicationVerificationFailed` | Free profile/bundle-id or signing issue; recheck the Apple ID and reinstall |
| App expires after a week | Expected free-provisioning limit; rerun the install |
| `The server certificate is not trusted` | The address must match a certificate SAN; check `beacon tls show`; rebuild if the CA was regenerated |
| Cannot reach the server | Same Wi-Fi, VPN off, port 8091 reachable, router client isolation off |

**Do not use AltServer-Linux v0.0.5** from the old upstream release: it fails on modern iOS because
its ldid signature is rejected and its Apple sign-in is outdated. This script pins the maintained
NG fork.

---

## 7. Security notes

- The Beacon server token is entered in the app and stored in the iOS Keychain. It is not in the
  IPA, the workflow, or this repository.
- The workflow uses `permissions: contents: read` and contains no Apple ID, password, token or
  signing certificate.
- The signed app still validates the server against the bundled private CA; signing does not
  weaken that check.
- The AltServer binary is a third-party static build. The script pins the release and verifies its
  SHA-256 before running it.
- Free provisioning is for personal use. Do not distribute the signed app or the provisioning
  profile.

---

## 8. What this path does not solve

- It does not create a permanent signed IPA. Every free-account install expires after 7 days.
- It does not install on a device running an iOS version older than 17 (Beacon’s minimum).
- It does not replace the real Xcode compile: GitHub Actions provides that. If the CI build fails,
  fix the iOS code/project first; signing cannot rescue a failed build.
- It does not require Windows. If USB detection fails, the netmuxd Wi-Fi route is the fallback; a
  Windows PC with Sideloadly is not required.
