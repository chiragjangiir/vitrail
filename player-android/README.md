# Vitrail Player — Android

🇫🇷 [Version française](README.fr.md)

**Native Kotlin** application (not Electron) for Android 9+ (`minSdk 28`) — Android TV boxes,
touch screens, phones. Package `app.vitrail.player`.

## Installation

- **Field (recommended)**: `docs/RUNBOOK_POSE_PLAYER.md` — `signflow-provision` ADB channel
  (`--os android --ip <ip>`, APK pushed + provisioned in one command).
- **Android TV / Google TV boxes**: `docs/RUNBOOK_POSE_ANDROID_TV.md` — kiosk = become the
  **launcher** (on Google TV `set-home-activity` is not enough: disable the HOME packages),
  `appops … REQUEST_INSTALL_PACKAGES allow` for OTA, `adb tcpip 5555` before anything else.
  ⚠️ **Google TV without Device Owner ≠ Android TV**: some OSes (consumer Google TV,
  ColorOS) refuse Device Owner — the #1 criterion when choosing hardware.
- **Local manual install**: `./install.sh [--release] [--ip <ip>]` (gradle build + `adb install`
  + set-home-activity).

## Technical decisions to know

- **WebView + ExoPlayer**: the WebView (shared renderer) renders all non-video content;
  a sibling **ExoPlayer TextureView (media3)**, on top, decodes in native HW what the WebView
  cannot handle (**HEVC, 4K@60**). The idle screen is a **native view** placed above both
  (the WebView of some Amlogic boxes does not composite when idle — screenshots would lie).
- **Debug and release = two distinct apps**: debug is suffixed `.debug`
  (`applicationIdSuffix`). Switching to release = fresh install (re-provision), then
  `adb uninstall app.vitrail.player.debug`.
- **Release signing**: `keystore.properties` (gitignored) pointing to your `.jks` key. Without
  it the release build comes out **unsigned** (not installable) — the debug build still works.
  **For a real fleet, sign with your own key** (official APK = trials only): how to create it,
  back it up and build with it → [`docs/GUIDE.md`, "Android: your own signing key"](../docs/GUIDE.md#android-your-own-signing-key).
  ⚠️ Losing the key = no more updates possible without uninstalling every device (Android
  requires the same key).
- **OTA by APK from the server**: the player downloads the bundle
  (`player-bundles/android/<version>.apk`, **relative URL** resolved against its `backend_url` —
  never a pre-signed MinIO URL, it expires) and installs it via **`PackageInstaller`**:
  silent if the app is **Device Owner**, otherwise an on-screen confirmation.
- The rest is at parity with Electron: `ContentStore.kt` (offline-first), `LanSyncController` /
  `VodLanController` (UDP 7778/7779), `LocalControlServer` (nanohttpd — LAN Store Control Panel
  §19.3), `PopSigner` (Ed25519 Proof of Play — low-level BouncyCastle, the native JCE
  only has Ed25519 from API 33), `WatchdogWorker`, `BootReceiver` (restart at boot).

## Config

No `config.json`: **`EncryptedSharedPreferences`** (`signflow_config`, AES-256, Android
Keystore). Keys: `backend_url`, `player_token` (provisioning `sfp_…`, replaced by a JWT
on registration), `player_name`. Entered via the setup screen on first launch, or
injected by `signflow-provision`.

## Logs / diagnostics

- `adb logcat -s SignFlow/Main` (+ the `SignFlow/*` tags of the other controllers).
- Version and status reported in the CMS heartbeat; on-device diagnostic overlay available.
