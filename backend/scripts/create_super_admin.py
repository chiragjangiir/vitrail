#!/usr/bin/env python3
"""Création du compte SUPER-ADMIN.

Le super-admin est le seul rôle qui peut créer des organisations et provisionner leurs
administrateurs (`/orgs`, 15 routes). Il n'a jamais existé en production : `bootstrap.py`
ne crée qu'un `CMS_ORG_ADMIN`, et l'attribuer par API est INTERDIT depuis le correctif
d'escalade du 2026-07-20 (`users.py:_PLATFORM_ROLE_KEYS`) — un org-admin pouvait sinon
se hisser super-admin via un groupe ou la copie d'un rôle plateforme.

Ce script est donc le **seul** chemin de création, et il est délibérément hors de l'API :
il exige un accès shell au serveur (preuve de possession, comme `bootstrap.py`).

⚠️ Le super-admin voit les données des organisations qu'il administre (décision Ed du
2026-07-23, D1). C'est ce qui lui permet de dépanner ses marques — et c'est à assumer
explicitement vis-à-vis d'elles.

Usage
-----
  docker compose exec -T backend python3 /app/scripts/create_super_admin.py \
      --email admin@integrateur.fr [--password '…'] [--org-slug signflow]

Sans `--password`, un mot de passe fort est tiré au sort et affiché UNE fois.
La 2FA est **obligatoire** : le secret et l'URI `otpauth` sont affichés à la création.
Ne pas les afficher produirait un compte structurellement inaccessible — c'est
exactement le défaut vécu le 2026-07-19 sur l'installeur.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "/app")

import pyotp  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.models.audit_log import CmsAuditLog  # noqa: E402
from app.models.organization import CmsOrganization  # noqa: E402
from app.models.role import CmsRole, CmsUserRoleAssignment  # noqa: E402
from app.models.user import CmsUser  # noqa: E402
from app.services.totp import protect_totp_secret  # noqa: E402

ROLE_KEY = "CMS_SUPER_ADMIN"


async def run(args: argparse.Namespace) -> None:
    password = args.password or (secrets.token_urlsafe(12) + "aA1!")
    engine = create_async_engine(os.environ["DATABASE_WORKER_URL"])
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        if (await db.execute(
            select(CmsUser).where(CmsUser.email == args.email)
        )).scalar_one_or_none():
            raise SystemExit(f"L'email {args.email} est déjà utilisé.")

        # Le super-admin est un compte PLATEFORME : ses endpoints passent par
        # get_db_worker (BYPASSRLS) et le login l'exempte de la suspension d'org.
        # Son rattachement à une organisation n'est donc qu'une formalité de schéma
        # (`cms_users.id_org` est NOT NULL) — on prend la plus ancienne par défaut,
        # sans en créer une nouvelle qui polluerait la console.
        q = select(CmsOrganization).order_by(CmsOrganization.id_org)
        if args.org_slug:
            q = select(CmsOrganization).where(CmsOrganization.org_slug == args.org_slug)
        org = (await db.execute(q.limit(1))).scalar_one_or_none()
        if org is None:
            raise SystemExit(
                f"Organisation introuvable ({args.org_slug or 'aucune organisation en base'}).\n"
                "  Lancez d'abord bootstrap.py sur une installation vierge."
            )

        # Le rôle système peut ne pas être seedé (bases anciennes) : même précaution
        # que bootstrap.py.
        await db.execute(
            pg_insert(CmsRole)
            .values(role_key=ROLE_KEY, label="Super Admin", is_system=True)
            .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
        )
        await db.flush()
        role = (await db.execute(
            select(CmsRole).where(CmsRole.role_key == ROLE_KEY)
        )).scalar_one()

        totp_secret = pyotp.random_base32()
        user = CmsUser(
            id_org=org.id_org,
            email=args.email,
            password_hash=hash_password(password),
            full_name=args.full_name,
            is_active=True,
            # Chiffré au repos si le coffre est disponible (repli clair sinon — la
            # lecture, `reveal_totp_secret`, tolère les deux formes).
            totp_secret=protect_totp_secret(totp_secret),
            totp_enabled=True,   # 2FA FORCÉE pour ce rôle (auth.py:158)
        )
        db.add(user)
        await db.flush()
        db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
        db.add(CmsAuditLog(
            id_org=org.id_org,
            id_user=None,
            action="super_admin_created",
            resource_type="user",
            resource_id=str(user.id_user),
            detail={"email": args.email},
            source="cli",
        ))
        await db.commit()

        uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
            name=args.email, issuer_name="Vitrail"
        )
        sep = "=" * 60
        print(f"\n{sep}\n  SUPER-ADMIN CRÉÉ\n{sep}")
        print(f"  Organisation : {org.org_name} (rattachement technique)")
        print(f"  Email        : {args.email}")
        print(f"  Mot de passe : {password}")
        print("  ^ AFFICHÉ UNE SEULE FOIS — notez-le maintenant.")
        print(f"  TOTP secret  : {totp_secret}")
        print(f"  TOTP URI     : {uri}")
        print("  2FA OBLIGATOIRE pour ce rôle : enrôlez l'URI AVANT de vous connecter,")
        print("  sinon le compte sera inutilisable.")
        print(f"{sep}\n")
        print("  Console de provisioning : Réglages → Organisations\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", help="généré si absent (affiché une fois)")
    ap.add_argument("--full-name", default=None)
    ap.add_argument("--org-slug",
                    help="organisation de rattachement (défaut : la plus ancienne)")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
