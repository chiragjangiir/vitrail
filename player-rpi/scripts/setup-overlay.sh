#!/usr/bin/env bash
# setup-overlay.sh -- Enable overlay rootfs on Raspberry Pi OS
#
# Protects the SD card from filesystem corruption on unclean shutdown (power loss).
# All writes go to a tmpfs overlay -- changes are lost on reboot (which is correct
# for a kiosk: the SD card never diverges from the installed state).
#
# IMPORTANT: run BEFORE installing SignFlow if you want config.json to persist.
# If you enable overlay AFTER installation, config.json is already on the real FS
# and will survive reboots (it was written before overlay was active).
# To persist new config changes after overlay is enabled, disable overlay, edit, re-enable.
#
# NOTE: if this file was created on Windows, strip CRLF before running:
#   sed -i 's/\r//' setup-overlay.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Error: run with sudo" >&2
  exit 1
fi

# ── Method 1: raspi-config (preferred on Raspberry Pi OS) ─────────────────────
if command -v raspi-config &>/dev/null; then
  echo "[overlay] Using raspi-config to enable overlay filesystem..."

  # raspi-config nonint: enable_overlayfs also write-protects /boot
  raspi-config nonint enable_overlayfs

  echo "[overlay] Overlay rootfs enabled via raspi-config."
  echo "[overlay] The boot partition will also be write-protected."
  echo "[overlay] A reboot is required for the changes to take effect."
  echo ""
  echo "To disable overlay (e.g. to update config):"
  echo "  sudo raspi-config nonint disable_overlayfs && sudo reboot"
  exit 0
fi

# ── Method 2: overlayroot package (fallback for non-raspi-config systems) ──────
echo "[overlay] raspi-config not found -- falling back to overlayroot package..."

apt-get install -y overlayroot

# overlayroot.conf: tmpfs overlay, recurse disabled (we only want / protected)
cat > /etc/overlayroot.conf <<'EOF'
overlayroot="tmpfs:swap=0,recurse=0"
overlayroot_cfgdisk="disabled"
EOF

echo "[overlay] overlayroot configured."
echo "[overlay] A reboot is required for the changes to take effect."
echo ""
echo "To disable overlay:"
echo "  sudo overlayroot-chroot  # enter the real FS"
echo "  # edit /etc/overlayroot.conf -> overlayroot=\"\""
echo "  # exit + reboot"
