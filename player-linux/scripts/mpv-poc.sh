#!/usr/bin/env bash
# mpv-poc.sh - SPIKE Phase 0 (jetable) : lever les inconnues AVANT d'integrer mpv.
# Cf. docs/SPIKE_mpv_hwdecode_linux.md.
#
# Valide sur le HW Intel/Linux (riri/fifi/NUC) :
#   (a) mpv decode la video en HW VAAPI plein ecran (--hwdec=vaapi --vo=gpu)
#   (c) mpv expose un IPC JSON pilotable (load/seek/speed/time-pos/end-file)
#   (b) z-order : mpv peut passer AU-DESSUS puis SOUS la fenetre Electron kiosk
#
# Usage (sur le player, en session graphique = depuis un terminal de la session X,
#        PAS en SSH sans DISPLAY) :
#   bash mpv-poc.sh /chemin/vers/video.mp4
#   bash mpv-poc.sh https://.../video.mp4
#
# Pendant le test, dans un 2e terminal :
#   intel_gpu_top         # moteur "Video" doit grimper (~50-70%) = decode HW reel
#
# Le script lance mpv en --idle avec un socket IPC, puis enchaine :
#   1. charge la video, lit hwdec-current (doit etre 'vaapi' et PAS 'no')
#   2. lit time-pos, met speed=1.05 puis 1.0, seek absolu (test du nudge LAN)
#   3. toggle 'ontop' yes/no toutes les 4s x4 (observer le z-order vs le kiosk)
# Ctrl-C pour finir (le script tue mpv proprement).
set -u

SRC="${1:-}"
SOCK="/tmp/mpv-poc.sock"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== mpv HW-decode PoC (Phase 0) ==="

# --- Prerequis -----------------------------------------------------------------
command -v mpv >/dev/null 2>&1 || { echo "ERREUR: mpv absent. -> sudo apt install -y mpv"; exit 1; }
echo "[ok] mpv: $(mpv --version | head -1)"

if command -v vainfo >/dev/null 2>&1; then
  echo "[vaapi] profils decode disponibles :"
  vainfo 2>/dev/null | grep -iE 'VAProfile.*(H264|HEVC|VP9|AV1)' | grep -i 'VAEntrypointVLD' \
    | sed 's/^/    /' || echo "    (aucun profil VLD liste - VAAPI peut-etre KO)"
else
  echo "[warn] vainfo absent (vainfo = paquet vainfo / intel-media-va-driver). On tente quand meme."
fi

if [ -z "$SRC" ]; then
  echo
  echo "Aucune video fournie. Usage: bash mpv-poc.sh <fichier|url>"
  echo "(idealement un H.264 1080p ou 4K pour voir le moteur Video grimper)"
  exit 1
fi

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "[warn] ni DISPLAY ni WAYLAND_DISPLAY : lance ce script depuis la session graphique du player."
fi

# --- Lancement mpv en --idle + IPC ---------------------------------------------
rm -f "$SOCK"
echo
echo "[mpv] lancement (fullscreen, hwdec=vaapi, vo=gpu, IPC=$SOCK)..."
mpv --idle=yes --force-window=yes --fullscreen=yes --no-border \
    --hwdec=vaapi --vo=gpu --gpu-context=x11egl \
    --no-osc --no-input-default-bindings --really-quiet \
    --input-ipc-server="$SOCK" &
MPV_PID=$!

cleanup() { echo; echo "[mpv] arret (pid $MPV_PID)"; kill "$MPV_PID" 2>/dev/null; rm -f "$SOCK"; }
trap cleanup EXIT INT TERM

# Attendre que le socket soit pret
for _ in $(seq 1 50); do [ -S "$SOCK" ] && break; sleep 0.1; done
[ -S "$SOCK" ] || { echo "ERREUR: socket IPC mpv jamais cree"; exit 1; }
echo "[ok] socket IPC pret."

# --- Test IPC (decode + nudge LAN) via Node ------------------------------------
# Le player a Node (install.sh installe Node 20). On delegue le pilotage fin a un
# script Node qui parle le protocole JSON-lines de mpv.
if command -v node >/dev/null 2>&1; then
  echo
  echo "[ipc] test de pilotage (charge la video, lit hwdec/time-pos, nudge speed, seek)..."
  node "$SCRIPT_DIR/mpv-poc-ipc.mjs" "$SOCK" "$SRC" || echo "[warn] test IPC Node en erreur (voir ci-dessus)"
else
  echo "[warn] node absent du PATH : on charge la video en direct (pas de test IPC fin)."
  printf '{ "command": ["loadfile", "%s", "replace"] }\n' "$SRC" | socat - "UNIX-CONNECT:$SOCK" 2>/dev/null \
    || echo "[warn] socat absent aussi : impossible de charger via IPC."
fi

# --- Test z-order vs le kiosk Electron -----------------------------------------
echo
echo "[zorder] === OBSERVE L'ECRAN === : mpv va alterner AU-DESSUS / EN-DESSOUS (4s chacun, x4)."
echo "          Au-dessus = video mpv visible. En-dessous = le kiosk Electron (UI) revient."
echo "          Note : flicker ? perte de focus kiosk ? bandes noires ? -> remonte-le."
mpv_set() { printf '{ "command": ["set_property", "%s", %s] }\n' "$1" "$2" | socat - "UNIX-CONNECT:$SOCK" >/dev/null 2>&1; }

if ! command -v socat >/dev/null 2>&1; then
  echo "[warn] socat absent : pas de toggle ontop automatique. -> sudo apt install -y socat"
  echo "       (le decode + l'IPC Node restent valides ; teste le z-order a la main avec wmctrl/xdotool)"
fi

for i in 1 2 3 4; do
  echo "  [$i] mpv ON TOP (au-dessus du kiosk)"
  mpv_set ontop true
  sleep 4
  echo "  [$i] mpv NORMAL (le kiosk doit reapparaitre)"
  mpv_set ontop false
  # Aide a faire repasser le kiosk devant si le WM ne le fait pas seul :
  command -v wmctrl >/dev/null 2>&1 && wmctrl -a "SignFlow" >/dev/null 2>&1 || true
  sleep 4
done

echo
echo "[done] PoC termine. Verdict a reporter :"
echo "  (a) decode HW   : hwdec-current=vaapi (log ci-dessus) + moteur Video monte sous intel_gpu_top ?"
echo "  (c) IPC         : loadfile/time-pos/speed/seek ont repondu sans erreur ?"
echo "  (b) z-order     : mpv passe proprement au-dessus PUIS sous le kiosk, sans flicker/perte focus ?"
echo "Ctrl-C si mpv est encore a l'ecran."
wait "$MPV_PID"
