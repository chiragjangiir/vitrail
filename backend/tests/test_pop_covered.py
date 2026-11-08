"""Proof of Play — preuves émises ZONE RECOUVERTE (migr 0125).

Depuis P3.6, un spot de campagne peut RECOUVRIR tout l'écran par-dessus un template
multi-zones. Les autres zones ne sont volontairement pas suspendues — les suspendre
décalerait leur wall-clock et désynchroniserait l'écran au retour — donc chaque item qui
démarre dessous émet une preuve : on atteste la diffusion d'un contenu que personne ne
voit. Le takeover VOD produit le même effet, plus longtemps.

Ce n'est pas une fraude annonceur (les spots ne vont que dans la zone 0, jamais un spot
facturé n'est masqué par un autre) : le coût est que ces preuves gonflent le DÉNOMINATEUR
du SOV ⇒ SOV servi sous-évalué ⇒ fausse alerte de sous-diffusion, visible par l'annonceur.

Décision Ed (2026-08-06) : marquer et exclure des comptages, garder en forensique —
le patron `screen_off`.

⚠️ Différence de nature avec `screen_off`, et c'est ce que ces tests protègent : `covered`
est déclaré PAR LE PLAYER (lui seul sait qu'un overlay le masquait) là où `screen_off` est
calculé par le serveur. Le serveur ne peut pas le recalculer : chaque zone a son propre
wall-clock, il n'existe aucune timeline globale à rejouer.

Couvre : marquage à l'ingestion, exclusion des agrégats, présence en vue forensique,
NON-filtrage des chemins d'intégrité, et le cumul des deux causes.
"""

import uuid
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_player_token, hash_password
from app.models.media import CmsMedia
from app.models.organization import CmsOrganization, CmsOrgAuthSettings, CmsSite, CmsSiteHours
from app.models.player import CmsPlayer
from app.models.pop import CmsProofOfPlay
from app.models.role import CmsRole, CmsUserRoleAssignment
from app.models.user import CmsUser

# Dates RELATIVES au jour courant (leçon `test_campaign_audio`, rouge des mois plus tard
# sans que personne n'y touche). Le site ouvre 7 j/7 : le jour de la semaine n'influe pas.
DAY = date.today()


def _utc(hh: int, mm: int = 0) -> str:
    local = datetime.combine(DAY, time(hh, mm), tzinfo=ZoneInfo("Europe/Paris"))
    return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# En pleine ouverture : l'écran est ALLUMÉ, donc `screen_off` ne peut pas se déclencher.
# Sans cette précaution un test « covered » passerait pour la mauvaise raison.
MIDDAY = _utc(12, 0)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="CoveredOrg", org_slug=f"cov-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


@pytest_asyncio.fixture
async def site(db_session: AsyncSession, org: CmsOrganization) -> CmsSite:
    s = CmsSite(
        id_org=org.id_org, site_name="Boutique", timezone="Europe/Paris",
        auto_power_enabled=True, power_lead_min=15, power_lag_min=15,
        respect_holidays=False, holiday_region="FR",
    )
    db_session.add(s)
    await db_session.flush()
    for wd in range(7):
        db_session.add(CmsSiteHours(
            id_site=s.id_site, weekday=wd, is_closed=False,
            open_time=time(8, 0), close_time=time(19, 0),
        ))
    await db_session.commit()
    await db_session.refresh(s)
    return s


