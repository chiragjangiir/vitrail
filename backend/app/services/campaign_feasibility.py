"""SOV réalisable — conseil A PRIORI à la création de campagne (demande Ed 2026-07-12).

Depuis l'anti-martèlement (`splice_ad_items` : au plus UNE pub par frontière de
boucle, jamais deux spots dos à dos), le nombre de passages d'une campagne est
physiquement plafonné par le nombre de frontières de la boucle maison : sur une
boucle de B items durant H ms, un créatif de d ms ne peut pas dépasser
**B×d / (H + B×d)** du temps d'antenne (1 passage par frontière et par cycle).
Une SOV vendue au-delà = sous-service garanti — mesuré a posteriori (rapport S4)
et alerté (§XXII `campaign_underserved`) ; ce service est le conseil a priori.

Calcule ce plafond PAR PLAYER ciblé puis l'agrège (le pire player borne la
campagne). Consommateurs : occupancy-check CMS (drawer campagne), portail
annonceur (réponse STRIPPÉE : agrégat seul, jamais le détail des players),
reviewer §21, dry-run d'import.

Approximations assumées (à refléter dans le hint UI) :
- boucle maison = la boucle COURANTE (event content actif > schedule actif par
  priorité — même préséance que le sync) ; elle varie au fil de la journée ;
- gouvernance §XVIII ignorée (programme compilé multi-couches, hors périmètre v1) ;
- filtres de réception (tags, règles d'item, gates capacité) ignorés → B/H
  légèrement surestimés ;
- item sans durée explicite → durée native du média, défaut 10 s.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import CmsCampaignCreative
from app.models.event import CmsEvent
from app.models.media import CmsMedia
from app.models.player import CmsPlayer
from app.models.player_group import CmsPlayerGroupMember
from app.models.playlist import CmsPlaylist, CmsPlaylistItem
from app.models.schedule import CmsSchedule, CmsScheduleRule, CmsScheduleTarget
from app.models.organization import CmsSite
from app.models.site_group import CmsSiteGroupMember
from app.core.timezones import safe_tz_name
from app.services.scheduling import local_now, schedule_active_at, time_rule_from_schedule
from app.services.targeting import Target, event_target_matches, players_for_targets

DEFAULT_CREATIVE_MS = 10_000
# Bornes de coût : la résolution de boucle se fait player par player (requêtes
# batchées mais boucle Python) — même esprit que le cap 50 de l'occupancy-check.
MAX_PLAYERS_COMPUTED = 100
MAX_PLAYERS_RETURNED = 20


async def creative_avg_ms(db: AsyncSession, id_campaign: int) -> int | None:
    """Durée moyenne PONDÉRÉE des créatifs actifs (même rotation que la diffusion :
    liste répétée par weight, cf. campaign_delivery). None si aucun créatif jouable."""
    rows = (await db.execute(
        select(CmsCampaignCreative.duration_ms, CmsCampaignCreative.weight,
               CmsMedia.duration_ms)
        .join(CmsMedia, CmsMedia.id_media == CmsCampaignCreative.id_media)
        .where(
            CmsCampaignCreative.id_campaign == id_campaign,
            CmsCampaignCreative.status == "active",
            CmsMedia.is_deleted == False,  # noqa: E712
            CmsMedia.is_blocked == False,  # noqa: E712
        )
    )).all()
    if not rows:
        return None
    total = weight_sum = 0
    for creative_ms, weight, native_ms in rows:
        w = max(1, int(weight or 1))
        total += w * int(creative_ms or native_ms or DEFAULT_CREATIVE_MS)
        weight_sum += w
    return round(total / weight_sum)


async def _media_rows(db: AsyncSession, id_playlist: int) -> list[tuple[int, int]]:
    """[(frontières, durée_ms)] des items MÉDIA jouables d'une playlist.
    Un document multipage = (1 frontière, N pages × durée/page) — pas de pub
    entre les pages (`no_ad_before`, décision Ed 2026-07-16)."""
    rows = (await db.execute(
        select(CmsPlaylistItem.duration_ms, CmsMedia.duration_ms,
               CmsMedia.page_count, CmsPlaylistItem.doc_page_count)
        .join(CmsMedia, CmsMedia.id_media == CmsPlaylistItem.id_media)
        .where(
            CmsPlaylistItem.id_playlist == id_playlist,
            CmsPlaylistItem.item_type == "media",
            CmsMedia.is_deleted == False,  # noqa: E712
            CmsMedia.is_blocked == False,  # noqa: E712
        )
    )).all()
    out: list[tuple[int, int]] = []
    for item_ms, native_ms, media_pages, item_pages in rows:
        if media_pages:
            n = max(1, int(item_pages or media_pages))
            out.append((1, int(item_ms or DEFAULT_CREATIVE_MS) * n))
        else:
            out.append((1, int(item_ms or native_ms or DEFAULT_CREATIVE_MS)))
    return out


async def _playlist_loop(
    db: AsyncSession, id_playlist: int, cache: dict[int, tuple[int, int] | None]
) -> tuple[int, int] | None:
    """(B, H_ms) d'une playlist : frontières publicitaires utilisables + durée totale.

    Inclut les SOUS-playlists (rotation §0091) : mode all = tout le bloc inline,
    rotation = contribution par tour (K items, K × durée moyenne). Une sous-playlist
    `no_ads_inside` = UNE seule frontière (le bloc passe d'une traite — même règle
    que les pages d'un document). None si rien de jouable.
    """
    if id_playlist in cache:
        return cache[id_playlist]
    b_count = 0
    h_ms = 0
    for b, ms in await _media_rows(db, id_playlist):
        b_count += b
        h_ms += ms
    # Sous-playlists imbriquées (1 seul niveau — garde d'imbrication côté CRUD).
    children = (await db.execute(
        select(CmsPlaylist)
        .join(CmsPlaylistItem, CmsPlaylistItem.id_child_playlist == CmsPlaylist.id_playlist)
        .where(
            CmsPlaylistItem.id_playlist == id_playlist,
            CmsPlaylistItem.item_type == "sub_playlist",
            CmsPlaylist.is_deleted == False,  # noqa: E712
        )
    )).scalars().all()
    for child in children:
        crows = await _media_rows(db, child.id_playlist)
        if not crows:
            continue
        n = len(crows)
        total = sum(ms for _, ms in crows)
        if child.rotation_mode in ("one_sequential", "one_random") and n > 1:
            k = max(1, min(child.items_per_turn or 1, n))
            contrib_ms = round(total * k / n)
            contrib_b = k
        else:
            contrib_ms = total
            contrib_b = sum(b for b, _ in crows)
        b_count += 1 if child.no_ads_inside else contrib_b
        h_ms += contrib_ms
    out = (b_count, h_ms) if b_count else None
    cache[id_playlist] = out
    return out


def _max_sov_pct(home_items: int, home_ms: int, creative_ms: int) -> float:
    """SOV max réalisable ≈ B×d / (H + B×d) — 1 passage par frontière et par cycle."""
    if home_items <= 0 or home_ms <= 0:
        return 0.0
    ad_ms = home_items * creative_ms
    return round(ad_ms / (home_ms + ad_ms) * 100.0, 1)


async def feasibility_for_players(
    db: AsyncSession,
    id_org: int,
    pids: set[int],
    *,
    creative_duration_ms: int | None = None,
    now: datetime | None = None,
) -> dict | None:
    """{max_sov_pct, creative_duration_ms, players[pire→meilleur], unresolved_players}.

    None si aucun player ciblé n'a de boucle courante résolue (rien d'utile à dire —
    l'UI n'affiche alors pas de conseil plutôt qu'un conseil faux).
    """
    if not pids:
        return None
    # `now` explicite = instant imposé par l'appelant, appliqué tel quel à tout le lot.
    # Sinon (cas nominal) l'instant est résolu PAR FUSEAU d'écran plus bas (P2.2) : une
    # campagne qui vise New York et Paris n'a pas une seule « boucle courante ».
    pinned_now = now
    d = int(creative_duration_ms or DEFAULT_CREATIVE_MS)
    computed = sorted(pids)[:MAX_PLAYERS_COMPUTED]
    pid_set = set(computed)

    # ── Contexte batché (1 requête par table, pas par player) ────────────────
    groups_by_player: dict[int, set[int]] = {}
    for pid, gid in (await db.execute(
        select(CmsPlayerGroupMember.id_player, CmsPlayerGroupMember.id_group)
        .where(CmsPlayerGroupMember.id_player.in_(pid_set))
    )).all():
        groups_by_player.setdefault(pid, set()).add(gid)
    sitegroups_by_player: dict[int, set[int]] = {}
    for pid, sgid in (await db.execute(
        select(CmsPlayer.id_player, CmsSiteGroupMember.id_site_group)
        .join(CmsSiteGroupMember, CmsSiteGroupMember.id_site == CmsPlayer.id_site)
        .where(CmsPlayer.id_player.in_(pid_set))
    )).all():
        sitegroups_by_player.setdefault(pid, set()).add(sgid)
    site_by_player: dict[int, int | None] = {pid: sid for pid, sid in (await db.execute(
        select(CmsPlayer.id_player, CmsPlayer.id_site).where(CmsPlayer.id_player.in_(pid_set))
    )).all()}
    names = {pid: name for pid, name in (await db.execute(
        select(CmsPlayer.id_player, CmsPlayer.player_name)
        .where(CmsPlayer.id_player.in_(pid_set))
    )).all()}

    # Events content ACTIFS (préséance sync : event > schedule), priorité desc.
    events = (await db.execute(
        select(CmsEvent).where(
            CmsEvent.id_org == id_org,
            CmsEvent.status == "active",
            CmsEvent.event_kind == "content",
        ).order_by(CmsEvent.priority.desc(), CmsEvent.id_event)
    )).scalars().all()

    # Schedules content actifs + règles + cibles (matching en Python par player).
    schedules = (await db.execute(
        select(CmsSchedule).where(
            CmsSchedule.id_org == id_org,
            CmsSchedule.schedule_kind == "content",
            CmsSchedule.is_active == True,   # noqa: E712
            CmsSchedule.is_deleted == False,  # noqa: E712
        ).order_by(CmsSchedule.priority.desc(), CmsSchedule.id_schedule)
    )).scalars().all()
    sched_ids = [s.id_schedule for s in schedules]
    rules_by_sched: dict[int, list[CmsScheduleRule]] = {}
    targets_by_sched: dict[int, list[CmsScheduleTarget]] = {}
    if sched_ids:
        for r in (await db.execute(
            select(CmsScheduleRule).where(CmsScheduleRule.id_schedule.in_(sched_ids))
        )).scalars().all():
            rules_by_sched.setdefault(r.id_schedule, []).append(r)
        for t in (await db.execute(
            select(CmsScheduleTarget).where(CmsScheduleTarget.id_schedule.in_(sched_ids))
        )).scalars().all():
            targets_by_sched.setdefault(t.id_schedule, []).append(t)
    # Un schedule n'est retenu que s'il est actif MAINTENANT (règles + validité). Le temps
    # DÉPEND de l'écran (P2.2 — l'ancien commentaire affirmait le contraire) : on évalue une
    # fois par FUSEAU distinct, pas une fois par écran (un lot a typiquement 1 ou 2 fuseaux).
    tz_by_site: dict[int, str | None] = {sid: tz for sid, tz in (await db.execute(
        select(CmsSite.id_site, CmsSite.timezone)
        .where(CmsSite.id_site.in_({s for s in site_by_player.values() if s is not None}))
    )).all()} if any(site_by_player.values()) else {}
    _active_cache: dict[str | None, list[CmsSchedule]] = {}

    def _active_scheds_for(pid: int) -> list[CmsSchedule]:
        tz = (
            None if pinned_now
            else safe_tz_name(tz_by_site.get(site_by_player.get(pid)))  # type: ignore[arg-type]
        )
        if tz not in _active_cache:
            at = pinned_now or local_now(tz)
            _active_cache[tz] = [
                s for s in schedules
                if any(
                    schedule_active_at(
                        time_rule_from_schedule(r), s.valid_from, s.valid_until, at
                    )
                    for r in rules_by_sched.get(s.id_schedule, [])
                )
            ]
        return _active_cache[tz]

    def _sched_targets_match(
        s: CmsSchedule, pid: int, g: set[int], sg: set[int], id_site: int | None
    ) -> bool:
        for t in targets_by_sched.get(s.id_schedule, []):
            if t.target_type == "player" and t.target_id == pid:
                return True
            if t.target_type == "player_group" and t.target_id in g:
                return True
            if t.target_type == "site" and id_site is not None and t.target_id == id_site:
                return True
            if t.target_type == "site_group" and t.target_id in sg:
                return True
        return False

    # ── Résolution par player (cache par playlist) ───────────────────────────
    playlist_cache: dict[int, tuple[int, int] | None] = {}
    rows: list[dict] = []
    unresolved = 0
    for pid in computed:
        g = groups_by_player.get(pid, set())
        sg = sitegroups_by_player.get(pid, set())
        loop: tuple[int, int] | None = None
        for ev in events:
            if not event_target_matches(
                ev.target_config, pid, g, sg, id_site=site_by_player.get(pid)
            ):
                continue
            if ev.id_playlist:
                loop = await _playlist_loop(db, ev.id_playlist, playlist_cache)
            elif ev.id_media:
                media_ms = (await db.execute(
                    select(CmsMedia.duration_ms).where(CmsMedia.id_media == ev.id_media)
                )).scalar_one_or_none()
                dur = int(ev.duration_ms or media_ms or DEFAULT_CREATIVE_MS)
                loop = (1, dur)
            break  # l'event le plus prioritaire qui matche fait autorité (même sans contenu)
        if loop is None:
            for s in _active_scheds_for(pid):
                if s.id_playlist and _sched_targets_match(
                    s, pid, g, sg, site_by_player.get(pid)
                ):
                    loop = await _playlist_loop(db, s.id_playlist, playlist_cache)
                    break
        if loop is None:
            unresolved += 1
            continue
        b, h = loop
        rows.append({
            "id_player": pid,
            "player_name": names.get(pid),
            "max_sov_pct": _max_sov_pct(b, h, d),
            "home_items": b,
            "home_duration_ms": h,
        })

    if not rows:
        return None
    rows.sort(key=lambda r: (r["max_sov_pct"], r["id_player"]))
    return {
        "max_sov_pct": rows[0]["max_sov_pct"],
        "creative_duration_ms": d,
        "players": rows[:MAX_PLAYERS_RETURNED],
        "unresolved_players": unresolved + max(0, len(pids) - len(computed)),
    }


async def campaign_feasibility(
    db: AsyncSession,
    id_org: int,
    *,
    targets: list[Target],
    id_campaign: int | None = None,
    id_advertiser: int | None = None,
    now: datetime | None = None,
) -> dict | None:
    """Point d'entrée : cibles canoniques → players éligibles (opt-out + exclusion
    concurrentielle déduits, même tuyau que l'occupation) → plafond agrégé.
    d = durée moyenne pondérée des créatifs de `id_campaign` si fourni, sinon 10 s."""
    from app.services.campaign_inventory import campaign_eligible_players

    pids = await players_for_targets(db, id_org, targets) if targets else set()
    pids = await campaign_eligible_players(db, pids, id_advertiser)
    if not pids:
        return None
    d = await creative_avg_ms(db, id_campaign) if id_campaign else None
    return await feasibility_for_players(
        db, id_org, pids, creative_duration_ms=d, now=now)
