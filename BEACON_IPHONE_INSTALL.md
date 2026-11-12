# Beacon — iPhone install handoff

**Purpose:** a self-contained brief you can give to another AI assistant (or read yourself) to
install the Beacon iOS app on a physical iPhone. It assumes no prior iOS/Xcode knowledge.

> **Secrets:** the server token is a password. Do not paste it into an AI chat, a screenshot, a
> git commit, or a public issue. The other AI only needs to know **where** the token is.

---

## 0. Current state (context for the assistant)

- The **backend is already deployed** on `ericserver` at `https://192.168.1.83:8091`. Do not
  reinstall it for this task.
- The **iPhone app has never been installed**. There is no App Store link, no TestFlight build,
  and no signed IPA.
- The app source and Xcode project are in `~/beacon/ios/` on the Linux server.
- The project is `ios/Beacon.xcodeproj`; deployment target is **iOS 17.0**.
- It is a personal LAN app: it needs the iPhone and server on the same Wi-Fi, and it validates
  the server's private CA using `ios/Beacon/Resources/ca.crt` bundled in the app.
- The app is not distributed; the final install happens from **Xcode on a Mac** with the user's
  own Apple ID.

---

## 1. STOP — collect four facts first

Do not give install steps until these are known:

1. **Mac model and chip** — Apple menu → About This Mac. Look for “Chip: Apple M…” vs
   “Processor: Intel…”, and the year/model.
2. **macOS version** — same About This Mac window (e.g. Ventura 13.6, Sonoma 14.5, Tahoe 26.2).
3. **iPhone model** — Settings → General → About → Model Name.
4. **iPhone iOS version** — Settings → General → About → iOS Version.

The compatibility answer depends on all four, not just the year “2020”.

---

## 2. Compatibility matrix

Apple's requirements (check current versions if reading this later):

| Mac can run | Newest Xcode | Can build Beacon (iOS 17 target)? | Can install on which iPhone? |
|---|---|---|---|
| macOS 26 Tahoe (latest point release) | Xcode 26.x | Yes | iOS 26 and older (current phones) |
| macOS 14.5–15.x (Sonoma/Sequoia) | Xcode 16.x | Yes | Generally up to iOS 18; **not** iOS 26 phones |
| macOS 14.0–14.4 | Xcode 15.4 | Yes (iOS 17 SDK) | **iOS 17 phones only** |
| macOS 13.x (Ventura) | Xcode 15.x | Yes (iOS 17 SDK) | **iOS 17 phones only** |
| macOS 12.x or older | Xcode 14.x | **No** — no iOS 17 SDK | — |

Key traps:

- **Xcode 16 requires macOS 14.5 or newer.**
- **Xcode 15 cannot install onto an iPhone running iOS 18 or newer.**
- **An iPhone on iOS 26 needs the Xcode 26 line**, which requires macOS Tahoe 26 or later.
  Current Xcode 26.x releases require macOS 26.2+, so install the latest Tahoe update.
- A 2020 Mac may be Apple silicon (M1) or Intel. M1 2020 MacBook Air/Pro can update to Tahoe;
  most Intel 2020 models cannot. Check the chip, not just the year.

If the Mac's macOS is older than 14.5, first check **System Settings → General → Software
Update**. Make a Time Machine backup before a major macOS upgrade. If the Mac cannot update far
enough, use one of the alternatives in section 6.

---

## 3. Recommended path (compatible Mac + iPhone)

### 3.1 Prepare

- Install **Xcode** from the Mac App Store (large download, 10–20 GB). Use the newest version the
  Mac's macOS supports, but at least Xcode 16 for an iOS 18 phone, or Xcode 26 for an iOS 26 phone.
- Copy the entire `ios/` folder from `~/beacon/ios` to the Mac (USB, AirDrop, or Samba). Keep
  `ios/Beacon/Resources/ca.crt`.
- Have the iPhone and server on the **same Wi-Fi/LAN**.
- Get the token from the server:

  ```bash
  cat ~/beacon/data/secrets/ios.token
  ```

  Use the **iOS token**, not `cli.token` or `agent.token`.

### 3.2 Run the simulator first (no signing)

1. Open `ios/Beacon.xcodeproj` in Xcode.
2. Choose an iPhone simulator (e.g. “iPhone 16”) and press **Run** (▶).
3. On the setup screen enter:
   - Server: `192.168.1.83:8091`
   - Token: the iOS token
   - Pin: leave blank for the first attempt
4. Allow the **Local Network** permission.
5. If the dashboard appears, the app and server work. This step needs no Apple ID.

### 3.3 Install on the iPhone

