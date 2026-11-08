---
title: Chrome Extension player (no hardware)
section: players
roles: [CMS_ORG_ADMIN, CMS_SCHEDULER]
keywords: [chrome, extension, player, no hardware, zero-hardware, browser, kiosk, sans matériel, navigateur]
---

# Chrome Extension player (no hardware)

The **Chrome extension** turns a plain Chrome into a Vitrail player, without installing
a dedicated device. Ideal for testing, or for an existing workstation that already has a screen.

## When to use it

- You want to try Vitrail without a NUC or a box.
- You have a PC/screen already in place running Chrome.
- You do not need LAN synchronization between screens (not available in the
  extension, which works with online playback and graceful offline degradation).

## Install

1. Get the extension folder from your administrator.
2. In Chrome: `chrome://extensions`, enable **developer mode**, then
   **"Load unpacked"** and point to the folder.
3. Open the extension's **popup**: enter the Vitrail server URL and a provisioning
   token (`sfp_…`), then launch. A full-screen kiosk window opens and the player
   registers.

The Chrome Extension player then appears in **Players** like any other, and
receives its schedule normally.

## Limitations

- No LAN synchronization between several screens.
- Offline mode is limited (streaming playback) compared with native players that
  download and play locally.
- For a locked-down, auto-launched deployment on managed ChromeOS, the **ChromeOS PWA
  player** (kiosk) is used instead.
