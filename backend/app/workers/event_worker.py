"""
Event Engine worker Celery — Sprint 2.2 (§XX).

Tâches planifiées via Celery Beat :
- expire_events             (30s) : active→reverting quand expires_at < now + push sync
- finalize_reverting_events (30s) : reverting→completed (ou inactive si récurrent valide)
- activate_scheduled_events (10s) : inactive→active pour events scheduled/conditional
  dont les conditions sont satisfaites + push sync

Machine à états (§20.3) : inactive → active → reverting → completed | inactive (récurrent).
L'état `reverting` est transitoire : au passage active→reverting on pousse un force_sync
qui fait recalculer la pile aux players ciblés (cascade : l'event actif suivant ou le
programme nominal reprend la main — cf. _resolve_sync_payload qui ne retient que
status='active'). finalize_reverting_events ne fait ensuite que finaliser l'état.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg2
import psycopg2.extras
import redis

from app.core.config import settings
from app.core.security import create_player_token
from app.core.timezones import safe_zoneinfo
from app.services.event_condition import EventConditionEvaluator
from app.services.player_token import grace_until, needs_rotation
from app.services.targeting import event_target_entries
from app.workers.celery_app import celery_app


def _compute_window_end(
    trigger_config: dict, now_utc: datetime, tz_name: str | None = None
) -> datetime | None:
    """
    Pour un event scheduled : retourne l'heure de fin de la fenêtre du jour en UTC.
    Permet de garder l'event actif pour toute la fenêtre sans gap.
    Retourne None si le trigger_config ne contient pas de source=schedule ou pas de time_end.
    """
    if not trigger_config:
        return None
    conditions = trigger_config.get("conditions", [])
    sched = next((c for c in conditions if c.get("source") == "schedule"), None)
    if not sched or not sched.get("time_end"):
        return None
    try:
        tz = safe_zoneinfo(tz_name)
        h, m = map(int, sched["time_end"].split(":"))
        now_local = now_utc.astimezone(tz)
        end_local = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        # Fenêtre nocturne ou activation légèrement après time_end (rare) → lendemain
        if end_local <= now_local:
            end_local += timedelta(days=1)
        return end_local.astimezone(UTC)
    except Exception:
        return None


def _interval_minutes(trigger_config: dict | None) -> int | None:
    """N minutes si l'event est en mode récurrence par INTERVALLE (« spot toutes les N min »),
    sinon None. `trigger_config.recurrence = {type:"interval", every_minutes:N}`."""
    rec = (trigger_config or {}).get("recurrence") or {}
    if rec.get("type") == "interval":
        try:
            n = int(rec.get("every_minutes") or 0)
            return n if n > 0 else None
        except (TypeError, ValueError):
            return None
    return None


def _window_start_local(trigger_config: dict, now_utc: datetime, tz_name: str | None = None):
    """Début (local, du jour de now_utc) de la fenêtre horaire du schedule, ou None si pas de
    time_start. Symétrique de _compute_window_end."""
    conditions = (trigger_config or {}).get("conditions", [])
    sched = next((c for c in conditions if c.get("source") == "schedule"), None)
    if not sched or not sched.get("time_start"):
        return None
    try:
        tz = safe_zoneinfo(tz_name)
        h, m = map(int, sched["time_start"].split(":"))
        now_local = now_utc.astimezone(tz)
        start_local = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
        # On est avant le time_start du jour → fenêtre entamée la veille (nocturne) : reculer.
        if start_local > now_local:
            start_local -= timedelta(days=1)
        return start_local
    except Exception:
        return None


def _interval_slot_start(
    trigger_config: dict, every_minutes: int, t_utc: datetime, tz_name: str | None = None
):
    """Datetime UTC du DÉBUT du créneau de N minutes contenant t_utc, ancré au début de la
    fenêtre horaire du jour (repli : minuit local). Sert de clé de créneau : deux activations
    dans le même créneau ont le même slot_start (robuste cross-jours car absolu). None si avant
    le début de fenêtre."""
    try:
        tz = safe_zoneinfo(tz_name)
        t_local = t_utc.astimezone(tz)
        start_local = _window_start_local(trigger_config, t_utc, tz_name)
        if start_local is None:
            start_local = t_local.replace(hour=0, minute=0, second=0, microsecond=0)
        delta_min = (t_local - start_local).total_seconds() / 60.0
        if delta_min < 0:
            return None
        k = int(delta_min // every_minutes)
        return (start_local + timedelta(minutes=k * every_minutes)).astimezone(UTC)
    except Exception:
        return None


def _in_same_occurrence(
    trigger_config: dict | None,
    every_min: int | None,
    last_act: datetime,
    now_utc: datetime,
    tz_name: str | None = None,
) -> bool:
    """True si `now_utc` est dans la MÊME occurrence jouable que `last_act` → l'event play-once
    a DÉJÀ été joué pour cette occurrence, donc ne pas le ré-activer. Trois régimes :

    - intervalle (`every_min`)            : même créneau de N min (slot absolu ancré au début de
      fenêtre, robuste cross-jours).
    - fenêtre horaire (`time_start`)      : même occurrence de fenêtre (même début de fenêtre,
      gère l'overnight via `_window_start_local`).
    - ni intervalle ni fenêtre            : même jour local ET conditions encore satisfaites par
      `last_act` (repli).

    Clé du fix « spot horaire » : ce cooldown repose sur `activated_at` (= `last_act`), que
    `finalize_reverting_events` CONSERVE désormais pour les play-once recurring (sinon le marqueur
    du dernier créneau joué était effacé à chaque revert → ré-activation en continu).
    """
    if every_min:
        slot_now = _interval_slot_start(trigger_config, every_min, now_utc, tz_name)
        slot_last = _interval_slot_start(trigger_config, every_min, last_act, tz_name)
        return slot_now is not None and slot_now == slot_last

    ws_now = _window_start_local(trigger_config, now_utc, tz_name)
    ws_last = _window_start_local(trigger_config, last_act, tz_name)
    if ws_now is not None and ws_last is not None:
        return ws_now == ws_last

    # Pas de fenêtre horaire bornée → occurrence = jour local (si les conditions matchent encore).
    tz = safe_zoneinfo(tz_name)
    same_day = last_act.astimezone(tz).date() == now_utc.astimezone(tz).date()
    return same_day and _evaluator.evaluate(
        trigger_config, {"now": last_act, "tz_name": tz_name}
    )


logger = logging.getLogger(__name__)

_evaluator = EventConditionEvaluator()


def _aware_utc(dt: datetime) -> datetime:
    """Force un datetime en UTC aware (les colonnes timestamptz reviennent parfois naïves)."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _db_conn():
    url = settings.db_worker_url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(url)


def _push_sync(player_ids: list[int], is_preemptive: bool = False) -> None:
    if not player_ids:
        return
    r = redis.from_url(settings.REDIS_URL)
    try:
        payload = json.dumps({"type": "player:force_sync", "preemptive": is_preemptive})
        for pid in player_ids:
            r.publish(f"signflow:player:{pid}:cmds", payload)
    finally:
        r.close()


def _push_token_refresh(items: list[tuple[int, str]]) -> None:
    """Pousse le nouveau token aux players (auto-refresh « Option B »). items = [(id_player, token)]."""
    if not items:
        return
    r = redis.from_url(settings.REDIS_URL)
    try:
        for pid, token in items:
            r.publish(
                f"signflow:player:{pid}:cmds",
                json.dumps({"type": "token:refresh", "token": token}),
            )
    finally:
        r.close()


def _ids_for_entry(cur, id_org: int, t_type: str, t_ids: list[int]) -> list[int]:
    """Résolution SQL d'UNE entrée (type, ids) — la seule partie propre au worker.

    ⚠️ COPIE ASSUMÉE du SQL de `services/targeting.players_for_target` : ce worker parle à
    la base en psycopg SYNCHRONE et ne peut pas appeler le service async. Toute évolution
    du vocabulaire de cibles doit donc toucher LES DEUX — c'est exactement ce qui a
    manqué : la cible `site` était absente **ici aussi**, si bien qu'un événement ciblant
    un site s'activait sans prévenir un seul écran (corrigé le 2026-07-29).

    La LECTURE du JSON, elle, n'est plus copiée : `event_target_entries` (fonction pure,
    partagée avec l'API) est la seule définition des deux formes de target_config.

    Les filtres par organisation manquaient également sur `player` et `group` : on pouvait
    publier une commande sur le canal d'un écran d'une AUTRE organisation.
    """
    if t_type == "org":
        cur.execute("SELECT id_player FROM cms_players WHERE id_org = %s", (id_org,))
        return [row[0] for row in cur.fetchall()]

    if not t_ids:
        return []

    if t_type == "player":
        cur.execute(
            "SELECT id_player FROM cms_players WHERE id_player = ANY(%s) AND id_org = %s",
            (list(t_ids), id_org),
        )
        return [row[0] for row in cur.fetchall()]

    if t_type == "group":
        cur.execute(
            "SELECT p.id_player FROM cms_players p"
            " JOIN cms_player_group_members m ON m.id_player = p.id_player"
            " WHERE m.id_group = ANY(%s) AND p.id_org = %s",
            (list(t_ids), id_org),
        )
        return [row[0] for row in cur.fetchall()]

    if t_type == "site":
        cur.execute(
            "SELECT id_player FROM cms_players WHERE id_site = ANY(%s) AND id_org = %s",
            (list(t_ids), id_org),
        )
        return [row[0] for row in cur.fetchall()]

    if t_type == "site_group":
        cur.execute(
            "SELECT p.id_player FROM cms_players p"
            " JOIN cms_site_group_members m ON m.id_site = p.id_site"
            " WHERE m.id_site_group = ANY(%s) AND p.id_org = %s",
            (list(t_ids), id_org),
        )
        return [row[0] for row in cur.fetchall()]

    return []


def _resolve_player_ids(cur, id_org: int, target_config: dict) -> list[int]:
    """Résout les IDs de players ciblés depuis un target_config JSONB (§XX.7).

    Comprend les deux formes (héritée et hétérogène) via le normaliseur partagé —
    l'union des entrées, comme le chemin de diffusion.
    """
    out: set[int] = set()
    for t_type, t_ids in event_target_entries(target_config):
        out.update(_ids_for_entry(cur, id_org, t_type, t_ids))
    return sorted(out)


def _revert_target_status(is_recurring: bool, past_validity: bool) -> str:
    """État final après la phase transitoire `reverting`.

    - is_recurring + encore dans la fenêtre de validité → inactive (se relancera)
    - sinon                                             → completed
    """
    return "inactive" if (is_recurring and not past_validity) else "completed"


@celery_app.task(name="app.workers.event_worker.expire_events")
def expire_events() -> dict:
    """Bascule les events actifs expirés (expires_at < now) vers l'état transitoire `reverting`.

    Le passage active→reverting pousse un force_sync vers les players ciblés : ils
    recalculent leur pile (cascade vers l'event actif suivant ou le programme nominal).
    La finalisation reverting→completed|inactive est faite par finalize_reverting_events.
    activated_at / expires_at sont conservés ici (nettoyés à la finalisation si inactive).
    """
    now_utc = datetime.now(UTC)
    reverting_count = 0

    conn = _db_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT id_event, id_org, target_config, is_preemptive
                FROM cms_events
                WHERE status = 'active'
                  AND expires_at IS NOT NULL
                  AND expires_at <= %s
                """,
                (now_utc,),
            )
            rows = cur.fetchall()

            for row in rows:
                cur.execute(
                    """
                    UPDATE cms_events
                    SET status = 'reverting',
                        updated_at = %s
                    WHERE id_event = %s
                    """,
                    (now_utc, row["id_event"]),
                )
                player_ids = _resolve_player_ids(cur, row["id_org"], row["target_config"])
                _push_sync(player_ids, is_preemptive=row["is_preemptive"])
                reverting_count += 1
                logger.info(
                    "Event %s expired → reverting, %d player(s) synced",
                    row["id_event"],
                    len(player_ids),
                )

        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("expire_events failed")
        raise
    finally:
        conn.close()

    return {"reverting": reverting_count}


@celery_app.task(name="app.workers.event_worker.finalize_reverting_events")
def finalize_reverting_events() -> dict:
    """Finalise les events en état `reverting` (§20.3).

    Le programme nominal a déjà été restauré au passage en `reverting` (push force_sync) ;
    cette tâche ne fait que figer l'état final :
    - is_recurring + encore valide → inactive (expires_at remis à NULL ; **activated_at CONSERVÉ**
      = marqueur du cooldown des play-once/spots, cf. _in_same_occurrence)
    - sinon                        → completed (on garde l'historique d'activation)
    """
    now_utc = datetime.now(UTC)
    finalized_count = 0

    conn = _db_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT id_event, is_recurring, valid_until
                FROM cms_events
                WHERE status = 'reverting'
                """
            )
            rows = cur.fetchall()

            for row in rows:
                past_validity = (
                    row["valid_until"] is not None and row["valid_until"] <= now_utc
                )
                final_status = _revert_target_status(row["is_recurring"], past_validity)
                # activated_at est CONSERVÉ (marqueur du cooldown play-once/spot) ; seul expires_at
                # est purgé quand l'event redevient inactive (il appartenait à l'occurrence passée).
                cur.execute(
                    """
                    UPDATE cms_events
                    SET status     = %s,
                        expires_at = CASE WHEN %s = 'inactive' THEN NULL ELSE expires_at END,
                        updated_at = %s
                    WHERE id_event = %s
                    """,
                    (final_status, final_status, now_utc, row["id_event"]),
                )
                finalized_count += 1
                logger.info(
                    "Event %s reverting → %s (recurring=%s)",
                    row["id_event"],
                    final_status,
                    row["is_recurring"],
                )

        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("finalize_reverting_events failed")
        raise
    finally:
        conn.close()

    return {"finalized": finalized_count}


