"""Seed démo SignFlow — 2 organisations (tenants) + 1 utilisateur par rôle métier
+ compte DÉMO lecture seule (`demo@…`, is_demo) + ANNONCEUR DÉMO complet
(annonceur + campagne approuvée + compte portail is_demo `advertiser@…`).

Idempotent (orgs par slug, users par email, annonceur par nom) : rejouable en 1 commande.
Usage : docker compose exec -T backend python3 - < backend/scripts/seed_demo.py

⚠️ 2FA forcée pour ORG_ADMIN au login → l'URI TOTP est imprimée à la création
(les rôles métier se connectent normalement, sans 2FA forcée).
"""

import asyncio
import os
import secrets
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "/app")

import pyotp
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import hash_password
from app.models.campaign import CmsAdvertiser, CmsCampaign, CmsCampaignTarget
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser
from app.services.tags import seed_standard_namespaces

ORGS = [("Boutique Démo", "boutique-demo"), ("Retail Démo", "retail-demo")]
# Jamais de mot de passe en dur : une valeur publiée dans le code est connue de tous. Tirés au
# sort à chaque exécution (affichés une fois ci-dessous), ou imposés par variable d'environnement.
ADMIN_PWD = os.environ.get("SEED_ADMIN_PASSWORD") or (secrets.token_urlsafe(12) + "aA1!")
USER_PWD = os.environ.get("SEED_USER_PASSWORD") or (secrets.token_urlsafe(12) + "aA1!")
BUSINESS_ROLES = [
    "CMS_CAMPAIGN_MANAGER",
    "CMS_DESIGNER",
    "CMS_SCHEDULER",
    "CMS_APPROVER",
    "CMS_REPORT_VIEWER",
    "CMS_VIEWER",
    "CMS_STORE_OPERATOR",
]


async def _role_id(db: AsyncSession, key: str) -> int:
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == key))).scalar_one_or_none()
    if role is None:
        raise SystemExit(f"Rôle système {key} absent — la base n'est pas seedée (IAM 0002).")
    return role.id_role


async def _get_or_create_org(db: AsyncSession, name: str, slug: str) -> CmsOrganization:
    org = (
        await db.execute(select(CmsOrganization).where(CmsOrganization.org_slug == slug))
    ).scalar_one_or_none()
    if org:
        return org
    org = CmsOrganization(org_name=name, org_slug=slug)
    db.add(org)
    await db.flush()
    db.add(CmsOrgAuthSettings(id_org=org.id_org))
    await seed_standard_namespaces(db, org.id_org)
    return org


async def _get_or_create_user(
    db: AsyncSession, id_org: int, email: str, pwd: str, role_keys: list[str], totp: bool,
    is_demo: bool = False, id_advertiser: int | None = None,
) -> tuple[CmsUser, bool, str | None]:
    user = (await db.execute(select(CmsUser).where(CmsUser.email == email))).scalar_one_or_none()
    created = False
    secret = None
    if user is None:
        secret = pyotp.random_base32() if totp else None
        user = CmsUser(
            id_org=id_org,
            email=email,
            password_hash=hash_password(pwd),
            is_active=True,
            totp_secret=secret,
            totp_enabled=totp,
            is_demo=is_demo,
            id_advertiser=id_advertiser,
        )
        db.add(user)
        await db.flush()
        created = True
    for key in role_keys:
        rid = await _role_id(db, key)
        await db.execute(
            pg_insert(CmsUserRoleAssignment)
            .values(id_user=user.id_user, id_role=rid, is_deny=False)
            .on_conflict_do_nothing(index_elements=["id_user", "id_role"])
        )
    return user, created, secret


