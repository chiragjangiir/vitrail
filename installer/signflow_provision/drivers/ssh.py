"""Driver SSH — Linux x86 / Raspberry Pi DÉJÀ installés (§XXIX).

Copie la config `signflow-provision.json` sur le device et lance le script d'install existant
(`player-linux/install.sh` ou `player-rpi`). N'utilise que le stdlib `subprocess` + le binaire
`ssh`/`scp` (pas de dépendance paramiko) → fonctionne partout où OpenSSH est présent.

Foothold : SSH activé + identifiants (clé ou mot de passe via l'agent/known config).
"""

from __future__ import annotations

import base64
import json
import tempfile

from .base import Driver, DriverError, require_tool, run


class SshDriver(Driver):
    os_name = "linux"

    def provision(self, log) -> None:
        dry = self.opts.get("dry_run")
        if not dry:
            require_tool("ssh")
            require_tool("scp")
        host = self.opts.get("ssh")  # user@host
        if not host:
            raise DriverError("SSH : --ssh user@host requis.")

        # config minimale lue par les players Electron (config.json)
        cfg = {
            "backend_url": self.payload["backend_url"],
            "provisioning_token": self.payload["token"],
        }
        if self.payload.get("options"):
            cfg.update(self.payload["options"])
        net = self.payload.get("network")
        if net and net.get("mode") == "static":
            cfg["network"] = net

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cfg, f, indent=2)
            local = f.name

        remote = "/tmp/signflow-provision.json"
        log(f"[1/4] Copie de la config → {host}:{remote}")
        if not dry:
            run(["scp", local, f"{host}:{remote}"], timeout=60)

        log("[2/4] Lancement de l'install à distance (si un installeur est présent)")
        # ⚠️ Le chemin n'est PAS toujours player-linux : sur un Raspberry Pi c'est player-rpi.
        # Codé en dur, ce driver répondait « NO_INSTALLER » sur tout RPi.
        # ⚠️ `-f` et non `-x` : l'installeur arrive souvent SANS le bit exécutable (rsync/copie
        # d'archive ne le préserve pas), et on l'invoque de toute façon via `bash`. Testé avec
        # `-x`, ce driver répondait « NO_INSTALLER » sur une machine où l'installeur était bien
        # présent — mesuré le 2026-08-09.
        remote_cmd = (
            "sudo bash -lc 'for d in /opt/signflow/player-rpi /opt/signflow/player-linux; do "
            "if [ -f \"$d/install.sh\" ]; then bash \"$d/install.sh\"; exit $?; fi; done; "
            "echo NO_INSTALLER'")
        if not dry:
            p = run(["ssh", host, remote_cmd], timeout=900, check=False)
            log((p.stdout or "").strip()[-800:])
        else:
            log(f"  $ ssh {host} {remote_cmd}")

        # ── 3) Écrire la config que le player LIT vraiment ────────────────────
        # C'est l'étape qui manquait entièrement, et elle rendait ce canal inopérant :
        # on déposait /tmp/signflow-provision.json avec une clé « provisioning_token » et on
        # passait SF_PROVISION à install.sh — or `grep SF_PROVISION player-{rpi,linux}/install.sh`
        # ne rend RIEN. Personne ne lisait ni le fichier ni la variable ; le player restait sur
        # « Setup required ». Le canal était pourtant marqué « prouvé » : on s'était arrêté à
        # « l'install s'est lancée », jamais à « le player est online » (mesuré le 2026-08-09).
        #
        # On écrit donc nous-mêmes, comme le fait le driver Windows, avec les DEUX règles que
        # le RPi a fait payer le même jour :
        #   - le répertoire est ~/.config/<name de package.json> (app.getPath('userData')),
        #     dérivé à distance et jamais réécrit à la main ;
        #   - la clé est « player_token » : c'est elle que lisent les players Electron
        #     rpi/linux (main.js l'envoie ensuite comme org_token à /players/register).
        #     « org_token » n'est compris que du player Windows.
        player_user = self.opts.get("player_user") or "signflow"
        log(f"[3/4] Écriture de la config de provisioning (compte « {player_user} »)")
        remote_script = f"""
set -e
PLAYER_DIR=""
for d in /opt/signflow/player-rpi /opt/signflow/player-linux; do
    if [ -f "$d/package.json" ]; then PLAYER_DIR="$d"; break; fi
done
[ -n "$PLAYER_DIR" ] || {{ echo "ERREUR: aucun player installé sous /opt/signflow"; exit 1; }}
APP=$(sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p' "$PLAYER_DIR/package.json" | head -1)
[ -n "$APP" ] || {{ echo "ERREUR: nom d'application illisible dans $PLAYER_DIR/package.json"; exit 1; }}
CFG="/home/{player_user}/.config/$APP"
mkdir -p "$CFG"
cat > "$CFG/config.json" <<'JSON'
{json.dumps({
    "backend_url": self.payload["backend_url"],
    "player_token": self.payload["token"],
    "player_name": self.payload.get("ref") or "",
}, indent=2)}
JSON
chown -R {player_user}:{player_user} "/home/{player_user}/.config" 2>/dev/null || true
echo "OK config -> $CFG/config.json (application $APP, source $PLAYER_DIR)"
"""
        if dry:
            log("  $ ssh <host> sudo bash -s  (écriture de config.json, dérivée du package.json)")
            return
        b64 = base64.b64encode(remote_script.encode()).decode()
        p = run(["ssh", host, f"echo {b64} | base64 -d | sudo bash"], timeout=120, check=False)
        out = (p.stdout or "").strip()
        log(f"  {out[-400:]}")
        if not out.startswith("OK config"):
            raise DriverError(
                "la config de provisioning n'a pas pu être écrite — le player resterait "
                f"sur « Setup required ». Détail : {out[-300:] or (p.stderr or '')[-300:]}")

        # ── 4) Relancer le player pour qu'il RELISE la config ─────────────────
        # Sur une machine « déjà installée » — le cas d'usage même de ce canal — le player
        # tourne, avec son ancienne configuration chargée en mémoire. Sans relance, on écrit
        # un fichier que personne ne rouvre : le provisioning est SANS EFFET, et rien ne le
        # signale. Le driver Windows a `--start-task` pour la même raison.
        log("[4/4] Relance du player (sans quoi il garderait son ancienne config en mémoire)")
        restart = (
            "sudo bash -lc 'if systemctl is-active --quiet lightdm; then "
            "systemctl restart lightdm && echo RESTART_LIGHTDM; "
            "elif pkill -f electron; then echo RESTART_ELECTRON; "
            "else echo NO_PLAYER_RUNNING; fi'")
        p = run(["ssh", host, restart], timeout=120, check=False)
        log(f"  {(p.stdout or '').strip()[-200:]}")
