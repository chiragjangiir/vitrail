# Runbook — installing a Vitrail player at a customer site

🇫🇷 [Version française](RUNBOOK_POSE_PLAYER.fr.md)

**Tested end to end** on all three channels: Raspberry Pi (SD card, bare machine), Windows 11
(WinRM, machine already installed), Linux/RPi (SSH, machine already in service).

> **This document explains how to INSTALL a player at a customer site.**
> Not to be confused with:
> - `installer/RUNBOOK_TEST_HW.md` — how to **test** the channels (internal acceptance procedure);
> - `docs/RUNBOOK_POSE_ANDROID_TV.md` — installation on an **Android TV box**, which has its own
>   pitfalls (Device Owner, launcher, factory reset);
> - `docs/RUNBOOK_DIAGNOSTIC.md` — when a player that is **already installed** misbehaves.

---

## 1. The principle, in one sentence

The CMS generates a **payload** — the server URL + a **single-use `sfp_` token** — and
**pre-creates the player** on the server side. The device **re-attaches** to it on first contact,
exchanges the token for a permanent JWT, and shows up *online*.

```
CMS ──payload (sfp_)──> [ carte SD | WinRM | SSH | ADB ] ──> player ──register──> online
```

⚠️ **A consumed token cannot be reused.** If an installation fails after registration, you must
**regenerate a payload** — otherwise the next attempt will fail for a reason unrelated to the
real cause, and you will look in the wrong place.

---

## 2. To prepare once (technician's workstation)

### 2.1 The operator key

In the CMS, as **org-admin**: **Provisioning → "Operator key"** → generate → copy the
`sfk_…` key (shown **only once**). Then, on the workstation:

```bash
signflow-provision --cms https://<votre-serveur>:8443 --key sfk_… --save-config
```

