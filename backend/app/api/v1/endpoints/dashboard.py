"""Dashboard « Mission Control » — synthèse KPI + fil d'activité (org-admin).

- GET /dashboard/summary   — 5 KPI cards (players online/offline/warning, campagnes
  actives, Proof of Play) : chiffre courant + évolution vs 7 jours + sparkline 8 points.
  Historique réel via le rollup quotidien `cms_network_metrics_daily` (§XXIV) ; le
  point du jour est la valeur LIVE (les rollups sont écrits par un beat quotidien).
- GET /dashboard/activity  — fil d'activité récente depuis `cms_audit_log`.

TENANT-SCOPED (RLS via l'org du compte connecté).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db, require_org_admin
from app.models.audit_log import CmsAuditLog
from app.models.campaign import CmsCampaign
from app.models.media import CmsMedia
from app.models.player import CmsPlayer
from app.models.pop import CmsProofOfPlay
from app.models.user import CmsUser
from app.schemas.dashboard import (
    ActivityFeed,
    ActivityItem,
    DashboardMedia,
    DashboardSummary,
    KpiCard,
    MediaTypeGroup,
    RecentMediaItem,
)
from app.services import analytics, pop_counting
from app.services.media import get_signed_url

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_SPARK_DAYS = 8  # 7 jours d'historique + aujourd'hui
_MEDIA_ORDER = ["video", "image", "audio", "document", "html_package", "feed_display", "url_display"]


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.SIGNFLOW_TZ)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")


def _delta(current: int, base: int) -> float | None:
    """Variation % courant vs base ; None si base 0 (incomparable, pas de badge)."""
    if base <= 0:
        return None
    return round((current - base) * 100.0 / base, 1)


def _card(key: str, spark: list[int]) -> KpiCard:
    """spark = 8 points (ancien→aujourd'hui). value = dernier, delta = vs 1er point."""
    value = spark[-1] if spark else 0
    base = spark[0] if spark else 0
    return KpiCard(key=key, value=value, delta_pct=_delta(value, base), spark=spark)


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    current_user: Annotated[CmsUser, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DashboardSummary:
    tz = _tz()
    now = datetime.now(tz)
    today = now.date()
    org = current_user.id_org
    days = [today - timedelta(days=_SPARK_DAYS - 1 - i) for i in range(_SPARK_DAYS)]

    # ── Players : historique quotidien (rollup) + valeur LIVE aujourd'hui ────────
    rows = await analytics.metrics_series(db, org, days[0], today)
    by_date = {r.metric_date: r for r in rows}

    prows = list((await db.execute(
        select(CmsPlayer.status, CmsPlayer.last_seen_at).where(CmsPlayer.id_org == org)
    )).all())
    # Statut EFFECTIF (comme la table NOC + la carte) : online/warning périmé → offline, pour
    # ne pas attendre le beat 5 min. Bucketing ALIGNÉ sur le rollup quotidien (analytics_worker)
    # ET sur le NOC/État du parc : `critical` = escalade d'`offline` (raison offline_critical),
    # donc compté OFFLINE — jamais warning. Sans cet alignement, le point live d'aujourd'hui
    # contredisait l'historique de sa propre sparkline et l'État du parc.
    statuses = [analytics.effective_status(s, ls, now) for s, ls in prows]
    live = {
        "online": sum(1 for s in statuses if s == "online"),
        "offline": sum(1 for s in statuses if s in ("offline", "critical")),
        "warning": sum(1 for s in statuses if s == "warning"),
    }

    def player_spark(field: str, live_val: int) -> list[int]:
        out: list[int] = []
        for d in days:
            if d == today:
                out.append(live_val)
            else:
                r = by_date.get(d)
                out.append(int(getattr(r, field)) if r else 0)
        return out

    online_card = _card("players_online", player_spark("players_online", live["online"]))
    offline_card = _card("players_offline", player_spark("players_offline", live["offline"]))
    warning_card = _card("players_warning", player_spark("players_warning", live["warning"]))

    # ── Campagnes actives par jour (proxy : planifiées & non brouillon/annulée) ──
    camp_rows = list((await db.execute(
        select(CmsCampaign.starts_on, CmsCampaign.ends_on)
        .where(
            CmsCampaign.id_org == org,
            CmsCampaign.is_deleted.is_(False),
            CmsCampaign.status.notin_(("draft", "cancelled")),
            CmsCampaign.ends_on >= days[0],
            CmsCampaign.starts_on <= today,
        )
    )).all())
    camp_spark = [sum(1 for c in camp_rows if c.starts_on <= d <= c.ends_on) for d in days]
    campaigns_card = _card("active_campaigns", camp_spark)

    # ── Proof of Play : plays/jour (rollup) + 24 h glissantes aujourd'hui ────────
    plays_24h = int((await db.execute(
        select(func.count()).select_from(CmsProofOfPlay).where(
            CmsProofOfPlay.id_org == org,
            CmsProofOfPlay.played_at >= now - timedelta(hours=24),
            # Écran coupé (migr 0102) ou zone recouverte (migr 0125) = pas de diffusion :
            # le KPI compte de l'antenne réelle.
            pop_counting.COUNTED,
        )
    )).scalar() or 0)
    pop_spark: list[int] = []
    for d in days:
        if d == today:
            pop_spark.append(plays_24h)
        else:
            r = by_date.get(d)
            pop_spark.append(int(r.plays_count) if r else 0)
    pop_card = _card("proof_of_play", pop_spark)

    return DashboardSummary(
        generated_at=now,
        players_online=online_card,
        players_offline=offline_card,
        players_warning=warning_card,
        active_campaigns=campaigns_card,
        proof_of_play=pop_card,
    )


# resource_type → (table, colonne id, colonne nom) : résout l'ID d'une ligne d'audit en NOM lisible
# dans le fil d'activité (au lieu de « playlist #24 »). Tables tenant-scoped → on filtre id_org
# (défense en profondeur). Un type absent d'ici ou une ressource supprimée → pas de nom → le front
# retombe sur « type #id ». Les noms de tables/colonnes sont figés ici (jamais de saisie utilisateur).
_ACTIVITY_NAMEABLE: dict[str, tuple[str, str, str]] = {
    "playlist":     ("cms_playlists",     "id_playlist",     "playlist_name"),
    "media":        ("cms_media",         "id_media",        "media_name"),
    "player":       ("cms_players",        "id_player",       "player_name"),
    "template":     ("cms_templates",     "id_template",     "template_name"),
    "campaign":     ("cms_campaigns",     "id_campaign",     "campaign_name"),
    "advertiser":   ("cms_advertisers",   "id_advertiser",   "advertiser_name"),
    "site":         ("cms_sites",         "id_site",         "site_name"),
    "event":        ("cms_events",        "id_event",        "event_name"),
    "schedule":     ("cms_schedules",     "id_schedule",     "schedule_name"),
    "player_group": ("cms_player_groups", "id_group",        "group_name"),
    "site_group":   ("cms_site_groups",   "id_site_group",   "group_name"),
}


# Clés de `detail` où chercher le nom quand la ressource N'EXISTE PLUS. Ordre = du plus
# spécifique au plus générique ; les producteurs d'audit n'ont pas tous la même convention
# (mesuré en prod : `playlist_name`, `template_name`, `media_name`, et `name` pour les
# campagnes, annonceurs et l'assistant IA).
# ⛔ `renamed_from` est volontairement exclu : c'est l'ANCIEN nom, pas le nom de la ressource.
_ACTIVITY_NAME_KEYS = ("{type}_name", "name", "media_name")


def _name_from_detail(resource_type: str, detail: dict | None) -> str | None:
    """Nom conservé DANS le journal — le seul qui survive à la suppression de la ressource.

    C'est tout l'intérêt de tracer le nom au moment de l'action (templates 28/07, playlists
    29/07) : « la ligne disparaît, le journal reste ». Sans ce repli, le fil d'activité
    affiche « Delete · playlist #46 » pour une playlist supprimée — c'est-à-dire précisément
    l'événement pour lequel on a le plus besoin de savoir DE QUOI on parle (constat d'Ed,
    2026-07-29).

    ⚠️ Seule la CHAÎNE du nom sort d'ici. Le dict `detail` reste hors de la charge utile
    exposée au navigateur (défaut D3 de l'audit du Dashboard, 2026-07-28).
    """
    if not isinstance(detail, dict):
        return None
    for key in _ACTIVITY_NAME_KEYS:
        value = detail.get(key.format(type=resource_type))
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def _resolve_activity_names(
    db: AsyncSession, id_org: int, pairs: list[tuple[str, int]]
) -> dict[tuple[str, int], str]:
    """(resource_type, resource_id) → nom, par requête groupée par type. Robuste : un type dont la
    requête échoue (schéma inattendu) ne casse pas le fil — il reste juste non résolu."""
    from collections import defaultdict

    by_type: dict[str, set[int]] = defaultdict(set)
    for rtype, rid in pairs:
        if rtype in _ACTIVITY_NAMEABLE:
            by_type[rtype].add(rid)
    out: dict[tuple[str, int], str] = {}
    for rtype, ids in by_type.items():
        table, id_col, name_col = _ACTIVITY_NAMEABLE[rtype]
        q = text(
            f"SELECT {id_col} AS rid, {name_col} AS rname FROM {table} "
            f"WHERE {id_col} IN :ids AND id_org = :org"
        ).bindparams(bindparam("ids", expanding=True))
        try:
            for rid, rname in (await db.execute(q, {"ids": list(ids), "org": id_org})).all():
                if rname:
                    out[(rtype, int(rid))] = rname
        except Exception:  # noqa: BLE001 — un type mal mappé ne doit pas casser le fil
            continue
    return out


@router.get("/activity", response_model=ActivityFeed)
async def dashboard_activity(
    current_user: Annotated[CmsUser, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(12, ge=1, le=40),
) -> ActivityFeed:
    rows = list((await db.execute(
        select(CmsAuditLog, CmsUser.full_name, CmsUser.email)
        .join(CmsUser, CmsUser.id_user == CmsAuditLog.id_user, isouter=True)
        .where(CmsAuditLog.id_org == current_user.id_org)
        .order_by(CmsAuditLog.created_at.desc())
        .limit(limit)
    )).all())

    # resource_id est stocké en TEXTE → ne résoudre que les valeurs numériques.
    pairs: list[tuple[str, int]] = []
    for a, _fn, _em in rows:
        if a.resource_id and str(a.resource_id).isdigit():
            pairs.append((a.resource_type, int(a.resource_id)))
    names = await _resolve_activity_names(db, current_user.id_org, pairs)

    items: list[ActivityItem] = []
    for a, full_name, email in rows:
        live = (
            names.get((a.resource_type, int(a.resource_id)))
            if a.resource_id and str(a.resource_id).isdigit() else None
        )
        # La ressource existe encore → son nom ACTUEL (un renommage doit se voir).
        # Sinon → le nom conservé dans le journal, et on signale qu'elle n'existe plus pour
        # que l'écran n'en fasse pas un lien mort.
        archived = _name_from_detail(a.resource_type, a.detail) if live is None else None
        # « Disparue » exige d'avoir CHERCHÉ la ressource sans la trouver : un type que le fil
        # ne sait pas résoudre, ou un resource_id qui n'est pas un identifiant (l'audit des
        # annonceurs y range le nom), ne prouve rien — on affiche le nom du journal sans
        # prétendre qu'elle est supprimée (créatif et annonceurs vivants marqués « since
        # deleted », vu le 2026-11-09).
        looked_up = (a.resource_type in _ACTIVITY_NAMEABLE
                     and bool(a.resource_id) and str(a.resource_id).isdigit())
        items.append(ActivityItem(
            id=a.id_audit,
            action=a.action,
            resource_type=a.resource_type,
            resource_id=a.resource_id,
            resource_name=live or archived,
            resource_gone=looked_up and live is None and archived is not None,
            user_name=full_name or email,
            source=a.source,
            created_at=a.created_at,
        ))
    return ActivityFeed(items=items)


@router.get("/media", response_model=DashboardMedia)
async def dashboard_media(
    current_user: Annotated[CmsUser, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DashboardMedia:
    """Panneau latéral média : par type, total + 3 contenus les plus récents."""
    org = current_user.id_org
    totals = dict((await db.execute(
        select(CmsMedia.media_type, func.count())
        .where(CmsMedia.id_org == org, CmsMedia.is_deleted.is_(False))
        .group_by(CmsMedia.media_type)
    )).all())

    groups: list[MediaTypeGroup] = []
    for ty in _MEDIA_ORDER:
        total = int(totals.get(ty, 0) or 0)
        if total == 0:
            continue
        recent = list((await db.execute(
            select(CmsMedia)
            .where(CmsMedia.id_org == org, CmsMedia.is_deleted.is_(False), CmsMedia.media_type == ty)
            .order_by(CmsMedia.created_at.desc())
            .limit(3)
        )).scalars().all())
        groups.append(MediaTypeGroup(
            media_type=ty,
            total=total,
            items=[
                RecentMediaItem(
                    id_media=m.id_media,
                    media_name=m.media_name,
                    media_type=m.media_type,
                    thumbnail_url=get_signed_url(m.thumbnail_url, ttl=3600) if m.thumbnail_url else None,
                )
                for m in recent
            ],
        ))
    return DashboardMedia(groups=groups)
