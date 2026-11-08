---
title: Enroll your first player
section: players
roles: [CMS_ORG_ADMIN, CMS_SCHEDULER]
keywords: [player, enrollment, enroll, provisioning, token, installation, install, NUC, raspberry, windows, android, chromeos, bulk commands, enrôlement]
---

# Enroll your first player

A player is a device that drives a screen. To join your organization, it needs a
**provisioning token**: a limited-use secret that the player presents to the
server in order to register.

## Generate a provisioning token

1. Go to **Players → Provisioning**.
2. Click **New token** in the top bar.
3. Choose the maximum number of players this token can enroll, and an expiry
   (or tick "No expiry" for a permanent token).
4. Copy the generated token (it starts with `sfp_`).

An active token can be **revoked** (⊘ icon): it can no longer enroll new
players, but those already enrolled keep working. A revoked token can then
be permanently **deleted**.

## Install the player on the device

The player software exists for Linux (Debian), Raspberry Pi, Windows 11, Android, and as a
ChromeOS PWA / Chrome extension. At installation, it is given two things:

- the Vitrail **server URL**,
- the **provisioning token** (`sfp_…`).

On first start, the player exchanges the token for its permanent identity and
appears in **Players**. From then on, it receives its configuration and content
automatically.

## Check that a player is online

In the Players list, a badge shows the status (online / offline) with the date
of last contact. Open a player's drawer to see its machine, its screen, its
network address, its media inventory and a recent screenshot.

## Configure a player remotely

From a player's drawer, without SSH, you can push: resolution, screen
rotation, volume, sound on/off, choice of rendering engine. The **"On-screen
info"** button displays a diagnostic panel directly on the player's screen (name,
machine, network, current schedule, media playing) — handy to identify a screen
remotely.

## Act on several players at once

The **"Bulk commands"** button at the top of the Players page sends the same command to
a whole **target**: entire organization, site, site group, player group, or a
specific player. The target is resolved by the server — a player added to the site later
will therefore be included in the next send.

Before sending, a **preview lists the affected screens**: check it, it is the only
chance to catch a target that is too broad.

**Destructive** commands (restart the machine or the application, quit the
application, maintenance mode) additionally require:

- a **confirmation checkbox** stating the number of screens affected;
- your **6-digit PIN** (the same as for the messaging assistant), to be set in
  your profile, "Messaging" card. Three wrong PINs lock the feature for 15 minutes.

Harmless commands (screenshot, capability detection, information
overlay) do not require a PIN.

Every bulk send is **logged** in the audit trail with the requested target and the list
of players actually affected.
