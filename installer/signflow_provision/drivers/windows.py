"""Driver WinRM — Windows 11 DÉJÀ installé / PC existant (§XXIX).

Windows n'a pas d'autorun USB (bloqué depuis Win7) : sur une machine déjà installée, le canal est
**WinRM/PSSession**. Ce driver reproduit à distance ce que fait `player-windows/install.ps1` puis
dépose le `config.json` de provisioning que lit le player Electron :

    %APPDATA%\\signflow-player-windows\\config.json
      { "backend_url": ..., "org_token": "<token sfp_>", "player_name": "<ref>" }

Au 1er lancement, le player s'auto-enregistre (`POST /players/register`, échange org_token → token
player, se ré-attache au player pré-créé côté CMS = zéro doublon), exactement comme les autres OS.

Foothold (ouvert par le technicien) : WinRM activé + identifiants d'un compte **administrateur**.
    winrm quickconfig -q                    # sur le poste cible
    Enable-PSRemoting -Force

Dépendance : `pywinrm` (import paresseux → n'impacte pas les autres drivers si absent).
"""

from __future__ import annotations

import base64
import json

from .base import Driver, DriverError

# userData Electron du player Windows (cf. package.json name) → %APPDATA%\<name>.
_PKG_NAME = "signflow-player-windows"
_TASK_NAME = "SignFlow Player"


