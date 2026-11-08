"""Audit menu ⑨ Campagnes + portail annonceur (2026-07-31) — sondes de sécurité/cohérence.

Chaque test affirme le comportement ATTENDU. Au moment de l'audit, les rouges sont la
MESURE des défauts (rouge-avant prouvé) ; après correctifs, le fichier reste comme filet.

Le point critique de ce menu n'est pas le multi-tenant (déjà couvert) mais **l'isolation
COMMERCIALE** : un compte annonceur est un EXTERNE logé dans l'organisation du retailer.
Tout ce qu'il lit au-delà de ses propres campagnes est une information de marché.

Constats visés :
  · `GET /campaigns/settings` n'a PAS `require_retailer` alors que le rôle CMS_ADVERTISER
    porte `campaigns:read` ⇒ l'acheteur lit la GRILLE TARIFAIRE du vendeur
    (`sov_daily_rate`, `audio_spot_daily_rate`) et ses quotas internes ;
  · cibles de campagne jamais validées (inexistantes / autre organisation acceptées) —
    même classe que l'audit menu ⑧ et celui des événements ;
  · sites du portail non validés dans `occupancy-check` (réponse « ok » sur un site
    étranger, donc un devis fondé sur du vide) ;
  · traçabilité : ni la modification d'un annonceur ni les mutations de créatifs CMS
    n'écrivent au journal, alors que la revue et la création le font ;
  · `updated_at` entretenu à la main sur 3 chemins seulement.
"""

import uuid
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.audit_log import CmsAuditLog
from app.models.campaign import CmsAdvertiser, CmsCampaign, CmsCampaignCreative
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite
from app.models.player import CmsPlayer
from app.models.role import (
    CmsPermission,
    CmsRole,
    CmsRolePermission,
    CmsUserRoleAssignment,
)
from app.models.user import CmsUser

_RETAILER_PERMS = [
    ("campaigns", "create"), ("campaigns", "read"), ("campaigns", "edit"),
    ("campaigns", "delete"), ("campaigns", "publish"), ("campaigns", "report"),
]
# Ce que porte RÉELLEMENT le rôle système CMS_ADVERTISER (cf. `_advertiser_role_id`).
_ADVERTISER_PERMS = [("campaigns", "read"), ("campaigns", "report")]


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="CampAudit", org_slug=f"ca-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def org_b(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="CampAuditB", org_slug=f"cb-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


async def _mk_user(
    db: AsyncSession, org: CmsOrganization, perms, *, id_advertiser: int | None = None
) -> CmsUser:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(
        id_org=org.id_org, email=f"ca-{uid}@test.com",
        password_hash=hash_password("Password1!"), is_active=True,
        id_advertiser=id_advertiser,
    )
    db.add(user)
    await db.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"CMS_CA_{uid}", label="CA", is_system=False)
    db.add(role)
    await db.flush()
    for module, operation in perms:
        await db.execute(
            pg_insert(CmsPermission)
            .values(module=module, operation=operation, label=f"{module}.{operation}")
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db.flush()
        perm = (await db.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == operation
        ))).scalar_one()
        db.add(CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission))
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    await db.refresh(user)
    return user


def _h(user: CmsUser) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id_user)}"}


@pytest_asyncio.fixture
async def advertiser(db_session: AsyncSession, org) -> CmsAdvertiser:
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="Dyson-like")
    db_session.add(adv)
    await db_session.commit()
    await db_session.refresh(adv)
    return adv


@pytest_asyncio.fixture
async def retailer(db_session: AsyncSession, org) -> CmsUser:
    return await _mk_user(db_session, org, _RETAILER_PERMS)


@pytest_asyncio.fixture
async def adv_user(db_session: AsyncSession, org, advertiser) -> CmsUser:
    """Compte PORTAIL : externe, lié à un annonceur, permissions du rôle système."""
    return await _mk_user(db_session, org, _ADVERTISER_PERMS,
                          id_advertiser=advertiser.id_advertiser)


def _camp_payload(id_advertiser: int, **over) -> dict:
    base = {
        "id_advertiser": id_advertiser, "campaign_name": "Sonde",
        "starts_on": "2026-08-01", "ends_on": "2026-08-31",
        "sov_percent": 10, "targets": [],
    }
    base.update(over)
    return base


