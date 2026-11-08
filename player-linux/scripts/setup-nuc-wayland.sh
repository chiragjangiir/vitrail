#!/usr/bin/env bash
# setup-nuc-wayland.sh — Bascule un player Linux/Intel d'une session X11/openbox
# vers une session Wayland/cage (comme le RPi), pour debloquer le decodage HW
# VA-API (Ozone/Wayland fournit le chemin NativePixmap/dma-buf que X11 n'a pas).
#
#   sudo bash setup-nuc-wayland.sh           # bascule -> Wayland/cage, puis reboot
#   sudo bash setup-nuc-wayland.sh --revert  # restaure openbox/X11, puis reboot
#
# Reversible : l'autologin openbox d'origine est sauvegarde. cage est lance par
# lightdm comme session Wayland -> vraie session logind (seat0 + VTnr) -> cage
# obtient le DRM master (≠ le hack openvt+su qui echouait sur libseat/VT).
set -euo pipefail

SERVICE_USER="${SERVICE_USER:-signflow}"
PLAYER_DIR="${PLAYER_DIR:-/opt/signflow/player-linux}"
ELECTRON_BIN="$PLAYER_DIR/node_modules/.bin/electron"
LIGHTDM_DIR=/etc/lightdm/lightdm.conf.d
LIGHTDM_CONF="$LIGHTDM_DIR/50-signflow-autologin.conf"
BACKUP="$LIGHTDM_CONF.openbox.bak"
WAYLAND_SESSIONS=/usr/share/wayland-sessions
START_SCRIPT="$PLAYER_DIR/start-player-wayland.sh"
ENV_FILE=/etc/default/signflow-player

if [[ "${1:-}" == "--revert" || "${1:-}" == "--clean" ]]; then
  if [[ -f "$BACKUP" ]]; then
    mv -f "$BACKUP" "$LIGHTDM_CONF"
    echo "Restaure : autologin openbox/X11."
  else
    echo "Pas de backup openbox ($BACKUP). Rien a restaurer."
  fi
  # Reactive les confs lightdm concurrentes desactivees a la bascule.
  for f in "$LIGHTDM_DIR"/*.conf.disabled-by-signflow; do
    [[ -e "$f" ]] || continue
    mv -f "$f" "${f%.disabled-by-signflow}"
    echo "Reactive : ${f%.disabled-by-signflow}"
  done
  # --clean : retire aussi les artefacts Wayland (session inactive => sans risque).
  if [[ "${1:-}" == "--clean" ]]; then
    rm -f "$WAYLAND_SESSIONS/signflow-player.desktop" "$START_SCRIPT" "$ENV_FILE"
    echo "Nettoye : signflow-player.desktop, start-player-wayland.sh, $ENV_FILE"
    echo "(cage/xwayland laisses installes, groupes video/render conserves : inoffensifs)"
  fi
  echo "-> sudo reboot pour appliquer."
  exit 0
fi

[[ $EUID -eq 0 ]] || { echo "Lancer en root (sudo)."; exit 1; }

echo "[1/5] Installation de cage + xwayland..."
# xwayland est OBLIGATOIRE : cage lance un serveur XWayland par defaut et avorte
# s'il est absent ("Cannot find Xwayland binary" -> session quitte -> greeter).
apt-get install -y cage xwayland >/dev/null

echo "[2/5] Groupes video/render pour $SERVICE_USER..."
usermod -aG video,render "$SERVICE_USER" 2>/dev/null || true

echo "[3/5] Start script Wayland ($START_SCRIPT)..."
# Lance le player sous cage avec le profil VA-API 'wayland' (--ozone-platform=
# wayland + features VA-API, cf. src/vaapi_profiles.js). Pour un run verbeux,
# poser SF_VLOG=2 dans $ENV_FILE puis redemarrer la session.
cat > "$START_SCRIPT" <<EOF
#!/usr/bin/env bash
LOG=/var/log/signflow-player.log
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
# Force la resolution si WLR_OUTPUT est defini (sinon EDID natif).
if [ -n "\${WLR_OUTPUT:-}" ]; then
  wlr-randr --output "\$WLR_OUTPUT" --mode "\${WLR_MODE:-1920x1080@60}" >>"\$LOG" 2>&1 || true
fi
sleep 1
exec env SF_VAAPI_PROFILE="\${SF_VAAPI_PROFILE:-wayland}" "$ELECTRON_BIN" "$PLAYER_DIR" >>"\$LOG" 2>&1
EOF
chmod +x "$START_SCRIPT"
chown "$SERVICE_USER:$SERVICE_USER" "$START_SCRIPT"

echo "[4/5] Session Wayland 'signflow-player'..."
mkdir -p "$WAYLAND_SESSIONS"
cat > "$WAYLAND_SESSIONS/signflow-player.desktop" <<EOF
[Desktop Entry]
Name=SignFlow Player
Comment=SignFlow digital signage kiosk (cage/Wayland)
Exec=cage -- $START_SCRIPT
Type=Application
EOF

echo "[5/5] Autologin lightdm -> session Wayland (backup openbox)..."
mkdir -p "$LIGHTDM_DIR"
if [[ -f "$LIGHTDM_CONF" && ! -f "$BACKUP" ]]; then
  cp "$LIGHTDM_CONF" "$BACKUP"
  echo "    backup openbox -> $BACKUP"
fi
cat > "$LIGHTDM_CONF" <<EOF
[Seat:*]
autologin-user=$SERVICE_USER
autologin-user-timeout=0
autologin-session=signflow-player
EOF
# Neutralise toute AUTRE conf lightdm.conf.d qui force autologin-session (sinon,
# lue apres la notre dans l'ordre alpha, elle l'ecrase -> retour a X11/openbox).
BASE_CONF="$(basename "$LIGHTDM_CONF")"
for f in "$LIGHTDM_DIR"/*.conf; do
  [[ -e "$f" ]] || continue
  [[ "$(basename "$f")" == "$BASE_CONF" ]] && continue
  if grep -q '^autologin-session=' "$f" 2>/dev/null; then
    mv -f "$f" "$f.disabled-by-signflow"
    echo "    desactive conf concurrente -> $f.disabled-by-signflow"
  fi
done

cat <<EOF

=== Termine. Bascule en session Wayland/cage prete. ===
  1. sudo reboot
  2. Depuis SSH, pendant que ca joue une video :
        sudo intel_gpu_top         (regarder l'engine 'Video' -> doit etre > 0%)
  3. Verbeux si besoin : echo 'SF_VLOG=2' | sudo tee $ENV_FILE ; relancer la session
  Revert : sudo bash $PLAYER_DIR/scripts/setup-nuc-wayland.sh --revert ; sudo reboot
EOF
