#!/bin/sh
# Teste le boot UEFI de la clé (arbre /work/out) dans QEMU + vérifie que le validateur
# a bien écrit un rapport sur le disque. À lancer dans un conteneur Alpine.
set -eu
OUT=/work/out
IMG=/work/usb.img

echo "[1/4] Outils QEMU + OVMF"
apk add --no-cache qemu-system-x86_64 ovmf dosfstools mtools >/dev/null

# firmware COMBINÉ (code+vars), pas OVMF_VARS.fd seul
OVMF=/usr/share/OVMF/OVMF.fd
[ -f "$OVMF" ] || OVMF=$(find / -name 'OVMF.fd' 2>/dev/null | head -1)
[ -f "$OVMF" ] || { echo "OVMF.fd introuvable"; exit 1; }
echo "     OVMF=$OVMF"

echo "[2/4] Image FAT32 « SIGNFLOW » (250 Mo) depuis $OUT"
dd if=/dev/zero of="$IMG" bs=1M count=250 status=none
mkfs.vfat -n SIGNFLOW "$IMG" >/dev/null
# copie récursive de l'arbre out/ à la racine (mtools, pas de mount)
for e in "$OUT"/*; do mcopy -Q -i "$IMG" -s "$e" ::/ ; done
echo "     contenu : $(mdir -i "$IMG" :: | grep -c '')"
# TEST uniquement : ajoute une console série pour capter les logs noyau dans QEMU
sed 's#console=tty1#console=tty1 console=ttyS0,115200#' "$OUT/boot/grub/grub.cfg" > /work/grub.test.cfg
mcopy -Q -o -i "$IMG" /work/grub.test.cfg ::/boot/grub/grub.cfg

echo "[3/4] Boot QEMU UEFI (TCG, ~2-4 min)…"
cp "$OVMF" /work/ovmf.fd
# TCG (pas de KVM en conteneur) ; -serial pour capter les logs noyau ; poweroff auto au bout de 40s
timeout 300 qemu-system-x86_64 \
    -machine q35 -m 2048 -smp 2 \
    -drive if=pflash,format=raw,file=/work/ovmf.fd \
    -drive file="$IMG",format=raw,if=virtio \
    -nographic -serial mon:stdio -no-reboot 2>&1 | tail -40 || true

echo "[4/4] Vérification : rapport écrit sur la clé ?"
if mdir -i "$IMG" ::/rapports >/dev/null 2>&1; then
    echo "  RAPPORTS trouvés :"
    mdir -i "$IMG" ::/rapports
    f=$(mdir -i "$IMG" -b ::/rapports 2>/dev/null | grep -i '\.txt$' | head -1)
    if [ -n "$f" ]; then
        echo "  --- contenu ---"; mtype -i "$IMG" "$f"
    fi
    echo "RESULT: OK (le validateur a booté et écrit un rapport)"
else
    echo "RESULT: KO (pas de rapport — voir les logs de boot ci-dessus)"
fi