# ── Isolation commerciale du portail ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_settings_are_not_readable_by_advertiser(
    client: AsyncClient, db_session: AsyncSession, org, retailer, adv_user
) -> None:
    """🔴 `GET /campaigns/settings` n'exige que `campaigns:read`, que le rôle système
    CMS_ADVERTISER porte — l'ACHETEUR lit donc la grille tarifaire du VENDEUR
    (`sov_daily_rate`, `audio_spot_daily_rate`) et ses quotas internes. Toutes les
    autres surfaces org-wide (inventaire, occupation, catégories) portent bien
    `require_retailer` : c'est la seule qui l'a oublié."""
    org_row = (await db_session.execute(
        select(CmsOrganization).where(CmsOrganization.id_org == org.id_org)
    )).scalar_one()
    org_row.campaign_sov_daily_rate = 42
    await db_session.commit()

    ok = await client.get("/api/v1/campaigns/settings", headers=_h(retailer))
    assert ok.status_code == 200, ok.text  # le retailer garde l'accès

    leak = await client.get("/api/v1/campaigns/settings", headers=_h(adv_user))
    assert leak.status_code == 403, leak.text


@pytest.mark.asyncio
async def test_portal_occupancy_rejects_foreign_site(
    client: AsyncClient, db_session: AsyncSession, org_b, adv_user
) -> None:
    """Le site d'une AUTRE organisation doit être refusé : sans validation, la réponse
    est calculée sur un ensemble d'écrans vide et annonce « disponible » — un devis
    fondé sur du néant."""
    site_b = CmsSite(id_org=org_b.id_org, site_name="SiteB")
    db_session.add(site_b)
    await db_session.commit()
    r = await client.post("/api/v1/portal/occupancy-check", headers=_h(adv_user), json={
        "starts_on": "2026-08-01", "ends_on": "2026-08-10",
        "sov_percent": 10, "site_ids": [site_b.id_site],
    })
    assert r.status_code in (404, 422), r.text


# ── Validation des cibles (CMS) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_campaign_rejects_unknown_target(
    client: AsyncClient, retailer, advertiser
) -> None:
    r = await client.post("/api/v1/campaigns/", headers=_h(retailer), json=_camp_payload(
        advertiser.id_advertiser,
        targets=[{"target_type": "player", "target_id": 99999999}],
    ))
    assert r.status_code in (404, 422), r.text


@pytest.mark.asyncio
async def test_create_campaign_rejects_cross_org_target(
    client: AsyncClient, db_session: AsyncSession, org_b, retailer, advertiser
) -> None:
    site_b = CmsSite(id_org=org_b.id_org, site_name="SiteB2")
    db_session.add(site_b)
    await db_session.commit()
    r = await client.post("/api/v1/campaigns/", headers=_h(retailer), json=_camp_payload(
        advertiser.id_advertiser,
        targets=[{"target_type": "site", "target_id": site_b.id_site}],
    ))
    assert r.status_code in (404, 422), r.text


@pytest.mark.asyncio
async def test_update_campaign_rejects_unknown_target(
    client: AsyncClient, retailer, advertiser
) -> None:
    """Le remplacement des cibles à l'update passe par le même helper que la création :
    s'il ne valide pas, la garde de création se contourne en deux appels."""
    r = await client.post("/api/v1/campaigns/", headers=_h(retailer),
                          json=_camp_payload(advertiser.id_advertiser))
    assert r.status_code == 201, r.text
    cid = r.json()["id_campaign"]
    r2 = await client.put(f"/api/v1/campaigns/{cid}", headers=_h(retailer), json={
        "targets": [{"target_type": "site_group", "target_id": 99999999}],
    })
    assert r2.status_code in (404, 422), r2.text


