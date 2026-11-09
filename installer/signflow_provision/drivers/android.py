"""Driver Android (ADB) — MVP de l'installeur terrain (§XXIX).

Rejoue la séquence validée manuellement (pose MINIX 2026-07-01) de façon industrielle :
connect IP → install APK → (Device Owner si fresh) → provisioning par INTENT (extras
backend_url+token, pas de pilotage clavier) → set-home-activity → le device s'enregistre seul.

Prérequis (foothold ouvert par le technicien) : Débogage USB activé + clé ADB autorisée.
Device Owner ⇒ appareil factory-fresh SANS compte Google (sinon `dpm set-device-owner` échoue).
"""

from __future__ import annotations

import time

from .base import Driver, DriverError, require_tool, run

PACKAGE = "app.vitrail.player"
SETUP_ACTIVITY = f"{PACKAGE}/.SetupActivity"
MAIN_ACTIVITY = f"{PACKAGE}/.MainActivity"
ADMIN_COMPONENT = f"{PACKAGE}/.SignFlowAdminReceiver"


class AndroidDriver(Driver):
    os_name = "android"

    def provision(self, log) -> None:
        dry = self.opts.get("dry_run")
        adb = "adb" if dry else require_tool("adb")
        ip = self.opts.get("ip")
        if not ip:
            raise DriverError("Android : --ip <IP:port> requis (ex. 192.168.1.50:5555).")
        target = ip if ":" in ip else f"{ip}:5555"
        apk = self.opts.get("apk")

        def adb_shell(*args, check=True, timeout=120):
            cmd = [adb, "-s", target, *args]
            log(f"  $ {' '.join(cmd)}")
            if dry:
                return None
            return run(cmd, check=check, timeout=timeout)

        # 1) Connexion ADB sur IP
        log(f"[1/6] Connexion ADB → {target}")
        if not dry:
            run([adb, "connect", target], timeout=30)
            time.sleep(1)

        # 2) Installation de l'APK (si fourni)
        if apk:
            log(f"[2/6] Installation de l'APK ({apk})")
            if not dry:
                run([adb, "-s", target, "install", "-r", apk], timeout=300)
        else:
            log("[2/6] APK non fourni (--apk) → on suppose l'app déjà installée")

        # 3) Device Owner (best-effort : nécessite un appareil fresh sans compte)
        log("[3/6] Device Owner (best-effort)")
        p = adb_shell("shell", "dpm", "set-device-owner", ADMIN_COMPONENT, check=False)
        if p is not None and p.returncode != 0:
            out = (p.stdout or "").lower()
            if "already" in out or "device owner" in out:
                log("      Device Owner déjà défini — OK")
            else:
                log("      ⚠ Device Owner non défini (appareil non-fresh ou compte présent).")
                log("        → factory reset SANS ajouter de compte, puis relance, si tu veux")
                log("          le reboot natif / mode kiosk complet. Non bloquant pour diffuser.")

        # 4) Provisioning par INTENT (backend_url + token → SetupActivity auto-enregistre)
        log("[4/6] Provisioning par intent (backend + token)")
        backend = self.payload["backend_url"]
        token = self.payload["token"]
        adb_shell("shell", "am", "start", "-n", SETUP_ACTIVITY,
                  "-e", "backend_url", backend, "-e", "token", token)

        # 5) Home activity = le player (kiosk)
        log("[5/6] Définition de l'activité d'accueil (kiosk)")
        adb_shell("shell", "cmd", "package", "set-home-activity", MAIN_ACTIVITY, check=False)
        adb_shell("shell", "pm", "set-home-activity", MAIN_ACTIVITY, check=False)

        # 6) Le device s'enregistre seul (SetupActivity → /players/register). La vérif online
        #    est faite par le CLI (poll CMS). On laisse un court instant à l'enregistrement.
        log("[6/6] Enregistrement déclenché sur le device — vérification online côté CMS…")
        if not dry:
            time.sleep(3)