1. Xcode → **Settings → Accounts → +** and add the user's Apple ID.
2. Select the **Beacon** target → **Signing & Capabilities**:
   - Tick **Automatically manage signing**.
   - Choose the **Personal Team**.
3. Change **Bundle Identifier** from `dev.ericserver.beacon` to something unique, for example
   `com.<name>.beacon`. Free provisioning fails if the identifier is already registered.
4. Connect the iPhone by USB, unlock it, and tap **Trust**.
5. On the iPhone: **Settings → Privacy & Security → Developer Mode → On**, restart, confirm.
6. Select the iPhone as the run destination and press **Run**.
7. If the phone says “Untrusted Developer”: **Settings → General → VPN & Device Management →
   Developer App → Trust**.
8. Open Beacon and enter the same server, token and optional pin.

### 3.4 Free Apple ID limits

- The app expires after **7 days**; re-run from Xcode to renew it.
- Up to **3 apps** per device.
- No paid capabilities such as push notifications (Beacon does not use APNs).

For a permanent install, use a paid Apple Developer account and TestFlight (internal testing,
builds expire after 90 days).

---

## 4. Values and where they come from

| Field | Value |
|---|---|
| Server | `192.168.1.83:8091` (the app adds `https://`) |
| Token | contents of `~/beacon/data/secrets/ios.token` |
| Optional pin | `beacon tls show` → `spki_pin` |
| CA | already bundled at `ios/Beacon/Resources/ca.crt`; do not install a phone profile |

The app does **not** require installing the private CA as an iOS profile. It trusts the bundled
CA directly. The server certificate must still be valid for `192.168.1.83`.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| “Untrusted Developer” | Settings → General → VPN & Device Management → Developer App → Trust |
| “Developer Mode disabled” | Settings → Privacy & Security → Developer Mode, restart, confirm |
| “Xcode requires macOS 14.5 or later” | Update macOS, or use an older Xcode only if the phone is iOS 17 |
| “Unsupported OS version” / device OS too new | Xcode 15 cannot install on iOS 18+; use Xcode 16 on macOS 14.5+ (or Xcode 26 for iOS 26) |
| “Unable to install” | Unique bundle id, unlock phone, trust Mac, delete an old copy |
| “Failed to register bundle identifier” | Pick a different unique bundle id |
| “Certificate not trusted” | Address must match a certificate SAN (`beacon tls show`); rebuild if the CA changed |
| Cannot connect | Same Wi-Fi, VPN off, port 8091 reachable, router client isolation off |
| “Token rejected” | Use `ios.token`; check `beacon token list`; do not use the CLI/agent token |
| App stops opening after a week | Free provisioning expired — re-run from Xcode |
| Build succeeds but install fails | This is almost always signing or an iOS/Xcode version mismatch |

---

## 6. If the Mac is too old or the iPhone is too new

Do not spend hours fighting an unsupported combination. Options, cheapest first:

1. **Update the Mac's macOS** if Apple still supports that model. Back up first.
2. **Borrow or rent a current Mac.** A current macOS + Xcode 26 machine is the most reliable path.
3. **Cloud Mac** (MacinCloud, MacStadium, AWS EC2 Mac): good for building and running the
   simulator, but a remote Mac usually cannot connect to a physical iPhone. It proves the build,
   not the phone install.
4. **GitHub Actions** (`.github/workflows/ios-build.yml` in this repo): builds and tests on a
   current Xcode for free, but does **not** install on a phone.
5. **Advanced sideloading** (Sideloadly/AltStore): build an IPA on a Mac/CI, sign it with a free
   Apple ID on a Windows/Linux computer, install over USB. It works, but it is fiddly and still
   expires after 7 days on a free account.

---

## 7. What “done” looks like

- Xcode reports **Build Succeeded**.
- The Beacon icon appears on the iPhone’s Home Screen.
- The app opens to setup, accepts the server/token, and shows the dashboard.
- The server sees the app: `beacon doctor` remains green; the app polls every 15 s while open.

If it only runs in the simulator, the app is **not installed** on the phone.

---

## 8. Copy-paste prompt for the summarizing AI

```text
Read the file BEACON_IPHONE_INSTALL.md completely.

You are helping a beginner install a personal iOS app. First ask me for the four facts in
section 1: Mac chip/model, macOS version, iPhone model, and iOS version. Then use section 2 to
tell me whether my combination is supported.

If it is supported, give me a numbered checklist based on section 3, with exact Xcode menu
names. Remind me not to paste the server token into this chat. Do not claim the app is installed
until Xcode says Build Succeeded and the app opens on the phone.

If it is not supported, explain the shortest alternative from section 6 in plain language.
Do not invent commands or Xcode features that are not in the file.
```
