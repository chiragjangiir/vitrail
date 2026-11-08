"""Analytics & Reporting Exécutif (§XXIV) — Executive Dashboard.

Agrégats *lecture seule* pour le dashboard direction : Network Health Score, KPIs flotte,
top contenus (Proof of Play) et séries temporelles (rollup quotidien `cms_network_metrics_daily`).

Aucune écriture ici — le rollup est produit par le worker `analytics_worker.rollup_network_metrics`.
Le calcul du score est une fonction PURE (`compute_health_score`) pour être testable et partagée
entre l'endpoint (snapshot live) et le worker (rollup historique).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import CmsNetworkMetricsDaily
from app.models.media import CmsMedia
from app.models.notification import CmsNotificationLog
from app.models.player import CmsPlayer
from app.models.pop import CmsProofOfPlay
from app.services import pop_counting
from app.services.targeting import Target, players_for_targets

# Diffusion écran coupé (migr 0102) ou zone recouverte par un overlay plein écran
# (migr 0125) : preuve conservée mais jamais comptée comme de l'antenne — sinon les
# indicateurs §XXIV créditeraient du temps d'écran que personne n'a pu voir.
# Définition unique : services/pop_counting.
_COUNTED = pop_counting.COUNTED

# Un player est considéré « frais » (sync récente) si vu il y a moins de ce délai.
FRESH_THRESHOLD = timedelta(minutes=10)
# Péremption du statut « online/warning » à la LECTURE : le beat check_player_health ne tourne
# que toutes les 5 min, donc une déconnexion met jusqu'à 5 min à passer le statut en base à
# offline. Les dashboards dérivent donc le statut « effectif » comme le fait le beat (défaut
# online_stale_min = 3 min), pour refléter la réalité au polling sans attendre le beat.
ONLINE_STALE_MIN = 3.0


def effective_status(status: str, last_seen_at: datetime | None, now: datetime) -> str:
    """Statut affiché « live » : online/warning dont le heartbeat est périmé → offline.
    Le beat reste la source de vérité PERSISTÉE (+ warning/critical/token/alertes) ; ceci ne
    fait que rafraîchir l'AFFICHAGE de la bascule online→offline entre deux passages du beat."""
    if status in ("online", "warning") and last_seen_at is not None:
        last = last_seen_at if last_seen_at.tzinfo else last_seen_at.replace(tzinfo=UTC)
        if (now - last).total_seconds() / 60 >= ONLINE_STALE_MIN:
            return "offline"
    return status
# Pondérations du Network Health Score (§24.1). Somme = 1.0.
W_ONLINE = 0.45
W_CONFORMITY = 0.30
W_FRESH = 0.25
# Pénalité par alerte ouverte (plafonnée) — les alertes ouvertes dégradent le score.
ALERT_PENALTY_EACH = 4
ALERT_PENALTY_MAX = 20


def compute_health_score(
    *,
    total: int,
    online: int,
    fresh: int,
    conforming: int,
    open_alerts: int,
) -> int | None:
    """Network Health Score 0–100 (§24.1) — fonction pure.

    Combine %online, taux de conformité diffusion (players qui diffusent réellement),
    fraîcheur de sync, moins une pénalité pour les alertes ouvertes. `None` si flotte vide.
    """
    if total <= 0:
        return None
    online_ratio = online / total
    conformity_ratio = conforming / total
    fresh_ratio = fresh / total
    base = 100.0 * (
        W_ONLINE * online_ratio + W_CONFORMITY * conformity_ratio + W_FRESH * fresh_ratio
    )
    penalty = min(ALERT_PENALTY_MAX, max(0, open_alerts) * ALERT_PENALTY_EACH)
    return max(0, min(100, round(base - penalty)))


