"""
Bootstrap SignFlow — crée l'org, l'admin, le player nuc-debian12 et génère le token.
Usage : docker compose exec -T backend python3 - < backend/scripts/bootstrap.py
"""

import asyncio
import json
import os
import secrets
import sys

# Assure que le package `app` est importable quel que soit le répertoire d'appel
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "/app")

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import pyotp

from app.core.security import create_player_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services.totp import protect_totp_secret


async def bootstrap() -> None:
    # Parametrable par l'environnement (2026-07-19). Avant, tout etait EN DUR : le meme mot
    # de passe `Admin1234!` pour TOUTE installation, un player de demo « nuc-debian12 » et
    # l'IP du serveur de dev dans le config.json affiche. Inutilisable pour un client --
    # c'est probablement pourquoi `install-ubuntu.sh` ne l'appelait pas du tout, laissant
    # les installations neuves SANS aucun compte pour se connecter.
    admin_email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@vitrail.local")
    # Jamais de mot de passe par defaut : a defaut d'etre fourni, on en tire un au hasard et
    # on l'affiche une seule fois (meme politique que les secrets generes du .env).
    admin_password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") or (
        secrets.token_urlsafe(12) + "aA1!"
    )
    org_name = os.environ.get("BOOTSTRAP_ORG_NAME", "Vitrail")
    org_slug = os.environ.get("BOOTSTRAP_ORG_SLUG", "signflow")
    # Player de demo : utile en dev, hors sujet chez un client. Desactive par defaut.
    demo_player = os.environ.get("BOOTSTRAP_DEMO_PLAYER", "").strip()
    public_url = os.environ.get("PUBLIC_WEB_URL", "").rstrip("/")

    url = os.environ["DATABASE_WORKER_URL"]
    engine = create_async_engine(url)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        org = CmsOrganization(org_name=org_name, org_slug=org_slug)
        db.add(org)
        await db.flush()
        db.add(CmsOrgAuthSettings(id_org=org.id_org))

        totp_secret = pyotp.random_base32()
        user = CmsUser(
            id_org=org.id_org,
            email=admin_email,
            password_hash=hash_password(admin_password),
            is_active=True,
            # Chiffre au repos si le coffre (CMS_VAULT_KEY) est disponible ; repli
            # clair sinon. La lecture (reveal_totp_secret) tolere les deux formes.
            totp_secret=protect_totp_secret(totp_secret),
            totp_enabled=True,
        )
        db.add(user)
        await db.flush()

        await db.execute(
            pg_insert(CmsRole)
            .values(role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
            .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
        )
        await db.flush()
        role = (
            await db.execute(select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN"))
        ).scalar_one()
        db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))

        token = None
        player = None
        if demo_player:
            player = CmsPlayer(id_org=org.id_org, player_name=demo_player, player_os="linux")
            db.add(player)
            await db.flush()
            token, expires_at = create_player_token(player.id_player)
            player.player_token = token
            player.token_expires_at = expires_at
        await db.commit()

        sep = "=" * 55
        print()
        print(sep)
        print("  Bootstrap OK")
        print(sep)
        totp_uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
            name=admin_email, issuer_name="Vitrail"
        )
        print(f"  Admin        : {admin_email}")
        print(f"  Mot de passe : {admin_password}")
        print("  ^ AFFICHE UNE SEULE FOIS -- notez-le maintenant.")
        print(f"  TOTP secret  : {totp_secret}")
        print(f"  TOTP URI     : {totp_uri}")
        print("  (2FA obligatoire pour un org-admin : scannez l'URI AVANT de vous connecter)")
        if player is not None:
            print(sep)
            print(f"  Player demo  : {player.player_name}  (id={player.id_player})")
            base = public_url or "http://<ip-du-serveur>:8080"
            print("  config.json  : " + json.dumps({"backend_url": base, "player_token": token}))
        print(sep)
        print()

asyncio.run(bootstrap())
