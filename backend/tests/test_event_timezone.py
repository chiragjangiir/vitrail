"""Un événement déclare le fuseau dans lequel ses heures se lisent (P3.13, option ②).

Un événement porte **une seule ligne** et **un seul `activated_at`** : il ne peut donc pas
s'activer à l'heure locale de chaque écran ciblé (ce serait l'option ①, écartée). Il déclare
donc, une fois, ce que « 18 h » veut dire. `NULL` = `SIGNFLOW_TZ` — le comportement
historique, pour qu'aucun événement existant ne change d'heure au déploiement.

⚠️ Ces tests portent sur l'ÉVALUATION (la fenêtre de déclenchement), jamais sur l'embargo :
`not_before_utc` est un instant **absolu**, volontairement hors de tout fuseau. Un test le
figera explicitement, parce que c'est exactement la confusion que ce champ pourrait induire.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.organization import CmsOrganization, CmsOrgAuthSettings
from app.schemas.event import EventCreate, EventRead, EventUpdate
from app.services.event_condition import EventConditionEvaluator
from app.workers.event_worker import (
    _compute_window_end,
    _in_same_occurrence,
    _interval_slot_start,
    _window_start_local,
)

# Instant de référence FIXE : 2026-03-10 17:00 UTC.
#   Europe/Paris     = 18:00  (UTC+1 en mars, avant le changement d'heure)
#   America/New_York = 12:00  (UTC-5)
# Le decalage de 6 h entre les deux est ce qui rend le test lisible : une fenetre 17:30-18:30
# « heure de Paris » contient l'instant, la meme fenetre « heure de New York » ne le contient pas.
NOW_UTC = datetime(2026, 3, 10, 17, 0, tzinfo=UTC)

WINDOW_1730_1830 = {
    "logic": "AND",
    "conditions": [{"source": "schedule", "time_start": "17:30", "time_end": "18:30"}],
}


@pytest_asyncio.fixture
async def org(db_session: AsyncSession) -> CmsOrganization:
    o = CmsOrganization(org_name="Ev TZ", org_slug=f"evtz-{uuid.uuid4().hex[:8]}")
    db_session.add(o)
    await db_session.flush()
    db_session.add(CmsOrgAuthSettings(id_org=o.id_org))
    await db_session.commit()
    await db_session.refresh(o)
    return o


# ── L'évaluation suit le fuseau déclaré ─────────────────────────────────────────

def test_window_is_read_in_the_event_timezone() -> None:
    """Le cœur de P3.13 : la MÊME fenêtre, le MÊME instant, deux verdicts opposés selon le
    fuseau que l'événement déclare.

    ROUGE AVANT : l'évaluateur ignorait `tz_name` et lisait toujours SIGNFLOW_TZ, donc les
    deux appels rendaient le même résultat — « 18 h » ne pouvait vouloir dire qu'une chose.
    """
    ev = EventConditionEvaluator()
    assert ev.evaluate(WINDOW_1730_1830, {"now": NOW_UTC, "tz_name": "Europe/Paris"}) is True
    assert ev.evaluate(WINDOW_1730_1830, {"now": NOW_UTC, "tz_name": "America/New_York"}) is False


def test_no_timezone_keeps_the_historical_behaviour() -> None:
    """`tz_name` absent ⇒ SIGNFLOW_TZ. C'est ce qui rend la migration 0123 neutre : aucun
    événement existant (colonne NULL) ne change d'heure au déploiement."""
    ev = EventConditionEvaluator()
    explicit = ev.evaluate(WINDOW_1730_1830, {"now": NOW_UTC, "tz_name": settings.SIGNFLOW_TZ})
    implicit = ev.evaluate(WINDOW_1730_1830, {"now": NOW_UTC})
    assert explicit == implicit


def test_day_of_week_also_follows_the_event_timezone() -> None:
    """Le JOUR aussi bascule : à 00:30 UTC un lundi, il est encore dimanche à New York.
    Un test qui ne couvrirait que l'heure laisserait passer la moitié du défaut."""
    ev = EventConditionEvaluator()
    monday_00_30_utc = datetime(2026, 3, 9, 0, 30, tzinfo=UTC)  # lundi
    monday_only = {"conditions": [{"source": "schedule", "days_of_week": [0]}]}
    sunday_only = {"conditions": [{"source": "schedule", "days_of_week": [6]}]}
    assert ev.evaluate(monday_only, {"now": monday_00_30_utc, "tz_name": "Europe/Paris"}) is True
    assert ev.evaluate(monday_only, {"now": monday_00_30_utc, "tz_name": "America/New_York"}) is False
    assert ev.evaluate(sunday_only, {"now": monday_00_30_utc, "tz_name": "America/New_York"}) is True


# ── Les helpers du worker : fin de fenêtre, créneaux, cooldown ──────────────────