async def main() -> None:
    engine = create_async_engine(settings.db_worker_url)  # BYPASSRLS : écrit dans plusieurs orgs
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    sep = "=" * 64
    print(f"\n{sep}\n  SEED DÉMO — organisations & utilisateurs\n{sep}")

    async with Session() as db:
        for name, slug in ORGS:
            org = await _get_or_create_org(db, name, slug)
            await db.flush()
            print(f"\n[{name}]  (id_org={org.id_org}, slug={slug})")

            admin_email = f"admin@{slug}.demo"
            _, created, secret = await _get_or_create_user(
                db, org.id_org, admin_email, ADMIN_PWD, ["CMS_ORG_ADMIN"], totp=True
            )
            await db.commit()
            if created and secret:
                uri = pyotp.totp.TOTP(secret).provisioning_uri(name=admin_email, issuer_name="SignFlow")
                print(f"  ORG_ADMIN   {admin_email}  /  {ADMIN_PWD}")
                print(f"     TOTP secret : {secret}")
                print(f"     TOTP URI    : {uri}")
            else:
                print(f"  ORG_ADMIN   {admin_email}  (existant — TOTP déjà enrôlé)")

            for rk in BUSINESS_ROLES:
                email = f"{rk.removeprefix('CMS_').lower()}@{slug}.demo"
                _, created, _ = await _get_or_create_user(db, org.id_org, email, USER_PWD, [rk], totp=False)
                await db.commit()
                tag = "créé" if created else "ok"
                print(f"  {rk:<22} {email}  /  {USER_PWD}   [{tag}]")

            # ── Compte DÉMO lecture seule (garde demo_blocked + bulles d'infos) ──
            demo_email = f"demo@{slug}.demo"
            _, created, _ = await _get_or_create_user(
                db, org.id_org, demo_email, USER_PWD, ["CMS_ORG_ADMIN"],
                totp=False, is_demo=True,
            )
            await db.commit()
            print(f"  {'DÉMO (lecture seule)':<22} {demo_email}  /  {USER_PWD}   "
                  f"[{'créé' if created else 'ok'}]")

            # ── Annonceur DÉMO + campagne approuvée + compte portail is_demo ─────
            adv = (await db.execute(select(CmsAdvertiser).where(
                CmsAdvertiser.id_org == org.id_org,
                CmsAdvertiser.advertiser_name == "Marque Démo",
                CmsAdvertiser.is_deleted == False,  # noqa: E712
            ))).scalars().first()
            if adv is None:
                adv = CmsAdvertiser(
                    id_org=org.id_org, advertiser_name="Marque Démo",
                    contact_email=f"advertiser@{slug}.demo",
                )
                db.add(adv)
                await db.flush()
                # Dossier médiathèque « Annonceurs/Marque Démo » (même helper que l'API)
                from app.api.v1.endpoints.campaigns import _ensure_advertiser_folder
                await _ensure_advertiser_folder(db, adv)
            camp = (await db.execute(select(CmsCampaign).where(
                CmsCampaign.id_advertiser == adv.id_advertiser,
                CmsCampaign.is_deleted == False,  # noqa: E712
            ))).scalars().first()
            if camp is None:
                camp = CmsCampaign(
                    id_org=org.id_org, id_advertiser=adv.id_advertiser,
                    campaign_name="Campagne Démo — Été", status="approved",
                    starts_on=date.today() - timedelta(days=7),
                    ends_on=date.today() + timedelta(days=23),
                    sov_percent=15, pricing_model="sov", price_amount=1500,
                )
                db.add(camp)
                await db.flush()
                db.add(CmsCampaignTarget(
                    id_org=org.id_org, id_campaign=camp.id_campaign,
                    target_type="org", target_id=None, tag_expr={},
                ))
            adv_email = f"advertiser@{slug}.demo"
            _, created, _ = await _get_or_create_user(
                db, org.id_org, adv_email, USER_PWD, ["CMS_ADVERTISER"],
                totp=False, is_demo=True, id_advertiser=adv.id_advertiser,
            )
            await db.commit()
            print(f"  {'ANNONCEUR DÉMO':<22} {adv_email}  /  {USER_PWD}   "
                  f"[{'créé' if created else 'ok'}]  → /portal (Marque Démo)")

    print(f"\n{sep}\n  Terminé. Les rôles métier se connectent sans 2FA forcée.\n{sep}\n")


asyncio.run(main())
