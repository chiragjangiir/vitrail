# Vitrail — Greenfield SD card image (Raspberry Pi)

🇫🇷 [Version française](README.fr.md)

Customizes the **official Raspberry Pi OS Lite (arm64) image** into a **ready-to-flash** Vitrail
appliance image: it injects `player-rpi` + a **first-boot systemd service** that reads the
provisioning payload, installs the player (via `player-rpi/install.sh`) and seeds the `config.json`
→ on the 2nd boot the RPi is playing content. "Pi Imager-style customization", done server-side.

> **Status: ✅ validated end to end** — installation from scratch on a real Raspberry Pi: 1st boot,
> player install, kiosk, player online, **zero intervention**.

## How it works

1. Start from the official **Raspberry Pi OS Lite arm64** image (downloaded + decompressed).
2. **Loop-mount** it (losetup + kpartx) and inject:
   - `player-rpi/` → `/opt/signflow/player-rpi` (without `node_modules`),
   - `signflow-firstboot.sh` + an enabled **oneshot systemd service** (`multi-user.target.wants`),
   - `signflow-provision.json` on the **boot partition** (FAT, editable after flashing),
   - `ssh` (field troubleshooting),
   - **`userconf.txt`** — the `signflow` system account. ⚠️ **Without it the image is not
     self-sufficient**: Raspberry Pi OS no longer has a default account, and first boot then stops
     on its wizard **waiting for a keyboard** ("Which user would you like to rename"), which defeats
     the purpose of an operator-free installation. The password is **randomly generated** and
     output at the end of the build (`out/signflow-rpi.credentials.txt`); `RPI_PASSWORD=…` lets you
     force one. The account name must stay `signflow`: it is the account for which `install.sh`
     configures the kiosk session.
3. On **first boot** (network required) the service reads the payload, runs `install.sh`, writes the
   `config.json` (`backend_url` + `player_token` `sfp_` + `player_name` — see
   `firstboot.sh:183-198`), disables itself and **reboots into the player**. The player
   self-registers and **re-attaches** to the pre-created player (zero duplicates).

> ⚠️ Unlike the **x86** image (PWA kiosk, offline), the RPi player is **Electron/Debian**:
> first boot **installs** Node/Electron via `install.sh` → **internet required on 1st boot**.

## Building the image (privileged Docker — loop + device-mapper)

```bash
cd installer/image-rpi
mkdir -p out cache
docker run --rm --privileged \
  -v "$PWD:/work/src:ro" -v "$(git rev-parse --show-toplevel):/work/repo:ro" \
  -v "$PWD/out:/work/out" -v "$PWD/cache:/work/cache" \
  alpine:3.20 sh /work/src/build.sh
# → out/signflow-rpi.img
```

`--privileged` is required (loop devices + kpartx). The official `.img.xz` is cached (`cache/`) to
avoid downloading it again. Use the `IMG_URL` variable to pin a specific version.

## Prepare + flash

1. Generate the player's **payload** from the CMS (Provisioning page, `os=rpi`).
2. Flash `out/signflow-rpi.img` onto the SD card with **Raspberry Pi Imager** (or `dd`).
3. Reopen the **boot** partition (mounted under Windows) and replace `signflow-provision.json` with
   the payload (or paste the `sfp_…` `token` + `backend_url` into it).
4. Insert the SD card into the RPi and power it on (network connected). First boot = install
   (several minutes) → reboot → player.

## Limitations

- **First boot = network required** (apt/node/npm/electron via `install.sh`). Offline pre-baking
  (arm64 chroot + qemu-binfmt) = future improvement.
- RPi = **flashed SD card** (no "USB boot"). Target models: RPi 4/5 (RPi OS Trixie, Debian 13 —
  the actual target of `player-rpi/install.sh`).
- Project reminder: **4K is ruled out** on RPi → the player forces FHD (see
  `player-rpi/install.sh`).