def roi_estimate(
    *,
    screens: int,
    uptime_pct: float | None,
    days: int,
    hours_per_day: float,
    contacts_per_hour: float,
    cpm_eur: float,
    paper_eur_per_month: float,
) -> dict:
    """ROI Estimator (§24.5) — fonction pure, valeurs INDICATIVES.

    - contacts estimés = écrans × heures/j × jours × (uptime%) × contacts/h/écran
    - valeur réseau (CPM) = contacts / 1000 × CPM
    - économie papier = écrans × coût affiche/mois × (jours / 30)
    - ROI cumulé = valeur réseau + économie papier
    """
    up = (uptime_pct if uptime_pct is not None else 100.0) / 100.0
    impressions = round(screens * hours_per_day * days * up * contacts_per_hour)
    network_value = round(impressions / 1000 * cpm_eur, 2)
    paper_savings = round(screens * paper_eur_per_month * (days / 30), 2)
    return {
        "screens": screens,
        "days": days,
        "hours_per_day": hours_per_day,
        "contacts_per_hour": contacts_per_hour,
        "cpm_eur": cpm_eur,
        "paper_eur_per_month": paper_eur_per_month,
        "uptime_pct": round(up * 100, 1),
        "impressions": impressions,
        "network_value_eur": network_value,
        "paper_savings_eur": paper_savings,
        "total_roi_eur": round(network_value + paper_savings, 2),
    }


async def resolve_player_ids(
    db: AsyncSession, id_org: int,
    id_players: list[int] | None, id_group: int | None, id_site: int | None,
    id_site_group: int | None = None,
) -> list[int] | None:
    """Union des filtres de reporting (players explicites / groupe / site / groupe de sites).
    None = toute l'org (aucun filtre).

    Délègue au **targeting canonique** (`players_for_targets`) au lieu de ré-implémenter la
    résolution : c'est ce qui manquait pour offrir `site_group` aux rapports (audit ciblage
    2026-07-18), et ça aligne les garde-fous org (le lookup de groupe maison ne filtrait pas
    par org). Cette fonction est aussi la source unique du Proof of Play (`pop.py`), qui en
    avait un clone à l'identique.
    """
    ids: set[int] = set(id_players or [])
    targets = [
        Target(target_type=tt, target_id=tid)
        for tt, tid in (("group", id_group), ("site", id_site), ("site_group", id_site_group))
        if tid
    ]
    if targets:
        ids |= await players_for_targets(db, id_org, targets)
    return sorted(ids) if ids else None


async def scoped_report_players(
    db: AsyncSession, user,
    id_players: list[int] | None = None, id_group: int | None = None,
    id_site: int | None = None, id_site_group: int | None = None,
) -> list[int] | None:
    """Périmètre de reporting = **filtre demandé ∩ périmètre de gouvernance** (D1 étendue
    au menu Rapports, 2026-07-31). `None` = aucune restriction (toute l'organisation).

    🔴 Pourquoi : les surfaces analytiques sont gatées `reports:read`, portée par 5 rôles
    système — l'audit du Dashboard (28/07) l'avait fermé sur `/noc` et `/geo` en notant que
    les AGRÉGATS DE DIFFUSION restaient à trancher. Ils exposaient : le classement des
    contenus (donc les campagnes du voisin), les indicateurs de tout le parc, l'audience
    estimée par site, et le **Proof of Play**, qui nomme l'écran et le contenu — la preuve
    de diffusion du réseau entier.

    🔑 **L'intersection est le point** : `id_players` vient du CLIENT. Sans elle, il suffit
    de nommer l'écran du voisin pour lire ses chiffres — le filtre d'affichage devient une
    porte. Une liste VIDE en retour signifie « rien à montrer » et se traduit par un
    `IN ()` qui ne rend aucune ligne : la défaillance est fermée, jamais ouverte.

    ⛔ Ne PAS appliquer aux chemins d'INTÉGRITÉ (`/pop/verify`, `/pop/certificate`) : leur
    racine de Merkle est AGRÉGÉE, une racine partielle est indiscernable d'une chaîne
    altérée. Même règle que `screen_off` le 23/07 — on filtre les comptages, pas les preuves.
    """
    from app.services.governance_scope import user_player_scope

    requested = await resolve_player_ids(
        db, user.id_org, id_players, id_group, id_site, id_site_group)
    scope = await user_player_scope(db, user)
    if scope is None:            # org-admin, ou utilisateur sans nœud administré
        return requested
    if requested is None:
        return sorted(scope)     # peut être vide = il ne voit rien (décision D1 d'Ed)
    return sorted(set(requested) & scope)


