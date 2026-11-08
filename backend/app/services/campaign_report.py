"""Retail Media S4 — rapport annonceur d'une campagne (§2.8, plan §4).

Agrège les Proof of Play (§XXIV, signés Ed25519) des créatifs de la campagne sur sa
période : passages (dont signés), temps d'antenne, joignabilité (players touchés vs
ciblés), SOV servi vs vendu (temps d'antenne créatifs / temps d'antenne TOTAL des
players ciblés), répartition par player / par jour / par créatif, et le montant
(flat/sov = prix vendu ; CPM indicatif = passages × cpm_rate / 1000 — v1 : 1 passage
= 1 impression, l'audience réelle attendra Quividi).

Aucune instrumentation player : tout sort de cms_proof_of_play (déjà émis pour chaque
item, créatifs compris — un créatif est un item média normal).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import CmsAdvertiser, CmsCampaign, CmsCampaignCreative, CmsCampaignTarget
from app.models.media import CmsMedia
from app.models.organization import CmsSite
from app.models.player import CmsPlayer
from app.models.pop import CmsProofOfPlay
from app.models.site_group import CmsSiteGroup, CmsSiteGroupMember
from app.services import pop_counting
from app.services.campaign_inventory import campaign_eligible_players
from app.services.targeting import Target, players_for_targets


# Ce qui n'a pas pu être vu n'est de l'antenne ni au numérateur (passages des créatifs)
# ni au dénominateur (antenne totale des players ciblés) du SOV servi.
# Définition unique : services/pop_counting.
#
# ⚠️ Les deux causes n'ont PAS le même effet sur le pourcentage, et c'est voulu :
#  · `screen_off` (migr 0102) coupe l'écran ENTIER — les deux termes baissent dans les
#    mêmes proportions, le POURCENTAGE reste juste, seuls les volumes absolus baissent ;
#  · `covered` (migr 0125) ne masque QUE les zones secondaires. Un spot n'est jamais
#    recouvert par un autre spot (l'injection ne vise que la zone 0) ⇒ le numérateur ne
#    bouge quasiment pas tandis que le dénominateur se dégonfle ⇒ **le SOV servi REMONTE**.
#    C'est exactement le défaut corrigé : le dénominateur gonflé faisait ressortir un SOV
#    sous-évalué, donc une fausse alerte de sous-diffusion visible par l'annonceur.
#    Seul cas où le numérateur bouge : un takeover VOD qui recouvre un spot — le spot n'a
#    alors réellement pas été vu, et la sous-diffusion qu'il signale est vraie.
_COUNTED = pop_counting.COUNTED


def _bounds(from_d: date, until_d: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[from 00:00, until+1 00:00) en heure locale — mêmes conventions que §24."""
    start = datetime.combine(from_d, time.min, tzinfo=tz)
    end = datetime.combine(until_d + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


async def build_campaign_report(
    db: AsyncSession,
    camp: CmsCampaign,
    tz: ZoneInfo,
    from_d: date | None = None,
    until_d: date | None = None,
) -> dict:
    """Payload du rapport annonceur. Période par défaut = [starts_on, min(ends_on, aujourd'hui)],
    bornable par `from_d`/`until_d` (rapport partiel en cours de campagne)."""
    today = datetime.now(tz).date()
    from_d = max(from_d or camp.starts_on, camp.starts_on)
    until_d = min(until_d or camp.ends_on, camp.ends_on, today)
    if until_d < from_d:
        until_d = from_d
    start, end = _bounds(from_d, until_d, tz)

    advertiser = (await db.execute(
        select(CmsAdvertiser.advertiser_name).where(
            CmsAdvertiser.id_advertiser == camp.id_advertiser)
    )).scalar_one_or_none()

    # Créatifs (tous — un créatif archivé en cours de campagne a quand même diffusé).
    creatives = (await db.execute(
        select(CmsCampaignCreative, CmsMedia.media_name)
        .join(CmsMedia, CmsMedia.id_media == CmsCampaignCreative.id_media)
        .where(CmsCampaignCreative.id_campaign == camp.id_campaign)
        .order_by(CmsCampaignCreative.sort_order, CmsCampaignCreative.id_creative)
    )).all()
    media_ids = {cr.id_media for cr, _ in creatives}
    media_names = {cr.id_media: name for cr, name in creatives}

    # Players ciblés (résolution canonique, opt-out exclu) — dénominateur du SOV servi.
    trows = (await db.execute(
        select(CmsCampaignTarget).where(CmsCampaignTarget.id_campaign == camp.id_campaign)
    )).scalars().all()
    targeted = await campaign_eligible_players(db, await players_for_targets(
        db, camp.id_org,
        [Target(target_type=t.target_type, target_id=t.target_id, tag_expr=t.tag_expr or {})
         for t in trows],
    ), camp.id_advertiser) if trows else set()

    empty = {
        "plays": 0, "signed_plays": 0, "airtime_ms": 0,
        "players_reached": 0, "players_targeted": len(targeted),
    }
    if not media_ids:
        per_player: list[dict] = []
        per_day: list[dict] = []
        per_creative: list[dict] = []
        totals = empty
        total_airtime_by_player: dict[int, int] = {}
        player_sites: dict[int, int | None] = {}
    else:
        pop_base = (
            select(
                CmsProofOfPlay.id_player,
                func.count().label("plays"),
                func.count(CmsProofOfPlay.signature).label("signed"),
                func.coalesce(func.sum(CmsProofOfPlay.duration_ms), 0).label("airtime"),
            )
            .where(
                CmsProofOfPlay.id_org == camp.id_org,
                CmsProofOfPlay.id_media.in_(media_ids),
                CmsProofOfPlay.played_at >= start,
                CmsProofOfPlay.played_at < end,
                _COUNTED,
            )
            .group_by(CmsProofOfPlay.id_player)
        )
        player_rows = (await db.execute(pop_base)).all()

        # Temps d'antenne TOTAL (tous médias) des players ciblés → dénominateur SOV servi.
        total_airtime_by_player = {}
        if targeted:
            for pid, total_ms in (await db.execute(
                select(CmsProofOfPlay.id_player,
                       func.coalesce(func.sum(CmsProofOfPlay.duration_ms), 0))
                .where(
                    CmsProofOfPlay.id_org == camp.id_org,
                    CmsProofOfPlay.id_player.in_(targeted),
                    CmsProofOfPlay.played_at >= start,
                    CmsProofOfPlay.played_at < end,
                    _COUNTED,
                )
                .group_by(CmsProofOfPlay.id_player)
            )).all():
                total_airtime_by_player[pid] = int(total_ms)

        player_names: dict[int, str] = {}
        player_sites: dict[int, int | None] = {}
        pids = [r.id_player for r in player_rows] + list(targeted)
        if pids:
            for pid, pname, psite in (await db.execute(
                select(CmsPlayer.id_player, CmsPlayer.player_name, CmsPlayer.id_site)
                .where(CmsPlayer.id_player.in_(set(pids))))).all():
                player_names[pid] = pname
                player_sites[pid] = psite

        per_player = []
        for r in sorted(player_rows, key=lambda r: -int(r.plays)):
            total_ms = total_airtime_by_player.get(r.id_player, 0)
            per_player.append({
                "id_player": r.id_player,
                "player_name": player_names.get(r.id_player) or f"#{r.id_player}",
                "id_site": player_sites.get(r.id_player),
                "plays": int(r.plays),
                "signed_plays": int(r.signed),
                "airtime_ms": int(r.airtime),
                "sov_served_pct": round(100.0 * int(r.airtime) / total_ms, 1)
                if total_ms else None,
            })

        # Série quotidienne (date locale — le rapport suit le fuseau de la plateforme).
        day_col = func.date(func.timezone(str(tz), CmsProofOfPlay.played_at))
        per_day = [
            {"date": d.isoformat(), "plays": int(n), "airtime_ms": int(ms)}
            for d, n, ms in (await db.execute(
                select(day_col, func.count(),
                       func.coalesce(func.sum(CmsProofOfPlay.duration_ms), 0))
                .where(
                    CmsProofOfPlay.id_org == camp.id_org,
                    CmsProofOfPlay.id_media.in_(media_ids),
                    CmsProofOfPlay.played_at >= start,
                    CmsProofOfPlay.played_at < end,
                    _COUNTED,
                )
                .group_by(day_col).order_by(day_col)
            )).all()
        ]

        per_creative = [
            {"id_media": mid, "media_name": media_names.get(mid) or f"#{mid}",
             "plays": int(n), "airtime_ms": int(ms)}
            for mid, n, ms in (await db.execute(
                select(CmsProofOfPlay.id_media, func.count(),
                       func.coalesce(func.sum(CmsProofOfPlay.duration_ms), 0))
                .where(
                    CmsProofOfPlay.id_org == camp.id_org,
                    CmsProofOfPlay.id_media.in_(media_ids),
                    CmsProofOfPlay.played_at >= start,
                    CmsProofOfPlay.played_at < end,
                    _COUNTED,
                )
                .group_by(CmsProofOfPlay.id_media)
                .order_by(func.count().desc())
            )).all()
        ]

        totals = {
            "plays": sum(p["plays"] for p in per_player),
            "signed_plays": sum(p["signed_plays"] for p in per_player),
            "airtime_ms": sum(p["airtime_ms"] for p in per_player),
            "players_reached": len(per_player),
            "players_targeted": len(targeted),
        }

    # ── Hiérarchie sites / groupes de sites (retour Ed #3 — grandes flottes) ──
    # per_site agrège per_player par site (SOV servi = antenne créatifs des players
    # du site / antenne TOTALE des players CIBLÉS du site) ; per_site_group agrège
    # les sites par groupe. Un site membre de plusieurs groupes est rattaché au
    # PREMIER (tri par nom) — jamais compté deux fois. Le frontend nest par id ;
    # sites hors groupe / players sans site restent adressables (id null).
    per_site: list[dict] = []
    per_site_group: list[dict] = []
    if per_player:
        site_ids_used = {p["id_site"] for p in per_player if p["id_site"]}
        site_names: dict[int, str] = {}
        if site_ids_used:
            site_names = dict((await db.execute(
                select(CmsSite.id_site, CmsSite.site_name)
                .where(CmsSite.id_site.in_(site_ids_used)))).all())

        denom_by_site: dict[int | None, int] = {}
        for pid in targeted:
            sid = player_sites.get(pid)
            denom_by_site[sid] = (denom_by_site.get(sid, 0)
                                  + total_airtime_by_player.get(pid, 0))

        site_agg: dict[int | None, dict] = {}
        for p in per_player:
            sid = p["id_site"]
            a = site_agg.setdefault(sid, {
                "plays": 0, "signed_plays": 0, "airtime_ms": 0, "players_reached": 0})
            a["plays"] += p["plays"]
            a["signed_plays"] += p["signed_plays"]
            a["airtime_ms"] += p["airtime_ms"]
            a["players_reached"] += 1
        for sid, a in site_agg.items():
            site_denom = denom_by_site.get(sid, 0)
            per_site.append({
                "id_site": sid,
                "site_name": site_names.get(sid) if sid else None,
                **a,
                "sov_served_pct": (round(100.0 * a["airtime_ms"] / site_denom, 1)
                                   if site_denom else None),
            })
        per_site.sort(key=lambda s: -s["plays"])

        if site_ids_used:
            site_to_group: dict[int, tuple[int, str]] = {}
            for sid, gid, gname in (await db.execute(
                select(CmsSiteGroupMember.id_site, CmsSiteGroup.id_site_group,
                       CmsSiteGroup.group_name)
                .join(CmsSiteGroup,
                      CmsSiteGroup.id_site_group == CmsSiteGroupMember.id_site_group)
                .where(CmsSiteGroup.id_org == camp.id_org,
                       CmsSiteGroupMember.id_site.in_(site_ids_used))
                .order_by(CmsSiteGroup.group_name, CmsSiteGroup.id_site_group)
            )).all():
                site_to_group.setdefault(sid, (gid, gname))
            group_agg: dict[int, dict] = {}
            for s in per_site:
                grp = site_to_group.get(s["id_site"]) if s["id_site"] else None
                if grp is None:
                    continue
                gid, gname = grp
                g = group_agg.setdefault(gid, {
                    "id_site_group": gid, "group_name": gname,
                    "plays": 0, "signed_plays": 0, "airtime_ms": 0,
                    "players_reached": 0, "site_ids": [], "_denom": 0})
                g["plays"] += s["plays"]
                g["signed_plays"] += s["signed_plays"]
                g["airtime_ms"] += s["airtime_ms"]
                g["players_reached"] += s["players_reached"]
                g["site_ids"].append(s["id_site"])
                g["_denom"] += denom_by_site.get(s["id_site"], 0)
            for g in group_agg.values():
                d = g.pop("_denom")
                g["sov_served_pct"] = (round(100.0 * g["airtime_ms"] / d, 1)
                                       if d else None)
                per_site_group.append(g)
            per_site_group.sort(key=lambda g: -g["plays"])

    # SOV servi global = antenne créatifs / antenne totale des players ciblés.
    denom = sum(total_airtime_by_player.values())
    sov_served = round(100.0 * totals["airtime_ms"] / denom, 1) if denom else None

    cpm_indicative = None
    if camp.cpm_rate is not None:
        cpm_indicative = round(totals["plays"] * float(camp.cpm_rate) / 1000.0, 2)

    # ── S2 AUDIO : spots servis vs ATTENDUS, rapportés aux heures d'ouverture ────────
    # Attendu = spots/h vendus × heures d'ouverture du site, par player et par jour
    # (décision Ed 16/07). v1 = horaires HEBDO seuls (sans exceptions/fériés) ; site
    # sans AUCUN horaire configuré = 24 h/j (pas d'auto-power) ; player sans site idem.
    # La fenêtre quotidienne de la campagne (daily_hours) borne les heures comptées.
    spots = None
    if camp.campaign_kind == "audio" and camp.spots_per_hour:
        from app.models.organization import CmsSiteHours
        from app.services.site_hours import DayHours, resolve_day, window_datetimes

        sites_of_targeted: dict[int, int | None] = {}
        if targeted:
            for pid, psite in (await db.execute(
                select(CmsPlayer.id_player, CmsPlayer.id_site)
                .where(CmsPlayer.id_player.in_(targeted))
            )).all():
                sites_of_targeted[pid] = psite
        site_ids = {s for s in sites_of_targeted.values() if s is not None}
        weekly_by_site: dict[int, dict[int, DayHours]] = {}
        if site_ids:
            for sid, wd, closed, ot, ct in (await db.execute(
                select(CmsSiteHours.id_site, CmsSiteHours.weekday, CmsSiteHours.is_closed,
                       CmsSiteHours.open_time, CmsSiteHours.close_time)
                .where(CmsSiteHours.id_site.in_(site_ids))
            )).all():
                weekly_by_site.setdefault(sid, {})[wd] = DayHours(
                    is_closed=closed, open_time=ot, close_time=ct)

        window_h = 24.0
        dh_cfg = camp.daily_hours or {}
        if dh_cfg.get("start") and dh_cfg.get("end"):
            try:
                sh, sm = map(int, dh_cfg["start"].split(":"))
                eh, em = map(int, dh_cfg["end"].split(":"))
                window_h = max(0.0, (eh * 60 + em - sh * 60 - sm) / 60.0)
            except (ValueError, TypeError):
                window_h = 24.0

        def _open_hours(sid: int | None, d: date) -> float:
            if sid is None or sid not in weekly_by_site:
                return 24.0
            dh = resolve_day(d, weekly_by_site[sid], [], False, "FR")
            if dh.is_closed:
                return 0.0
            wnd = window_datetimes(d, dh)
            if wnd is None:
                return 0.0
            return (wnd[1] - wnd[0]).total_seconds() / 3600.0

        expected = 0
        d = from_d
        while d <= until_d:
            for pid in targeted:
                h = min(_open_hours(sites_of_targeted.get(pid), d), window_h)
                expected += int(round(int(camp.spots_per_hour) * h))
            d += timedelta(days=1)
        spots = {
            "sold_per_hour": int(camp.spots_per_hour),
            "served": totals["plays"],
            "expected": expected,
            "served_ratio_pct": (round(100.0 * totals["plays"] / expected, 1)
                                 if expected else None),
        }

    return {
        "campaign": {
            "id_campaign": camp.id_campaign,
            "campaign_name": camp.campaign_name,
            "advertiser_name": advertiser,
            "status": camp.status,
            "starts_on": camp.starts_on.isoformat(),
            "ends_on": camp.ends_on.isoformat(),
            "daily_hours": camp.daily_hours,
            "sov_percent": float(camp.sov_percent),
            "campaign_kind": camp.campaign_kind,
            "spots_per_hour": (int(camp.spots_per_hour)
                               if camp.spots_per_hour is not None else None),
        },
        "period": {"from": from_d.isoformat(), "until": until_d.isoformat()},
        "totals": totals,
        "sov": {"sold_pct": float(camp.sov_percent), "served_pct": sov_served},
        "spots": spots,
        "amount": {
            "model": camp.pricing_model,
            "amount": float(camp.price_amount) if camp.price_amount is not None else None,
            "currency": camp.price_currency,
            "cpm_rate": float(camp.cpm_rate) if camp.cpm_rate is not None else None,
            "cpm_indicative": cpm_indicative,
        },
        "per_player": per_player,
        "per_site": per_site,
        "per_site_group": per_site_group,
        "per_day": per_day,
        "per_creative": per_creative,
        "creatives_count": len(creatives),
    }
