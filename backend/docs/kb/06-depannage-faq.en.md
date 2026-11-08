---
title: Troubleshooting and frequently asked questions
section: troubleshooting
roles: []
keywords: [troubleshooting, problem, FAQ, black screen, offline, disconnected player, sound, media unavailable, help, dépannage, écran noir, hors-ligne]
---

# Troubleshooting and frequently asked questions

## A player appears offline

The server always initiates the connection to the player: check that the device is
powered on, connected to the network, and that the configured server URL is reachable from it.
The status badge shows the date of last contact. An offline player **keeps
broadcasting** the last content it received, because it works in local mode.

**Offline at night or outside opening hours?** This is normal if auto-power turns off
its screens: some devices (Android boxes in particular) also cut their network in standby.
The player is then marked **"Scheduled standby"** — no alert is raised, and it
comes back by itself at opening time. An alert is only sent if it has **not come back** a few
minutes after opening time.

## The screen displays "No Signal Detected"

This screen appears during an **"HDMI Input"** content when the source connected to the
player (set-top box, box…) sends no signal: source off, cable unplugged or wrong
input. Turn the source back on / reconnect it — the image comes back automatically within a few seconds,
without touching the player.

## The screen displays "Media unavailable"

This is usually a player whose software is not up to date for the type of content
scheduled (for example a feed or a web page on a version that is too old). Update the
player. Also check that the media has finished processing on the server side.

## The screen stays black or freezes

- Check that the media is properly transcoded (status in Media).
- On synchronized walls, make sure the group is **homogeneous** (same hardware);
  a heterogeneous group can cause offsets or skips.
- The **"On-screen info"** button of the player drawer displays a diagnostic directly on
  the screen (current media, actual playback resolution, network status) to pinpoint the
  problem.

## No sound

Sound depends on the player's **audio role**: "Standard content" plays the sound of videos
without background music; "Audio only" plays only background audio (audio baskets);
"Mixed" plays the background audio with content muted. Also check the volume pushed
from the player drawer and that sound is not muted.

## Content does not update

Any change (playlist, schedule, configuration) normally pushes an immediate
synchronization to online players. If nothing changes, check that the player
is online and that the schedule actually targets this player (or its group).

## Offline: what keeps working?

Native players (Linux, Raspberry Pi, Windows, Android, ChromeOS PWA) download their
content and play it **locally**. They therefore keep broadcasting playlists, videos,
images, feeds (with their cached thumbnails) even with the server or the Internet down. The Chrome
extension, on the other hand, works mostly online.
