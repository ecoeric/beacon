# Install Beacon on your iPhone (beginner guide)

Beacon has two parts, and only one of them is not deployed yet:

| Part | State |
|---|---|
| `beacon-api` on `ericserver` | **Already running** at `https://192.168.1.83:8091` |
| Native iPhone app | **Never installed** — there is no App Store link; you build it once with your own Apple ID |

This guide is for a **personal install**, not App Store distribution. Nothing here signs or
installs the app automatically; you do the final Run from Xcode.

---

## The short version

**Borrow a Mac for 1–2 hours, open the project, press Run, then plug in your iPhone.**

A free Apple ID is enough. The app will work for **7 days**, after which you re-run it from Xcode
to renew it. If you want it permanently, see [TestFlight](#permanent-option-testflight) later.

You do **not** need to modify the server, install a CA profile on the phone, or use a paid account
for the first install.

---

## What you need

- An iPhone running **iOS 17 or newer** (Settings → General → About).
- A **Mac** with the current **Xcode** from the Mac App Store. Xcode is a large download
  (roughly 10–20 GB); start it early.
- Your **Apple ID** (the normal one you use on the iPhone). A free account is fine.
- A USB cable for the iPhone.
- The iPhone and the server on the **same Wi-Fi/LAN**.
- The iOS token from the server: `~/beacon/data/secrets/ios.token`.

> The token is a secret. Do not paste it into a chat, issue tracker, screenshot or git commit.
> The app stores it in the iOS Keychain.

---

## Step 1 — Get the project onto the Mac

Copy the `ios/` folder from `~/beacon/ios` to the Mac (USB drive, AirDrop, or the Samba share).
Keep the whole folder, especially:

- `ios/Beacon.xcodeproj`
- `ios/Beacon/Resources/ca.crt` (the private CA the app trusts)

Do not copy `ios/.build`; it is a Linux build cache and is not needed.

If the project file is ever missing, regenerate it on any machine with Python:

```bash
python3 scripts/gen_xcodeproj.py
```

---

## Step 2 — Open it and run the simulator first

1. Install and open **Xcode**.
2. Choose **File → Open** and select `ios/Beacon.xcodeproj`.
3. At the top, choose an **iPhone simulator** (for example “iPhone 16”) and press **Run** (▶).
4. The app opens on the simulator. On the setup screen enter:
   - **Server:** `192.168.1.83:8091`
   - **Token:** the contents of `ios.token`
   - **Pin:** leave blank for the first attempt
5. Allow the **Local Network** permission prompt.

If the dashboard appears, the app and server are working. This step needs no signing or iPhone.

---

## Step 3 — Sign and install on the iPhone

1. In Xcode: **Xcode → Settings → Accounts → +** and add your Apple ID.
2. In the project navigator select the **Beacon** project, then the **Beacon** target.
3. Open **Signing & Capabilities**:
   - Tick **Automatically manage signing**.
   - **Team:** choose your name (Personal Team).
4. Change **Bundle Identifier** from `dev.ericserver.beacon` to something unique to you, for
   example `com.yourname.beacon`. Free provisioning fails if the identifier is already taken.
   If Xcode also complains about the test bundle, give it a matching unique id too.
5. Connect the iPhone by USB. Unlock it and tap **Trust** on the phone.
6. On the iPhone enable **Developer Mode**:
   **Settings → Privacy & Security → Developer Mode → On**, then restart and confirm.
7. In Xcode choose your **iPhone** as the run destination and press **Run**.
8. The first launch may say “Untrusted Developer”. On the phone go to
   **Settings → General → VPN & Device Management → Developer App → Trust**.
9. Open Beacon and enter the same server, token and optional pin.

### Where to get the values

On `ericserver`:

```bash
cat ~/beacon/data/secrets/ios.token   # the token for the app
beacon tls show                        # SANs, validity, optional SPKI pin
```

Use the **iOS token**, not `cli.token` or `agent.token`.

The pin is optional. Leave it blank first. If you want the extra check, copy the `SPKI pin` value
exactly from `beacon tls show`.

---

## Free Apple ID limits

With a free Personal Team:

- The app expires after **7 days**; re-run from Xcode to renew it.
- Up to **3 apps** per device.
- Some capabilities (push notifications, associated domains, etc.) are unavailable. Beacon does
  not use APNs, so this does not matter here.

---

## Permanent option: TestFlight

If you want to install once and keep it for months, use Apple’s **TestFlight**:

1. Join the **Apple Developer Program** (99 USD/year).
2. Archive and upload the app from Xcode (or from CI with signing certificates).
3. In App Store Connect → TestFlight, add yourself as an **internal tester**.
4. Install TestFlight on the iPhone and accept the build.

Internal TestFlight does not need App Store review. Builds expire after 90 days. This is the
cleanest long-term route, but it costs money and is more setup than the free 7-day method.

---

## If you have no Mac at all

Be realistic about the options:

- **Cloud Mac** (MacinCloud, MacStadium, AWS EC2 Mac): you can build and run the simulator, but a
  remote Mac usually cannot plug into your physical iPhone. Not a simple install path.
- **GitHub Actions** (`.github/workflows/ios-build.yml`): builds and tests the app, but **does not
  install it on a phone**.
- **Advanced sideloading**: build a signed/unsigned IPA, then use Sideloadly/AltStore with your
  Apple ID. This can work without owning a Mac, but it needs a second computer, signing setup, and
  still expires after 7 days on a free account. Not the first thing to try.

The least painful path for a first install is still a borrowed Mac with a USB cable.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| “Untrusted Developer” | Settings → General → VPN & Device Management → Developer App → Trust |
| “Developer Mode disabled” | Settings → Privacy & Security → Developer Mode, restart, confirm |
| “Unable to install” | Use a unique bundle id, unlock the phone, trust the Mac, delete an old copy of the app |
| “The server certificate is not trusted” | The address must match a certificate SAN (`beacon tls show`); rebuild if the server CA was regenerated |
| Cannot connect | Same Wi-Fi, VPN off, port 8091 reachable, router client isolation disabled |
| “Token rejected” | Use `ios.token`; check `beacon token list` scopes and that the token was not revoked |
| App stops opening after a week | Free provisioning expired — re-run from Xcode |
| Simulator works but phone does not | Check the phone is on the LAN and the Local Network permission is allowed |

The app does **not** require installing the private CA as a phone profile: it validates the
certificate against `ca.crt` bundled inside the app. The server certificate still has to be valid
for the address you type (currently `192.168.1.83`).

---

## Redeploying the backend (probably not needed)

The backend is already installed as a systemd service. If you change backend code later:

```bash
cd ~/beacon
sudo scripts/install.sh     # idempotent: venv, TLS check, units, health wait
beacon doctor               # should end with "all checks passed"
```

Do not run this just to install the iPhone app.