def test_window_end_is_computed_in_the_event_timezone() -> None:
    """`expires_at` d'un event à fenêtre : 18:30 à Paris et 18:30 à New York ne sont pas le
    même instant. Sans le fuseau, l'événement s'éteindrait 6 h trop tôt ou trop tard."""
    end_paris = _compute_window_end(WINDOW_1730_1830, NOW_UTC, "Europe/Paris")
    end_ny = _compute_window_end(WINDOW_1730_1830, NOW_UTC, "America/New_York")
    assert end_paris is not None and end_ny is not None
    assert end_paris != end_ny
    # 18:30 Paris = 17:30 UTC ce jour-là (UTC+1).
    assert end_paris.astimezone(UTC).hour == 17 and end_paris.astimezone(UTC).minute == 30


def test_window_start_is_computed_in_the_event_timezone() -> None:
    start_paris = _window_start_local(WINDOW_1730_1830, NOW_UTC, "Europe/Paris")
    start_ny = _window_start_local(WINDOW_1730_1830, NOW_UTC, "America/New_York")
    assert start_paris is not None and start_ny is not None
    assert start_paris != start_ny


def test_interval_slot_follows_the_event_timezone() -> None:
    """Le créneau d'un event « toutes les N minutes » est ancré au DÉBUT DE FENÊTRE, donc au
    fuseau. Deux fuseaux ⇒ deux ancrages ⇒ deux grilles de créneaux.

    ⚠️ L'intervalle est choisi à 25 min VOLONTAIREMENT. Mon premier jet prenait 30 min et
    échouait : Paris et New York sont séparés de 6 h, soit un multiple exact de 30 min, donc
    les deux grilles COÏNCIDENT — ce n'est pas un défaut, c'est de l'arithmétique. Un test
    qui ne peut pas distinguer les deux cas ne prouve rien, quel que soit son verdict.
    """
    assert (_interval_slot_start(WINDOW_1730_1830, 25, NOW_UTC, "Europe/Paris")
            != _interval_slot_start(WINDOW_1730_1830, 25, NOW_UTC, "America/New_York"))
    # Le témoin de l'explication ci-dessus : à 30 min, les grilles coïncident, et c'est juste.
    assert (_interval_slot_start(WINDOW_1730_1830, 30, NOW_UTC, "Europe/Paris")
            == _interval_slot_start(WINDOW_1730_1830, 30, NOW_UTC, "America/New_York"))


def test_cooldown_occurrence_follows_the_event_timezone() -> None:
    """Le cooldown play-once (« déjà joué pour cette occurrence ») dépend du jour LOCAL. Sur
    le mauvais fuseau, un event rejouerait — ou resterait muet — une journée entière."""
    no_window = {"conditions": [{"source": "schedule", "days_of_week": [0, 1, 2, 3, 4, 5, 6]}]}
    last_act = datetime(2026, 3, 10, 2, 0, tzinfo=UTC)   # 03:00 Paris (10/03) / 21:00 NY (09/03)
    now = datetime(2026, 3, 10, 17, 0, tzinfo=UTC)       # 18:00 Paris (10/03) / 12:00 NY (10/03)
    assert _in_same_occurrence(no_window, None, last_act, now, "Europe/Paris") is True
    assert _in_same_occurrence(no_window, None, last_act, now, "America/New_York") is False


# ── L'embargo n'est PAS concerné, et ça se fige ────────────────────────────────

def test_embargo_stays_absolute_and_ignores_the_event_timezone() -> None:
    """`not_before_utc` est un instant ABSOLU : déclarer un fuseau sur l'événement ne doit
    rien y changer. C'est la confusion que ce champ pourrait induire — on la ferme ici.

    (Le champ ne passe par aucun fuseau côté serveur : la comparaison est `now_utc <
    not_before_utc`. Ce test verrouille le fait que le schéma ne les couple pas non plus.)
    """
    at = datetime(2026, 3, 10, 17, 0, tzinfo=UTC)
    base = dict(event_name="E", event_type="scheduled", id_playlist=1,
                target_config={"target_type": "org"}, not_before_utc=at)
    paris = EventCreate(**base, timezone="Europe/Paris")
    ny = EventCreate(**base, timezone="America/New_York")
    assert paris.not_before_utc == ny.not_before_utc == at


# ── Validation à la saisie et résolution à la lecture ──────────────────────────

def test_unknown_timezone_is_refused_at_write_time() -> None:
    base = dict(event_name="E", event_type="scheduled", id_playlist=1,
                target_config={"target_type": "org"})
    assert EventCreate(**base, timezone="America/New_York").timezone == "America/New_York"
    assert EventCreate(**base, timezone=None).timezone is None
    assert EventUpdate(timezone="").timezone is None  # champ vidé = retour au défaut
    for bad in ("Paris", "UTC+2", "Europe/Pariss"):
        with pytest.raises(ValidationError):
            EventCreate(**base, timezone=bad)
        with pytest.raises(ValidationError):
            EventUpdate(timezone=bad)


