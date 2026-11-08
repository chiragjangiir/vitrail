#!/usr/bin/env bash
# vaapi-diag.sh — Boucle de diagnostic VA-API pour le player Linux (Intel/Gemini Lake).
#
# Lance le vrai player avec un PROFIL de flags (cf. src/vaapi_profiles.js) + un log
# Chromium verbeux ciblé VA-API, échantillonne intel_gpu_top (engine Video = vérité
# terrain), puis extrait les lignes de décision VA-API du log.
#
#   sudo ./vaapi-diag.sh [profil] [duree_s]
#   sudo ./vaapi-diag.sh gl-angle 25
#
# Profils dispo : current gl-angle gl-egl gl-desktop gl-angle-core gl-vulkan
#
# Pré-requis : un média vidéo (idéalement 4K H.264) doit être programmé sur ce
# player (la playlist du mur d'images convient). Lancer en root (su vers le user).
# Après le diag, l'autostart ne relance PAS le player → reboot pour revenir au kiosk.
set -uo pipefail

PROFILE="${1:-gl-angle}"
DURATION="${2:-25}"
SERVICE_USER="${SERVICE_USER:-signflow}"
PLAYER_DIR="${PLAYER_DIR:-/opt/signflow/player-linux}"
USERDATA="/home/$SERVICE_USER/.config/signflow-player"
CHROMIUM_LOG="$USERDATA/logs/chromium.log"
ELECTRON_BIN="$PLAYER_DIR/node_modules/.bin/electron"

echo "==================================================================="
echo " VA-API diag : profil=$PROFILE  duree=${DURATION}s  user=$SERVICE_USER"
echo " player=$PLAYER_DIR"
echo "==================================================================="

echo "-- 1. vainfo (support VA-API au niveau OS) --"
vainfo 2>/dev/null | grep -E "Driver version|VAProfileH264|VAProfileHEVCMain" \
  || echo "   vainfo indisponible (apt install vainfo intel-media-va-driver)"

echo "-- 2. arret du/des player(s) en cours (instance unique = pas de collision DRM 1002) --"
pkill -f "$PLAYER_DIR" 2>/dev/null || true
for i in $(seq 1 10); do
  pgrep -f "$PLAYER_DIR" >/dev/null 2>&1 || break
  sleep 1
  pkill -9 -f "$PLAYER_DIR" 2>/dev/null || true
done
sleep 1
rm -f "$USERDATA"/Singleton* 2>/dev/null || true
rm -f "$CHROMIUM_LOG" 2>/dev/null || true
: > /tmp/vaapi-diag-stderr.log

echo "-- 3. lancement du player (profil=$PROFILE, verbeux) sur DISPLAY=:0 --"
su - "$SERVICE_USER" -c \
  "DISPLAY=:0 SF_VAAPI_PROFILE='$PROFILE' SF_VLOG=2 '$ELECTRON_BIN' '$PLAYER_DIR'" \
  >/tmp/vaapi-diag-stderr.log 2>&1 &
sleep 8   # laisse le temps de se connecter + demarrer la lecture

echo "-- 4. echantillon intel_gpu_top (engine 'Video' % > 0 = decodage HW) --"
if command -v intel_gpu_top >/dev/null 2>&1; then
  timeout 6 intel_gpu_top -o - 2>/dev/null | head -16 || true
else
  echo "   intel_gpu_top absent (apt install intel-gpu-tools)"
fi

echo "-- 5. lecture en cours encore ${DURATION}s... --"
sleep "$DURATION"

echo "-- 6. arret du player de diagnostic --"
pkill -f "$PLAYER_DIR" 2>/dev/null || true
sleep 1

# Le decodage VA-API vit dans le GPU process -> logge sur stderr (capte ici),
# PAS dans chromium.log (process navigateur uniquement).
echo "-- 7. lignes de decision VA-API (stderr du GPU process) --"
SRC="/tmp/vaapi-diag-stderr.log"
grep -aiE "vaapi|VA-API|VaapiVideoDecoder|frame pool|framepool|video.?decode|GpuVideoDecode|gpu process|error_code|hardware video|software|fallback|fell back|not (supported|available)|disabled|native_pixmap|pixmap|gpu_memory_buffer|gbm|allocat|create.*buffer|buffer.*format|modifier|coded.?size|unsupported|NV12|P010" \
  "$SRC" | grep -aivE "alsa|pulseaudio" | tail -70 || echo "   (aucune ligne VA-API trouvee dans $SRC)"

echo "==================================================================="
echo " Verdict : Video% > 0 dans (4) ET 'VaapiVideoDecoder ... Initialize' dans (7)"
echo "           = HW decode ACTIF. Sinon (7) dit pourquoi ca retombe en soft."
echo " Restaurer le kiosk normal : sudo reboot"
echo "==================================================================="