@celery_app.task(name="app.workers.event_worker.activate_scheduled_events")
def activate_scheduled_events() -> dict:
    """Active les events inactive de type scheduled/conditional dont les conditions sont remplies."""
    now_utc = datetime.now(UTC)
    activated_count = 0

    conn = _db_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT id_event, id_org, event_type, trigger_config, target_config,
                       duration_ms, valid_from, valid_until, activated_at, is_preemptive,
                       timezone
                FROM cms_events
                WHERE status = 'inactive'
                  AND event_type IN ('scheduled', 'conditional')
                  AND (valid_from     IS NULL OR valid_from     <= %s)
                  AND (valid_until    IS NULL OR valid_until    >= %s)
                  AND (not_before_utc IS NULL OR not_before_utc <= %s)
                """,
                (now_utc, now_utc, now_utc),
            )
            rows = cur.fetchall()

            for row in rows:
                # Fuseau de RÉFÉRENCE de cet événement (P3.13) : c'est lui qui dit ce que
                # « 18 h » veut dire. NULL ⇒ SIGNFLOW_TZ, soit le comportement historique.
                tz_name = row["timezone"]
                # Passe now_utc (timezone-aware) — l'évaluateur convertit lui-même.
                if not _evaluator.evaluate(
                    row["trigger_config"], {"now": now_utc, "tz_name": tz_name}
                ):
                    continue

                # Cooldown anti-ré-activation (play-once duration_ms non nul, event récurrent qui
                # repasse inactive après lecture) : ne pas rejouer dans la MÊME occurrence —
                #  - INTERVALLE (« spot toutes les N min ») : même créneau de N minutes,
                #  - play-once fenêtre : même occurrence de fenêtre / même jour.
                # Repose sur activated_at, désormais CONSERVÉ par finalize_reverting_events.
                every_min = _interval_minutes(row["trigger_config"])
                if row["event_type"] == "scheduled" and row["duration_ms"] and row["activated_at"]:
                    last_act = row["activated_at"]
                    # Normaliser en UTC-aware si le TIMESTAMPTZ arrive naïf (rare selon driver)
                    if last_act.tzinfo is None:
                        last_act = last_act.replace(tzinfo=UTC)
                    if _in_same_occurrence(
                        row["trigger_config"], every_min, last_act, now_utc, tz_name
                    ):
                        continue  # déjà joué pour cette occurrence → pas de ré-lecture

                # Calcul de expires_at selon le mode :
                # - Scheduled + duration_ms NULL  → loop : expire à time_end (pas de gap)
                # - Scheduled + duration_ms fourni → play-once : expire après la durée du contenu
                # - Manual/conditional/webhook    → fallback duration_ms ou None
                if row["event_type"] == "scheduled":
                    if row["duration_ms"]:
                        # play-once
                        expires_at = now_utc + timedelta(milliseconds=row["duration_ms"])
                    else:
                        # loop jusqu'à time_end
                        expires_at = _compute_window_end(
                            row["trigger_config"], now_utc, tz_name
                        )
                else:
                    expires_at = (
                        now_utc + timedelta(milliseconds=row["duration_ms"])
                        if row["duration_ms"]
                        else None
                    )
                cur.execute(
                    """
                    UPDATE cms_events
                    SET status = 'active',
                        activated_at = %s,
                        expires_at   = %s,
                        updated_at   = %s
                    WHERE id_event = %s
                    """,
                    (now_utc, expires_at, now_utc, row["id_event"]),
                )
                player_ids = _resolve_player_ids(cur, row["id_org"], row["target_config"])
                _push_sync(player_ids, is_preemptive=row["is_preemptive"])

                # ── EXPIRATION PROGRAMMÉE À L'INSTANT EXACT ────────────────────────
                # `expire_events` tourne toutes les 30 s : un event « joue une fois »
                # restait donc actif jusqu'à 30 s APRÈS son échéance. Le player, lui,
                # arrivait au bout de son média — d'où soit un rebouclage (défaut
                # d'origine), soit, une fois le rebouclage corrigé, une DERNIÈRE IMAGE
                # FIGÉE pendant plusieurs secondes, qui se lit comme une panne
                # (constat d'Ed à l'écran, 2026-08-11).
                # On programme donc la bascule à la seconde près. Le battement de 30 s
                # reste en place comme FILET : si ce déclenchement se perd (worker
                # redémarré, file purgée), l'event expirera quand même.
                # ⚠️ Seulement pour un play-once : un event en mode boucle expire à la
                # fin de sa fenêtre, que le battement couvre très bien.
                if expires_at is not None and row["duration_ms"]:
                    delay = (expires_at - now_utc).total_seconds()
                    try:
                        expire_events.apply_async(countdown=max(0.0, delay))
                        logger.info(
                            "Event %s : expiration programmée dans %.1f s (filet : beat 30 s)",
                            row["id_event"], delay,
                        )
                    except Exception:  # noqa: BLE001 — le filet du beat reste
                        logger.warning(
                            "Event %s : programmation de l'expiration impossible, "
                            "le battement de 30 s prendra le relais", row["id_event"],
                        )
                activated_count += 1
                logger.info(
                    "Event %s (%s) scheduled → active, %d player(s) synced",
                    row["id_event"],
                    row["event_type"],
                    len(player_ids),
                )

        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("activate_scheduled_events failed")
        raise
    finally:
        conn.close()

    return {"activated": activated_count}


@celery_app.task(name="app.workers.event_worker.lift_media_embargoes")
def lift_media_embargoes() -> dict:
    """Détecte les levers d'embargo média et force-sync les players concernés.

    Cas 1 : cms_media.not_before_utc vient de passer (embargo direct).
    Cas 2 : cms_media.embargo_event_id → l'event lié vient de passer not_before_utc.
    Dans les deux cas : push force_sync (graceful) vers tous les players de l'org.
    """
    now_utc = datetime.now(UTC)
    window_start = now_utc - timedelta(seconds=35)  # marge légère par rapport au cycle 30s
    synced_orgs = 0

    conn = _db_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                """
                SELECT DISTINCT m.id_org
                FROM cms_media m
                LEFT JOIN cms_events e ON e.id_event = m.embargo_event_id
                WHERE m.is_deleted = false
                  AND (
                    -- Embargo direct qui vient de lever
                    (m.not_before_utc IS NOT NULL
                     AND m.embargo_event_id IS NULL
                     AND m.not_before_utc > %s
                     AND m.not_before_utc <= %s)
                    OR
                    -- Embargo via event lié qui vient de lever
                    (m.embargo_event_id IS NOT NULL
                     AND e.not_before_utc IS NOT NULL
                     AND e.not_before_utc > %s
                     AND e.not_before_utc <= %s)
                  )
                """,
                (window_start, now_utc, window_start, now_utc),
            )
            orgs = [row["id_org"] for row in cur.fetchall()]

            for id_org in orgs:
                cur.execute(
                    "SELECT id_player FROM cms_players WHERE id_org = %s",
                    (id_org,),
                )
                player_ids = [row[0] for row in cur.fetchall()]
                _push_sync(player_ids, is_preemptive=False)
                synced_orgs += 1
                logger.info(
                    "Media embargo lifted for org %s — %d player(s) synced",
                    id_org,
                    len(player_ids),
                )

        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("lift_media_embargoes failed")
        raise
    finally:
        conn.close()

    return {"orgs_synced": synced_orgs}


# Fenêtre « player en ligne » pour le tick de ré-application horaire : le heartbeat
# player est à 10s, on garde une marge confortable.
_ONLINE_WINDOW_SEC = 90


@celery_app.task(name="app.workers.event_worker.reapply_time_windows")
def reapply_time_windows() -> dict:
    """Re-pousse un sync graceful aux players en ligne pour ré-évaluer les fenêtres horaires.

    Les filtres temporels (item-rules § retours clients, règles horaires des schedules)
    ne sont calculés qu'au moment où le serveur résout un sync. Sans ce tick, un player
    garde le jeu d'items reçu à son dernier sync : un item limité à 18h-19h ne s'active
    (ni ne s'éteint) jamais de lui-même. On émet donc périodiquement un force_sync
    *graceful* (non-preemptive) : le player re-résout schedules + item-rules à l'heure
    courante, dédoublonne par fingerprint (no-op si le contenu n'a pas changé) et applique
    le changement à la prochaine frontière d'item — sans coupure.

    Restreint aux players en ligne (last_seen_at récent) : les players déconnectés
    reçoivent de toute façon un sync frais à la reconnexion.
    """
    online_cutoff = datetime.now(UTC) - timedelta(seconds=_ONLINE_WINDOW_SEC)
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id_player FROM cms_players WHERE last_seen_at >= %s",
                (online_cutoff,),
            )
            player_ids = [row[0] for row in cur.fetchall()]
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("reapply_time_windows failed")
        raise
    finally:
        conn.close()

    _push_sync(player_ids, is_preemptive=False)
    if player_ids:
        logger.debug("reapply_time_windows: %d online player(s) re-synced", len(player_ids))
    return {"players_synced": len(player_ids)}


def _load_site_power_schedule(cur, site, now_utc: datetime):
    """Charge le contexte horaire d'un site auto-power : (now_local, weekly, exceptions).

    `site` doit porter id_site + timezone ; les exceptions sont restreintes à
    veille → lendemain (suffisant pour l'overnight et les marges lead/lag).
    Partagé entre apply_site_power et check_player_health (offline attendu).
    """
    from app.services.site_hours import DayHours, Exception_

    try:
        tz = ZoneInfo(site["timezone"] or settings.SIGNFLOW_TZ)
    except (ZoneInfoNotFoundError, KeyError):
        tz = ZoneInfo("UTC")
    now_local = now_utc.astimezone(tz).replace(tzinfo=None)

    cur.execute(
        "SELECT weekday, is_closed, open_time, close_time "
        "FROM cms_site_hours WHERE id_site = %s",
        (site["id_site"],),
    )
    weekly = {
        h["weekday"]: DayHours(
            is_closed=h["is_closed"], open_time=h["open_time"], close_time=h["close_time"]
        )
        for h in cur.fetchall()
    }

    # Exceptions pertinentes (veille → lendemain pour couvrir l'overnight/marges)
    cur.execute(
        "SELECT date_from, date_to, kind, open_time, close_time "
        "FROM cms_site_exceptions WHERE id_site = %s "
        "AND date_to >= %s AND date_from <= %s",
        (site["id_site"], now_local.date() - timedelta(days=1),
         now_local.date() + timedelta(days=1)),
    )
    exceptions = [
        Exception_(
            date_from=e["date_from"], date_to=e["date_to"], kind=e["kind"],
            open_time=e["open_time"], close_time=e["close_time"],
        )
        for e in cur.fetchall()
    ]
    return now_local, weekly, exceptions


@celery_app.task(name="app.workers.event_worker.apply_site_power")
def apply_site_power() -> dict:
    """Allume/éteint les écrans selon les heures d'ouverture des sites (auto-power).

    Pour chaque site `auto_power_enabled` : calcule si l'écran doit être allumé à
    l'instant courant (heure locale du site, marges lead/lag, exceptions datées,
    fériés optionnels), puis applique à chaque player du site son mode d'alimentation
    (follow_site / always_on / custom vitrine / manual).

    Edge-triggered : n'émet `power_on`/`power_off` qu'aux *transitions* (dédup via
    `cms_players.last_power_state`, persistée → survit au restart du worker). Restreint
    aux players EN LIGNE (un offline ne peut pas recevoir la commande ; il sera repris
    à sa reconnexion car son last_power_state n'aura pas été mis à jour) et dont l'écran
    est piloté physiquement (display_config.type = rs232 | ip).

    Lot 2 — events « garder écrans allumés » : un event ACTIF avec keep_screens_on=true
    force l'écran ALLUMÉ pour ses players ciblés, même hors des heures d'ouverture du
    site (extension d'alimentation, jamais d'extinction). Quand l'event se termine, le
    tick suivant recalcule l'alimentation depuis les heures du site (→ extinction si fermé).
    """
    from app.services.site_hours import player_desired_power, site_screen_on_at

    now_utc = datetime.now(UTC)
    online_cutoff = now_utc - timedelta(seconds=_ONLINE_WINDOW_SEC)
    commands: list[tuple[int, bool]] = []  # (id_player, power_on)
    n_sites = 0

    conn = _db_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # Players à garder allumés par un event actif keep_screens_on (extension d'alim).
            cur.execute(
                "SELECT id_event, id_org, target_config FROM cms_events "
                "WHERE status = 'active' AND keep_screens_on = true"
            )
            keep_on_players: set[int] = set()
            for ev in cur.fetchall():
                keep_on_players.update(
                    _resolve_player_ids(cur, ev["id_org"], ev["target_config"] or {})
                )

            cur.execute(
                "SELECT id_site, timezone, power_lead_min, power_lag_min, "
                "respect_holidays, holiday_region FROM cms_sites "
                "WHERE auto_power_enabled = true"
            )
            sites = cur.fetchall()
            n_sites = len(sites)

            for site in sites:
                now_local, weekly, exceptions = _load_site_power_schedule(cur, site, now_utc)

                site_on = site_screen_on_at(
                    now_local, weekly, exceptions,
                    lead_min=site["power_lead_min"], lag_min=site["power_lag_min"],
                    respect_holidays=site["respect_holidays"], region=site["holiday_region"],
                )

                cur.execute(
                    "SELECT id_player, display_config, last_seen_at, last_power_state "
                    "FROM cms_players WHERE id_site = %s",
                    (site["id_site"],),
                )
                for p in cur.fetchall():
                    dc = p["display_config"] or {}
                    # Écran piloté physiquement (RS232/IP/CEC) OU repli « couper la sortie
                    # vidéo du player » (écran non pilotable, opt-in par player) : le player
                    # coupe alors son propre signal HDMI (DPMS/wlr-randr/SC_MONITORPOWER/
                    # veille Android/SetPowerSaveMode BrightSign) sur power_off.
                    if (dc.get("type") not in ("rs232", "ip", "cec")
                            and not dc.get("output_power_fallback")):
                        continue  # écran non piloté et pas de repli → on ne tente rien
                    desired = player_desired_power(dc.get("power_schedule"), now_local, site_on)
                    # Event keep_screens_on : étend l'allumage (jamais l'extinction).
                    # Ne force rien en mode manual (desired None reste None → non piloté).
                    if desired is False and p["id_player"] in keep_on_players:
                        desired = True
                    if desired is None:
                        continue  # mode manual ou site ne pilotant pas
                    if p["last_seen_at"] is None or p["last_seen_at"] < online_cutoff:
                        continue  # offline → repris à la reconnexion (état non mis à jour)
                    if p["last_power_state"] == desired:
                        continue  # pas de transition → rien à envoyer
                    commands.append((p["id_player"], desired))
                    cur.execute(
                        "UPDATE cms_players SET last_power_state = %s, last_power_at = %s "
                        "WHERE id_player = %s",
                        (desired, now_utc, p["id_player"]),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("apply_site_power failed")
        raise
    finally:
        conn.close()

    if commands:
        r = redis.from_url(settings.REDIS_URL)
        try:
            for pid, on in commands:
                r.publish(
                    f"signflow:player:{pid}:cmds",
                    json.dumps({
                        "type": "player:command",
                        "command": "display_command",
                        "params": {"display_cmd": "power_on" if on else "power_off"},
                    }),
                )
        finally:
            r.close()
        logger.info("apply_site_power: %d power transition(s) sent", len(commands))

    return {"sites": n_sites, "commands": len(commands)}


# ── Valeurs par défaut pour les seuils d'alerte ───────────────────────────────

_DEFAULT_ALERT_SETTINGS = {
    "offline_critical_min": 10,
    # Péremption du statut « online » : un player connecté envoie un heartbeat player:status
    # toutes les ~10 s (rafraîchit last_seen_at). S'il n'en a pas envoyé depuis N minutes alors
    # que son statut est encore online/warning, sa WS est morte sans close détecté (extension
    # Chrome / SW MV3, coupure réseau brutale, machine éteinte sans FIN) → on le bascule offline.
    "online_stale_min": 3,
    "cpu_warn_pct": 90.0,
    "ram_warn_pct": 90.0,
    "disk_warn_pct": 85.0,
    # Saturation : au-dela, le player ne peut plus rien telecharger. Distinct de
    # `disk_warn_pct` (simple avertissement) car celui-ci NOTIFIE. Un pourcentage reste un
    # pis-aller -- 512 Mo libres valent 87 % sur un disque de 4 Go et 99,9 % sur 500 Go ;
    # le controle exact se fera en octets a l'affectation (point 4).
    "disk_critical_pct": 95.0,
    "token_warn_days": 7,
    "min_player_version": None,
}


def _offline_expected(sctx: dict, power_cfg: dict | None, grace_min: float) -> bool:
    """Offline « attendu » : écran programmé éteint maintenant, OU ré-allumé depuis
    moins de `grace_min` minutes (temps de réveil/reconnexion du device)."""
    from app.services.site_hours import scheduled_off_at

    for t in (sctx["now_local"], sctx["now_local"] - timedelta(minutes=grace_min)):
        if scheduled_off_at(
            t, sctx["weekly"], sctx["exceptions"], power_cfg,
            lead_min=sctx["lead"], lag_min=sctx["lag"],
            respect_holidays=sctx["respect"], region=sctx["region"],
        ):
            return True
    return False


def _version_lt(v1: str, v2: str) -> bool:
    """Retourne True si v1 < v2 (comparaison semver simplifiée)."""
    try:
        p1 = [int(x) for x in str(v1).split(".")]
        p2 = [int(x) for x in str(v2).split(".")]
        while len(p1) < len(p2):
            p1.append(0)
        while len(p2) < len(p1):
            p2.append(0)
        return p1 < p2
    except (ValueError, AttributeError):
        return False


@celery_app.task(name="app.workers.event_worker.check_player_health")
def check_player_health() -> dict:
    """Vérifie la santé des players toutes les 5 min.

    Actions :
    - offline > N min → status=critical + reason offline_critical
    - offline pendant une coupure programmée (auto-power) → reason offline_scheduled,
      PAS d'escalade ni d'alerte (grâce offline_critical_min après la ré-ouverture)
    - CPU/RAM/Disk > seuil → reason cpu_high / ram_high / disk_high + warning si online
    - Token (online) proche de l'expiration / legacy → ROTATION + push token:refresh (Option B) ;
      sinon expirant < token_warn_days → reason token_7d ; < 3j → reason token_3d
    - Token (offline) déjà expiré → reason token_expired (visibilité, rattrapé à la reconnexion)
    - Version < min_player_version → reason version_outdated
    - Plus de raisons ET status=warning (posé par cette tâche) → retour online
    """
    from app.services import notifications

    now_utc = datetime.now(UTC)
    updated_count = 0
    to_refresh: list[tuple[int, str]] = []  # (id_player, nouveau token) à pousser après commit
    offline_alerts: list[tuple[int, dict]] = []  # (id_org, ctx), alerte offline→critical
    storage_alerts: list[tuple[int, dict]] = []  # (id_org, ctx), alerte saturation stockage

    conn = _db_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT id_org, player_alert_settings, player_version_lock FROM cms_organizations"
            )
            orgs = cur.fetchall()

            # ── Contexte « offline attendu » (coupures programmées, §XXII) ────
            # Pendant une fenêtre d'extinction auto-power, certains devices dorment
            # DÉCONNECTÉS (veille Android = réseau coupé) : leur offline est attendu.
            # On charge une fois les horaires des sites auto-power + les players
            # maintenus allumés par un event keep_screens_on (alerting normal pour eux).
            power_sites: dict[int, dict] = {}
            cur.execute(
                "SELECT id_site, timezone, power_lead_min, power_lag_min, "
                "respect_holidays, holiday_region FROM cms_sites "
                "WHERE auto_power_enabled = true"
            )
            for site in cur.fetchall():
                now_local, weekly, exceptions = _load_site_power_schedule(cur, site, now_utc)
                power_sites[site["id_site"]] = {
                    "now_local": now_local, "weekly": weekly, "exceptions": exceptions,
                    "lead": site["power_lead_min"], "lag": site["power_lag_min"],
                    "respect": site["respect_holidays"], "region": site["holiday_region"],
                }
            keep_on_players: set[int] = set()
            if power_sites:
                cur.execute(
                    "SELECT id_org, target_config FROM cms_events "
                    "WHERE status = 'active' AND keep_screens_on = true"
                )
                for ev in cur.fetchall():
                    keep_on_players.update(
                        _resolve_player_ids(cur, ev["id_org"], ev["target_config"] or {})
                    )

            for org in orgs:
                s = {**_DEFAULT_ALERT_SETTINGS, **(org["player_alert_settings"] or {})}
                offline_crit_min = float(s["offline_critical_min"])
                disk_crit_thr = float(s.get("disk_critical_pct", 95.0))
                online_stale_min = float(s["online_stale_min"])
                cpu_thr = float(s["cpu_warn_pct"])
                ram_thr = float(s["ram_warn_pct"])
                disk_thr = float(s["disk_warn_pct"])
                token_warn_days = float(s["token_warn_days"])
                min_ver = s.get("min_player_version") or org["player_version_lock"]

                cur.execute(
                    """
                    SELECT id_player, player_name, status, last_seen_at,
                           cpu_usage, ram_usage, disk_usage,
                           token_expires_at, player_version, alert_reasons,
                           id_site, display_config, capabilities
                    FROM cms_players
                    WHERE id_org = %s
                    """,
                    (org["id_org"],),
                )
                players = cur.fetchall()

                for p in players:
                    reasons: list[str] = []
                    offline_min = 0.0

                    # ── Péremption du heartbeat : online/warning sans player:status récent =
                    # WS morte non détectée (extension Chrome, coupure brutale) → offline. On
                    # dérive un statut « effectif » qui pilote le reste de la logique (et évite
                    # de faire tourner le token d'un player en réalité déconnecté).
                    cur_status = p["status"]
                    if cur_status in ("online", "warning") and p["last_seen_at"]:
                        last = _aware_utc(p["last_seen_at"])
                        if (now_utc - last).total_seconds() / 60 >= online_stale_min:
                            cur_status = "offline"
                    new_status = cur_status

                    # ── Offline → critical après N minutes ───────────────────
                    if cur_status in ("offline", "critical"):
                        if p["last_seen_at"]:
                            last = p["last_seen_at"]
                            if last.tzinfo is None:
                                last = last.replace(tzinfo=UTC)
                            offline_min = (now_utc - last).total_seconds() / 60
                        # Offline ATTENDU : écran programmé éteint (auto-power) → pas
                        # d'escalade critical ni d'alerte, raison informative seulement.
                        # Grâce d'offline_critical_min après la ré-ouverture (temps de
                        # réveil/reconnexion) ; au-delà l'alerting normal reprend — et
                        # détecte donc un parc qui ne s'est PAS réveillé. Un player DÉJÀ
                        # critical (panne signalée avant la fermeture) le reste.
                        sctx = power_sites.get(p["id_site"])
                        if (sctx is not None and p["status"] != "critical"
                                and p["id_player"] not in keep_on_players
                                and _offline_expected(
                                    sctx,
                                    (p["display_config"] or {}).get("power_schedule"),
                                    offline_crit_min,
                                )):
                            reasons.append("offline_scheduled")
                        elif offline_min >= offline_crit_min:
                            reasons.append("offline_critical")
                            new_status = "critical"
                        # Token expiré ALORS QUE le player est offline : visibilité « alerte si
                        # offline » (Option B). Aucune action requise — la grâce-à-la-reconnexion
                        # renouvellera le token dès que le player reviendra en ligne.
                        if p["token_expires_at"]:
                            exp = _aware_utc(p["token_expires_at"])
                            if exp < now_utc:
                                reasons.append("token_expired")

                    # ── Ressources + token + version (players connectés) ──────
                    if cur_status in ("online", "warning"):
                        if p["cpu_usage"] is not None and p["cpu_usage"] >= cpu_thr:
                            reasons.append("cpu_high")
                        if p["ram_usage"] is not None and p["ram_usage"] >= ram_thr:
                            reasons.append("ram_high")
                        if p["disk_usage"] is not None and p["disk_usage"] >= disk_thr:
                            reasons.append("disk_high")

                        # ── Auto-refresh proactif du token (« Option B ») ─────────
                        # Player online proche de l'expiration / legacy « 100 ans » → on fait
                        # tourner le token et on le pousse. En nominal, les tokens n'atteignent
                        # donc jamais l'expiration. Idempotent : après rotation token_expires_at
                        # = now+EXPIRE_DAYS → needs_rotation False jusqu'à la prochaine fenêtre.
                        if needs_rotation(p["token_expires_at"], now_utc):
                            new_token, new_exp = create_player_token(p["id_player"])
                            cur.execute(
                                """
                                UPDATE cms_players
                                SET player_token            = %s,
                                    token_expires_at        = %s,
                                    player_token_prev       = player_token,
                                    player_token_prev_until = %s,
                                    updated_at              = %s
                                WHERE id_player = %s
                                """,
                                (new_token, new_exp, grace_until(now_utc), now_utc, p["id_player"]),
                            )
                            to_refresh.append((p["id_player"], new_token))
                        elif p["token_expires_at"]:
                            # Pas de rotation → alerte de proximité d'expiration (filet).
                            exp = _aware_utc(p["token_expires_at"])
                            days_left = (exp - now_utc).total_seconds() / 86400
                            if days_left <= 3:
                                reasons.append("token_3d")
                            elif days_left <= token_warn_days:
                                reasons.append("token_7d")

                        if min_ver and p["player_version"]:
                            if _version_lt(p["player_version"], min_ver):
                                reasons.append("version_outdated")

                        # Escalade online → warning si raisons présentes
                        if reasons and cur_status == "online":
                            new_status = "warning"
                        # Désescalade warning → online si plus de raisons
                        elif not reasons and cur_status == "warning":
                            new_status = "online"

                    # ── Saturation du stockage ───────────────────────────────
                    # Calculé HORS des branches online/offline, volontairement : un disque
                    # plein fait justement DISPARAÎTRE le player (mesuré le 2026-08-06 — un
                    # stick à 100 % passe offline, et l'ancien code n'évaluait les motifs de
                    # ressources que sur un player en ligne : il ne restait donc AUCUNE
                    # alerte, alors que c'est exactement le moment où il faut prévenir).
                    # On raisonne sur la dernière valeur remontée, qui reste la vérité connue.
                    # Deux signaux, volontairement : les surfaces NATIVES (Electron, Android)
                    # remontent un pourcentage `disk`, les surfaces NAVIGATEUR (ChromeOS,
                    # extension, BrightSign) n'en remontent AUCUN — mesuré le 2026-08-06 :
                    # `disk_usage` y est NULL sur les 4 écrans du parc. Une alerte branchée
                    # sur le seul pourcentage aurait donc été aveugle sur la moitié du parc,
                    # c'est-à-dire exactement le défaut (`storage_pressure: false` en dur)
                    # qu'on venait de corriger côté player. Le second signal est la pression
                    # que le player DÉCLARE lui-même, désormais honnête sur les 6 surfaces.
                    _store = (p["capabilities"] or {}).get("store") or {}
                    _pressure = bool(_store.get("storage_pressure"))
                    _blocked = _store.get("blocked_ids") or []
                    if ((p["disk_usage"] is not None and p["disk_usage"] >= disk_crit_thr)
                            or _pressure or _blocked):
                        reasons.append("storage_full")

                    # Alerte à la TRANSITION offline→critical (une fois, pas à chaque beat) : le
                    # player passe critical alors qu'il ne l'était pas → notifie (§XXII).
                    if ("offline_critical" in reasons and new_status == "critical"
                            and p["status"] != "critical"):
                        offline_alerts.append((org["id_org"], {
                            "player_name": p["player_name"], "id_player": p["id_player"],
                            "offline_min": int(offline_min),
                        }))

                    old_reasons = list(p["alert_reasons"] or [])
                    # Notification à l'APPARITION du motif seulement (pas à chaque beat, sinon
                    # un écran saturé inonderait le canal toutes les minutes).
                    if "storage_full" in reasons and "storage_full" not in old_reasons:
                        storage_alerts.append((org["id_org"], {
                            "player_name": p["player_name"], "id_player": p["id_player"],
                            # Un écran navigateur n'a pas de pourcentage : on ne fabrique pas
                            # un chiffre pour faire joli, le message s'en passe.
                            "disk_usage": (round(float(p["disk_usage"]))
                                           if p["disk_usage"] is not None else None),
                            "blocked_count": len(_blocked) or None,
                        }))
                    if reasons != old_reasons or new_status != p["status"]:
                        cur.execute(
                            """
                            UPDATE cms_players
                            SET alert_reasons = %s,
                                status        = %s,
                                updated_at    = %s
                            WHERE id_player = %s
                            """,
                            (json.dumps(reasons), new_status, now_utc, p["id_player"]),
                        )
                        updated_count += 1
                        if reasons:
                            logger.info(
                                "Player %s → %s reasons=%s",
                                p["id_player"], new_status, reasons,
                            )

        conn.commit()

        # Alertes offline (§XXII) — après le commit santé (dispatch_sync fait ses propres INSERT log
        # + commit). Best-effort : un webhook injoignable ne doit pas casser le health-check.
        for id_org_a, ctx_a in offline_alerts:
            try:
                notifications.dispatch_sync(conn, id_org_a, "player_offline", ctx_a)
            except Exception:
                logger.exception("dispatch player_offline failed (org %s)", id_org_a)
        # Saturation du stockage (§XXII). Même politique best-effort : un canal injoignable
        # ne doit pas casser le health-check du parc.
        for id_org_a, ctx_a in storage_alerts:
            try:
                notifications.dispatch_sync(conn, id_org_a, "player_storage_full", ctx_a)
            except Exception:
                logger.exception("dispatch player_storage_full failed (org %s)", id_org_a)
    except Exception:
        conn.rollback()
        logger.exception("check_player_health failed")
        raise
    finally:
        conn.close()

    # Push des tokens renouvelés APRÈS commit (les nouveaux tokens sont déjà persistés → un
    # player qui reçoit le push trouvera bien son token courant en base).
    _push_token_refresh(to_refresh)
    if to_refresh:
        logger.info("Auto-refresh token : %d player(s) renouvelé(s)", len(to_refresh))

    return {"updated": updated_count, "tokens_refreshed": len(to_refresh)}
