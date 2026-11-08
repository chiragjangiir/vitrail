"""Affiche le secret TOTP + l'URI otpauth d'un utilisateur (dépannage local).

⚠️ OUTIL DE DEV / BOOTSTRAP LOCAL UNIQUEMENT — lit le secret 2FA stocké en base.
En production, l'enrôlement 2FA passe par l'auto-enrôlement de l'utilisateur ou par
la console super-admin (cf. modèle « platform admin »), jamais par la lecture du secret.

Usage :
  SHOW_TOTP_EMAIL=admin@boutique-demo.demo \
    docker compose -p signflow exec -T -e SHOW_TOTP_EMAIL \
      backend python3 - < backend/scripts/show_totp.py

⚠️ CORRIGÉ le 2026-07-19 — ce script affichait `user.totp_secret` BRUT. Depuis que
les secrets 2FA sont chiffrés au repos (durcissement du pentest 2026-06-24), cette
colonne contient un jeton Fernet (`gAAAAA…`, ~140 caractères) et non le secret TOTP.
Il livrait donc une clé INEXPLOITABLE : saisie dans une application d'authentification
elle ne produit aucun code valide, sans que rien ne signale l'erreur. Constaté sur une
installation neuve où c'était le SEUL moyen documenté d'entrer dans le compte admin.
On passe désormais par `reveal_totp_secret()`, la même fonction que le chemin de
connexion — tolérante aux secrets hérités non chiffrés.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "/app")

import pyotp
from sqlalchemy import select

from app.db.session import WorkerSessionLocal
from app.models.organization import CmsOrganization
from app.models.user import CmsUser
from app.services.totp import reveal_totp_secret

EMAIL = os.environ.get("SHOW_TOTP_EMAIL")


async def main() -> None:
    if not EMAIL:
        raise SystemExit("Définir SHOW_TOTP_EMAIL=<email>")
    async with WorkerSessionLocal() as db:
        user = (
            await db.execute(select(CmsUser).where(CmsUser.email == EMAIL))
        ).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"Utilisateur {EMAIL} introuvable.")
        org_name = (
            await db.execute(
                select(CmsOrganization.org_name).where(CmsOrganization.id_org == user.id_org)
            )
        ).scalar_one_or_none() or "SignFlow"

    if not user.totp_secret:
        print(f"{EMAIL} : aucun secret TOTP enrôlé (totp_enabled={user.totp_enabled}).")
        return

    secret = reveal_totp_secret(user.totp_secret)

    # Un secret TOTP est du base32 (~32 caractères). Si le déchiffrement a échoué,
    # `reveal_totp_secret` renvoie la valeur stockée telle quelle — donc le jeton
    # Fernet, qui ne produirait aucun code valide. Mieux vaut le dire que livrer
    # une clé silencieusement inutilisable.
    if secret.startswith("gAAAA") or len(secret) > 64:
        raise SystemExit(
            "Le secret n'a pas pu être déchiffré (CMS_VAULT_KEY absente ou différente "
            "de celle ayant servi au chiffrement). Aucune clé exploitable à afficher."
        )

    uri = pyotp.TOTP(secret).provisioning_uri(name=EMAIL, issuer_name=org_name)
    print(f"\n{EMAIL}  (org={org_name}, 2FA active={user.totp_enabled})")
    print(f"  Clé (saisie manuelle Google Authenticator) : {secret}")
    print(f"  URI otpauth                                : {uri}\n")


asyncio.run(main())