# ── Traçabilité ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_advertiser_update_writes_audit(
    client: AsyncClient, db_session: AsyncSession, org, retailer, advertiser
) -> None:
    """Créer et supprimer un annonceur sont journalisés, MODIFIER ne l'est pas — or
    c'est la mutation qui change le nom commercial, les catégories d'exclusion et les
    droits de campagne du portail."""
    r = await client.put(f"/api/v1/advertisers/{advertiser.id_advertiser}",
                         headers=_h(retailer), json={"advertiser_name": "Renommé"})
    assert r.status_code == 200, r.text
    n = (await db_session.execute(
        select(func.count()).select_from(CmsAuditLog).where(
            CmsAuditLog.id_org == org.id_org,
            CmsAuditLog.resource_type == "advertiser",
            CmsAuditLog.action == "update",
        )
    )).scalar_one()
    assert n >= 1, "aucune trace d'audit pour la modification d'un annonceur"


@pytest.mark.asyncio
async def test_creative_mutations_write_audit(
    client: AsyncClient, db_session: AsyncSession, org, retailer, advertiser
) -> None:
    """Ajouter / retirer un créatif change ce qui passe à l'antenne et ce qui est
    facturé. La REVUE est journalisée, les mutations non."""
    media = CmsMedia(
        id_org=org.id_org, media_name="spot.mp4", media_type="video",
        storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256="x",
        duration_ms=8000, transcode_status="ready",
    )
    db_session.add(media)
    await db_session.commit()
    r = await client.post("/api/v1/campaigns/", headers=_h(retailer),
                          json=_camp_payload(advertiser.id_advertiser))
    cid = r.json()["id_campaign"]
    add = await client.post(f"/api/v1/campaigns/{cid}/creatives", headers=_h(retailer),
                            json={"id_media": media.id_media})
    assert add.status_code == 201, add.text
    id_creative = add.json()["id_creative"]
    await client.delete(f"/api/v1/campaigns/creatives/{id_creative}", headers=_h(retailer))
    n = (await db_session.execute(
        select(func.count()).select_from(CmsAuditLog).where(
            CmsAuditLog.id_org == org.id_org,
            CmsAuditLog.resource_type == "campaign_creative",
        )
    )).scalar_one()
    assert n >= 2, f"{n} ligne(s) d'audit pour ajout + retrait de créatif"


@pytest.mark.asyncio
async def test_advertiser_updated_at_moves(
    client: AsyncClient, db_session: AsyncSession, retailer, advertiser
) -> None:
    """`updated_at` est entretenu à la main sur 3 chemins de campagne et nulle part
    ailleurs — un annonceur modifié garde la date de sa création."""
    r = await client.put(f"/api/v1/advertisers/{advertiser.id_advertiser}",
                         headers=_h(retailer), json={"contact_name": "Nouveau contact"})
    assert r.status_code == 200, r.text
    row = (await db_session.execute(
        select(CmsAdvertiser).where(
            CmsAdvertiser.id_advertiser == advertiser.id_advertiser)
    )).scalar_one()
    await db_session.refresh(row)
    assert row.updated_at > row.created_at, "updated_at figé à created_at"


# ── Suppression de brouillon au portail (demande d'Ed, 31/07) ────────────────

@pytest.mark.asyncio
async def test_portal_can_delete_own_draft(
    client: AsyncClient, db_session: AsyncSession, org, advertiser, adv_user
) -> None:
    camp = CmsCampaign(
        id_org=org.id_org, id_advertiser=advertiser.id_advertiser,
        campaign_name="Brouillon", status="draft",
        starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31), sov_percent=10,
    )
    db_session.add(camp)
    await db_session.commit()
    await db_session.refresh(camp)
    r = await client.delete(f"/api/v1/portal/campaigns/{camp.id_campaign}",
                            headers=_h(adv_user))
    assert r.status_code == 204, r.text
    await db_session.refresh(camp)
    assert camp.is_deleted is True
    # Elle disparaît de SA liste (le portail lit /campaigns/ scopé annonceur).
    lst = await client.get("/api/v1/campaigns/", headers=_h(adv_user))
    assert camp.id_campaign not in [c["id_campaign"] for c in lst.json()]


