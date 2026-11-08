# Vitrail — Bootable USB key for hardware validation

🇫🇷 [Version française](README.fr.md)

A key that **boots Linux (Alpine, without installing anything)**, **automatically** runs the
hardware validation of a candidate machine (CPU / RAM / storage / GPU / network), **writes a report
onto the key** (`rapports/` folder) and displays the verdict on screen:

    VALIDÉ · VALIDÉ AVEC RÉSERVES · NON VALIDÉ

(validated · validated with reservations · not validated)

Ideal for testing a **bare** box (no OS) before installing Vitrail. This key installs nothing: it
only judges whether the machine is suitable.

## How it works

- **Diskless Alpine** boots from the key and loads all drivers (modloop).
- An **overlay** (`localhost.apkovl.tar.gz`) replaces the `tty1` login with the validator
  (`validate.sh`) → it runs on its own at startup, writes the report, then shuts the machine down.
- **UEFI** boot simply through the presence of `EFI/BOOT/BOOTX64.EFI` (standalone grub) → **no raw
  write to the key is needed**, you just copy files onto a FAT32 key.

## Building the image (in Docker)

```bash
cd installer/bootable
# produit ./out = les fichiers à copier sur la clé
docker run --rm -v "$PWD:/work/src:ro" -v "$PWD/out:/work/out" alpine:3.20 sh /work/src/build.sh
# (optionnel) tester le boot en QEMU + vérifier qu'un rapport est écrit
docker run --rm -v "$PWD:/work/src:ro" -v "$PWD/out:/work/out:ro" alpine:3.20 sh /work/src/test-boot.sh
```

(The first command produces `./out` = the files to copy onto the key; the second, optional, tests
the boot in QEMU and checks that a report is written.)

## Deploying onto the USB key

The key must be **FAT32** (single partition). **Copy** the `out/` tree to the root — nothing to
format or flash (UEFI boot = files):

```
CLE:\
  EFI\BOOT\BOOTX64.EFI
  boot\vmlinuz-lts, initramfs-lts, modloop-lts, grub\grub.cfg
  localhost.apkovl.tar.gz
  signflow-check.conf
  rapports\        (créé au 1er boot)
```

(`rapports\` is created on first boot.)

Windows (PowerShell), with the key as E::
```powershell
Copy-Item -Recurse -Force .\out\* E:\
```

The key remains a normal FAT32 key (the files of the "manual" test key can coexist on it).

## Using it on a candidate machine

1. Plug in the key, start the machine, enter the boot menu (F12/F11/Esc depending on the BIOS).
2. Choose the USB key in **UEFI** mode.
3. The validator starts on its own → verdict on screen → **report written to the key's
   `rapports\`**.
4. The machine shuts down (40 s); read the report on a PC (`.html`/`.txt` file).

## Configuration

`signflow-check.conf` at the root of the key:
```
BACKEND=https://cms.example.com   # serveur testé (réseau/latence)
PROFILE=fhd                                   # fhd (1080p) ou 4k
```

(`BACKEND` = server tested for network/latency; `PROFILE` = `fhd` (1080p) or `4k`.)

## Limitations

- **UEFI boot** (machines from ~2012 onwards). Pure legacy BIOS is not covered (adding syslinux is
  possible, but requires writing the boot sector — not done, to remain a safe "file copy").
- **Secure Boot**: `BOOTX64.EFI` (standalone grub) is **not signed** → on a machine with Secure
  Boot enabled, booting it fails. Temporarily disable Secure Boot in the BIOS (common on signage
  boxes). shim/MOK signing = future improvement if needed.
- **Resolution** detection is indicative in a live environment (no graphical server).
- Tested in **QEMU/UEFI**; validating on the real target box is still recommended.