→ nothing to re-enter afterwards. The key is **scoped to provisioning** (create a payload, read a
player's state) — it does **not** grant org-admin rights — and it can be revoked from the CMS.

⚠️ **The `sfk_` key expires** (default **90 days**, adjustable up to 730 at creation). A
`--save-config` that fails with "CMS authentication refused" months later is most likely
caused by this: generate a new one in the CMS.

> *Alternative without a key*: `--token <JWT org-admin>`, but it **expires after 15 minutes**.
> Avoid it in the field.

### 2.2 The tool

- **Technician without Python**: copy **a single file**, `installer/dist/signflow-provision.exe`
  (~13 MB). Nothing else to install.

  ⚠️ **Check that the distributed exe is up to date**: `signflow-provision --selftest` must display
  "code du 2026-08-16" (or more recent). An older exe does not contain the fixes of
  2026-08-09 (SSH channel that wrote no config). To rebuild:
  `cd installer && pyinstaller --clean signflow-provision.spec`.
- **Workstation with Python**: `cd installer && pip install -r requirements.txt`, then
  `python -m signflow_provision …`.

Check the available channels: `signflow-provision --selftest`.

---

## 3. Which channel to choose

| Situation | Channel | Human action required on site |
|---|---|---|
| **New Raspberry Pi** (nothing on it) | SD card | insert the card, power on — **that's all** |
| **Windows PC already installed** | WinRM | open WinRM once (§5.1) |
| **Linux / RPi already in service** | SSH | none if SSH is already open |
| **Android box** | ADB | enable USB debugging → `docs/RUNBOOK_POSE_ANDROID_TV.md` |
| **BrightSign** | ZIP on SD card | copy the generated `config.json` to the root of an already prepared SD card (ZIP from the CMS) |

**General rule**: the tool cannot open the door for you. A **foothold** (WinRM, SSH, ADB,
physical access to the SD card) must exist; everything else is automated.

---

## 4. New Raspberry Pi — SD card

### 4.1 Build the image (once per player version, not per machine)

On a machine with Docker (the build needs privileged mode: loop + device-mapper):

```bash
cd installer/image-rpi && mkdir -p out cache
docker run --rm --privileged \
  -v "$PWD:/work/src:ro" -v "$(git rev-parse --show-toplevel):/work/repo:ro" \
  -v "$PWD/out:/work/out" -v "$PWD/cache:/work/cache" \
  alpine:3.20 sh /work/src/build.sh
```

At the end of the build, **write down the password displayed** — it is randomly generated and
written to `out/signflow-rpi.credentials.txt`:

```
- compte système : signflow / <mot de passe>
```

> `RPI_PASSWORD=…` lets you set one yourself. This account is used for **on-site troubleshooting**
> (SSH) and has `sudo`. Without it, a failed machine could not be inspected by anyone.

### 4.2 Inject the payload (once per machine)

Generate the payload from the CMS (**Provisioning → Generate payload**, `os = rpi`), then place it
in the image's **boot** partition, named `signflow-provision.json`, replacing the example file.

> The boot partition is FAT: it can be read on Windows after flashing, if you prefer to flash
> first and edit afterwards.

### 4.3 Flash

**Raspberry Pi Imager** (choose "custom image") or `dd`.

⚠️ **Before any `dd`, check the disk letter three times.** A mistake overwrites a data disk
without confirmation. Minimum checks: the device must be **USB**, be the **size of the card**,
and **not be mounted**.

### 4.4 On site

> **Insert the card. Connect network and screen. Power on. Do nothing.**

The screen shows:

```
===============================================
   Vitrail - installation du player en cours
   NE PAS ETEINDRE / DO NOT POWER OFF
===============================================
[signflow-firstboot] attente de l'horloge (NTP)...
[signflow-firstboot] reseau utilisable (serveur joignable)
  -> installation de Node, Electron et du player (plusieurs minutes)...
```

then **"Installation TERMINEE - redemarrage dans 5s"** (installation finished, rebooting in 5 s).
The machine reboots **by itself** and the player starts in kiosk mode. Allow **~10 minutes**;
internet access is required.

**No question is asked. No keyboard is needed. No second boot.**

On failure, the screen shows the cause and the last lines of the log, then returns control.
**Rebooting is enough to retry**: the service stays armed until it succeeds.

---

## 5. Windows PC already installed — WinRM

### 5.1 Open the foothold (once, on the target machine, PowerShell as administrator)

```powershell
Set-NetConnectionProfile -NetworkCategory Private   # sinon Enable-PSRemoting échoue
Enable-PSRemoting -Force
New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' `
  -Name LocalAccountTokenFilterPolicy -PropertyType DWord -Value 1 -Force
```

> The 1st line is not decorative: on a fresh machine the network is classified as "Public" and
> `Enable-PSRemoting` refuses (the comment means "otherwise Enable-PSRemoting fails"). Nor is the
> 3rd: without it, the **local** admin account receives a restricted token over the network, and
> writes to `%APPDATA%` fail. The tool displays `admin=True/False` — **if it says `False`, this key
> did not take effect.**

### 5.2 Copy the player sources

Copy the `player-windows/` folder to the machine, for example to `C:\signflow\player-windows`.

### 5.3 Install, from the technician's workstation

```bash
signflow-provision --ref "PC Accueil" --os windows \
  --winrm 192.168.1.32 --winrm-user Administrateur --winrm-password '…' \
  --source 'C:\signflow\player-windows' --start-task
```

The tool installs **Node.js if it is missing**, installs Electron, writes the config, starts the
scheduled task and **waits for the player to come online** before returning.

- `--windows-user <account>` if the **kiosk account** differs from the WinRM account (its
  `%APPDATA%` is what receives the configuration).
- Without `--source`, the tool assumes the player is **already installed** and only writes the
  configuration.

> A pywinrm `UserWarning` about converting a PowerShell message is **cosmetic** — ignore it
> if the player comes online.

---

## 6. Linux or Raspberry Pi already in service — SSH

```bash
signflow-provision --ref "Vitrine Lyon" --os rpi --ssh signflow@192.168.1.20
```

The tool reruns the installer present on the machine, writes the configuration **to the directory
the player actually reads**, then **restarts the player** so that it picks it up.

- `--player-user <account>` if the player runs under an account other than `signflow`.
- Authentication goes through the `ssh` binary: set up a **key** (an interactive password cannot
  be provided to the tool).

**SSH channel prerequisites**: the player must be installed under `/opt/signflow/player-rpi` or
`/opt/signflow/player-linux`, and the player account must have its home under `/home/<compte>` —
these paths are hard-coded in the driver. Otherwise the channel stops and says so.

---

## 7. Checking that the installation succeeded

Do not settle for the tool's message. Three proofs:

1. **The CMS**: the player is **online**, with the right OS, and there is **only one row**
   (no duplicate).
2. **The token was consumed**: in the player's `config.json`, `player_token` starts with
   `eyJ…` (a JWT) and **no longer** with `sfp_`. If it still starts with `sfp_`, registration did
   not happen. ⚠️ On **Windows**, before registration the key is called `org_token` (the player
   replaces it with `player_token` when registering) — so the proof is "the `org_token` sfp_
   is gone, replaced by a `player_token` eyJ…", not "player_token still starts with sfp_".
3. **The screen** is playing content (or shows the fallback if no content is scheduled).

---

## 8. Pitfalls (all encountered for real)

**Re-provisioning an existing player without `--reattach <id>` creates a DUPLICATE.** Get the `id`
from CMS → Players. Note: a `--dry-run` **also creates** a player on the CMS side.

**The SSH host key changes on every reinstallation.** The refusal that follows (`REMOTE HOST
IDENTIFICATION HAS CHANGED`) is the system doing its job. Remove the old fingerprint:
`ssh-keygen -R <ip>`. ⚠️ Until it is removed, OpenSSH **also disables password
authentication** — you think the password is wrong when it is actually the key.

**A Raspberry Pi has no clock.** On first boot it starts from the image's date; until NTP has
synchronised, **every HTTPS connection is refused** ("certificate is not yet valid"). The image
handles the wait — but if a site blocks NTP, the installation will fail and say so.

**A machine without network at the right moment fails cleanly**: the message says so, and a
reboot retries. Do not re-flash the card because of it.

**Windows has no virtio drivers.** On a VM, use a **SATA** disk and an **e1000e** network card,
otherwise the installer cannot see the disk and the machine has no network.

---

## 9. If it does not work

**Raspberry Pi** — connect over SSH with the build account (`signflow` + the password from
`signflow-rpi.credentials.txt`; it has `sudo`):

```bash
cat /var/log/signflow-firstboot.log     # tout le déroulé, y compris la sortie de l'installeur
tail -f /var/log/signflow-player.log    # le player une fois installé
```

> The first log contains the whole run, including the installer output; the second is the player
> once installed. This log **survives reboots**, unlike this image's systemd journal. It is the
> first thing to read.

**Windows** — check that the task exists and that the configuration is in the right place:

```powershell
Get-ScheduledTask 'SignFlow Player'
Get-Content "$env:APPDATA\signflow-player-windows\config.json"
```

**All OSes** — if the player stays on "Setup required" although the configuration exists, it
**is not reading the file you are looking at**. The directory is `~/.config/<package name>` on
linux/rpi (`signflow-player-rpi`, `signflow-player`), and `%APPDATA%\signflow-player-windows` on
Windows. The name is **derived from the player's `package.json`** (`app.getPath('userData')`) —
never rewritten by hand.

For what comes next, see `docs/RUNBOOK_DIAGNOSTIC.md`.