async def fleet_counts(
    db: AsyncSession, id_org: int, player_ids: list[int] | None
) -> dict[str, int]:
    """Compte des players par statut (+ frais) sur le périmètre demandé."""
    now = datetime.now(UTC)
    fresh_after = now - FRESH_THRESHOLD
    stmt = select(
        func.count().label("total"),
        func.count().filter(CmsPlayer.status == "online").label("online"),
        func.count().filter(CmsPlayer.status == "warning").label("warning"),
        func.count().filter(CmsPlayer.status.in_(("offline", "critical"))).label("offline"),
        func.count().filter(CmsPlayer.status == "maintenance").label("maintenance"),
        func.count().filter(CmsPlayer.last_seen_at >= fresh_after).label("fresh"),
    ).where(CmsPlayer.id_org == id_org)
    if player_ids is not None:
        stmt = stmt.where(CmsPlayer.id_player.in_(player_ids))
    row = (await db.execute(stmt)).one()
    return {
        "total": row.total or 0,
        "online": row.online or 0,
        "warning": row.warning or 0,
        "offline": row.offline or 0,
        "maintenance": row.maintenance or 0,
        "fresh": row.fresh or 0,
    }


async def play_totals(
    db: AsyncSession, id_org: int, start_utc: datetime, end_utc: datetime,
    player_ids: list[int] | None,
) -> tuple[int, int, int]:
    """(nb diffusions, secondes cumulées, players distincts ayant diffusé) sur la période."""
    stmt = select(
        func.count(CmsProofOfPlay.id_pop).label("plays"),
        func.coalesce(func.sum(CmsProofOfPlay.duration_ms), 0).label("total_ms"),
        func.count(func.distinct(CmsProofOfPlay.id_player)).label("players"),
    ).where(
        CmsProofOfPlay.id_org == id_org,
        CmsProofOfPlay.played_at >= start_utc,
        CmsProofOfPlay.played_at < end_utc,
        _COUNTED,
    )
    if player_ids is not None:
        stmt = stmt.where(CmsProofOfPlay.id_player.in_(player_ids))
    row = (await db.execute(stmt)).one()
    return int(row.plays or 0), round((row.total_ms or 0) / 1000), int(row.players or 0)


async def open_alerts_count(db: AsyncSession, id_org: int, since: datetime) -> int:
    """Alertes émises depuis `since` (proxy des alertes ouvertes — journal d'envois §XXII)."""
    stmt = select(func.count(CmsNotificationLog.id_log)).where(
        CmsNotificationLog.id_org == id_org,
        CmsNotificationLog.created_at >= since,
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def top_content(
    db: AsyncSession, id_org: int, start_utc: datetime, end_utc: datetime,
    player_ids: list[int] | None, limit: int = 5,
) -> list[dict]:
    """Top contenus par nombre de diffusions sur la période (Proof of Play)."""
    stmt = (
        select(
            CmsProofOfPlay.id_media,
            CmsMedia.media_name,
            CmsMedia.media_type,
            func.count(CmsProofOfPlay.id_pop).label("plays"),
            func.coalesce(func.sum(CmsProofOfPlay.duration_ms), 0).label("total_ms"),
        )
        .join(CmsMedia, CmsMedia.id_media == CmsProofOfPlay.id_media, isouter=True)
        .where(
            CmsProofOfPlay.id_org == id_org,
            CmsProofOfPlay.played_at >= start_utc,
            CmsProofOfPlay.played_at < end_utc,
            CmsProofOfPlay.id_media.isnot(None),
            _COUNTED,
        )
        .group_by(CmsProofOfPlay.id_media, CmsMedia.media_name, CmsMedia.media_type)
        .order_by(func.count(CmsProofOfPlay.id_pop).desc())
        .limit(limit)
    )
    if player_ids is not None:
        stmt = stmt.where(CmsProofOfPlay.id_player.in_(player_ids))
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id_media": r.id_media,
            "media_name": r.media_name,
            "media_type": r.media_type,
            "plays": int(r.plays or 0),
            "seconds": round((r.total_ms or 0) / 1000),
        }
        for r in rows
    ]


