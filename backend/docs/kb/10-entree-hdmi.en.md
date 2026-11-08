---
title: HDMI input (broadcasting an external source)
section: media
roles: []
keywords: [HDMI, HDMI input, hdmi-in, external source, TV set-top box, box, switch, switchover, BrightSign, no signal, /control, VOD HDMI, antenna socket, entrée HDMI, source externe, décodeur TV]
---

# HDMI input: broadcasting an external source on a screen

The **"HDMI Input"** media lets you display on a screen **any source
connected** to the player's HDMI input: TV set-top box, store box, demo console,
computer… Playback is purely local (nothing goes through the server).

**Compatible players**: BrightSign with a physical HDMI input — **XT** series (XT1143/1144/
1145, XT2145…), **4K1142/4K1242** and **XD1230**. The HD/LS series and the other player
types have no input: they ignore this media.

## Create the media

Media → **HDMI Input** button → give it a name. It is a "pointer" media: no
file, no download.

## Use it in a playlist (scheduled slot)

Add the media to a playlist like any other content, with a **duration**: during this
slot, the player switches to its HDMI source, then resumes the playlist. Players without
an HDMI input **never receive this item** (they move on to the rest); when the
schedule is created, a warning lists the targeted players that are not compatible.

**No signal?** If the source is unplugged or turned off, the screen displays
**"No Signal Detected"** (after ~3 s) instead of a black screen, for the duration of the item — the
playlist is not shifted. As soon as the signal comes back, the image displays by itself.

## The on-demand switch (VOD)

To switch **whenever you want** (not at a fixed time): create a **VOD config** (On-Demand
page) containing the HDMI Input media — only compatible players are offered.
Two buttons replace the usual playback:
- **Switch to HDMI**: the screen switches to the source, the playlist is suspended;
- **Back to playlist**: resumes exactly where the schedule is (not from the beginning).

## Local control, without the CMS

Each compatible BrightSign serves a **local control page**:
`http://<ip-du-player>:8888/control` — usable from any phone or PC on the
store's network, without an account or server, even offline. Two buttons: switch / back.

## Safeguards and traceability

- **Automatic shutdown**: if the screen turns off (site closing, manual shutdown), a
  switch left active is **ended automatically** — the next day, the playlist resumes
  normally.
- **Everything is traced**: each switchover appears in the audit log (source of the
  trigger — VOD, drawer or local page — and actual duration), and a **signed proof
  of play** is issued with the actual duration of the session (visible in the Proof of
  Play reports, like the playlist item).