class WinRmDriver(Driver):
    os_name = "windows"

    def provision(self, log) -> None:
        dry = self.opts.get("dry_run")
        host = self.opts.get("winrm")
        user = self.opts.get("winrm_user")
        password = self.opts.get("winrm_password")
        if not host:
            raise DriverError("Windows : --winrm <host[:port]> requis (WinRM du poste cible).")
        if not dry and (not user or not password):
            raise DriverError("Windows : --winrm-user et --winrm-password requis.")

        transport = self.opts.get("winrm_transport") or "ntlm"
        use_https = bool(self.opts.get("winrm_https"))
        scheme = "https" if use_https else "http"
        port = 5986 if use_https else 5985
        if ":" in host:
            host, port_s = host.rsplit(":", 1)
            port = int(port_s)
        endpoint = f"{scheme}://{host}:{port}/wsman"

        # Utilisateur dont le %APPDATA% reçoit le config.json (le player tourne au logon de ce
        # compte kiosk). Défaut = le compte WinRM lui-même.
        win_user = self.opts.get("windows_user") or user

        # ── Session WinRM (import paresseux) ──────────────────────────────────
        session = None
        if not dry:
            try:
                import winrm  # noqa: PLC0415
            except ImportError as e:
                raise DriverError(
                    "Module « pywinrm » manquant. Installe-le : pip install pywinrm") from e
            session = winrm.Session(
                endpoint, auth=(user, password), transport=transport,
                server_cert_validation="ignore")

        def run_ps(script: str, *, label: str, check: bool = True) -> str:
            log(f"  [ps] {label}")
            if dry:
                return ""
            r = session.run_ps(script)
            out = (r.std_out or b"").decode("utf-8", "replace").strip()
            err = (r.std_err or b"").decode("utf-8", "replace").strip()
            if check and r.status_code != 0:
                raise DriverError(f"WinRM « {label} » a échoué (code {r.status_code}) : "
                                  f"{err or out}")
            return out

        # ── 1) Sonde de connexion ─────────────────────────────────────────────
        log(f"[1/5] Connexion WinRM → {scheme}://{host}:{port} ({transport}, user {user})")
        who = run_ps("[Environment]::UserName + ' | admin=' + "
                     "([bool]([Security.Principal.WindowsPrincipal]"
                     "[Security.Principal.WindowsIdentity]::GetCurrent())"
                     ".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))",
                     label="whoami + élévation")
        if who:
            log(f"      {who}")

        # ── 2) Install player (optionnel : lance install.ps1 si --source fourni) ──
        source = self.opts.get("source")
        if source:
            log(f"[2/5] Installation du player (install.ps1 dans {source})")
            # ⚠️ ExecutionPolicy : sur un Windows CLIENT elle vaut « Restricted » par défaut,
            # donc `& $p` refuse le script (« running scripts is disabled on this system ») —
            # mesuré le 2026-08-09 sur un Win11 25H2 neuf, c'est-à-dire le cas nominal de ce
            # canal. On la contourne pour CE processus seulement : rien n'est modifié sur la
            # machine du client, contrairement à un Set-ExecutionPolicy persistant.
            script = (
                "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; "
                f"$p = Join-Path '{source}' 'install.ps1'; "
                "if (-not (Test-Path $p)) { Write-Error 'install.ps1 introuvable'; exit 1 } "
                "& $p")
            run_ps(script, label="install.ps1")
        else:
            log("[2/5] --source non fourni → on suppose le player déjà installé "
                "(on ne dépose que la config)")

        # ── 3) Résolution du dossier userData du compte cible ─────────────────
        # Si le compte WinRM == compte kiosk → $env:APPDATA. Sinon on reconstruit le profil.
        if win_user.lower() == (user or "").lower() and not dry:
            appdata_expr = "$env:APPDATA"
        else:
            appdata_expr = f"(Join-Path $env:SystemDrive 'Users\\{win_user}\\AppData\\Roaming')"
        cfg_dir_ps = f"(Join-Path {appdata_expr} '{_PKG_NAME}')"
        log(f"[3/5] Dossier de config du player (utilisateur {win_user})")

        # ── 4) Écriture du config.json (+ display_config.json) ────────────────
        config = {
            "backend_url": self.payload["backend_url"].rstrip("/"),
            "org_token": self.payload["token"],
            "player_name": self.payload.get("ref") or f"player-{self.payload.get('id_player')}",
        }
        files = {"config.json": config}

        display_cfg: dict = {}
        opts = self.payload.get("options") or {}
        if opts.get("resolution"):
            display_cfg["resolution"] = opts["resolution"]
        if opts.get("rotation") is not None:
            display_cfg["rotation"] = opts["rotation"]
        if display_cfg:
            files["display_config.json"] = display_cfg

        net = self.payload.get("network")
        if net and net.get("mode") == "static":
            log("      ⚠ Config réseau statique demandée : non appliquée automatiquement sous "
                "Windows (MVP). Configure l'IP fixe manuellement (netsh) si besoin.")

        log(f"[4/5] Écriture de {', '.join(files)} → {_PKG_NAME}\\")
        for name, obj in files.items():
            raw = json.dumps(obj, indent=2).encode("utf-8")
            b64 = base64.b64encode(raw).decode("ascii")
            # base64 → octets → fichier : évite tout problème de quoting/UTF-16 sur le contenu.
            script = (
                f"$dir = {cfg_dir_ps}; "
                "New-Item -ItemType Directory -Force -Path $dir | Out-Null; "
                f"[IO.File]::WriteAllBytes((Join-Path $dir '{name}'), "
                f"[Convert]::FromBase64String('{b64}')); "
                f"Write-Output ('wrote ' + (Join-Path $dir '{name}'))")
            out = run_ps(script, label=f"écrire {name}")
            if out:
                log(f"      {out}")

        # ── 5) (Re)lancement de la tâche planifiée pour prise en compte immédiate ──
        if self.opts.get("start_task"):
            log(f"[5/5] Démarrage de la tâche planifiée « {_TASK_NAME} »")
            script = (
                f"$t = Get-ScheduledTask -TaskName '{_TASK_NAME}' -ErrorAction SilentlyContinue; "
                "if ($t) { Stop-ScheduledTask -TaskName '" + _TASK_NAME + "' "
                "-ErrorAction SilentlyContinue; Start-ScheduledTask -TaskName '" + _TASK_NAME
                + "'; Write-Output 'task started' } "
                "else { Write-Output 'task absente (player pas encore installé ?)' }")
            out = run_ps(script, label="start task", check=False)
            if out:
                log(f"      {out}")
        else:
            log("[5/5] Config déposée. Le player la prendra au prochain (re)démarrage de la "
                "tâche « SignFlow Player » (--start-task pour forcer maintenant).")
