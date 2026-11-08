"""Tests AI Assistant RAG (§XXVII).

Conçus pour tourner SANS Ollama : on insère des chunks avec des vecteurs fixes et on teste
le découpage/frontmatter (pur) + le filtrage par rôle de la recherche (SQL pgvector).
"""

import pytest

from app.models.assistant import CmsDocChunk
from app.models.organization import CmsOrganization
from app.models.player import CmsPlayer
from app.services import doc_index
from app.services.assistant_agent import build_system_prompt
from app.services.assistant_tools import query_tenant_data, search_chunks

_VEC = [1.0] + [0.0] * 767  # vecteur non nul (cosine défini)


def test_doc_chunk_indexed_with_correct_roles(tmp_path):
    """Le frontmatter `roles` est correctement extrait dans chaque chunk du fichier."""
    md = tmp_path / "secret.md"
    md.write_text(
        "---\n"
        "title: Page admin\n"
        "roles: [CMS_ORG_ADMIN, CMS_SCHEDULER]\n"
        "keywords: [config, avancé]\n"
        "---\n\n"
        "# Page admin\n\n"
        "## Section A\n\nContenu de la section A, suffisamment long pour être un chunk valide.\n\n"
        "## Section B\n\nContenu de la section B, lui aussi assez long pour passer le seuil.\n",
        encoding="utf-8",
    )
    chunks = doc_index.build_chunks(md)

    assert len(chunks) == 2
    assert chunks[0]["roles"] == ["CMS_ORG_ADMIN", "CMS_SCHEDULER"]
    assert chunks[1]["roles"] == ["CMS_ORG_ADMIN", "CMS_SCHEDULER"]
    assert chunks[0]["keywords"] == ["config", "avancé"]
    assert chunks[0]["section_anchor"] == "Section A"
    # chunk_id stable (hash du fichier + index) → réindexation idempotente
    assert chunks[0]["chunk_id"] != chunks[1]["chunk_id"]
    assert doc_index.build_chunks(md)[0]["chunk_id"] == chunks[0]["chunk_id"]


def test_open_doc_has_empty_roles(tmp_path):
    """Un doc sans `roles` (ou `roles: []`) est visible par tous (liste vide)."""
    md = tmp_path / "public.md"
    md.write_text(
        "---\ntitle: Public\nroles: []\n---\n\n# Public\n\n## Intro\n\n"
        "Du texte public assez long pour constituer un chunk valide et indexable.\n",
        encoding="utf-8",
    )
    chunks = doc_index.build_chunks(md)
    assert chunks and chunks[0]["roles"] == []


@pytest.mark.asyncio
async def test_rag_search_filters_by_user_role(db_session):
    """La recherche RAG ne renvoie pas à un VIEWER un chunk réservé à un autre rôle."""
    db_session.add_all([
        CmsDocChunk(chunk_id="open1", source_file="t.md", title="T", section_anchor="Open",
                    content="contenu public", roles=[], embedding=_VEC),
        CmsDocChunk(chunk_id="adm1", source_file="t.md", title="T", section_anchor="Admin",
                    content="contenu réservé admin", roles=["CMS_ORG_ADMIN"], embedding=_VEC),
    ])
    await db_session.flush()

    # Un VIEWER (non-admin) ne voit que le chunk ouvert
    viewer = await search_chunks(db_session, _VEC, roles=["CMS_VIEWER"], admin=False, limit=10)
    assert {r["content"] for r in viewer} == {"contenu public"}

    # Un utilisateur dont un rôle figure dans `roles` voit aussi le chunk réservé (overlap)
    overlap = await search_chunks(db_session, _VEC, roles=["CMS_ORG_ADMIN"], admin=False, limit=10)
    assert {r["content"] for r in overlap} == {"contenu public", "contenu réservé admin"}

    # Un admin (super/org-admin) voit toute la doc, quel que soit `roles`
    adm = await search_chunks(db_session, _VEC, roles=["CMS_SUPER_ADMIN"], admin=True, limit=10)
    assert {r["content"] for r in adm} == {"contenu public", "contenu réservé admin"}

    # Score cosine présent et borné
    assert all(0.0 <= r["score"] <= 1.0001 for r in adm)


