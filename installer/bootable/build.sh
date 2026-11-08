#!/bin/sh
# Construit l'arbre d'une clé USB bootable de validation matérielle SignFlow.
# À lancer DANS un conteneur Alpine (voir Dockerfile.build / la commande docker du README).
# Produit /work/out = les fichiers à copier tels quels à la racine d'une clé FAT32 (boot UEFI).
set -eu

ALPINE_VER="${ALPINE_VER:-3.20}"
ARCH=x86_64
MIRROR="https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VER}/releases/${ARCH}"
SRC=/work/src        # validate.sh monté ici
OUT=/work/out
WORK=/work/tmp

echo "[1/6] Outils de build"
apk add --no-cache wget tar gzip grub grub-efi libarchive-tools >/dev/null

echo "[2/6] Téléchargement + extraction de l'ISO Alpine standard ${ALPINE_VER}"
# ISO STANDARD (kernel lts = TOUS les pilotes matériels, ≠ virt qui n'a que virtio). Contient le
# dépôt local /apks (indispensable au boot diskless) + boot/ (kernel/initramfs/modloop). On copie
# ces éléments sur la clé → l'init Alpine scanne le média, monte modloop et installe la base.
ISO=$(wget -q -O- "${MIRROR}/" | grep -o "alpine-standard-${ALPINE_VER}[0-9.]*-${ARCH}\.iso" | sort -u | tail -1)
[ -n "$ISO" ] || { echo "ISO introuvable"; exit 1; }
mkdir -p "$WORK" "$OUT/boot/grub" "$OUT/EFI/BOOT"
# cache optionnel (/work/cache monté) pour éviter de re-télécharger l'ISO à chaque build
if [ -f "/work/cache/$ISO" ]; then
    cp "/work/cache/$ISO" "$WORK/alpine.iso"; echo "     - $ISO (cache)"
else
    wget -q -O "$WORK/alpine.iso" "${MIRROR}/${ISO}"
    [ -d /work/cache ] && cp "$WORK/alpine.iso" "/work/cache/$ISO" 2>/dev/null || true
    echo "     - $ISO ($(du -h "$WORK/alpine.iso" | cut -f1))"
fi
mkdir -p "$WORK/iso"
bsdtar -C "$WORK/iso" -xf "$WORK/alpine.iso" boot apks 2>/dev/null || bsdtar -C "$WORK/iso" -xf "$WORK/alpine.iso"
# boot : kernel + initramfs + modloop (de l'ISO)
cp "$WORK/iso/boot/vmlinuz-lts" "$WORK/iso/boot/initramfs-lts" "$WORK/iso/boot/modloop-lts" "$OUT/boot/"
# dépôt local (base packages) → nécessaire pour construire le système à froid
cp -a "$WORK/iso/apks" "$OUT/apks"
for f in vmlinuz-lts initramfs-lts modloop-lts; do echo "     - boot/$f ($(du -h "$OUT/boot/$f" | cut -f1))"; done
echo "     - apks/ ($(du -sh "$OUT/apks" | cut -f1))"

echo "[3/6] Overlay auto-run (apkovl)"
OVL="$WORK/ovl"
mkdir -p "$OVL/usr/local/bin" "$OVL/etc/local.d" "$OVL/etc/runlevels/default" "$OVL/etc"
install -m 0755 "$SRC/validate.sh" "$OVL/usr/local/bin/validate.sh"
# Lance le validateur sur tty1 au démarrage puis éteint après lecture.
cat > "$OVL/usr/local/bin/sf-run.sh" <<'EOF'
#!/bin/sh
exec >/dev/tty1 2>&1 </dev/tty1
# laisse le coldplug finir de charger les modules (réseau/stockage/GPU) : attendre l'apparition
# d'une interface réseau réelle (le dossier /sys/class/net existe toujours, même avec juste lo).
i=0; while [ $i -lt 10 ] && ! ls /sys/class/net/ 2>/dev/null | grep -qvx lo; do sleep 1; i=$((i+1)); done
sleep 2
clear 2>/dev/null
/usr/local/bin/validate.sh
echo
echo "  Extinction dans 40s. (Entree = shell)"
read -t 40 _ || true
poweroff
EOF
chmod 0755 "$OVL/usr/local/bin/sf-run.sh"
# inittab : tty1 exécute le validateur au lieu d'un login
cat > "$OVL/etc/inittab" <<'EOF'
::sysinit:/sbin/openrc sysinit
::sysinit:/sbin/openrc boot
::wait:/sbin/openrc default
tty1::respawn:/usr/local/bin/sf-run.sh
::ctrlaltdel:/sbin/reboot
::shutdown:/sbin/openrc shutdown
EOF
# apkovl = tar gz de la racine de l'overlay
( cd "$OVL" && tar -czf "$OUT/localhost.apkovl.tar.gz" . )
echo "     - localhost.apkovl.tar.gz ($(du -h "$OUT/localhost.apkovl.tar.gz" | cut -f1))"

echo "[4/6] Configuration grub (UEFI)"
# cmdline = celle de l'ISO Alpine standard + vfat (lecture du média FAT) + console tty1 (écran).
CMDLINE="modules=loop,squashfs,sd-mod,usb-storage,vfat console=tty1 quiet"
cat > "$OUT/boot/grub/grub.cfg" <<EOF
set timeout=3
set default=0
menuentry "SignFlow - Validation materielle du player" {
    linux /boot/vmlinuz-lts ${CMDLINE}
    initrd /boot/initramfs-lts
}
EOF

echo "[5/6] Bootloader UEFI (BOOTX64.EFI autonome)"
# config embarquée : trouve la partition qui porte le noyau puis charge le grub.cfg de la clé
cat > "$WORK/embed.cfg" <<'EOF'
search --no-floppy --file --set=root /boot/vmlinuz-lts
set prefix=($root)/boot/grub
configfile /boot/grub/grub.cfg
EOF
grub-mkstandalone -O x86_64-efi \
    --modules="part_gpt part_msdos fat search configfile normal linux echo" \
    -o "$OUT/EFI/BOOT/BOOTX64.EFI" \
    "boot/grub/grub.cfg=$WORK/embed.cfg" >/dev/null 2>&1
echo "     - EFI/BOOT/BOOTX64.EFI ($(du -h "$OUT/EFI/BOOT/BOOTX64.EFI" | cut -f1))"

echo "[6/6] Config par défaut + LISEZMOI"
cat > "$OUT/signflow-check.conf" <<EOF
# Serveur SignFlow à tester (réseau/latence) + profil (fhd|4k)
BACKEND=https://cms.example.com
PROFILE=fhd
EOF

echo "OK -> $OUT"
du -sh "$OUT"