@pytest_asyncio.fixture
async def player(db_session: AsyncSession, org: CmsOrganization, site: CmsSite) -> CmsPlayer:
    p = CmsPlayer(
        id_org=org.id_org, player_name=f"p-{uuid.uuid4().hex[:8]}", player_os="linux",
        id_site=site.id_site, display_config={"output_power_fallback": True},
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def visual(db_session: AsyncSession, org: CmsOrganization) -> CmsMedia:
    """Média VISUEL explicite — jamais d'`id_media` codé en dur (ids séquentiels partagés)."""
    m = CmsMedia(id_org=org.id_org, media_name="clip", media_type="video",
                 storage_key=f"k/{uuid.uuid4().hex}.mp4", checksum_sha256=uuid.uuid4().hex * 2)
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return m


@pytest_asyncio.fixture
async def admin_token(db_session: AsyncSession, org: CmsOrganization) -> str:
    user = CmsUser(id_org=org.id_org, email=f"a-{uuid.uuid4().hex[:8]}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsRole).values(role_key="CMS_ORG_ADMIN", label="Org Admin", is_system=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == "CMS_ORG_ADMIN"))).scalar_one()
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    return create_access_token(
        user.id_user, extra={"org": org.id_org, "roles": ["CMS_ORG_ADMIN"], "locale": "en"})


async def _post(client: AsyncClient, player: CmsPlayer, logs: list[dict]):
    token, _ = create_player_token(player.id_player)
    return await client.post(
        "/api/v1/pop/batch", json={"logs": logs},
        headers={"Authorization": f"Bearer {token}"},
    )


async def _flags(db_session: AsyncSession, player: CmsPlayer) -> list[bool]:
    return list((await db_session.execute(
        select(CmsProofOfPlay.covered)
        .where(CmsProofOfPlay.id_player == player.id_player)
        .order_by(CmsProofOfPlay.id_pop)
    )).scalars().all())


# ── Marquage à l'ingestion ─────────────────────────────────────────────────────

async def test_covered_flag_is_persisted_from_the_player(
    client: AsyncClient, db_session: AsyncSession, player: CmsPlayer, visual: CmsMedia
) -> None:
    """Le drapeau déclaré par le player est stocké tel quel, preuve par preuve."""
    resp = await _post(client, player, [
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": True},
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": False},
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": True},
    ])
    assert resp.status_code == 200
    assert resp.json()["covered"] == 2
    assert await _flags(db_session, player) == [True, False, True]
    # Témoin : l'écran est allumé à midi, donc AUCUN marquage `screen_off` — sinon les
    # assertions d'exclusion ci-dessous passeraient pour la mauvaise raison.
    assert resp.json()["screen_off"] == 0


async def test_absent_field_defaults_to_not_covered(
    client: AsyncClient, db_session: AsyncSession, player: CmsPlayer, visual: CmsMedia
) -> None:
    """Un player ANTÉRIEUR au correctif n'envoie pas le champ : il ne ment pas, il ne sait
    pas. Sa preuve doit donc rester comptée — l'inverse retirerait de l'antenne tout le
    parc non encore mis à jour."""
    resp = await _post(client, player, [
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000},
    ])
    assert resp.status_code == 200
    assert resp.json()["covered"] == 0
    assert await _flags(db_session, player) == [False]


# ── Exclusion des comptages ────────────────────────────────────────────────────

async def test_covered_plays_are_excluded_from_analytics(
    client: AsyncClient, player: CmsPlayer, visual: CmsMedia, admin_token: str
) -> None:
    """3 preuves dont 2 recouvertes → l'antenne n'en compte qu'une."""
    await _post(client, player, [
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": True},
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": True},
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 7000, "covered": False},
    ])
    r = await client.get("/api/v1/pop/analytics?days=2",
                         headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_plays"] == 1
    assert body["total_duration_ms"] == 7000


async def test_covered_plays_stay_visible_in_the_forensic_table(
    client: AsyncClient, player: CmsPlayer, visual: CmsMedia, admin_token: str
) -> None:
    """La vue forensique les MONTRE, marquées. Les masquer rendrait le phénomène
    indétectable — on neutralise le comptage, jamais la trace."""
    await _post(client, player, [
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": True},
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": False},
    ])
    r = await client.get(
        f"/api/v1/pop/plays?from={DAY.isoformat()}&until={DAY.isoformat()}"
        f"&id_players={player.id_player}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2, "les deux lignes restent visibles"
    assert sorted(row["covered"] for row in body["rows"]) == [False, True]


# ── Intégrité : JAMAIS filtrée ─────────────────────────────────────────────────

async def test_integrity_paths_never_filter_covered_proofs(
    client: AsyncClient, player: CmsPlayer, visual: CmsMedia, admin_token: str
) -> None:
    """La chaîne et le Merkle root portent sur TOUTES les lignes.

    C'est l'invariant le plus important du module : filtrer un chemin d'intégrité ferait
    diverger le recalcul et produirait un faux « chaîne altérée » — une racine partielle
    est indiscernable d'une chaîne trafiquée.
    """
    await _post(client, player, [
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": True},
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": False},
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": True},
    ])
    h = {"Authorization": f"Bearer {admin_token}"}

    v = await client.get("/api/v1/pop/verify?days=2", headers=h)
    assert v.status_code == 200
    assert v.json()["total"] == 3, "la vérification lit toutes les preuves"
    assert v.json()["chain_valid"] is True, "la chaîne reste continue"

    c = await client.get(
        f"/api/v1/pop/certificate?from={DAY.isoformat()}&until={DAY.isoformat()}", headers=h)
    assert c.status_code == 200
    cert = c.json()
    assert cert["total_covered"] == 3 - 1
    assert cert["total_plays"] == 1, "seuls les COMPTEURS excluent"
    assert cert["merkle_root"], "la racine est calculée sur toutes les lignes"


async def test_both_causes_on_one_proof_are_deducted_only_once(
    client: AsyncClient, player: CmsPlayer, visual: CmsMedia, admin_token: str
) -> None:
    """Une preuve peut cumuler écran coupé ET zone recouverte (spot plein écran diffusé
    après l'extinction programmée). Les deux compteurs de diagnostic la comptent chacun,
    mais l'antenne ne la déduit qu'UNE fois — sinon `total_plays` devient négatif dès que
    les deux causes se recouvrent.
    """
    await _post(client, player, [
        # 06:00 = avant l'allumage → screen_off, ET déclarée recouverte par le player.
        {"id_media": visual.id_media, "played_at": _utc(6, 0), "duration_ms": 5000, "covered": True},
        {"id_media": visual.id_media, "played_at": MIDDAY, "duration_ms": 5000, "covered": False},
    ])
    r = await client.get(
        f"/api/v1/pop/certificate?from={DAY.isoformat()}&until={DAY.isoformat()}",
        headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    cert = r.json()
    assert cert["total_screen_off"] == 1
    assert cert["total_covered"] == 1
    assert cert["total_plays"] == 1, "2 preuves - 1 ligne non comptée (et non - 2 causes)"
    assert cert["players"][0]["plays"] == 1