@pytest.mark.asyncio
async def test_intent_count_players_respects_rls(db_session):
    """L'intent ne compte que les players de l'org demandée (scoping id_org)."""
    org_a = CmsOrganization(org_name="OrgA", org_slug="org-a-assist")
    org_b = CmsOrganization(org_name="OrgB", org_slug="org-b-assist")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    db_session.add_all([
        CmsPlayer(id_org=org_a.id_org, player_name="A1", status="online"),
        CmsPlayer(id_org=org_a.id_org, player_name="A2", status="offline"),
        CmsPlayer(id_org=org_b.id_org, player_name="B1", status="online"),
    ])
    await db_session.flush()

    res = await query_tenant_data(db_session, org_a.id_org, "count_players_by_status")
    assert res["total"] == 2
    assert res["by_status"] == {"online": 1, "offline": 1}

    # L'org B ne voit jamais les players de A
    res_b = await query_tenant_data(db_session, org_b.id_org, "count_players_by_status")
    assert res_b["total"] == 1
    assert res_b["by_status"] == {"online": 1}

    # Health score dérivé du même périmètre org
    health = await query_tenant_data(db_session, org_a.id_org, "get_network_health_score")
    assert health["total_players"] == 2 and health["online_players"] == 1
    assert health["score"] == 50


@pytest.mark.asyncio
async def test_assistant_cannot_trigger_write_endpoint(db_session):
    """L'agent n'a AUCUN intent d'écriture : tout intent hors whitelist est rejeté sans effet."""
    org = CmsOrganization(org_name="OrgW", org_slug="org-w-assist")
    db_session.add(org)
    await db_session.flush()
    db_session.add(CmsPlayer(id_org=org.id_org, player_name="W1", status="online"))
    await db_session.flush()

    for forbidden in ("delete_player", "update_schedule", "drop_table", "create_user"):
        res = await query_tenant_data(db_session, org.id_org, forbidden)
        assert "error" in res
        assert "allowed" in res  # la réponse expose la whitelist, ne fait aucune écriture

    # La donnée est intacte : le player existe toujours
    after = await query_tenant_data(db_session, org.id_org, "count_players_by_status")
    assert after["total"] == 1


def test_assistant_responds_in_user_locale():
    """Le prompt système force la langue de réponse sur la locale de l'utilisateur (§XXVIII.6)."""
    fr = build_system_prompt("fr", ["CMS_VIEWER"], {"page": "/players"})
    assert "français" in fr and "« fr »" in fr
    assert "/players" in fr  # le contexte de page est injecté

    en = build_system_prompt("en", [], None)
    assert "English" in en and "« en »" in en

    # Lecture seule annoncée dans le prompt (garde-fou §27.9)
    assert "LECTURE SEULE" in fr


@pytest.mark.asyncio
async def test_intent_list_players_status(db_session):
    """list_players_status renvoie la liste nominative + le nombre de déconnectés (RLS)."""
    org = CmsOrganization(org_name="OrgPS", org_slug="org-ps-assist")
    db_session.add(org)
    await db_session.flush()
    db_session.add_all([
        CmsPlayer(id_org=org.id_org, player_name="P-online", status="online"),
        CmsPlayer(id_org=org.id_org, player_name="P-offline", status="offline"),
    ])
    await db_session.flush()

    res = await query_tenant_data(db_session, org.id_org, "list_players_status")
    assert res["count"] == 2 and res["offline_count"] == 1
    assert {p["player"] for p in res["players"]} == {"P-online", "P-offline"}


@pytest.mark.asyncio
async def test_intent_list_playlists(db_session):
    """list_playlists renvoie nom + nombre d'items."""
    from app.models.media import CmsMedia
    from app.models.playlist import CmsPlaylist, CmsPlaylistItem
    org = CmsOrganization(org_name="OrgPL", org_slug="org-pl-assist")
    db_session.add(org)
    await db_session.flush()
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="Vitrine")
    db_session.add(pl)
    await db_session.flush()
    m = CmsMedia(id_org=org.id_org, media_name="clip", media_type="video",
                 storage_key="k", checksum_sha256="x" * 64)
    db_session.add(m)
    await db_session.flush()
    db_session.add(CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m.id_media, sort_order=0))
    await db_session.flush()

    res = await query_tenant_data(db_session, org.id_org, "list_playlists")
    assert res["count"] == 1
    assert res["playlists"][0]["name"] == "Vitrine" and res["playlists"][0]["items"] == 1


