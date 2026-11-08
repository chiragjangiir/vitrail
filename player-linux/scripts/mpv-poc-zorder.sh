#!/usr/bin/env bash
# mpv-poc-zorder.sh - SPIKE Phase 0 : confirmation z-order LENTE et ETIQUETEE.
# Cf. docs/SPIKE_mpv_hwdecode_linux.md. Complement de mpv-poc.sh (toggle trop rapide a suivre).
#
# 3 cycles de 7s : MPV DEVANT (gros bandeau incruste "MPV DEVANT - cycle N") puis MPV DERRIERE
# (le kiosk SignFlow doit revenir). Le bandeau rend mpv impossible a confondre avec le kiosk.
#
# Usage (session graphique) : DISPLAY=:0 bash mpv-poc-zorder.sh <video>
set -u
V="${1:?usage: mpv-poc-zorder.sh <video>}"
SOCK=/tmp/mpv-zt.sock
rm -f "$SOCK"

# Titre unique -> wmctrl peut cibler la fenetre mpv pour le RAISE explicite.
MPV_TITLE="SIGNFLOW-MPV-POC"
mpv --idle=yes --force-window=yes --fullscreen --no-border --loop=inf \
    --title="$MPV_TITLE" \
    --hwdec=vaapi --vo=gpu --gpu-context=x11egl --no-osc --no-input-default-bindings \
    --really-quiet --input-ipc-server="$SOCK" "$V" >/tmp/mpv-zt.log 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null; rm -f "$SOCK"' EXIT INT TERM

for _ in $(seq 1 50); do [ -S "$SOCK" ] && break; sleep 0.1; done
[ -S "$SOCK" ] || { echo "ERREUR: socket mpv jamais cree"; exit 1; }
ipc() { echo "$1" | socat - "UNIX-CONNECT:$SOCK" >/dev/null 2>&1; }

# LECON PoC : la propriete mpv 'ontop' (_NET_WM_STATE_ABOVE) ne RESTACKE pas une fois
# le kiosk repasse devant. Le mecanisme fiable sous Openbox = RAISE explicite via
# wmctrl -a (active+remonte) la fenetre cible a chaque bascule. C'est ce que fera la prod.
raise() { wmctrl -a "$1" >/dev/null 2>&1; }

for i in 1 2 3; do
  echo ">>> CYCLE $i : MPV DEVANT (video HW VAAPI) - 7s  [wmctrl raise mpv]"
  raise "$MPV_TITLE"
  ipc "{ \"command\": [\"show-text\", \"=== MPV DEVANT (HW VAAPI) - cycle $i ===\", 7000, 1] }"
  sleep 7
  echo ">>> CYCLE $i : MPV DERRIERE (le kiosk SignFlow revient) - 7s  [wmctrl raise kiosk]"
  raise "SignFlow Player"
  sleep 7
done
echo ">>> fin (mpv tue par le trap)"
