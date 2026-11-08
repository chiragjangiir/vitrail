# SignFlow — Image carte SD greenfield (Raspberry Pi)

🇬🇧 [English version](README.md)

Customise l'**image officielle Raspberry Pi OS Lite (arm64)** en image d'appliance SignFlow **prête
à flasher** : injecte `player-rpi` + un **service systemd de premier boot** qui lit le payload de
provisioning, installe le player (via `player-rpi/install.sh`) et sème le `config.json` → au 2ᵉ boot
le RPi diffuse. « Customisation type Pi Imager », côté serveur.

> **Statut : ✅ validé de bout en bout le 2026-08-09** — installation de zéro sur un vrai
> Raspberry Pi : 1er boot, install player, kiosk, player online, **zéro intervention**.

## Comment ça marche

1. On part de l'image **Raspberry Pi OS Lite arm64** officielle (téléchargée + décompressée).
2. On la **loop-monte** (losetup + kpartx) et on injecte :
   - `player-rpi/` → `/opt/signflow/player-rpi` (sans `node_modules`),
   - `signflow-firstboot.sh` + un **service systemd oneshot** activé (`multi-user.target.wants`),
   - `signflow-provision.json` sur la **partition boot** (FAT, éditable après flash),
   - `ssh` (dépannage terrain),
   - **`userconf.txt`** — le compte système `signflow`. ⚠️ **Sans lui l'image n'est pas
     autonome** : Raspberry Pi OS n'a plus de compte par défaut, et le premier démarrage
     s'arrête alors sur son assistant en **attendant un clavier** (« Which user would you like
     to rename »), ce qui vide de son sens une pose sans opérateur. Le mot de passe est
     **généré aléatoirement** et rendu en fin de build (`out/signflow-rpi.credentials.txt`) ;
     `RPI_PASSWORD=…` permet d'en imposer un. Le nom du compte doit rester `signflow` :
     c'est pour lui qu'`install.sh` configure la session kiosk.
3. Au **premier boot** (réseau requis) le service lit le payload, lance `install.sh`, écrit le
   `config.json` (`backend_url` + `player_token` `sfp_` + `player_name` — voir
   `firstboot.sh:183-198`), se désactive et **redémarre sur le player**. Le player s'auto-enregistre et se **ré-attache** au player pré-créé (zéro doublon).

> ⚠️ Contrairement à l'image **x86** (kiosk PWA, offline), le player RPi est **Electron/Debian** :
> le premier boot **installe** Node/Electron via `install.sh` → **internet requis au 1er boot**.

## Construire l'image (Docker privilégié — loop + device-mapper)

```bash
cd installer/image-rpi
mkdir -p out cache
docker run --rm --privileged \
  -v "$PWD:/work/src:ro" -v "$(git rev-parse --show-toplevel):/work/repo:ro" \
  -v "$PWD/out:/work/out" -v "$PWD/cache:/work/cache" \
  alpine:3.20 sh /work/src/build.sh
# → out/signflow-rpi.img
```

`--privileged` est nécessaire (loop devices + kpartx). Le `.img.xz` officiel est mis en cache
(`cache/`) pour éviter de le retélécharger. Variable `IMG_URL` pour épingler une version précise.

## Préparer + flasher

1. Générer le **payload** du player depuis le CMS (page Provisioning, `os=rpi`).
2. Flasher `out/signflow-rpi.img` sur la carte SD avec **Raspberry Pi Imager** (ou `dd`).
3. Rouvrir la partition **boot** (montée sous Windows) et remplacer `signflow-provision.json` par le
   payload (ou y coller le `token` `sfp_…` + `backend_url`).
4. Insérer la SD dans le RPi, le démarrer (réseau branché). Premier boot = install (plusieurs
   minutes) → reboot → player.

## Limites

- **Premier boot = réseau requis** (apt/node/npm/electron via `install.sh`). Pré-bake offline
  (chroot arm64 + qemu-binfmt) = amélioration future.
- RPi = **carte SD flashée** (pas de « boot USB »). Modèles visés : RPi 4/5 (RPi OS Trixie,
  Debian 13 — cible réelle de `player-rpi/install.sh`).
- Rappel projet : **4K éliminé** sur RPi → le player force FHD (cf. `player-rpi/install.sh`).
