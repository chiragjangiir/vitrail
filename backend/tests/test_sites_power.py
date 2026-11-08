"""
Tests Sites + auto-power écrans (§ heures d'ouverture).

  - Endpoints CRUD sites / horaires hebdo / exceptions / players du site
  - Tâche beat apply_site_power : transitions edge-triggered + dédup + filtres
    (online, écran piloté RS232/IP, mode d'alimentation).
"""

import json
import uuid
from datetime import UTC, datetime, time, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.models.player import CmsPlayer
from app.models.role import CmsPermission, CmsRole, CmsRolePermission, CmsUserRoleAssignment
from app.models.user import CmsUser


# ── Fixtures ─────────────────────────────────────────────────────────────────
async def _make_org(db: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="Site Org", org_slug=f"site-{uuid.uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    db.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db.commit()
    await db.refresh(o)
    return o


async def _make_user(db: AsyncSession, org: CmsOrganization) -> tuple[CmsUser, str]:
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"site-{uid}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db.add(user)
    await db.flush()
    role_key = f"CMS_SITE_{uid}"
    await db.execute(pg_insert(CmsRole).values(role_key=role_key, label="Site", is_system=False, is_active=True)
                     .on_conflict_do_nothing(constraint="uq_cms_roles_role_key"))
    await db.flush()
    role = (await db.execute(select(CmsRole).where(CmsRole.role_key == role_key))).scalar_one()
    for module, op in [("players", "read"), ("players", "edit")]:
        await db.execute(pg_insert(CmsPermission).values(module=module, operation=op)
                         .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation"))
        await db.flush()
        perm = (await db.execute(select(CmsPermission).where(
            CmsPermission.module == module, CmsPermission.operation == op))).scalar_one()
        await db.execute(pg_insert(CmsRolePermission).values(
            id_role=role.id_role, id_permission=perm.id_permission).on_conflict_do_nothing())
    db.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db.commit()
    await db.refresh(user)
    token = create_access_token(user.id_user, extra={"org": org.id_org, "roles": [role_key], "locale": "en"})
    return user, token


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    return await _make_org(db_session)


@pytest_asyncio.fixture
async def auth(db_session, org):
    return await _make_user(db_session, org)


# ── Endpoints ────────────────────────────────────────────────────────────────
async def test_site_crud_and_hours_and_exceptions(client: AsyncClient, auth, org, db_session) -> None:
    _, token = auth
    headers = {"Authorization": f"Bearer {token}"}

    # Création
    resp = await client.post("/api/v1/sites", json={
        "site_name": "Magasin Centre",
        "auto_power_enabled": True,
        "power_lead_min": 10,
        "power_lag_min": 20,
        "timezone": "Europe/Paris",
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    site = resp.json()
    sid = site["id_site"]
    assert site["auto_power_enabled"] is True
    assert site["power_lead_min"] == 10

    # Horaires hebdo (Lun-Ven 08:00-19:00, Sam fermé)
    hours = [{"weekday": d, "is_closed": False, "open_time": "08:00", "close_time": "19:00"} for d in range(5)]
    hours.append({"weekday": 5, "is_closed": True})
    resp = await client.put(f"/api/v1/sites/{sid}/hours", json={"hours": hours}, headers=headers)
    assert resp.status_code == 200, resp.text
    got = resp.json()
    assert len(got) == 6
    mon = next(h for h in got if h["weekday"] == 0)
    assert mon["open_time"].startswith("08:00")

    # Remplacement idempotent (pas de doublon malgré la contrainte UNIQUE)
    resp = await client.put(f"/api/v1/sites/{sid}/hours", json={"hours": hours}, headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 6

    # Exception datée (soirée exceptionnelle)
    resp = await client.post(f"/api/v1/sites/{sid}/exceptions", json={
        "date_from": "2026-12-24", "date_to": "2026-12-24",
        "kind": "hours", "open_time": "08:00", "close_time": "23:00",
        "label": "Veille de Noël",
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    eid = resp.json()["id_exception"]

    resp = await client.get(f"/api/v1/sites/{sid}/exceptions", headers=headers)
    assert resp.status_code == 200 and len(resp.json()) == 1

    # Update site (désactive l'auto-power)
    resp = await client.put(f"/api/v1/sites/{sid}", json={"auto_power_enabled": False}, headers=headers)
    assert resp.status_code == 200 and resp.json()["auto_power_enabled"] is False

    # Suppression exception puis site
    assert (await client.delete(f"/api/v1/sites/{sid}/exceptions/{eid}", headers=headers)).status_code == 204
    assert (await client.delete(f"/api/v1/sites/{sid}", headers=headers)).status_code == 204
    assert (await client.get(f"/api/v1/sites/{sid}", headers=headers)).status_code == 404


async def test_exception_hours_requires_times_422(client: AsyncClient, auth) -> None:
    _, token = auth
    headers = {"Authorization": f"Bearer {token}"}
    sid = (await client.post("/api/v1/sites", json={"site_name": "S"}, headers=headers)).json()["id_site"]
    resp = await client.post(f"/api/v1/sites/{sid}/exceptions", json={
        "date_from": "2026-12-24", "date_to": "2026-12-24", "kind": "hours",
    }, headers=headers)
    assert resp.status_code == 422


async def test_list_site_players_exposes_power_mode(client: AsyncClient, auth, org, db_session) -> None:
    _, token = auth
    headers = {"Authorization": f"Bearer {token}"}
    sid = (await client.post("/api/v1/sites", json={"site_name": "S"}, headers=headers)).json()["id_site"]
    db_session.add(CmsPlayer(
        id_org=org.id_org, id_site=sid, player_name="Vitrine", player_os="linux",
        display_config={"type": "ip", "power_schedule": {"mode": "always_on"}},
    ))
    await db_session.commit()
    resp = await client.get(f"/api/v1/sites/{sid}/players", headers=headers)
    assert resp.status_code == 200
    players = resp.json()
    assert len(players) == 1 and players[0]["power_mode"] == "always_on"


async def test_attach_detach_player(client: AsyncClient, auth, org, db_session) -> None:
    _, token = auth
    headers = {"Authorization": f"Bearer {token}"}
    sid = (await client.post("/api/v1/sites", json={"site_name": "S"}, headers=headers)).json()["id_site"]
    p = CmsPlayer(id_org=org.id_org, player_name="P1", player_os="linux")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    # Attache
    assert (await client.post(f"/api/v1/sites/{sid}/players/{p.id_player}", headers=headers)).status_code == 204
    players = (await client.get(f"/api/v1/sites/{sid}/players", headers=headers)).json()
    assert [x["id_player"] for x in players] == [p.id_player]

    # Détache
    assert (await client.delete(f"/api/v1/sites/{sid}/players/{p.id_player}", headers=headers)).status_code == 204
    assert (await client.get(f"/api/v1/sites/{sid}/players", headers=headers)).json() == []


# ── Tâche beat apply_site_power ──────────────────────────────────────────────
def test_apply_site_power_sends_only_transitions(monkeypatch) -> None:
    """Le tick n'émet power_on/off qu'aux transitions, pour les players online à écran piloté."""
    from app.workers import event_worker

    now_utc = datetime.now(UTC)
    recent = now_utc
    old = now_utc - timedelta(hours=1)

    # Site ouvert 24h/24 (horaires 00:00-00:00 chaque jour) → site_on = True à tout instant.
    sites = [{"id_site": 1, "timezone": None, "power_lead_min": 15, "power_lag_min": 15,
              "respect_holidays": False, "holiday_region": "FR"}]
    hours = [{"weekday": i, "is_closed": False, "open_time": time(0, 0), "close_time": time(0, 0)}
             for i in range(7)]
    players = [
        # transition None→on : doit envoyer power_on + UPDATE
        {"id_player": 101, "display_config": {"type": "ip"}, "last_seen_at": recent, "last_power_state": None},
        # écran non piloté (pas rs232/ip) → ignoré
        {"id_player": 102, "display_config": {"type": "hdmi"}, "last_seen_at": recent, "last_power_state": None},
        # mode manual → jamais piloté
        {"id_player": 103, "display_config": {"type": "rs232", "power_schedule": {"mode": "manual"}},
         "last_seen_at": recent, "last_power_state": None},
        # offline → ignoré (repris à la reconnexion)
        {"id_player": 104, "display_config": {"type": "ip"}, "last_seen_at": old, "last_power_state": None},
        # déjà allumé → pas de transition
        {"id_player": 105, "display_config": {"type": "ip"}, "last_seen_at": recent, "last_power_state": True},
    ]

    updates: list = []

    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def execute(self, sql, params=None):
            self._sql = sql
            if sql.strip().upper().startswith("UPDATE"):
                updates.append(params)

        def fetchall(self):
            s = self._sql
            if "FROM cms_sites" in s:
                return sites
            if "cms_site_hours" in s:
                return hours
            if "cms_site_exceptions" in s:
                return []
            if "cms_players WHERE id_site" in s:
                return players
            # Résolution des cibles d'un event keep_screens_on. Depuis le 2026-07-29, le
            # type `player` passe lui aussi par une requête (filtre d'organisation ajouté :
            # sans lui, une commande pouvait partir sur le canal d'un écran d'une AUTRE
            # organisation). Le double doit donc savoir y répondre — il rendait []
            # jusque-là, donc « aucun écran ciblé », ce qu'aucune base réelle ne ferait.
            # Tuples et non dicts : le vrai curseur est un DictCursor, dont les lignes
            # s'indexent aussi par entier, et le code lit `row[0]`.
            if "WHERE id_player = ANY" in s:
                return [(201,)]
            return []

    class _Conn:
        def cursor(self, *a, **k): return _Cur()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    published: list = []

    class _Redis:
        def publish(self, ch, payload): published.append((ch, json.loads(payload)))
        def close(self): pass

    monkeypatch.setattr(event_worker, "_db_conn", lambda: _Conn())
    monkeypatch.setattr(event_worker.redis, "from_url", lambda url: _Redis())

    result = event_worker.apply_site_power()

    assert result == {"sites": 1, "commands": 1}
    assert len(published) == 1
    ch, payload = published[0]
    assert ch == "signflow:player:101:cmds"
    assert payload["command"] == "display_command"
    assert payload["params"]["display_cmd"] == "power_on"
    # Dédup : seul le player en transition est persisté (last_power_state=True, id=101)
    assert len(updates) == 1
    assert updates[0][0] is True and updates[0][2] == 101


def test_apply_site_power_event_keeps_screens_on(monkeypatch) -> None:
    """Un event actif keep_screens_on force l'allumage même site fermé (extension d'alim)."""
    from app.workers import event_worker

    now_utc = datetime.now(UTC)

    # Site FERMÉ tous les jours → site_on = False partout.
    sites = [{"id_site": 1, "timezone": None, "power_lead_min": 0, "power_lag_min": 0,
              "respect_holidays": False, "holiday_region": "FR"}]
    hours = [{"weekday": i, "is_closed": True, "open_time": None, "close_time": None}
             for i in range(7)]
    # 201 ciblé par l'event keep-on (était éteint car fermé) → doit rallumer.
    # 202 non ciblé, déjà éteint → aucune transition.
    players = [
        {"id_player": 201, "display_config": {"type": "ip"}, "last_seen_at": now_utc, "last_power_state": False},
        {"id_player": 202, "display_config": {"type": "ip"}, "last_seen_at": now_utc, "last_power_state": False},
    ]
    keep_on_events = [{"id_event": 1, "id_org": 1,
                       "target_config": {"target_type": "player", "target_ids": [201]}}]

    updates: list = []

    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def execute(self, sql, params=None):
            self._sql = sql
            if sql.strip().upper().startswith("UPDATE"):
                updates.append(params)

        def fetchall(self):
            s = self._sql
            if "keep_screens_on" in s:
                return keep_on_events
            if "FROM cms_sites" in s:
                return sites
            if "cms_site_hours" in s:
                return hours
            if "cms_site_exceptions" in s:
                return []
            if "cms_players WHERE id_site" in s:
                return players
            # Résolution des cibles d'un event keep_screens_on. Depuis le 2026-07-29, le
            # type `player` passe lui aussi par une requête (filtre d'organisation ajouté :
            # sans lui, une commande pouvait partir sur le canal d'un écran d'une AUTRE
            # organisation). Le double doit donc savoir y répondre — il rendait []
            # jusque-là, donc « aucun écran ciblé », ce qu'aucune base réelle ne ferait.
            # Tuples et non dicts : le vrai curseur est un DictCursor, dont les lignes
            # s'indexent aussi par entier, et le code lit `row[0]`.
            if "WHERE id_player = ANY" in s:
                return [(201,)]
            return []

    class _Conn:
        def cursor(self, *a, **k): return _Cur()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    published: list = []

    class _Redis:
        def publish(self, ch, payload): published.append((ch, json.loads(payload)))
        def close(self): pass

    monkeypatch.setattr(event_worker, "_db_conn", lambda: _Conn())
    monkeypatch.setattr(event_worker.redis, "from_url", lambda url: _Redis())

    result = event_worker.apply_site_power()

    assert result == {"sites": 1, "commands": 1}
    assert len(published) == 1
    ch, payload = published[0]
    assert ch == "signflow:player:201:cmds"
    assert payload["params"]["display_cmd"] == "power_on"
    # Seul 201 transitionne (False→True) ; 202 reste éteint, pas d'UPDATE.
    assert len(updates) == 1 and updates[0][0] is True and updates[0][2] == 201


# ── Bloc offline_power (autonomie player sans serveur, sync payload) ──────────
async def test_resolve_offline_power_block(client: AsyncClient, auth, org, db_session) -> None:
    from app.api.v1.endpoints.ws import _resolve_offline_power

    _, token = auth
    headers = {"Authorization": f"Bearer {token}"}
    sid = (await client.post("/api/v1/sites", json={
        "site_name": "S-offline", "auto_power_enabled": True,
        "power_lead_min": 15, "power_lag_min": 15, "timezone": "Europe/Paris",
    }, headers=headers)).json()["id_site"]
    hours = [{"weekday": d, "is_closed": False, "open_time": "08:00", "close_time": "19:00"}
             for d in range(7)]
    assert (await client.put(f"/api/v1/sites/{sid}/hours",
                             json={"hours": hours}, headers=headers)).status_code == 200

    p = CmsPlayer(id_org=org.id_org, id_site=sid, player_name="P-offline", player_os="linux",
                  display_config={"output_power_fallback": True})
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    # follow_site (défaut) : 14 j de fenêtres datées, marges lead/lag appliquées
    block = await _resolve_offline_power(db_session, p, p.display_config)
    assert block is not None and block["mode"] == "follow_site"
    assert len(block["intervals"]) >= 13  # ouvert 7j/7 sur l'horizon (+ veille éventuelle)
    on_s, off_s = block["intervals"][1]
    assert on_s.endswith("T07:45:00") and off_s.endswith("T19:15:00")

    # manual → pas de pilotage offline
    assert await _resolve_offline_power(db_session, p, {
        "output_power_fallback": True, "power_schedule": {"mode": "manual"}}) is None
    # always_on → mode seul, pas d'intervalles
    assert await _resolve_offline_power(db_session, p, {
        "type": "cec", "power_schedule": {"mode": "always_on"}}) == {"mode": "always_on"}
    # custom (vitrine) → fenêtres propres, indépendantes des horaires du site
    b3 = await _resolve_offline_power(db_session, p, {
        "output_power_fallback": True,
        "power_schedule": {"mode": "custom", "on_time": "07:00", "off_time": "23:00"}})
    assert b3 is not None and b3["mode"] == "custom" and len(b3["intervals"]) >= 13
    assert b3["intervals"][0][0].endswith("T07:00:00")
    # écran non piloté (ni contrôleur ni repli) → None
    assert await _resolve_offline_power(db_session, p, {}) is None

    # auto_power désactivé sur le site → plus aucun pilotage offline (même always_on)
    await client.put(f"/api/v1/sites/{sid}", json={"auto_power_enabled": False}, headers=headers)
    assert await _resolve_offline_power(db_session, p, {"output_power_fallback": True}) is None
    assert await _resolve_offline_power(db_session, p, {
        "type": "cec", "power_schedule": {"mode": "always_on"}}) is None


async def test_sites_campaign_stats(client: AsyncClient, auth, org, db_session) -> None:
    """Tooltip sites (retour Ed #4) : players/éligibles + occupation SOV par jour."""
    from datetime import date

    from app.models.campaign import CmsAdvertiser, CmsCampaign, CmsCampaignTarget
    from app.models.organization import CmsSite

    _, token = auth
    headers = {"Authorization": f"Bearer {token}"}

    site = CmsSite(id_org=org.id_org, site_name="Stats-Site")
    db_session.add(site)
    await db_session.flush()
    db_session.add_all([
        CmsPlayer(id_org=org.id_org, player_name="ST1", player_os="linux",
                  id_site=site.id_site),
        CmsPlayer(id_org=org.id_org, player_name="ST2", player_os="linux",
                  id_site=site.id_site, campaigns_optout=True),
    ])
    adv = CmsAdvertiser(id_org=org.id_org, advertiser_name="StatsBrand")
    db_session.add(adv)
    await db_session.flush()
    camp = CmsCampaign(
        id_org=org.id_org, id_advertiser=adv.id_advertiser, campaign_name="Occ",
        status="approved", starts_on=date.today(), ends_on=date.today(),
        sov_percent=30.0, pricing_model="flat")
    db_session.add(camp)
    await db_session.flush()
    db_session.add(CmsCampaignTarget(id_org=org.id_org, id_campaign=camp.id_campaign,
                                     target_type="org", target_id=None))
    await db_session.commit()

    resp = await client.get("/api/v1/sites/campaign-stats?days=3", headers=headers)
    assert resp.status_code == 200, resp.text
    entry = next(e for e in resp.json() if e["id_site"] == site.id_site)
    assert entry["player_count"] == 2
    assert entry["eligible_count"] == 1  # opt-out déduit
    assert len(entry["days"]) == 3
    # J1 : la campagne (30 %) occupe le seul écran éligible ; J2-J3 : rien
    assert entry["days"][0]["avg_pct"] == 30.0 and entry["days"][0]["max_pct"] == 30.0
    assert entry["days"][1]["avg_pct"] == 0.0
