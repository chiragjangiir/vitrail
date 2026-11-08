"""Driver BrightSign — canal carte SD (§XXIX).

BrightSign n'a pas d'équivalent « adb » : le provisioning passe par une **carte SD** (ou upload
DWS si activé). Ce driver écrit le `config.json` attendu par l'autorun BrightSign dans un dossier
de sortie et guide l'opérateur pour copier le contenu à la racine de la SD. La génération du ZIP
complet (autorun + renderers) reste faite par le CMS (`BrightSignSdDrawer`) ; ici on produit au
minimum le `config.json` de provisioning à déposer sur une SD déjà préparée.
"""

from __future__ import annotations

import json
import os

from .base import Driver


class BrightSignDriver(Driver):
    os_name = "brightsign"

    def provision(self, log) -> None:
        out = self.opts.get("out") or os.path.join(os.getcwd(), "brightsign-sd")
        os.makedirs(out, exist_ok=True)

        # L'autorun lit `cfg.token` (autorun.brs) — pas `provisioning_token`.
        cfg = {
            "backend_url": self.payload["backend_url"],
            "token": self.payload["token"],
        }
        if self.payload.get("options"):
            cfg.update(self.payload["options"])
        net = self.payload.get("network")
        if net and net.get("mode") == "static":
            cfg["network"] = net

        path = os.path.join(out, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

        log(f"[1/1] config.json de provisioning écrit → {path}")
        log("")
        log("  BrightSign = canal carte SD (pas de prise en main réseau) :")
        log("  1) Génère la carte SD complète depuis le CMS (page Provisioning → « Carte SD "
            "BrightSign ») OU utilise une SD déjà préparée (autorun + renderers).")
        log(f"  2) Copie ce config.json à la RACINE de la SD (remplace l'existant) : {path}")
        log("  3) Insère la SD dans le BrightSign et démarre-le.")
