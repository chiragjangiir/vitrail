#!/bin/sh
# Customise l'image officielle Raspberry Pi OS Lite (arm64) en image d'appliance SignFlow prête à
# flasher : injecte player-rpi + un service systemd de PREMIER BOOT (firstboot.sh) qui lit le
# payload de provisioning et pose le player. « Customisation type Pi Imager », côté serveur.
#
# À lancer DANS un conteneur Alpine PRIVILÉGIÉ (loop + device-mapper) :
#   docker run --rm --privileged \
#     -v "$PWD:/work/src:ro" -v "$REPO:/work/repo:ro" \
#     -v "$PWD/out:/work/out" -v "$PWD/cache:/work/cache" \
#     alpine:3.20 sh /work/src/build.sh
# Produit /work/out/signflow-rpi.img (à flasher avec Raspberry Pi Imager / dd).
set -eu

SRC=/work/src          # firstboot.sh
REPO=/work/repo        # racine du dépôt (pour player-rpi/)
OUT=/work/out
CACHE=/work/cache
WORK=/work/tmp
IMG_URL="${IMG_URL:-https://downloads.raspberrypi.com/raspios_lite_arm64_latest}"

echo "[1/7] Outils de build"
apk add --no-cache wget xz util-linux e2fsprogs dosfstools multipath-tools rsync openssl >/dev/null

echo "[2/7] Image Raspberry Pi OS Lite (arm64)"
mkdir -p "$WORK" "$OUT" "$CACHE"
XZ="$CACHE/raspios_lite_arm64.img.xz"
if [ -s "$XZ" ]; then
    echo "     - image (cache) $(du -h "$XZ" | cut -f1)"
else
    echo "     - téléchargement (~500 Mo)…"
    wget -q -O "$XZ" "$IMG_URL"
    echo "     - téléchargé $(du -h "$XZ" | cut -f1)"
fi
IMG="$WORK/signflow-rpi.img"
echo "     - décompression → $(basename "$IMG")"
xz -dc "$XZ" > "$IMG"
echo "     - image brute $(du -h "$IMG" | cut -f1)"

echo "[3/7] Montage (losetup + kpartx)"
LD=$(losetup -f --show "$IMG")
kpartx -as "$LD" >/dev/null
base=$(basename "$LD")
BOOTP="/dev/mapper/${base}p1"   # FAT (bootfs)
ROOTP="/dev/mapper/${base}p2"   # ext4 (rootfs)
sleep 1
mkdir -p "$WORK/boot" "$WORK/root"
mount "$BOOTP" "$WORK/boot"
mount "$ROOTP" "$WORK/root"
echo "     - boot=$BOOTP root=$ROOTP"

cleanup() {
    sync
    umount "$WORK/boot" 2>/dev/null || true
    umount "$WORK/root" 2>/dev/null || true
    kpartx -d "$LD" 2>/dev/null || true
    losetup -d "$LD" 2>/dev/null || true
}
trap cleanup EXIT

echo "[4/7] Injection de player-rpi → /opt/signflow/player-rpi"
mkdir -p "$WORK/root/opt/signflow/player-rpi"
rsync -a --exclude 'node_modules' --exclude 'dist' \
    "$REPO/player-rpi/" "$WORK/root/opt/signflow/player-rpi/"
sed -i 's/\r$//' "$WORK/root/opt/signflow/player-rpi/install.sh" 2>/dev/null || true

echo "[5/7] Service systemd de premier boot"
install -m 0755 "$SRC/firstboot.sh" "$WORK/root/opt/signflow/signflow-firstboot.sh"
sed -i 's/\r$//' "$WORK/root/opt/signflow/signflow-firstboot.sh"
cat > "$WORK/root/etc/systemd/system/signflow-firstboot.service" <<'EOF'
[Unit]
Description=SignFlow premier boot (provisioning + installation du player)
After=network-online.target time-sync.target
Wants=network-online.target time-sync.target
ConditionPathExists=/opt/signflow/player-rpi/install.sh

[Service]
Type=oneshot
ExecStart=/opt/signflow/signflow-firstboot.sh
RemainAfterExit=yes
StandardOutput=journal+console

[Install]
WantedBy=multi-user.target
EOF
# activation = symlink dans multi-user.target.wants (pas de systemctl dispo hors du système)
mkdir -p "$WORK/root/etc/systemd/system/multi-user.target.wants"
ln -sf ../signflow-firstboot.service \
    "$WORK/root/etc/systemd/system/multi-user.target.wants/signflow-firstboot.service"