@pytest.mark.asyncio
async def test_intent_playlist_details(db_session):
    """playlist_details : items ordonnés + durée de boucle + programmation + players en
    lecture ; erreurs filtre manquant / introuvable."""
    from app.models.media import CmsMedia
    from app.models.playlist import CmsPlaylist, CmsPlaylistItem
    from app.models.schedule import CmsSchedule, CmsScheduleTarget
    org = CmsOrganization(org_name="OrgPD", org_slug="org-pd-assist")
    db_session.add(org)
    await db_session.flush()
    pl = CmsPlaylist(id_org=org.id_org, playlist_name="Playlist XT1144")
    db_session.add(pl)
    await db_session.flush()
    m1 = CmsMedia(id_org=org.id_org, media_name="clip-a", media_type="video",
                  storage_key="k1", checksum_sha256="a" * 64, duration_ms=120_000)
    m2 = CmsMedia(id_org=org.id_org, media_name="promo-b", media_type="image",
                  storage_key="k2", checksum_sha256="b" * 64)
    db_session.add_all([m1, m2])
    await db_session.flush()
    db_session.add_all([
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m2.id_media,
                        sort_order=1, duration_ms=30_000),
        CmsPlaylistItem(id_playlist=pl.id_playlist, id_media=m1.id_media, sort_order=0),
    ])
    player = CmsPlayer(id_org=org.id_org, player_name="BS-test", status="online")
    db_session.add(player)
    await db_session.flush()
    # « qui la joue » = PoP récent (current_playlist_id n'est pas alimenté)
    from datetime import datetime, timezone
    from app.models.pop import CmsProofOfPlay
    db_session.add(CmsProofOfPlay(
        id_org=org.id_org, id_player=player.id_player, id_playlist=pl.id_playlist,
        id_media=m1.id_media, played_at=datetime.now(timezone.utc),
        duration_ms=1000, merkle_hash="h" * 64))
    sched = CmsSchedule(id_org=org.id_org, schedule_name="Prog vitrine",
                        id_playlist=pl.id_playlist)
    db_session.add(sched)
    await db_session.flush()
    db_session.add(CmsScheduleTarget(id_schedule=sched.id_schedule,
                                     target_type="player", target_id=player.id_player))
    await db_session.flush()

    res = await query_tenant_data(db_session, org.id_org, "playlist_details",
                                  {"playlist": "XT1144"})
    assert res["playlist"] == "Playlist XT1144" and res["item_count"] == 2
    # ordre = sort_order (clip-a d'abord) ; durée item = override sinon durée média
    assert [i["media"] for i in res["items"]] == ["clip-a", "promo-b"]
    assert res["items"][0]["duration_seconds"] == 120
    assert res["items"][1]["duration_seconds"] == 30
    assert res["loop_duration_seconds"] == 150
    assert res["schedules"][0]["schedule"] == "Prog vitrine"
    assert res["schedules"][0]["targets"] == ["BS-test"]
    assert res["currently_playing_on"][0]["player"] == "BS-test"

    assert "error" in await query_tenant_data(
        db_session, org.id_org, "playlist_details", {})
    assert "error" in await query_tenant_data(
        db_session, org.id_org, "playlist_details", {"playlist": "n-existe-pas"})


