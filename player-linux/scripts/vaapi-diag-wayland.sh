#!/usr/bin/env bash
# vaapi-diag-wayland.sh — Confirme si la VA-API se debloque sous Wayland (cage)
# sur un player Linux/Intel, SANS modifier la conf de session ni rebooter.
#
# X11 ne fournit pas le chemin NativePixmap/dma-buf dont le frame pool VA-API a
# besoin (constat NUC : 3 backends ANGLE echouent tous "failed Initialize()ing
# the frame pool"). Sous Ozone/Wayland ce chemin existe. Ce script stoppe X,
# lance le player sous cage sur un VT (openvt), echantillonne intel_gpu_top,
# puis relance X. 100% reversible.
#
#   sudo ./vaapi-diag-wayland.sh [profil] [duree_s]
#   sudo ./vaapi-diag-wayland.sh wayland 25
#
# Pre-requis : sudo apt install -y cage kbd intel-gpu-tools vainfo
set -uo pipefail

PROFILE="${1:-wayland}"
DURATION="${2:-25}"
SERVICE_USER="${SERVICE_USER:-signflow}"
PLAYER_DIR="${PLAYER_DIR:-/opt/signflow/player-linux}"
ELECTRON_BIN="$PLAYER_DIR/node_modules/.bin/electron"
LOG=/tmp/vaapi-diag-stderr.log

echo "==================================================================="
echo " VA-API diag WAYLAND : profil=$PROFILE  duree=${DURATION}s  user=$SERVICE_USER"
echo "==================================================================="

for bin in cage openvt intel_gpu_top; do
  command -v "$bin" >/dev/null 2>&1 || { echo "MANQUE: $bin (sudo apt install -y cage kbd intel-gpu-tools)"; exit 1; }
done

echo "-- 1. vainfo --"
vainfo 2>/dev/null | grep -E "Driver version|VAProfileH264High" || echo "   vainfo indisponible"

echo "-- 2. arret de X (lightdm) pour liberer le DRM master --"
systemctl stop lightdm 2>/dev/null || true
pkill -f "$PLAYER_DIR" 2>/dev/null || true
for i in $(seq 1 8); do pgrep -f "$PLAYER_DIR" >/dev/null 2>&1 || break; sleep 1; pkill -9 -f "$PLAYER_DIR" 2>/dev/null || true; done
pkill cage 2>/dev/null || true
sleep 2

echo "-- 3. lancement cage + player (profil=$PROFILE, verbeux) sur un nouveau VT --"
: > "$LOG"; chmod 666 "$LOG"
# cage exige XDG_RUNTIME_DIR (su - ne le propage pas) : on le cree + l'exporte.
RUID="$(id -u "$SERVICE_USER")"
RUNTIME="/run/user/$RUID"
mkdir -p "$RUNTIME"; chown "$SERVICE_USER:$SERVICE_USER" "$RUNTIME"; chmod 700 "$RUNTIME"
# openvt alloue un VT (-s y bascule, -w attend) ; su - ouvre une session logind
# sur le seat du VT -> DRM master pour cage. Redirection DANS le -c pour capter
# le stderr de cage+electron (sinon il part sur le VT).
openvt -s -w -- su - "$SERVICE_USER" -c \
  "export XDG_RUNTIME_DIR='$RUNTIME'; SF_VAAPI_PROFILE='$PROFILE' SF_VLOG=2 cage -- '$ELECTRON_BIN' '$PLAYER_DIR' > '$LOG' 2>&1" &
OPENVT_PID=$!
sleep 10   # laisse cage + electron demarrer + se connecter + jouer

echo "-- 4. intel_gpu_top (colonne 'VCS/0' Video % > 0 = decodage HW) --"
timeout 6 intel_gpu_top -o - 2>/dev/null | head -16 || true

echo "-- 5. lecture encore ${DURATION}s... --"
sleep "$DURATION"

echo "-- 6. arret du player de test --"
pkill -f "$PLAYER_DIR" 2>/dev/null || true
pkill cage 2>/dev/null || true
kill "$OPENVT_PID" 2>/dev/null || true
sleep 1
chvt 1 2>/dev/null || true

echo "-- 7. lignes de decision VA-API --"
grep -aiE "vaapi|frame pool|VaapiVideoDecoder|video.?decode|error_code|exit_code|wayland|ozone|gbm|native_pixmap|fallback|software|not (supported|available)" \
  "$LOG" | grep -aivE "alsa|pulse" | tail -50 || echo "   (rien — voir $LOG en entier)"

echo "-- 8. restauration de X (kiosk normal) --"
systemctl start lightdm 2>/dev/null || true

echo "==================================================================="
echo " Verdict : VCS/0 > 0 en (4) ET plus de 'failed Initialize()ing the frame"
echo "           pool' en (7) = WAYLAND DEBLOQUE LA VA-API."
echo "           -> on installe alors la session cage permanente sur le NUC."
echo "==================================================================="
