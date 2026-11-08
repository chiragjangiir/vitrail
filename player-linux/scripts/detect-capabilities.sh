#!/usr/bin/env bash
# Detection des capacites de decodage video materiel (VA-API) -> capabilities.json.
#
# Reprend la logique de install.sh SANS apt-get (donc executable par l'utilisateur du
# player, pas besoin de root). Le player lit capabilities.json au boot et le remonte au
# serveur dans player:status ; un restart (ou la commande 'detect_capabilities' depuis
# le CMS) re-applique/re-remonte.
#
# Usage :
#   bash detect-capabilities.sh [chemin/capabilities.json]
# Sans argument, le chemin est calcule = ~/.config/<package.json name> (userData Electron).
#
# Override : SF_HW_DECODE=auto|on|off (off = pas de HW, on = force hw_decode_active=true).
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAYER_DIR="$(dirname "$SCRIPT_DIR")"
SF_HW_DECODE="${SF_HW_DECODE:-auto}"

# Cible : argument explicite, sinon userData Electron (~/.config/<name>).
OUT="${1:-}"
if [ -z "$OUT" ]; then
  APP_NAME="$(grep -m1 '"name"' "$PLAYER_DIR/package.json" 2>/dev/null | sed -E 's/.*"name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')"
  [ -z "$APP_NAME" ] && APP_NAME="signflow-player"
  OUT="$HOME/.config/$APP_NAME/capabilities.json"
fi
mkdir -p "$(dirname "$OUT")"

HW_VENDOR="unknown"; HW_MODEL=""; HW_METHOD="none"; HW_ACTIVE="false"
HW_CODECS="[]"; HW_GL="egl"

if [ "$SF_HW_DECODE" != "off" ]; then
  if command -v lspci >/dev/null 2>&1; then
    GPU_LINE="$(lspci -nn 2>/dev/null | grep -iE 'VGA|3D controller|Display controller' | head -1 || true)"
    HW_MODEL="$(printf '%s' "$GPU_LINE" | sed -E 's/^.*\]: //; s/ \[[0-9a-f]{4}:[0-9a-f]{4}\].*//' | head -c 120)"
    case "$GPU_LINE" in
      *[Ii]ntel*|*8086*)  HW_VENDOR="intel" ;;
      *AMD*|*ATI*|*1002*) HW_VENDOR="amd" ;;
      *NVIDIA*|*10de*)    HW_VENDOR="nvidia" ;;
    esac
  fi
  if [ -e /dev/dri/renderD128 ]; then
    case "$HW_VENDOR" in
      intel|amd) HW_METHOD="vaapi" ;;
      nvidia)    HW_METHOD="none" ;;  # NVDEC proprio non auto-configure
    esac
  fi
  if [ "$HW_METHOD" = "vaapi" ] && command -v vainfo >/dev/null 2>&1; then
    VA_OUT="$(vainfo 2>/dev/null || true)"
    CODECS=()
    echo "$VA_OUT" | grep -q "VAProfileH264" && CODECS+=('"h264"') || true
    echo "$VA_OUT" | grep -q "VAProfileHEVC" && CODECS+=('"hevc"') || true
    echo "$VA_OUT" | grep -q "VAProfileVP9"  && CODECS+=('"vp9"')  || true
    echo "$VA_OUT" | grep -q "VAProfileAV1"  && CODECS+=('"av1"')  || true
    HW_CODECS="[$(IFS=,; echo "${CODECS[*]:-}")]"
  fi
fi

# Voie mpv (decode HW VAAPI alternatif au <video> Chromium). Pas d'apt ici (sans root) :
# on detecte la PRESENCE de mpv (installe par install.sh) + un profil decode VLD.
MPV_VAAPI="false"
if [ "$SF_HW_DECODE" != "off" ] && [ "$HW_METHOD" = "vaapi" ] \
   && command -v mpv >/dev/null 2>&1 && [ "$HW_CODECS" != "[]" ]; then
  MPV_VAAPI="true"
fi
# Sur Linux/Electron la VA-API n'est pas reellement declenchee (cf. EVOLUTIONS) -> false
# par defaut (le CMS alerte « GPU detecte mais decodage inactif »). SF_HW_DECODE=on force.
[ "$SF_HW_DECODE" = "on" ] && HW_ACTIVE="true"

SF_CAP_VENDOR="$HW_VENDOR" SF_CAP_MODEL="$HW_MODEL" SF_CAP_METHOD="$HW_METHOD" \
SF_CAP_ACTIVE="$HW_ACTIVE" SF_CAP_CODECS="$HW_CODECS" SF_CAP_GL="$HW_GL" \
SF_CAP_MODE="$SF_HW_DECODE" SF_CAP_MPV_VAAPI="$MPV_VAAPI" \
python3 - "$OUT" <<'PYCAP'
import json, os, sys, datetime
method = os.environ.get("SF_CAP_METHOD", "none")
flags = []
if method == "vaapi":
    flags = ["--ignore-gpu-blocklist",
             "--enable-features=VaapiVideoDecoder,VaapiVideoDecodeLinuxGL",
             "--disable-features=UseChromeOSDirectVideoDecoder",
             "--disable-gpu-driver-bug-workarounds"]
try:
    codecs = json.loads(os.environ.get("SF_CAP_CODECS") or "[]")
except Exception:
    codecs = []
data = {
    "gpu_vendor": os.environ.get("SF_CAP_VENDOR", "unknown"),
    "gpu_model": os.environ.get("SF_CAP_MODEL", ""),
    "hw_decode": method,
    "hw_decode_active": os.environ.get("SF_CAP_ACTIVE") == "true",
    "codecs": codecs,
    "gl_backend": os.environ.get("SF_CAP_GL", "egl"),
    "sf_hw_decode": os.environ.get("SF_CAP_MODE", "auto"),
    "mpv_vaapi": os.environ.get("SF_CAP_MPV_VAAPI") == "true",
    "chromium_flags": flags,
    "detection_source": "manual",
    "detected_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
with open(sys.argv[1], "w") as f:
    json.dump(data, f, indent=2)
print("[detect] %s -> vendor=%s method=%s active=%s codecs=%s" % (
    sys.argv[1], data["gpu_vendor"], data["hw_decode"], data["hw_decode_active"],
    ",".join(codecs) or "-"))
PYCAP