@pytest.mark.asyncio
async def test_intent_list_sites_and_players_by_site(db_session):
    """list_sites : compte + parc rattaché + non-rattachés + HORAIRES D'OUVERTURE
    (« ouvert le dimanche ? » — jour absent = fermé, exceptions à venir listées) ;
    list_players_status filtre par filters.site."""
    from datetime import date, time, timedelta

    from app.models.organization import CmsSite, CmsSiteException, CmsSiteHours
    org = CmsOrganization(org_name="OrgSI", org_slug="org-si-assist")
    db_session.add(org)
    await db_session.flush()
    s1 = CmsSite(id_org=org.id_org, site_name="Domicile", timezone="Europe/Paris",
                 auto_power_enabled=True, respect_holidays=True)
    s2 = CmsSite(id_org=org.id_org, site_name="Bureau")
    db_session.add_all([s1, s2])
    await db_session.flush()
    # Lun→Sam 08:00-19:00 ; dimanche = PAS de ligne (= fermé, sémantique resolve_day).
    db_session.add_all([
        CmsSiteHours(id_site=s1.id_site, weekday=d,
                     open_time=time(8, 0), close_time=time(19, 0))
        for d in range(6)
    ])
    db_session.add(CmsSiteException(
        id_site=s1.id_site, date_from=date.today() + timedelta(days=3),
        date_to=date.today() + timedelta(days=3), kind="closed", label="Inventaire"))
    db_session.add_all([
        CmsPlayer(id_org=org.id_org, player_name="P-dom-1", status="online",
                  id_site=s1.id_site),
        CmsPlayer(id_org=org.id_org, player_name="P-dom-2", status="offline",
                  id_site=s1.id_site),
        CmsPlayer(id_org=org.id_org, player_name="P-sans-site", status="online"),
    ])
    await db_session.flush()

    res = await query_tenant_data(db_session, org.id_org, "list_sites")
    assert res["count"] == 2 and res["players_without_site"] == 1
    dom = next(s for s in res["sites"] if s["name"] == "Domicile")
    assert dom["players"] == 2 and dom["players_online"] == 1
    assert dom["timezone"] == "Europe/Paris" and dom["auto_power_enabled"] is True
    assert dom["opening_hours"]["samedi"] == "08:00-19:00"
    assert dom["opening_hours"]["dimanche"] == "fermé"
    assert dom["closed_on_public_holidays"] == "oui (FR)"
    assert dom["upcoming_exceptions"][0]["kind"] == "closed"
    assert dom["upcoming_exceptions"][0]["label"] == "Inventaire"
    bur = next(s for s in res["sites"] if s["name"] == "Bureau")
    assert bur["opening_hours"] == "non configurés"
    assert bur["upcoming_exceptions"] == []

    only_dom = await query_tenant_data(db_session, org.id_org, "list_players_status",
                                       {"site": "domicile"})
    assert only_dom["count"] == 2
    assert {pp["player"] for pp in only_dom["players"]} == {"P-dom-1", "P-dom-2"}
    assert all(pp["site"] == "Domicile" for pp in only_dom["players"])


@pytest.mark.asyncio
async def test_intent_list_player_groups(db_session):
    """list_player_groups renvoie nom + nombre de membres (RLS)."""
    from app.models.player_group import CmsPlayerGroup, CmsPlayerGroupMember
    org = CmsOrganization(org_name="OrgG", org_slug="org-g-assist")
    db_session.add(org)
    await db_session.flush()
    p = CmsPlayer(id_org=org.id_org, player_name="G1", status="online")
    db_session.add(p)
    await db_session.flush()
    g = CmsPlayerGroup(id_org=org.id_org, group_name="Boutiques")
    db_session.add(g)
    await db_session.flush()
    db_session.add(CmsPlayerGroupMember(id_group=g.id_group, id_player=p.id_player))
    await db_session.flush()

    res = await query_tenant_data(db_session, org.id_org, "list_player_groups")
    assert res["count"] == 1
    assert res["groups"][0]["name"] == "Boutiques" and res["groups"][0]["members"] == 1


@pytest.mark.asyncio
async def test_intent_explain_player_power(db_session):
    """explain_player_power : croise mode d'alimentation, contrôlabilité écran et raison
    « veille programmée » (offline attendu ≠ incident)."""
    org = CmsOrganization(org_name="OrgPW", org_slug="org-pw-assist")
    db_session.add(org)
    await db_session.flush()
    db_session.add(CmsPlayer(
        id_org=org.id_org, player_name="Box-veille", status="offline",
        alert_reasons=["offline_scheduled"],
        display_config={"output_power_fallback": True,
                        "power_schedule": {"mode": "custom"}},
    ))
    await db_session.flush()

    res = await query_tenant_data(db_session, org.id_org, "explain_player_power",
                                  {"player": "Box-veille"})
    assert res["offline_is_expected"] is True
    assert res["power_mode"] == "custom"
    assert res["screen_controllable"] is True
    assert res["status"] == "offline"

    missing = await query_tenant_data(db_session, org.id_org, "explain_player_power", {})
    assert "error" in missing
    unknown = await query_tenant_data(db_session, org.id_org, "explain_player_power",
                                      {"player": "n-existe-pas"})
    assert "error" in unknown