@pytest.mark.asyncio
async def test_portal_cannot_delete_published_campaign(
    client: AsyncClient, db_session: AsyncSession, org, advertiser, adv_user
) -> None:
    """Une campagne approuvée diffuse : sa suppression appartient au retailer."""
    camp = CmsCampaign(
        id_org=org.id_org, id_advertiser=advertiser.id_advertiser,
        campaign_name="En diffusion", status="approved",
        starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31), sov_percent=10,
    )
    db_session.add(camp)
    await db_session.commit()
    await db_session.refresh(camp)
    r = await client.delete(f"/api/v1/portal/campaigns/{camp.id_campaign}",
                            headers=_h(adv_user))
    assert r.status_code == 409, r.text
    await db_session.refresh(camp)
    assert camp.is_deleted is False


@pytest.mark.asyncio
async def test_portal_cannot_delete_campaign_under_review(
    client: AsyncClient, db_session: AsyncSession, org, advertiser, adv_user
) -> None:
    """🔑 Le statut reste `draft` pendant la revue : sans garde explicite, l'annonceur
    ferait disparaître une demande de la file du valideur pendant qu'il l'examine."""
    from app.models.approval import CmsApprovalRequest

    camp = CmsCampaign(
        id_org=org.id_org, id_advertiser=advertiser.id_advertiser,
        campaign_name="Soumise", status="draft",
        starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31), sov_percent=10,
    )
    db_session.add(camp)
    await db_session.flush()
    db_session.add(CmsApprovalRequest(
        id_org=org.id_org, resource_type="campaign", resource_id=camp.id_campaign,
        status="pending_review", submitted_by=adv_user.id_user))
    await db_session.commit()
    await db_session.refresh(camp)
    r = await client.delete(f"/api/v1/portal/campaigns/{camp.id_campaign}",
                            headers=_h(adv_user))
    assert r.status_code == 409, r.text
    await db_session.refresh(camp)
    assert camp.is_deleted is False


@pytest.mark.asyncio
async def test_portal_delete_is_scoped_to_own_advertiser(
    client: AsyncClient, db_session: AsyncSession, org, adv_user
) -> None:
    """Le brouillon d'un CONCURRENT (même organisation) = 404, jamais 403."""
    other = CmsAdvertiser(id_org=org.id_org, advertiser_name="Concurrent")
    db_session.add(other)
    await db_session.flush()
    camp = CmsCampaign(
        id_org=org.id_org, id_advertiser=other.id_advertiser,
        campaign_name="Chez le voisin", status="draft",
        starts_on=date(2026, 8, 1), ends_on=date(2026, 8, 31), sov_percent=10,
    )
    db_session.add(camp)
    await db_session.commit()
    await db_session.refresh(camp)
    r = await client.delete(f"/api/v1/portal/campaigns/{camp.id_campaign}",
                            headers=_h(adv_user))
    assert r.status_code == 404, r.text
    await db_session.refresh(camp)
    assert camp.is_deleted is False


# ── Garde de durée des créatifs ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_creative_update_reenforces_duration_limit(
    client: AsyncClient, db_session: AsyncSession, org, retailer, advertiser
) -> None:
    """La limite de durée est vérifiée à l'AJOUT et au publish, mais pas à la
    MODIFICATION : on ajoute une image à 10 s puis on la passe à 300 s. Le publish
    rattrape, mais entre-temps l'écran affiche une valeur que l'organisation interdit
    (et le portail montre un créatif « conforme »)."""
    org_row = (await db_session.execute(
        select(CmsOrganization).where(CmsOrganization.id_org == org.id_org)
    )).scalar_one()
    org_row.campaign_creative_max_duration_s = 30
    media = CmsMedia(
        id_org=org.id_org, media_name="visuel.png", media_type="image",
        storage_key=f"k/{uuid.uuid4().hex}", checksum_sha256="y",
        transcode_status="ready",
    )
    db_session.add(media)
    await db_session.commit()
    r = await client.post("/api/v1/campaigns/", headers=_h(retailer),
                          json=_camp_payload(advertiser.id_advertiser))
    cid = r.json()["id_campaign"]
    add = await client.post(f"/api/v1/campaigns/{cid}/creatives", headers=_h(retailer),
                            json={"id_media": media.id_media, "duration_ms": 10_000})
    assert add.status_code == 201, add.text
    up = await client.put(f"/api/v1/campaigns/creatives/{add.json()['id_creative']}",
                          headers=_h(retailer), json={"duration_ms": 300_000})
    assert up.status_code == 422, up.text
