#!/bin/sh
# SignFlow — lancé par sf-provision@.service (règle udev) à l'insertion d'une clé USB (§XXIX.10).
# Monte la clé ; si elle porte signflow-config.json, ouvre sf-configure DANS UN TERMINAL sur l'écran
# actif (le technicien voit l'assignation et étiquette la machine). Sinon démonte et sort.
# NE matche que l'USB (règle udev) → jamais le disque interne.
set -u

DEV="${1:-}"
[ -n "$DEV" ] || exit 0
MP=/run/sf-usb
LOCK=/run/sf-provision.lock

# Une seule instance à la fois (udev peut déclencher plusieurs events).
exec 9>"$LOCK" 2>/dev/null || exit 0
command -v flock >/dev/null 2>&1 && { flock -n 9 || exit 0; }

cleanup() { mountpoint -q "$MP" && umount "$MP" 2>/dev/null; }
trap cleanup EXIT

mkdir -p "$MP"
mountpoint -q "$MP" && umount "$MP" 2>/dev/null
# rw pour pouvoir écrire consumed.json (lot). Si la clé est RO, sf-configure s'appuie sur le
# backstop serveur (max_uses=1).
mount "/dev/$DEV" "$MP" 2>/dev/null || exit 0

[ -f "$MP/signflow-config.json" ] || exit 0   # pas notre clé → cleanup (trap) démonte

# Écran/Xauthority de la session graphique active (openbox), robuste quel que soit l'user/display.
DISP=""; XA=""
OBPID=$(pgrep -x openbox 2>/dev/null | head -1)
if [ -n "$OBPID" ] && [ -r "/proc/$OBPID/environ" ]; then
    DISP=$(tr '\0' '\n' < "/proc/$OBPID/environ" | sed -n 's/^DISPLAY=//p' | head -1)
    XA=$(tr '\0' '\n' < "/proc/$OBPID/environ" | sed -n 's/^XAUTHORITY=//p' | head -1)
fi
[ -n "$DISP" ] || DISP=:0
[ -n "$XA" ] || XA=$(getent passwd 1000 | cut -d: -f6)/.Xauthority

TERM_BIN=$(command -v xterm || command -v x-terminal-emulator || true)
if [ -z "$TERM_BIN" ]; then
    # Pas de terminal X : fallback console (VT actif). sf-configure reste interactif sur ce TTY.
    /usr/local/bin/sf-configure.sh "$MP/signflow-config.json" || true
    exit 0
fi

# Terminal plein écran lisible, au premier plan sur la session du player.
DISPLAY="$DISP" XAUTHORITY="$XA" "$TERM_BIN" \
    -fa Monospace -fs 15 -geometry 130x42 \
    -T "Vitrail - Player configuration" \
    -e /usr/local/bin/sf-configure.sh "$MP/signflow-config.json" 2>/dev/null || true

# On n'arrive ici QUE si sf-configure n'a pas redémarré (config incomplète / abandon) → trap démonte.