@pytest.mark.asyncio
async def test_intent_media_airtime_unfiled_never_played(db_session):
    """media_airtime agrège les PoP (plays/durée/signées) ; list_never_played et
    list_unfiled trouvent les médias sans diffusion / sans dossier."""
    from datetime import datetime, timedelta, timezone

    from app.models.media import CmsMedia
    from app.models.pop import CmsProofOfPlay
    org = CmsOrganization(org_name="OrgAT", org_slug="org-at-assist")
    db_session.add(org)
    await db_session.flush()
    player = CmsPlayer(id_org=org.id_org, player_name="AT-P1", status="online")
    played = CmsMedia(id_org=org.id_org, media_name="pub-tournee.mp4", media_type="video",
                      storage_key="k/at1", checksum_sha256="a" * 64)
    never = CmsMedia(id_org=org.id_org, media_name="jamais-vu.mp4", media_type="video",
                     storage_key="k/at2", checksum_sha256="b" * 64)
    db_session.add_all([player, played, never])
    await db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add_all([
        CmsProofOfPlay(id_org=org.id_org, id_player=player.id_player,
                       id_media=played.id_media, played_at=now - timedelta(hours=2),
                       duration_ms=30000, merkle_hash="m" * 64, signature="sig"),
        CmsProofOfPlay(id_org=org.id_org, id_player=player.id_player,
                       id_media=played.id_media, played_at=now - timedelta(hours=1),
                       duration_ms=30000, merkle_hash="n" * 64),
    ])
    await db_session.flush()

    air = await query_tenant_data(db_session, org.id_org, "media_airtime",
                                  {"media": "pub-tournee", "days": 7})
    assert air["plays"] == 2 and air["signed_plays"] == 1
    assert air["total_seconds"] == 60
    assert air["by_player"][0]["player"] == "AT-P1"

    npl = await query_tenant_data(db_session, org.id_org, "list_never_played_media")
    names = {m["name"] for m in npl["media"]}
    assert "jamais-vu.mp4" in names and "pub-tournee.mp4" not in names

    unf = await query_tenant_data(db_session, org.id_org, "list_unfiled_media")
    assert unf["count"] == 2  # les deux médias sont sans dossier


@pytest.mark.asyncio
async def test_intent_campaign_status(db_session):
    """campaign_status : vue d'ensemble sans filtre (statuts effectifs par dates), détail
    d'UNE campagne avec filters.campaign (cibles nommées, créatifs, SOV) ; erreurs
    introuvable / ambigu."""
    import uuid as _uuid
    from datetime import date, timedelta

    from app.models.campaign import (
        CmsAdvertiser, CmsCampaign, CmsCampaignCreative, CmsCampaignTarget,
    )
    from app.models.media import CmsMedia
    org = CmsOrganization(org_name="OrgCS", org_slug="org-cs-assist")
    db_session.add(org)
    await db_session.flush()
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="Brightwell")
    db_session.add(adv)
    await db_session.flush()
    live = CmsCampaign(
        id_org=org.id_org, id_advertiser=adv.id_advertiser, campaign_name="Été Brightwell",
        status="approved", starts_on=date.today() - timedelta(days=2),
        ends_on=date.today() + timedelta(days=5), sov_percent=20.0)
    draft = CmsCampaign(
        id_org=org.id_org, id_advertiser=adv.id_advertiser, campaign_name="Rentrée",
        status="draft", starts_on=date.today(), ends_on=date.today() + timedelta(days=30),
        sov_percent=10.0)
    db_session.add_all([live, draft])
    await db_session.flush()
    m = CmsMedia(id_org=org.id_org, media_name="spot-brightwell", media_type="video",
                 storage_key=f"k/{_uuid.uuid4().hex}", checksum_sha256="c" * 64,
                 duration_ms=15_000)
    db_session.add(m)
    await db_session.flush()
    db_session.add_all([
        CmsCampaignCreative(id_org=org.id_org, id_campaign=live.id_campaign,
                            id_media=m.id_media, approval_status="pending"),
        CmsCampaignTarget(id_org=org.id_org, id_campaign=live.id_campaign,
                          target_type="org", target_id=None),
    ])
    await db_session.flush()

    # Vue d'ensemble : les 2 campagnes, statut effectif calculé (approved + dates = live)
    res = await query_tenant_data(db_session, org.id_org, "campaign_status")
    assert res["count"] == 2
    by_name = {c["name"]: c for c in res["campaigns"]}
    assert by_name["Été Brightwell"]["status"] == "live"
    assert by_name["Rentrée"]["status"] == "draft"

    # Détail d'une campagne (résolution ILIKE partielle)
    res = await query_tenant_data(db_session, org.id_org, "campaign_status",
                                  {"campaign": "brightwell"})
    assert res["campaign"] == "Été Brightwell" and res["status"] == "live"
    assert res["advertiser"] == "Brightwell" and res["sov_percent_sold"] == 20.0
    assert res["targets"] == ["toute l'organisation"]
    assert res["creatives"] == [{"media": "spot-brightwell", "status": "active",
                                 "approval_status": "pending", "weight": 1}]

    unknown = await query_tenant_data(db_session, org.id_org, "campaign_status",
                                      {"campaign": "n-existe-pas"})
    assert "error" in unknown


