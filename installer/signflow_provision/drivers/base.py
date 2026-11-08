"""Contrat commun des drivers de provisioning (§XXIX).

Un driver consomme le `payload` (dict, cf. ProvisioningPayload backend) et pose SignFlow sur
le device via le canal propre à l'OS (ADB / SSH / SD…). Il n'appelle PAS le CMS lui-même — le
CLI orchestre auth CMS → payload → driver → vérif online.
"""

from __future__ import annotations

import shutil
import subprocess


class DriverError(RuntimeError):
    pass


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise DriverError(
            f"Outil « {name} » introuvable dans le PATH. Installe-le puis réessaie.")
    return path


def run(cmd: list[str], *, timeout: int = 120, check: bool = True,
        capture: bool = True) -> subprocess.CompletedProcess:
    """Exécute une commande externe (jamais via shell → pas d'injection)."""
    proc = subprocess.run(
        cmd, timeout=timeout, check=False,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None, text=True)
    if check and proc.returncode != 0:
        out = (proc.stdout or "").strip()
        raise DriverError(f"Échec de : {' '.join(cmd)}\n{out}")
    return proc


class Driver:
    os_name: str = ""

    def __init__(self, payload: dict, opts: dict):
        self.payload = payload
        self.opts = opts          # options CLI (ip, apk, ssh creds, dry_run…)

    def provision(self, log) -> None:
        """Pose SignFlow sur le device. `log(msg)` = feedback à l'opérateur."""
        raise NotImplementedError
