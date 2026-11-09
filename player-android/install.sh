#!/usr/bin/env bash
# Vitrail Player — Android TV deploy script
# Requires: Android SDK (adb), device connected via ADB (USB or TCP)
#
# Usage:
#   ./install.sh              — install debug APK + set as launcher
#   ./install.sh --release    — install release APK (must be signed)
#   ./install.sh --ip 192.168.1.50  — connect to device over TCP before install
set -e

APK_DEBUG="app/build/outputs/apk/debug/app-debug.apk"
APK_RELEASE="app/build/outputs/apk/release/app-release.apk"
PACKAGE="app.vitrail.player"
RELEASE=false
DEVICE_IP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release) RELEASE=true ;;
    --ip) DEVICE_IP="$2"; shift ;;
  esac
  shift
done

# ADB TCP connect
if [[ -n "$DEVICE_IP" ]]; then
  echo "Connecting to $DEVICE_IP:5555..."
  adb connect "$DEVICE_IP:5555"
  sleep 2
fi

# Check device
adb get-state >/dev/null 2>&1 || { echo "ERROR: No ADB device found."; exit 1; }
echo "Device: $(adb shell getprop ro.product.model | tr -d '\r')"
echo "Android: $(adb shell getprop ro.build.version.release | tr -d '\r')"

# Build
if [[ ! -f "./gradlew" ]]; then
  echo "ERROR: gradlew not found. Open the project in Android Studio first,"
  echo "       or run: gradle wrapper --gradle-version=8.2"
  exit 1
fi

if $RELEASE; then
  echo "Building release APK (signed — needs keystore.properties + signflow-release.jks)..."
  ./gradlew assembleRelease
  APK="$APK_RELEASE"
  # Le release = package 'app.vitrail.player' ; le debug = 'app.vitrail.player.debug' (suffixe).
  # Ce sont 2 apps DISTINCTES : le release s'installe à neuf (pas de token) → PROVISIONNER via l'écran
  # de setup ; puis retirer l'ancien debug : adb uninstall app.vitrail.player.debug
  RELEASE_NOTE=true
else
  echo "Building debug APK..."
  ./gradlew assembleDebug
  APK="$APK_DEBUG"
fi

# Install
echo "Installing $APK..."
adb install -r "$APK"

# Set as default launcher (kiosk mode)
echo "Setting as default home app..."
adb shell pm set-home-activity "${PACKAGE}/.MainActivity" 2>/dev/null || true

# Allow clear-text HTTP (dev — remove in production with TLS)
adb shell settings put global http_proxy "" 2>/dev/null || true

if [[ "${RELEASE_NOTE:-false}" == "true" ]]; then
  echo ""
  echo ">>> Release installé (app.vitrail.player). PROVISIONNER le token via l'écran de setup."
  echo ">>> Puis retirer l'ancien debug s'il reste : adb uninstall app.vitrail.player.debug"
fi

echo ""
echo "Vitrail Player installed successfully."
echo ""
echo "Next steps:"
echo "  1. The setup wizard will appear on first launch"
echo "  2. Enter the server URL: http://<server-ip>:8080"
echo "  3. Enter a provisioning token (sfp_...) from the CMS"
echo ""
echo "To open the player now:"
echo "  adb shell am start -n ${PACKAGE}/.MainActivity"
echo ""
echo "To enable ADB over TCP (for future wireless deploys):"
echo "  adb tcpip 5555"
echo "  adb connect <device-ip>:5555"
