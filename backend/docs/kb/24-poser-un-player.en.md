---
title: Installing a player at a customer site — the 4 channels and the 3 proofs
section: players
roles: []
keywords: [install a player, installation, player installation, provisioning, provision, payload, token, sfp_, operator key, sfk_, SD card, SD image, Raspberry Pi, WinRM, Windows, SSH, ADB, Android, BrightSign, reattach, duplicate, field, technician, installer, first boot, poser un player, clé opérateur]
---

# Installing a player at a customer site — the 4 channels and the 3 proofs

The CMS generates a **payload** — the server address plus a **single-use `sfp_` token** — and
**pre-creates the player**. The device reattaches to it on first contact, exchanges the token for a
permanent token, and appears **online**.

⚠️ **A consumed token cannot be reused.** If an installation fails after registration, you must
**regenerate a payload**: otherwise the next attempt fails for a reason unrelated to the real
cause, and you look in the wrong place.

📄 Full step-by-step procedure for the technician: `docs/RUNBOOK_POSE_PLAYER.md`.
Android boxes (Device Owner pitfalls): `player-android/README.md`.

## To prepare only once

In the CMS, as organization administrator: **Provisioning → Operator key** → generate →
copy the `sfk_…` key (**displayed only once**). On the technician's computer:

```
signflow-provision --cms https://<serveur>:8443 --key sfk_… --save-config
```

There is nothing more to retype afterwards. This key is **limited to provisioning** (creating a
payload, reading a player's state) — it does **not** grant administration rights — and it can be
revoked from the CMS. An administrator token works too, but it **expires after 15 minutes**:
avoid it in the field.

The technician only needs **a single file** (`signflow-provision.exe`, ~13 MB); no
Python to install. `signflow-provision --selftest` lists the available channels.

## Which channel for which situation

| Situation | Channel | Human action on site |
|---|---|---|
| **New Raspberry Pi** | SD card image | insert the card, power on — **that's all** |
| **Windows PC already installed** | WinRM | open WinRM once |
| **Linux / RPi already in service** | SSH | none if SSH is already open |
| **Android box** | ADB | enable USB debugging |
| **BrightSign** | ZIP on SD card | copy the ZIP onto the card |

🔑 **The tool cannot open the door for you.** An entry point must exist (WinRM,
SSH, ADB, or physical access to the SD card); everything else is automated.

## The 3 proofs that an installation succeeded

Do not settle for the tool's message — it says that the script ran, not that the player
works.

1. **In the CMS**: the player is **online**, with the right system, and there is **only one
   row** — no duplicate.
2. **The token has been consumed**: in the player's `config.json`, the value starts with `eyJ…`
   (a permanent token) and **no longer** with `sfp_`. If it still starts with `sfp_`,
   registration did not happen.
3. **The screen is playing** (or shows the fallback if nothing is scheduled yet).

## Pitfalls met in real life

**Re-provisioning an existing player without the reattach option creates a DUPLICATE.** Get its
identifier in **Players** and pass it to the tool. ⚠️ Even a simulation (`--dry-run`) creates a
player on the CMS side.

**The SSH host key changes with every reinstallation.** The refusal that follows is the system doing its
job. Remove the old fingerprint (`ssh-keygen -R <ip>`) — ⚠️ as long as it is there, OpenSSH
**also disables password authentication**, and you think the password is wrong
when it is the key.

**A Raspberry Pi has no clock.** On first boot it restarts from the image's date; until
the time is synchronized, **every secure connection is refused** ("certificate is not
yet valid"). The image waits on its own — but if the site blocks time synchronization,
the installation fails and says so.

**No network at the right moment = clean failure.** The message says so and a reboot retries:
no need to redo the card.

**On a Windows virtual machine**, use a **SATA** disk and an **e1000e** network card:
Windows has no virtio driver, otherwise it sees neither the disk nor the network.

## If it does not work

On a Raspberry Pi installed via SD card, the first boot writes a **persistent log**:
`/var/log/signflow-firstboot.log`. It survives reboots and says at which step it broke —
it is the first place to look before redoing anything.
