"""Installeur terrain SignFlow (§XXIX) — CLI « 1 payload, plusieurs canaux ».

Flux commun : auth CMS → payload (généré ou chargé) → driver OS → vérif online → rapport.

Auth : clé opérateur `sfk_` (recommandé, longue durée) OU JWT org-admin (`--token`, 15 min).
Config UNIQUE : `signflow-provision --cms <url> --key sfk_… --save-config` → plus rien à re-saisir.

Exemples (clé configurée via --save-config) :
  # Android (crée un nouveau player, génère le payload et provisionne par ADB)
  signflow-provision --ref "Boutique Lyon" --os android --ip 192.168.1.50 --apk app-release.apk

  # Ré-attache à un player existant (anti-doublon)
  signflow-provision --os android --ip 192.168.1.50 --reattach 42 --apk app-release.apk

  # Réutiliser un payload déjà généré depuis l'UI (fichier signflow-provision.json)
  signflow-provision --payload signflow-provision.json --ip 192.168.1.50
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .cms import CmsClient, CmsError
from .drivers import DriverError, get_driver

# Date du dernier changement de code embarqué — affichée par --selftest, seul moyen de juger la
# fraîcheur d'un exe distribué (le binaire ne porte pas le git). À bumper à chaque correctif.
BUILD_STAMP = "2026-08-16"


def _config_path() -> Path:
    """~/.signflow/provision.json (ou %APPDATA%\\signflow\\provision.json sous Windows)."""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home()
    return root / "signflow" / "provision.json"


def _load_config() -> dict:
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_config(cms: str | None, key: str | None, token: str | None) -> int:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if cms:
        data["cms"] = cms
    if key:
        data["key"] = key
    elif token:
        data["token"] = token
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(p, 0o600)  # secret → lisible par l'utilisateur seul (POSIX)
    except Exception:  # noqa: BLE001
        pass
    _log(f"✔ Config enregistrée dans {p} (clé/token = secret, ne pas partager).")
    return 0

# La console Windows (PowerShell) est souvent en cp1252 → les symboles ✔/✗/▶ planteraient.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _log(msg: str) -> None:
    print(msg, flush=True)


def _selftest() -> int:
    """Diagnostic hors-ligne : quels canaux de provisioning sont utilisables ici."""
    import shutil

    from .drivers import DRIVERS

    _log(f"signflow-provision — code du {BUILD_STAMP} — canaux enregistrés : {', '.join(sorted(DRIVERS))}")
    adb = shutil.which("adb")
    _log(f"  Android (ADB)      : {'✔ adb ' + adb if adb else '✗ adb absent du PATH'}")
    ssh = shutil.which("ssh")
    _log(f"  Linux/RPi (SSH)    : {'✔ ssh présent' if ssh else '✗ ssh absent du PATH'}")
    try:
        import winrm  # noqa: F401,PLC0415
        _log("  Windows (WinRM)    : ✔ pywinrm disponible")
    except ImportError:
        _log("  Windows (WinRM)    : ✗ pywinrm absent (pip install pywinrm)")
    _log("  BrightSign (SD)    : ✔ (écrit un config.json, aucun outil requis)")
    return 0


def build_network(args) -> dict | None:
    if args.wifi_ssid:
        return {"mode": "dhcp", "wifi_ssid": args.wifi_ssid, "wifi_psk": args.wifi_psk}
    if args.static_ip:
        return {"mode": "static", "ip": args.static_ip, "mask": args.mask,
                "gw": args.gw, "dns": args.dns}
    return None


def build_options(args) -> dict | None:
    opts: dict = {}
    if args.resolution:
        opts["resolution"] = args.resolution
    if args.rotation is not None:
        opts["rotation"] = args.rotation
    return opts or None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="signflow-provision",
        description="Pose SignFlow sur un player (§XXIX) — 1 payload, plusieurs canaux.")
    ap.add_argument("--cms", help="URL du CMS (ex. https://cms.example.com)")
    ap.add_argument("--key", help="Clé opérateur de provisioning sfk_… (longue durée, recommandé)")
    ap.add_argument("--token", help="JWT bearer org-admin (alternative à --key ; expire en 15 min)")
    ap.add_argument("--save-config", action="store_true",
                    help=f"Enregistre --cms + --key/--token dans {_config_path()} puis quitte "
                         "(à faire une fois → plus rien à re-saisir ensuite)")
    ap.add_argument("--insecure", action="store_true", help="Ne pas vérifier le TLS (dev)")
    ap.add_argument("--selftest", action="store_true",
                    help="Diagnostic : liste les canaux disponibles (adb/ssh/winrm) puis quitte")

    # payload : soit fichier, soit paramètres de génération
    ap.add_argument("--payload", help="Fichier signflow-provision.json (généré depuis l'UI)")
    ap.add_argument("--ref", help="Libellé/nom du player (création)")
    ap.add_argument("--os", choices=["android", "linux", "rpi", "windows", "brightsign"])
    ap.add_argument("--reattach", type=int, metavar="ID_PLAYER",
                    help="Ré-attacher à un player existant (anti-doublon)")
    ap.add_argument("--expires-days", type=int, default=30)

    # réseau / options
    ap.add_argument("--wifi-ssid")
    ap.add_argument("--wifi-psk")
    ap.add_argument("--static-ip", dest="static_ip")
    ap.add_argument("--mask")
    ap.add_argument("--gw")
    ap.add_argument("--dns")
    ap.add_argument("--resolution")
    ap.add_argument("--rotation", type=int, choices=[0, 90, 180, 270])

    # canal / driver
    ap.add_argument("--ip", help="Android : IP[:port] ADB du device")
    ap.add_argument("--apk", help="Android : chemin de l'APK release à installer")
    ap.add_argument("--ssh", help="Linux/RPi : user@host SSH")
    ap.add_argument("--player-user", dest="player_user", default="signflow",
                    help="Linux/RPi : compte SOUS LEQUEL tourne le player (defaut: signflow). "
                         "C'est dans son ~/.config que la config de provisioning est ecrite : "
                         "un compte errone laisse le player sur « Setup required ».")
    ap.add_argument("--out", help="BrightSign : dossier de sortie du config.json")
    # Windows (WinRM)
    ap.add_argument("--winrm", help="Windows : host[:port] WinRM du poste cible")
    ap.add_argument("--winrm-user", dest="winrm_user", help="Windows : compte WinRM (administrateur)")
    ap.add_argument("--winrm-password", dest="winrm_password", help="Windows : mot de passe WinRM")
    ap.add_argument("--winrm-transport", dest="winrm_transport",
                    choices=["ntlm", "basic", "credssp", "kerberos"], default="ntlm",
                    help="Windows : transport WinRM (défaut ntlm)")
    ap.add_argument("--winrm-https", dest="winrm_https", action="store_true",
                    help="Windows : WinRM en HTTPS (port 5986)")
    ap.add_argument("--windows-user", dest="windows_user",
                    help="Windows : compte kiosk dont le %%APPDATA%% reçoit la config "
                         "(défaut = --winrm-user)")
    ap.add_argument("--source", help="Windows : chemin distant du dossier player-windows "
                                     "(lance install.ps1 si fourni)")
    ap.add_argument("--start-task", dest="start_task", action="store_true",
                    help="Windows : (re)démarre la tâche « SignFlow Player » après la config")
    ap.add_argument("--dry-run", action="store_true", help="N'exécute rien, affiche les étapes")
    ap.add_argument("--no-verify-online", action="store_true",
                    help="Ne pas attendre que le player passe online")
    ap.add_argument("--timeout", type=int, default=180, help="Timeout vérif online (s)")

    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    # Résolution CMS + credential : args > env > fichier de config.
    cfg = _load_config()
    cms_url = args.cms or os.environ.get("SIGNFLOW_CMS") or cfg.get("cms")
    credential = (args.key or args.token
                  or os.environ.get("SIGNFLOW_KEY") or os.environ.get("SIGNFLOW_TOKEN")
                  or cfg.get("key") or cfg.get("token"))

    if args.save_config:
        if not cms_url or not credential:
            _log("✗ --save-config exige --cms et --key (ou --token).")
            return 2
        return _save_config(cms_url, args.key or cfg.get("key"),
                            args.token or cfg.get("token"))

    if not cms_url or not credential:
        _log("✗ --cms + --key (ou --token) requis. Astuce : configure-les une fois avec "
             "`signflow-provision --cms <url> --key sfk_… --save-config`, "
             "ou via $SIGNFLOW_CMS / $SIGNFLOW_KEY. (--selftest pour le diagnostic.)")
        return 2
    cms = CmsClient(cms_url, credential, verify_tls=not args.insecure)

    # 1) Auth + org
    try:
        me = cms.whoami()
    except (CmsError, Exception) as e:  # noqa: BLE001
        _log(f"✗ Auth CMS échouée : {e}")
        return 2
    id_org = me.get("id_org")
    _log(f"✔ Connecté au CMS (org {id_org}, auth {me.get('kind', '?')})")

    # 2) Payload : chargé ou généré
    if args.payload:
        with open(args.payload, encoding="utf-8") as f:
            payload = json.load(f)
        _log(f"✔ Payload chargé ({payload.get('ref')} / {payload.get('os')})")
    else:
        if not args.os or (not args.ref and args.reattach is None):
            _log("✗ Fournir --payload OU (--os et --ref/--reattach) pour générer un payload.")
            return 2
        try:
            payload = cms.create_payload(
                id_org, ref=args.ref or f"player-{args.reattach}", os=args.os,
                backend_url=cms_url.rstrip("/"),
                network=build_network(args), options=build_options(args),
                id_player=args.reattach, expires_in_days=args.expires_days)
        except CmsError as e:
            _log(f"✗ Génération du payload échouée : {e}")
            return 2
        _log(f"✔ Payload généré (player #{payload['id_player']}, token {payload['token'][:12]}…)")

    os_name = payload["os"]
    id_player = payload.get("id_player")

    # 3) Driver
    opts = {"ip": args.ip, "apk": args.apk, "ssh": args.ssh, "out": args.out,
            "dry_run": args.dry_run, "player_user": args.player_user,
            "winrm": args.winrm, "winrm_user": args.winrm_user,
            "winrm_password": args.winrm_password, "winrm_transport": args.winrm_transport,
            "winrm_https": args.winrm_https, "windows_user": args.windows_user,
            "source": args.source, "start_task": args.start_task}
    try:
        driver = get_driver(os_name, payload, opts)
        _log(f"\n▶ Provisioning {os_name}…")
        driver.provision(_log)
    except DriverError as e:
        _log(f"✗ {e}")
        return 3

    # 4) Vérif online
    if args.no_verify_online or args.dry_run or id_player is None:
        _log("\n✔ Terminé (vérification online non demandée).")
        return 0
    _log(f"\n⏳ Attente du passage online du player #{id_player} (max {args.timeout}s)…")
    ok = cms.wait_online(id_player, timeout_s=args.timeout,
                         on_tick=lambda st: _log(f"   … statut = {st or 'inconnu'}"))
    if ok:
        _log(f"✅ Player #{id_player} ONLINE — provisioning réussi.")
        return 0
    _log(f"⚠ Player #{id_player} n'est pas passé online dans le délai. Vérifie le device "
         f"(réseau, écran de setup) — le token reste valide pour réessayer.")
    return 4


if __name__ == "__main__":
    sys.exit(main())