@pytest.mark.asyncio
async def test_intent_campaign_report_permission_gate(db_session):
    """campaign_report expose des montants € → gaté campaigns:report (1er intent lecture
    RBAC-gaté) : sans id_user ou sans la permission = refus ; avec = chiffres du rapport."""
    import uuid as _uuid
    from datetime import date, timedelta

    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.core.security import hash_password
    from app.models.campaign import CmsAdvertiser, CmsCampaign
    from app.models.role import (
        CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment,
    )
    from app.models.user import CmsUser
    org = CmsOrganization(org_name="OrgCR", org_slug="org-cr-assist")
    db_session.add(org)
    await db_session.flush()
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="Corvane")
    db_session.add(adv)
    await db_session.flush()
    camp = CmsCampaign(
        id_org=org.id_org, id_advertiser=adv.id_advertiser, campaign_name="Corvane Q3",
        status="approved", starts_on=date.today() - timedelta(days=1),
        ends_on=date.today() + timedelta(days=7), sov_percent=15.0,
        pricing_model="flat", price_amount=900)
    db_session.add(camp)
    await db_session.flush()

    viewer = CmsUser(id_org=org.id_org, email=f"v-{_uuid.uuid4().hex[:8]}@t.com",
                     password_hash=hash_password("Password1!"), is_active=True)
    reporter = CmsUser(id_org=org.id_org, email=f"r-{_uuid.uuid4().hex[:8]}@t.com",
                       password_hash=hash_password("Password1!"), is_active=True)
    db_session.add_all([viewer, reporter])
    await db_session.flush()
    role = CmsRole(id_org=org.id_org, role_key=f"RPT-{_uuid.uuid4().hex[:6]}",
                   label="Reporter", is_system=False)
    db_session.add(role)
    await db_session.flush()
    await db_session.execute(
        pg_insert(CmsPermission)
        .values(module="campaigns", operation="report", label="campaigns.report")
        .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation"))
    await db_session.flush()
    perm = (await db_session.execute(select(CmsPermission).where(
        CmsPermission.module == "campaigns",
        CmsPermission.operation == "report"))).scalar_one()
    db_session.add_all([
        CmsRolePermission(id_role=role.id_role, id_permission=perm.id_permission),
        CmsUserRoleAssignment(id_user=reporter.id_user, id_role=role.id_role),
    ])
    await db_session.flush()

    # Sans id_user (contexte inconnu) ou sans la permission → refus
    res = await query_tenant_data(db_session, org.id_org, "campaign_report",
                                  {"campaign": "Corvane"})
    assert "error" in res and "campaigns:report" in res["error"]
    res = await query_tenant_data(db_session, org.id_org, "campaign_report",
                                  {"campaign": "Corvane"}, id_user=viewer.id_user)
    assert "error" in res and "campaigns:report" in res["error"]

    # Avec la permission → chiffres du rapport (0 passage, montant flat présent)
    res = await query_tenant_data(db_session, org.id_org, "campaign_report",
                                  {"campaign": "Corvane"}, id_user=reporter.id_user)
    assert res["intent"] == "campaign_report"
    assert res["campaign"]["campaign_name"] == "Corvane Q3"
    assert res["totals"]["plays"] == 0
    assert res["sov"]["sold_pct"] == 15.0
    assert res["amount"] == {"model": "flat", "amount": 900.0, "currency": "EUR",
                             "cpm_rate": None, "cpm_indicative": None}

    # Filtre manquant → erreur explicite
    res = await query_tenant_data(db_session, org.id_org, "campaign_report", {},
                                  id_user=reporter.id_user)
    assert "error" in res
