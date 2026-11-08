---
title: On-demand broadcasting (VOD)
section: content
roles: []
keywords: [VOD, on demand, on-demand, takeover, broadcast now, play now, immediate playback, store, flash promo, trigger, à la demande, diffuser maintenant]
---

# On-demand broadcasting (VOD)

The **On-Demand (VOD)** page lets you **broadcast content immediately** on screens,
on top of the current schedule — without touching playlists or schedules. Use
cases: flash promo, in-store announcement, demonstration to a customer.

## Create a VOD config

A VOD config groups **media** (videos, images, documents — and the
**HDMI Input** media to switch to an external source) and a **target**, either:

- **Selected players**: you tick the players one by one — all from the **same site**;
- **Entire site**: you choose a site, and **all its players** are targeted. The target
  is *dynamic*: a player installed on this site later automatically receives the
  pre-download and the triggers, **without reopening the config**. This is the preferred mode
  for a store whose fleet changes.

As soon as the config is saved, the media are **pre-downloaded** to the relevant
players: triggering is instant, even on a slow connection.

## Trigger a broadcast

Open the config → **Broadcast now** section:
1. select the target players (all by default);
2. on the desired media: **Once** (the content plays once then the schedule
   resumes) or **Loop** (until the **Stop** button).

For an **HDMI Input** media, the buttons become **Switch to HDMI / Back to
playlist** (see the "HDMI input" article), and only players with a physical HDMI input
are offered.

## Who can trigger?

Triggering requires the **vod : trigger** permission: you can give this single right to
a "store" account (e.g. operator role) so that the on-site team launches broadcasts
without accessing the rest of the CMS.

## Good to know

- On-demand broadcasting is a **takeover**: at the end (or on Stop), the normal
  schedule resumes exactly where it is (current time, not from the beginning).
- A VOD config is restricted to **a single site** in both modes (constraint of the
  local LAN triggering between players); a warning flags players on different
  networks (playback remains possible, local LAN triggering between players does not).
- **Pre-downloading** can take time right after the config is created
  (large 4K files, sequential downloads). As long as a media is not yet
  cached on a player (visible in the player drawer, content inventory), a
  trigger plays it **by streaming** — slightly delayed start. Once cached,
  playback is instant and local.
- **BrightSign specifics**: starting and stopping an on-demand broadcast
  can take **up to 2 seconds** (local relay embedded on the player) — this is
  normal, including from the local control page (phone). During the broadcast,
  the playlist is **suspended** (a single hardware video stream on these players) then resumes
  at the current time. Triggering from the local panel also works
  **offline** (signed LAN broadcast between players, like the Electron players).