def test_read_always_serves_a_resolved_timezone() -> None:
    """L'écran doit pouvoir afficher le fuseau sans connaître le `SIGNFLOW_TZ` du serveur.
    ⚠️ `mode="before"` obligatoire : sans lui, un `timezone` NULL en base (tous les
    événements antérieurs à la migr 0123) ferait échouer la sérialisation."""
    base = dict(id_event=1, id_org=1, event_name="E", event_type="scheduled", priority=0,
                revert_on_end=True, status="inactive", target_config={"target_type": "org"},
                created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    assert EventRead(**base, timezone=None).timezone == settings.SIGNFLOW_TZ
    assert EventRead(**base, timezone="Paris").timezone == settings.SIGNFLOW_TZ  # illisible
    assert EventRead(**base, timezone="Asia/Tokyo").timezone == "Asia/Tokyo"


# ── Bout en bout par l'API ─────────────────────────────────────────────────────

async def test_event_timezone_round_trips_through_the_api(
    client, db_session, org
) -> None:
    """Le fuseau saisi est bien celui qui ressort — un champ accepté puis perdu en base est
    le mode de panne le plus courant d'un ajout de colonne."""
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.core.security import create_access_token, hash_password
    from app.models.playlist import CmsPlaylist
    from app.models.role import (
        CmsPermission,
        CmsRole,
        CmsRolePermission,
        CmsUserRoleAssignment,
    )
    from app.models.user import CmsUser

    pl = CmsPlaylist(id_org=org.id_org, playlist_name="PL")
    db_session.add(pl)
    # ⚠️ Deux pièges enchaînés, tous deux rencontrés en écrivant ce test :
    #  ① le jeton doit désigner un compte RÉEL et actif (`get_current_user` le relit en base,
    #    et depuis P1.1 compare `sessions_valid_from`) — un identifiant inventé rend **401** ;
    #  ② nommer `CMS_ORG_ADMIN` dans le jeton n'accorde RIEN : les permissions sont lues en
    #    base, et ce rôle est créé SANS permission par `bootstrap.py` — d'où un **403**.
    #    Il faut donc un vrai rôle porteur d'`events:create`.
    uid = uuid.uuid4().hex[:8]
    user = CmsUser(id_org=org.id_org, email=f"evtz-{uid}@t.com",
                   password_hash=hash_password("Password1!"), is_active=True)
    db_session.add(user)
    await db_session.flush()
    role_key = f"CMS_EVTZ_{uid}"
    await db_session.execute(
        pg_insert(CmsRole)
        .values(role_key=role_key, label="EvTZ", is_system=False, is_active=True)
        .on_conflict_do_nothing(constraint="uq_cms_roles_role_key")
    )
    await db_session.flush()
    role = (await db_session.execute(
        select(CmsRole).where(CmsRole.role_key == role_key)
    )).scalar_one()
    for module, op in (("events", "create"), ("events", "read")):
        await db_session.execute(
            pg_insert(CmsPermission).values(module=module, operation=op)
            .on_conflict_do_nothing(constraint="uq_cms_permissions_module_operation")
        )
        await db_session.flush()
        perm = (await db_session.execute(
            select(CmsPermission).where(
                CmsPermission.module == module, CmsPermission.operation == op
            )
        )).scalar_one()
        await db_session.execute(
            pg_insert(CmsRolePermission)
            .values(id_role=role.id_role, id_permission=perm.id_permission)
            .on_conflict_do_nothing()
        )
    db_session.add(CmsUserRoleAssignment(id_user=user.id_user, id_role=role.id_role))
    await db_session.commit()
    await db_session.refresh(pl)
    await db_session.refresh(user)

    token = create_access_token(
        user.id_user, extra={"org": org.id_org, "roles": [role_key], "locale": "en"}
    )
    h = {"Authorization": f"Bearer {token}"}
    body = {
        "event_name": "Happy hour",
        "event_type": "scheduled",
        "id_playlist": pl.id_playlist,
        "timezone": "America/New_York",
        "target_config": {"target_type": "org"},
        "trigger_config": WINDOW_1730_1830,
    }
    r = await client.post("/api/v1/events", json=body, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["timezone"] == "America/New_York"

    r2 = await client.get(f"/api/v1/events/{r.json()['id_event']}", headers=h)
    assert r2.json()["timezone"] == "America/New_York"

    # Un fuseau inconnu est refusé par l'API, pas seulement par le schéma en mémoire.
    r3 = await client.post("/api/v1/events", json={**body, "timezone": "Paris"}, headers=h)
    assert r3.status_code == 422
