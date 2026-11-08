#!/bin/sh
# SignFlow — installe l'AUTO-PROVISION par clé USB (§XXIX.10) sur un player Debian/RPi.
# À exécuter UNE FOIS sur le master (baké dans le clone) : pose la règle udev + le service systemd
# + les scripts dans le PATH, et s'assure que xterm + python3 sont présents.
#   sudo sf-configure/install-autoprovision.sh
set -e
[ "$(id -u)" = "0" ] || { echo "root required: sudo install-autoprovision.sh" >&2; exit 1; }
D=$(cd "$(dirname "$0")" && pwd)

install -m 644 "$D/udev/99-signflow-provision.rules" /etc/udev/rules.d/99-signflow-provision.rules
install -m 644 "$D/systemd/sf-provision@.service"    /etc/systemd/system/sf-provision@.service
install -m 755 "$D/sf-autoprovision.sh"              /usr/local/bin/sf-autoprovision.sh
# sf-configure dans le PATH = symlink vers la copie du repo (une seule source de vérité).
ln -sf "$D/sf-configure.sh" /usr/local/bin/sf-configure.sh

# Dépendances : xterm (terminal sur l'écran actif) + python3 (parse du bundle lot v2).
MISS=""
command -v xterm   >/dev/null 2>&1 || MISS="$MISS xterm"
command -v python3 >/dev/null 2>&1 || MISS="$MISS python3"
if [ -n "$MISS" ]; then
    echo "Installing dependencies:$MISS"
    apt-get update -qq && apt-get install -y $MISS
fi

udevadm control --reload-rules
systemctl daemon-reload
echo "OK - USB auto-provision installed (udev rule + sf-provision@.service)."
echo "Insert a key carrying signflow-config.json to test."