echo "[6/7] Payload de provisioning (partition boot) + SSH"
cat > "$WORK/boot/signflow-provision.json" <<'EOF'
{
  "ref": "RPi - a nommer",
  "os": "rpi",
  "backend_url": "https://cms.example.com",
  "token": "sfp_REMPLACER_PAR_LE_TOKEN_DE_PROVISIONING"
}
EOF
touch "$WORK/boot/ssh"   # SSH activé (dépannage terrain ; retirer si non voulu)

# userconf.txt — SANS LUI L'IMAGE N'EST PAS AUTONOME AU PREMIER BOOT.
# Raspberry Pi OS n'a plus de compte par défaut : sans ce fichier, le premier démarrage
# s'arrête sur son assistant de configuration et ATTEND un clavier (« Which user would you
# like to rename ») — constaté en réel le 2026-08-09 sur un RPi du parc. Une image greenfield
# qui réclame un humain sur site ne remplit pas le contrat de ce canal.
# Le compte doit s'appeler comme SERVICE_USER de firstboot.sh (« signflow ») : c'est pour lui
# qu'install.sh configure la session kiosk, et firstboot.sh ne le recrée pas s'il existe déjà.
RPI_USER="${RPI_USER:-signflow}"
RPI_PASSWORD="${RPI_PASSWORD:-}"
PASS_GENERATED=0
if [ -z "$RPI_PASSWORD" ]; then
    # Jamais de mot de passe en dur : toutes les images partageraient le même.
    RPI_PASSWORD=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 16)
    PASS_GENERATED=1
fi
printf '%s:%s\n' "$RPI_USER" "$(openssl passwd -6 "$RPI_PASSWORD")" > "$WORK/boot/userconf.txt"

# ⚠️ userconf.txt cree le compte mais ne lui donne AUCUN privilege — mesure le 2026-08-09 :
# `id` ne rend que son propre groupe. Sans sudo, la machine est ININSTALLABLE A DEPANNER :
# on ne peut ni lire `journalctl -u signflow-firstboot`, ni relancer le service, ni rien
# corriger sur site. C'est exactement ce qui a bloque le diagnostic ce jour-la.
# On accorde donc sudo explicitement, dans le rootfs (le seul endroit qui survit au 1er boot).
mkdir -p "$WORK/root/etc/sudoers.d"
printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$RPI_USER" > "$WORK/root/etc/sudoers.d/010-signflow"
chmod 0440 "$WORK/root/etc/sudoers.d/010-signflow"   # sudo REFUSE un fichier plus permissif
echo "     - boot/signflow-provision.json + boot/ssh + boot/userconf.txt (compte $RPI_USER)"
echo "     - root/etc/sudoers.d/010-signflow (sans lui, aucun depannage possible sur site)"

echo "[7/7] Vérification de l'injection"
ok=1
[ -f "$WORK/root/opt/signflow/player-rpi/install.sh" ] || { echo "  MANQUE player-rpi/install.sh"; ok=0; }
[ -f "$WORK/root/opt/signflow/signflow-firstboot.sh" ] || { echo "  MANQUE firstboot.sh"; ok=0; }
[ -L "$WORK/root/etc/systemd/system/multi-user.target.wants/signflow-firstboot.service" ] || { echo "  MANQUE l'activation du service"; ok=0; }
[ -f "$WORK/boot/signflow-provision.json" ] || { echo "  MANQUE le payload boot"; ok=0; }
# Sans userconf.txt l'image demande un clavier au premier boot : c'est un échec de build,
# pas un détail — l'image serait inutilisable en pose sans écran ni opérateur.
[ -s "$WORK/boot/userconf.txt" ] || { echo "  MANQUE boot/userconf.txt (1er boot bloquerait)"; ok=0; }

cleanup
trap - EXIT
mv "$IMG" "$OUT/signflow-rpi.img"
echo "     - out/signflow-rpi.img ($(du -h "$OUT/signflow-rpi.img" | cut -f1))"
if [ "$ok" = 1 ]; then
    # Un mot de passe généré puis jamais affiché serait perdu : on le rend, et on l'écrit
    # à côté de l'image (le technicien en a besoin pour le dépannage SSH sur site).
    printf '%s\n' "user=$RPI_USER" "password=$RPI_PASSWORD" > "$OUT/signflow-rpi.credentials.txt"
    echo "     - compte système : $RPI_USER / $RPI_PASSWORD"
    if [ "$PASS_GENERATED" = 1 ]; then
        echo "       (généré aléatoirement — passer RPI_PASSWORD=… pour en imposer un)"
    fi
    echo "       également écrit dans out/signflow-rpi.credentials.txt"
    echo "RESULT: OK (image RPi customisée + injection vérifiée)"
else
    echo "RESULT: KO (injection incomplète — voir ci-dessus)"; exit 1
fi
