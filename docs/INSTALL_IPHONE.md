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

> **No usable Mac?** There is now a Linux-only route: GitHub Actions builds an unsigned IPA and
> `docs/LINUX_IPA_INSTALL.md` signs and installs it with AltServer-Linux-NG. The Mac route below is
> still the simplest if you can borrow one, but it is no longer the only route.

---

## What you need

- An iPhone running **iOS 17 or newer** (Settings → General → About).
- A **Mac** running **macOS Sonoma 14.5 or newer** with **Xcode 16+**. Xcode is a large download
  (roughly 10–20 GB); start it early. See [Old Macs and older Xcode](#old-macs-and-older-xcode) —
  an un-updated Mac may need a different Xcode, and Xcode 15 cannot install on iOS 18 phones.
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

## Old Macs and older Xcode

Check the Mac first: **Apple menu → About This Mac**. The macOS version decides which Xcode you
can run.

From Apple's own release notes:

| Xcode | Minimum macOS | iOS SDK | Notes |
|---|---|---|---|
| Xcode 16.x | Sonoma **14.5** | up to iOS 18 | recommended; runs `simulator` apps and installs on iOS 18 phones |
| Xcode 15.4 | Sonoma **14** | iOS 17.5 | can install on iOS 17 devices |
| Xcode 15.x | Ventura **13.5** | iOS 17.0 | installs on iOS 17 devices only |
| Xcode 14.3 | Ventura 13.0 / Monterey 12.5+ | iOS 16.4 | **cannot install on an iOS 17 or 18 phone** |

Real-world consequences:

- **Mac on macOS 13 (Ventura)** → newest possible is Xcode 15.x, iOS 17 SDK. That builds Beacon
  (which targets iOS 17) but only installs on phones running **iOS 17**. If the phone is on iOS 18
  or later, Xcode will refuse to install it.
- **Mac on macOS 12 (Monterey) or older** → Xcode 14/15.0 at best — not enough for iOS 17.

Your options in that case, cheapest first:

1. **Update the Mac's macOS** (System Settings → General → Software Update). Free, but on
   Intel Macs the newest macOS often cannot be installed. Do a Time Machine backup first.
2. **Build on the Mac, install the app to an iOS 17 device.** Check the phone's version first.
3. **Use the iPad/iPhone-equivalent route: a cloud Mac.** MacinCloud and similar rent a
   current-macOS Mac by the hour with Xcode pre-installed. They can build and run the simulator;
   a physical iPhone usually cannot be attached, so this proves the app but may not install it.
4. **Use the GitHub Actions workflow** in this repository (`.github/workflows/ios-build.yml`):
   it builds and tests on a current Xcode for free. It produces proof the app compiles, but it
   does not install anything on a phone.
5. **Borrow/upgrade to an Apple-silicon Mac.** macOS 26 (Tahoe) and Xcode 26 require Apple
   silicon or a few late Intel models, so an Intel Mac from 2020 has a limited window.

> Do not install a newer Xcode than the Mac's macOS supports — the installer refuses, and
> unofficial patchers are not recommended for a first-time setup.

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

Use the Linux route first:

1. Push the repository to GitHub.
2. Run the **iOS build, tests & unsigned IPA** workflow.
3. Download the `Beacon-unsigned-ipa` artifact.
4. On this Linux host, run `scripts/install_ipa_linux.sh` as described in
   [`LINUX_IPA_INSTALL.md`](LINUX_IPA_INSTALL.md).

That path needs no Mac and no Windows. It uses a free Apple ID and still expires after 7 days.

Other options, in case the Linux route is blocked:

- **Cloud Mac** (MacinCloud, MacStadium, AWS EC2 Mac): you can build and run the simulator, but a
  remote Mac usually cannot plug into your physical iPhone. Not a simple install path.
- **GitHub Actions alone**: builds and tests the app and produces the IPA, but **does not install it
  on a phone**.
- **Advanced sideloading**: an unsigned IPA plus Sideloadly/AltStore with your Apple ID. This is
  the same idea as the Linux path, but may require Windows and a different signing tool.

The least painful path for a first install is still a borrowed Mac with a USB cable; the Linux
path is the fallback when that is not available.

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
| “Xcode requires macOS 14.5 or later” | The Mac needs a newer macOS, or use an older Xcode as described above |
| “Unsupported OS version” / device OS too new | Xcode 15 cannot install on iOS 18+ phones; use Xcode 16 on macOS 14.5+ |
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