def _day_bounds_utc(tz: ZoneInfo, from_d: date, until_d: date) -> tuple[datetime, datetime]:
    """Bornes [début from, fin until] en UTC, jours définis en `tz` (until inclus)."""
    start_local = datetime.combine(from_d, time.min, tzinfo=tz)
    end_local = datetime.combine(until_d + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


async def build_executive_payload(
    db: AsyncSession, id_org: int, from_d: date, until_d: date,
    player_ids: list[int] | None, tz: ZoneInfo,
) -> dict:
    """Assemble le payload complet de l'Executive Dashboard (§24.1).

    Partagé entre l'endpoint authentifié, la route publique (share link) et le PDF.
    Snapshot live de la flotte (robuste sans rollup) + séries depuis le rollup quotidien.
    """
    fleet = await fleet_counts(db, id_org, player_ids)
    now = datetime.now(UTC)
    total = fleet["total"]

    start_utc, end_utc = _day_bounds_utc(tz, from_d, until_d)
    plays_count, play_seconds, _ = await play_totals(db, id_org, start_utc, end_utc, player_ids)

    _, _, players_recent = await play_totals(
        db, id_org, now - timedelta(hours=24), now, player_ids)
    conformity_pct = round(100.0 * players_recent / total, 1) if total else None
    open_alerts = await open_alerts_count(db, id_org, now - timedelta(hours=24))

    health = compute_health_score(
        total=total, online=fleet["online"], fresh=fleet["fresh"],
        conforming=players_recent, open_alerts=open_alerts,
    )
    top = await top_content(db, id_org, start_utc, end_utc, player_ids, limit=5)

    rows = await metrics_series(db, id_org, from_d, until_d)
    series: list[dict] = []
    uptime_vals: list[float] = []
    for r in rows:
        online_pct = (
            round(100.0 * r.players_online / r.players_total, 1) if r.players_total else None
        )
        if online_pct is not None:
            uptime_vals.append(online_pct)
        series.append({
            "date": r.metric_date,
            "players_total": r.players_total,
            "players_online": r.players_online,
            "online_pct": online_pct,
            "conformity_pct": float(r.conformity_pct) if r.conformity_pct is not None else None,
            "alerts_active": r.alerts_active,
            "plays_count": r.plays_count,
            "health_score": r.health_score,
        })
    uptime_pct = round(sum(uptime_vals) / len(uptime_vals), 1) if uptime_vals else (
        round(100.0 * fleet["online"] / total, 1) if total else None)

    return {
        "from_date": from_d,
        "until_date": until_d,
        "health_score": health,
        "fleet": {
            "total": total, "online": fleet["online"], "warning": fleet["warning"],
            "offline": fleet["offline"], "maintenance": fleet["maintenance"],
        },
        "conformity_pct": conformity_pct,
        "alerts_active": open_alerts,
        "uptime_pct": uptime_pct,
        "plays_count": plays_count,
        "play_seconds": play_seconds,
        "top_content": top,
        "series": series,
    }


async def metrics_series(
    db: AsyncSession, id_org: int, from_d: date, until_d: date
) -> list[CmsNetworkMetricsDaily]:
    """Rollup quotidien de la période [from, until] (ordre chronologique)."""
    stmt = (
        select(CmsNetworkMetricsDaily)
        .where(
            CmsNetworkMetricsDaily.id_org == id_org,
            CmsNetworkMetricsDaily.metric_date >= from_d,
            CmsNetworkMetricsDaily.metric_date <= until_d,
        )
        .order_by(CmsNetworkMetricsDaily.metric_date)
    )
    return list((await db.execute(stmt)).scalars().all())
