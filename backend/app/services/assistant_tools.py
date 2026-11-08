"""Outils de l'AI Assistant (§XXVII) — accès données pour l'agent LangGraph.

Tool 1 — `search_documentation` : recherche vectorielle (pgvector cosine top-K) dans la
documentation produit indexée, FILTRÉE PAR RÔLE (un VIEWER ne voit pas un chunk réservé
ORG_ADMIN). Les administrateurs (super-admin / org-admin) voient toute la doc.

Tool 2 — `query_tenant_data` : 5 intents prédéfinis en LECTURE SEULE sur les données du
tenant (RLS `id_org`). Ajouté en Task 7.

Séparation embed/recherche : `search_chunks` prend un vecteur déjà calculé (testable sans
Ollama) ; `search_documentation` ajoute l'embedding de la requête (via LiteLLM→Ollama).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.campaign import CmsCampaign
from app.services import pop_counting, rbac
from app.services.campaign_report import build_campaign_report
from app.services.embeddings import EmbeddingError, embed_text, to_pgvector
from app.services.targeting import event_target_entries

logger = logging.getLogger(__name__)

ADMIN_ROLES = {"CMS_SUPER_ADMIN", "CMS_ORG_ADMIN"}


def is_admin(roles: list[str]) -> bool:
    return bool(ADMIN_ROLES.intersection(roles))


def _safe_roles(roles: list[str]) -> list[str]:
    """Garde-fou : ne conserve que des role_keys plausibles ([A-Za-z0-9_])."""
    return [r for r in roles if r and all(c.isalnum() or c == "_" for c in r)]


async def search_chunks(
    db: AsyncSession,
    query_vector: list[float],
    *,
    roles: list[str],
    admin: bool,
    limit: int = 5,
) -> list[dict]:
    """Recherche cosine top-K dans cms_doc_chunks, filtrée par rôle. Vecteur déjà calculé."""
    rows = await db.execute(
        text(
            """
            SELECT id_chunk, source_file, title, section_anchor, content,
                   1 - (embedding <=> CAST(:qvec AS vector)) AS score
            FROM cms_doc_chunks
            WHERE embedding IS NOT NULL
              AND (
                    :admin
                    OR cardinality(roles) = 0
                    OR roles && CAST(:roles AS text[])
                  )
            ORDER BY embedding <=> CAST(:qvec AS vector)
            LIMIT :limit
            """
        ),
        {
            "qvec": to_pgvector(query_vector),
            "admin": admin,
            "roles": _safe_roles(roles),
            "limit": limit,
        },
    )
    return [dict(r._mapping) for r in rows]


async def search_documentation(
    db: AsyncSession,
    query: str,
    *,
    roles: list[str],
    limit: int = 5,
) -> list[dict]:
    """Embedde la requête puis cherche dans la doc. Dégradation gracieuse si Ollama KO."""
    if not query or not query.strip():
        return []
    try:
        vector = await asyncio.to_thread(embed_text, query)
    except EmbeddingError as exc:
        logger.info("search_documentation: embeddings indisponibles: %s", exc)
        return []
    return await search_chunks(db, vector, roles=roles, admin=is_admin(roles), limit=limit)


# ── Tool 2 — données tenant (LECTURE SEULE, RLS id_org) ───────────────────────

# Whitelist STRICTE des intents : l'agent ne peut RIEN faire d'autre que ces 5 lectures.
# Aucun chemin d'écriture (pas d'INSERT/UPDATE/DELETE), aucun SQL généré par le LLM.
TENANT_INTENTS = (
    "count_players_by_status",
    "list_active_schedules",
    "count_media_by_type",
    "list_recent_alerts",
    "get_network_health_score",
    # État du parc (Phase P.1)
    "list_players_status",
    "list_players_content_readiness",
    # Qui diffuse quoi (Phase 1)
    "list_playlists",
    "list_audio_baskets",
    "list_events",
    "list_schedules_with_targets",
    "list_player_groups",
    # Diagnostic écrans / HDMI / médiathèque (2026-07-08)
    "explain_player_power",
    "media_airtime",
    "list_hdmi_sessions",
    "list_unfiled_media",
    "list_never_played_media",
    # Détail playlist / sites (questions Jeanine sans réponse, 2026-07-09)
    "playlist_details",
    "list_sites",
    # Retail media §2.8 S5 (2026-07-10) — « où en est la campagne X ? » / rapport
    "campaign_status",
    "campaign_report",
)


async def _org_name_maps(db: AsyncSession, id_org: int) -> tuple[dict[int, str], dict[int, str]]:
    """(groupes, players) → {id: nom} pour résoudre les cibles en noms (events/schedules)."""
    groups = {
        r.id_group: r.group_name
        for r in await db.execute(
            text("SELECT id_group, group_name FROM cms_player_groups WHERE id_org = :org"),
            {"org": id_org},
        )
    }
    players = {
        r.id_player: r.player_name
        for r in await db.execute(
            text("SELECT id_player, player_name FROM cms_players WHERE id_org = :org"),
            {"org": id_org},
        )
    }
    return groups, players


def _target_names(target_type: str, ids: list, groups: dict, players: dict) -> list[str]:
    if target_type == "org":
        return ["toute l'organisation"]
    src = groups if target_type in ("group", "player_group") else players
    return [src.get(i, f"#{i}") for i in (ids or [])]


async def query_tenant_data(
    db: AsyncSession,
    id_org: int,
    intent: str,
    filters: dict | None = None,
    id_user: int | None = None,
) -> dict:
    """Exécute un intent prédéfini en lecture seule, scoping `id_org` explicite + RLS.

    Renvoie toujours un dict (jamais d'exception propagée à l'agent). Un intent hors
    whitelist → `{"error": ...}` sans toucher la base. `id_user` ne sert qu'aux intents
    gatés par une permission (campaign_report → campaigns:report, montants €).
    """
    if intent not in TENANT_INTENTS:
        return {"error": f"intent inconnu : {intent}", "allowed": list(TENANT_INTENTS)}
    p = {"org": id_org}

    if intent == "count_players_by_status":
        rows = await db.execute(
            text(
                "SELECT status, count(*) AS n FROM cms_players "
                "WHERE id_org = :org GROUP BY status ORDER BY n DESC"
            ),
            p,
        )
        by = {r.status: r.n for r in rows}
        return {"intent": intent, "by_status": by, "total": sum(by.values())}

    if intent == "list_active_schedules":
        rows = await db.execute(
            text(
                "SELECT schedule_name, priority, valid_from, valid_until FROM cms_schedules "
                "WHERE id_org = :org AND is_active = true AND is_deleted = false "
                "  AND (valid_from IS NULL OR valid_from <= current_date) "
                "  AND (valid_until IS NULL OR valid_until >= current_date) "
                "ORDER BY priority DESC, schedule_name LIMIT 50"
            ),
            p,
        )
        items = [
            {
                "name": r.schedule_name,
                "priority": r.priority,
                "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                "valid_until": r.valid_until.isoformat() if r.valid_until else None,
            }
            for r in rows
        ]
        return {"intent": intent, "count": len(items), "schedules": items}

    if intent == "count_media_by_type":
        rows = await db.execute(
            text(
                "SELECT media_type, count(*) AS n FROM cms_media "
                "WHERE id_org = :org AND is_deleted = false GROUP BY media_type ORDER BY n DESC"
            ),
            p,
        )
        by = {r.media_type: r.n for r in rows}
        return {"intent": intent, "by_type": by, "total": sum(by.values())}

    if intent == "list_recent_alerts":
        # Pas de table d'alertes dédiée : on dérive les anomalies opérationnelles des players
        # (hors-ligne ou disque saturé). Lecture seule.
        rows = await db.execute(
            text(
                "SELECT player_name, status, last_seen_at, disk_usage FROM cms_players "
                "WHERE id_org = :org AND (status <> 'online' OR disk_usage >= 90) "
                "ORDER BY last_seen_at NULLS FIRST LIMIT 50"
            ),
            p,
        )
        alerts = []
        for r in rows:
            if r.status != "online":
                issue = f"player hors-ligne (statut: {r.status})"
            else:
                issue = f"disque saturé ({r.disk_usage}%)"
            alerts.append(
                {
                    "player": r.player_name,
                    "issue": issue,
                    "last_seen": r.last_seen_at.isoformat() if r.last_seen_at else None,
                }
            )
        return {"intent": intent, "count": len(alerts), "alerts": alerts}

    if intent == "list_players_status":
        # filters.site (optionnel) : restreint au site nommé — « quels players au site X ? »
        site_q = str((filters or {}).get("site", "")).strip()
        rows = await db.execute(
            text(
                "SELECT p.player_name, p.status, p.last_seen_at, p.disk_usage, "
                "  p.alert_reasons, p.capabilities->>'timezone' AS device_tz, "
                "  s.site_name, s.timezone AS site_tz, "
                "  (SELECT string_agg(g.group_name, ', ') "
                "   FROM cms_player_group_members m "
                "   JOIN cms_player_groups g ON g.id_group = m.id_group "
                "   WHERE m.id_player = p.id_player) AS groups "
                "FROM cms_players p "
                "LEFT JOIN cms_sites s ON s.id_site = p.id_site "
                "WHERE p.id_org = :org "
                + ("AND s.site_name ILIKE :site " if site_q else "")
                + "ORDER BY (p.status = 'online'), p.player_name LIMIT 200"
            ),
            {**p, **({"site": f"%{site_q}%"} if site_q else {})},
        )
        players = [
            {
                "player": r.player_name,
                "status": r.status,
                # « Veille programmée » = offline ATTENDU (écran éteint par le programme).
                "alert_reasons": r.alert_reasons or [],
                "last_seen": r.last_seen_at.isoformat() if r.last_seen_at else None,
                "disk_usage": r.disk_usage,
                "groups": r.groups,
                "site": r.site_name,
                "device_timezone": r.device_tz,
                "site_timezone": r.site_tz,
            }
            for r in rows
        ]
        offline = [pl for pl in players if pl["status"] != "online"]
        return {"intent": intent, "count": len(players),
                "offline_count": len(offline), "players": players}

    if intent == "list_players_content_readiness":
        from app.services.readiness import player_readiness
        rows = (await db.execute(
            text("SELECT id_player, player_name FROM cms_players "
                 "WHERE id_org = :org ORDER BY player_name LIMIT 50"),
            p,
        )).all()
        out = []
        for r in rows:
            rd = await player_readiness(db, r.id_player)
            missing = rd.get("summary", {}).get("missing", 0)
            reported = rd.get("reported", False)
            out.append({
                "player": r.player_name,
                "reported": reported,
                "up_to_date": bool(reported and missing == 0),
                "missing": missing,
                "overall_ready_at": rd.get("summary", {}).get("overall_ready_at"),
            })
        up = sum(1 for o in out if o["up_to_date"])
        return {"intent": intent, "count": len(out), "up_to_date_count": up, "players": out}

    if intent == "list_playlists":
        rows = await db.execute(
            text(
                "SELECT pl.playlist_name, "
                "  (SELECT count(*) FROM cms_playlist_items i "
                "   WHERE i.id_playlist = pl.id_playlist) AS items, "
                "  EXISTS(SELECT 1 FROM cms_schedules s WHERE s.id_playlist = pl.id_playlist "
                "    AND s.is_deleted = false AND s.is_active = true) AS scheduled "
                "FROM cms_playlists pl WHERE pl.id_org = :org AND pl.is_deleted = false "
                "ORDER BY pl.playlist_name LIMIT 200"
            ),
            p,
        )
        items = [{"name": r.playlist_name, "items": r.items, "scheduled": r.scheduled}
                 for r in rows]
        return {"intent": intent, "count": len(items), "playlists": items}

    if intent == "list_audio_baskets":
        rows = await db.execute(
            text(
                "SELECT b.basket_name, b.basket_type, "
                "  (SELECT count(*) FROM cms_audio_basket_items it "
                "   WHERE it.id_basket = b.id_basket) AS tracks, "
                "  (SELECT count(*) FROM cms_player_basket_config c "
                "   WHERE c.id_basket = b.id_basket AND c.is_active = true) AS players "
                "FROM cms_audio_baskets b WHERE b.id_org = :org "
                "ORDER BY b.basket_name LIMIT 200"
            ),
            p,
        )
        items = [{"name": r.basket_name, "type": r.basket_type,
                  "tracks": r.tracks, "players_assigned": r.players} for r in rows]
        return {"intent": intent, "count": len(items), "baskets": items}

    if intent == "list_events":
        groups, players = await _org_name_maps(db, id_org)
        rows = await db.execute(
            text(
                "SELECT e.event_name, e.status, e.event_kind, e.event_type, "
                "  pl.playlist_name, m.media_name, e.target_config "
                "FROM cms_events e "
                "LEFT JOIN cms_playlists pl ON pl.id_playlist = e.id_playlist "
                "LEFT JOIN cms_media m ON m.id_media = e.id_media "
                "WHERE e.id_org = :org AND e.status <> 'cancelled' "
                "ORDER BY e.status, e.event_name LIMIT 200"
            ),
            p,
        )
        events = []
        for r in rows:
            tc = r.target_config or {}
            events.append({
                "name": r.event_name,
                "status": r.status,
                "kind": r.event_kind,
                "type": r.event_type,
                "content": r.playlist_name or r.media_name,
                # Les deux formes de target_config (hétérogène = concaténation des entrées).
                "targets": [n for tt, tids in event_target_entries(tc)
                            for n in _target_names(tt, tids, groups, players)],
            })
        return {"intent": intent, "count": len(events), "events": events}

    if intent == "list_schedules_with_targets":
        groups, players = await _org_name_maps(db, id_org)
        rows = (await db.execute(
            text(
                "SELECT s.id_schedule, s.schedule_name, s.priority, s.is_active, "
                "  pl.playlist_name "
                "FROM cms_schedules s "
                "LEFT JOIN cms_playlists pl ON pl.id_playlist = s.id_playlist "
                "WHERE s.id_org = :org AND s.is_deleted = false "
                "ORDER BY s.priority DESC, s.schedule_name LIMIT 100"
            ),
            p,
        )).all()
        sched_ids = [r.id_schedule for r in rows]
        tgts_by_sched: dict[int, list[str]] = {}
        if sched_ids:
            trows = await db.execute(
                text("SELECT id_schedule, target_type, target_id FROM cms_schedule_targets "
                     "WHERE id_schedule = ANY(:ids)"),
                {"ids": sched_ids},
            )
            for tr in trows:
                src = groups if tr.target_type in ("group", "player_group") else players
                tgts_by_sched.setdefault(tr.id_schedule, []).append(
                    src.get(tr.target_id, f"{tr.target_type}#{tr.target_id}")
                )
        schedules = [
            {
                "name": r.schedule_name,
                "priority": r.priority,
                "is_active": r.is_active,
                "playlist": r.playlist_name,
                "targets": tgts_by_sched.get(r.id_schedule, []),
            }
            for r in rows
        ]
        return {"intent": intent, "count": len(schedules), "schedules": schedules}

    if intent == "list_player_groups":
        rows = await db.execute(
            text(
                "SELECT g.group_name, "
                "  (SELECT count(*) FROM cms_player_group_members m "
                "   WHERE m.id_group = g.id_group) AS members "
                "FROM cms_player_groups g WHERE g.id_org = :org "
                "ORDER BY g.group_name LIMIT 200"
            ),
            p,
        )
        groups = [{"name": r.group_name, "members": r.members} for r in rows]
        return {"intent": intent, "count": len(groups), "groups": groups}

    if intent == "explain_player_power":
        # « Pourquoi l'écran X est éteint / le player hors ligne ? » — croise le mode
        # d'alimentation, les fenêtres du site (mêmes calculs que le sync) et l'état courant.
        name = str((filters or {}).get("player", "")).strip()
        if not name:
            return {"error": "Préciser filters.player (nom du player)."}
        from sqlalchemy import select as _select

        from app.models.organization import CmsSite
        from app.models.player import CmsPlayer
        pls = (await db.execute(_select(CmsPlayer).where(
            CmsPlayer.id_org == id_org, CmsPlayer.player_name.ilike(f"%{name}%"),
        ))).scalars().all()
        if not pls:
            return {"error": f"Aucun player nommé « {name} »."}
        if len(pls) > 1:
            return {"error": f"Plusieurs players correspondent à « {name} »",
                    "candidates": [x.player_name for x in pls[:8]]}
        pl = pls[0]
        dc = pl.display_config or {}
        site = None
        if pl.id_site:
            site = (await db.execute(_select(CmsSite).where(
                CmsSite.id_site == pl.id_site))).scalar_one_or_none()
        out = {
            "intent": intent,
            "player": pl.player_name,
            "status": pl.status,
            "alert_reasons": pl.alert_reasons or [],
            # offline_scheduled = veille PROGRAMMÉE : hors ligne ATTENDU, pas un incident.
            "offline_is_expected": "offline_scheduled" in (pl.alert_reasons or []),
            "screen_controllable": dc.get("type") in ("rs232", "ip", "cec")
                                   or bool(dc.get("output_power_fallback")),
            "power_mode": (dc.get("power_schedule") or {}).get("mode", "follow_site"),
            "last_power_command": ({True: "power_on", False: "power_off"}
                                   .get(pl.last_power_state, "aucune")),
            "site": site.site_name if site else None,
            "site_auto_power_enabled": bool(site.auto_power_enabled) if site else False,
        }
        try:  # fenêtres d'allumage à venir (mêmes calculs que le payload de sync)
            from app.api.v1.endpoints.ws import _resolve_offline_power
            op = await _resolve_offline_power(db, pl, dc, site=site)
            if op is not None:
                out["power_windows_mode"] = op.get("mode")
                out["next_power_windows"] = (op.get("intervals") or [])[:3]
        except Exception:  # noqa: BLE001 — le diagnostic reste utilisable sans les fenêtres
            pass
        row = (await db.execute(text(
            "SELECT count(*) FROM cms_events WHERE id_org = :org AND status = 'active' "
            "AND keep_screens_on = true"), p)).scalar()
        out["active_keep_screens_on_events"] = row or 0
        return out

    if intent == "media_airtime":
        # Temps d'antenne d'un média (Proof of Play) : « la pub A est-elle passée ? combien ? »
        name = str((filters or {}).get("media", "")).strip()
        if not name:
            return {"error": "Préciser filters.media (nom du média)."}
        try:
            days = max(1, min(int((filters or {}).get("days") or 7), 90))
        except (TypeError, ValueError):
            days = 7
        mrows = (await db.execute(text(
            "SELECT id_media, media_name FROM cms_media WHERE id_org = :org "
            "AND is_deleted = false AND media_name ILIKE :q LIMIT 8"),
            {**p, "q": f"%{name}%"})).all()
        if not mrows:
            return {"error": f"Aucun média nommé « {name} »."}
        if len(mrows) > 1:
            return {"error": f"Plusieurs médias correspondent à « {name} »",
                    "candidates": [r.media_name for r in mrows]}
        mid = mrows[0].id_media
        q = {**p, "mid": mid, "days": days}
        tot = (await db.execute(text(
            "SELECT count(*) AS plays, coalesce(sum(duration_ms), 0) AS total_ms, "
            "count(*) FILTER (WHERE signature IS NOT NULL AND signature <> '') AS signed, "
            "min(played_at) AS first_play, max(played_at) AS last_play "
            "FROM cms_proof_of_play WHERE id_org = :org AND id_media = :mid "
            "AND played_at > now() - make_interval(days => :days) "
            "AND " + pop_counting.COUNTED_SQL), q)).one()
        per = (await db.execute(text(
            "SELECT pl.player_name, count(*) AS plays, coalesce(sum(pp.duration_ms),0) AS ms "
            "FROM cms_proof_of_play pp JOIN cms_players pl ON pl.id_player = pp.id_player "
            "WHERE pp.id_org = :org AND pp.id_media = :mid "
            "AND pp.played_at > now() - make_interval(days => :days) "
            "AND " + pop_counting.COUNTED_SQL_FOR("pp") + " "
            "GROUP BY pl.player_name ORDER BY ms DESC LIMIT 30"), q)).all()
        return {
            "intent": intent, "media": mrows[0].media_name, "period_days": days,
            "plays": tot.plays, "total_seconds": round((tot.total_ms or 0) / 1000),
            "signed_plays": tot.signed,
            "first_play": tot.first_play.isoformat() if tot.first_play else None,
            "last_play": tot.last_play.isoformat() if tot.last_play else None,
            "by_player": [{"player": r.player_name, "plays": r.plays,
                           "seconds": round(r.ms / 1000)} for r in per],
        }

    if intent == "list_hdmi_sessions":
        # Sessions d'entrée HDMI (audit) : qui a switché, quand, combien de temps, par où.
        try:
            days = max(1, min(int((filters or {}).get("days") or 7), 90))
        except (TypeError, ValueError):
            days = 7
        rows = (await db.execute(text(
            "SELECT a.created_at, a.action, a.detail FROM cms_audit_log a "
            "WHERE a.id_org = :org AND a.action IN ('hdmi_session', 'vod_hdmi_switch') "
            "AND a.created_at > now() - make_interval(days => :days) "
            "ORDER BY a.created_at DESC LIMIT 100"), {**p, "days": days})).all()
        _groups, players_map = await _org_name_maps(db, id_org)
        sessions = []
        for r in rows:
            d = r.detail or {}
            pid = d.get("id_player")
            sessions.append({
                "at": r.created_at.isoformat(),
                "kind": ("session terminée" if r.action == "hdmi_session"
                         else "déclenchement VOD"),
                "player": players_map.get(pid, f"#{pid}") if pid else None,
                "source": d.get("source") or d.get("mode"),
                "duration_seconds": (round(d["duration_ms"] / 1000)
                                     if d.get("duration_ms") else None),
            })
        return {"intent": intent, "period_days": days,
                "count": len(sessions), "sessions": sessions}

    if intent == "playlist_details":
        # « Donne-moi des infos sur la playlist X » : items ordonnés (média, type, durée),
        # durée totale, programmation (schedules actifs + cibles) et players en lecture.
        name = str((filters or {}).get("playlist", "")).strip()
        if not name:
            return {"error": "Préciser filters.playlist (nom de la playlist)."}
        plrows = (await db.execute(text(
            "SELECT id_playlist, playlist_name FROM cms_playlists WHERE id_org = :org "
            "AND is_deleted = false AND playlist_name ILIKE :q LIMIT 8"),
            {**p, "q": f"%{name}%"})).all()
        if not plrows:
            return {"error": f"Aucune playlist nommée « {name} »."}
        if len(plrows) > 1:
            return {"error": f"Plusieurs playlists correspondent à « {name} »",
                    "candidates": [r.playlist_name for r in plrows]}
        plid = plrows[0].id_playlist
        q = {**p, "pl": plid}
        items = (await db.execute(text(
            "SELECT m.media_name, m.media_type, i.zone_index, i.transition_type, "
            "  coalesce(i.duration_ms, m.duration_ms) AS duration_ms "
            "FROM cms_playlist_items i JOIN cms_media m ON m.id_media = i.id_media "
            "WHERE i.id_playlist = :pl ORDER BY i.zone_index, i.sort_order LIMIT 200"),
            q)).all()
        groups, players_map = await _org_name_maps(db, id_org)
        sites_map = {r.id_site: r.site_name for r in (await db.execute(text(
            "SELECT id_site, site_name FROM cms_sites WHERE id_org = :org"), p)).all()}
        sgroups_map = {r.id_site_group: r.group_name for r in (await db.execute(text(
            "SELECT id_site_group, group_name FROM cms_site_groups WHERE id_org = :org"), p)).all()}
        scheds = (await db.execute(text(
            "SELECT s.id_schedule, s.schedule_name, s.priority, s.is_active "
            "FROM cms_schedules s WHERE s.id_org = :org AND s.id_playlist = :pl "
            "AND s.is_deleted = false ORDER BY s.priority DESC LIMIT 20"), q)).all()
        sched_out = []
        for s in scheds:
            tgt = (await db.execute(text(
                "SELECT target_type, target_id FROM cms_schedule_targets "
                "WHERE id_schedule = :sid LIMIT 20"), {"sid": s.id_schedule})).all()
            names = []
            for t in tgt:
                if t.target_type == "player":
                    names.append(players_map.get(t.target_id, f"player #{t.target_id}"))
                elif t.target_type in ("group", "player_group"):
                    names.append(f"groupe {groups.get(t.target_id, f'#{t.target_id}')}")
                elif t.target_type == "site":
                    names.append(f"site {sites_map.get(t.target_id, f'#{t.target_id}')}")
                elif t.target_type == "site_group":
                    names.append(f"groupe de sites {sgroups_map.get(t.target_id, f'#{t.target_id}')}")
                else:
                    names.append(f"{t.target_type} #{t.target_id}" if t.target_id
                                 else t.target_type)
            sched_out.append({"schedule": s.schedule_name, "priority": s.priority,
                              "active": s.is_active, "targets": names})
        # « Qui la joue ? » via les PoP récents (30 min) — current_playlist_id n'est pas
        # alimenté par les players ; la preuve de diffusion est la source de vérité.
        playing = (await db.execute(text(
            "SELECT pl.player_name, pl.status, max(pp.played_at) AS last_play "
            "FROM cms_proof_of_play pp "
            "JOIN cms_players pl ON pl.id_player = pp.id_player "
            "WHERE pp.id_org = :org AND pp.id_playlist = :pl "
            "AND pp.played_at > now() - interval '30 minutes' "
            # Écran coupé = pas de diffusion (migr 0102) : un player qui tourne dans le
            # noir ne doit pas être annoncé comme diffusant la playlist.
            "AND " + pop_counting.COUNTED_SQL_FOR("pp") + " "
            "GROUP BY pl.player_name, pl.status ORDER BY pl.player_name LIMIT 50"), q)).all()
        main_ms = sum(i.duration_ms or 0 for i in items if i.zone_index == 0)
        return {
            "intent": intent, "playlist": plrows[0].playlist_name,
            "item_count": len(items),
            "loop_duration_seconds": round(main_ms / 1000),
            "items": [{"media": i.media_name, "type": i.media_type,
                       "zone": i.zone_index, "transition": i.transition_type,
                       "duration_seconds": (round(i.duration_ms / 1000)
                                            if i.duration_ms else None)} for i in items],
            "schedules": sched_out,
            "currently_playing_on": [{"player": r.player_name, "status": r.status,
                                      "last_play": r.last_play.isoformat()}
                                     for r in playing],
        }

    if intent == "list_sites":
        # « Combien de sites ? lesquels ? le site X est-il ouvert le dimanche ? » —
        # sites + parc rattaché + réglages clés (fuseau, NTP, auto-power) + HORAIRES
        # D'OUVERTURE (mêmes règles que l'auto-power : jour non défini = FERMÉ,
        # exception datée > férié > horaires hebdo — cf. site_hours.resolve_day).
        rows = (await db.execute(text(
            "SELECT s.id_site, s.site_name, s.address, s.country, s.timezone, "
            "  s.ntp_server, s.auto_power_enabled, s.power_lead_min, s.power_lag_min, "
            "  s.respect_holidays, s.holiday_region, "
            "  count(pl.id_player) AS players, "
            "  count(pl.id_player) FILTER (WHERE pl.status = 'online') AS online "
            "FROM cms_sites s LEFT JOIN cms_players pl ON pl.id_site = s.id_site "
            "WHERE s.id_org = :org "
            "GROUP BY s.id_site ORDER BY s.site_name LIMIT 100"), p)).all()
        unattached = (await db.execute(text(
            "SELECT count(*) FROM cms_players WHERE id_org = :org AND id_site IS NULL"),
            p)).scalar()
        hrows = (await db.execute(text(
            "SELECT h.id_site, h.weekday, h.is_closed, h.open_time, h.close_time "
            "FROM cms_site_hours h JOIN cms_sites s ON s.id_site = h.id_site "
            "WHERE s.id_org = :org ORDER BY h.weekday"), p)).all()
        hours_by_site: dict[int, dict[int, object]] = {}
        for h in hrows:
            hours_by_site.setdefault(h.id_site, {})[h.weekday] = h
        erows = (await db.execute(text(
            "SELECT e.id_site, e.date_from, e.date_to, e.kind, e.open_time, "
            "  e.close_time, e.label "
            "FROM cms_site_exceptions e JOIN cms_sites s ON s.id_site = e.id_site "
            "WHERE s.id_org = :org AND e.date_to >= CURRENT_DATE "
            "ORDER BY e.date_from LIMIT 50"), p)).all()
        exc_by_site: dict[int, list] = {}
        for e in erows:
            exc_by_site.setdefault(e.id_site, []).append(e)

        days_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

        def _day(h) -> str:
            # Aligné sur resolve_day : ligne absente / is_closed / horaire manquant = fermé.
            if h is None or h.is_closed or h.open_time is None or h.close_time is None:
                return "fermé"
            return f"{str(h.open_time)[:5]}-{str(h.close_time)[:5]}"

        return {
            "intent": intent, "count": len(rows),
            "players_without_site": unattached or 0,
            "opening_hours_note": ("Jour non listé/fermé = site fermé ce jour-là ; les "
                                   "exceptions datées puis les jours fériés (si respectés) "
                                   "priment sur les horaires hebdomadaires."),
            "sites": [{
                "name": r.site_name, "address": r.address, "country": r.country,
                "timezone": r.timezone, "ntp_server": r.ntp_server,
                "auto_power_enabled": r.auto_power_enabled,
                "power_margins_min": {"lead": r.power_lead_min, "lag": r.power_lag_min},
                "players": r.players, "players_online": r.online,
                "opening_hours": ({days_fr[d]: _day(hours_by_site[r.id_site].get(d))
                                   for d in range(7)}
                                  if r.id_site in hours_by_site else "non configurés"),
                "closed_on_public_holidays": (f"oui ({r.holiday_region})"
                                              if r.respect_holidays else "non"),
                "upcoming_exceptions": [{
                    "from": e.date_from.isoformat(), "to": e.date_to.isoformat(),
                    "kind": e.kind, "label": e.label,
                    "hours": (f"{str(e.open_time)[:5]}-{str(e.close_time)[:5]}"
                              if e.kind == "hours" else None),
                } for e in exc_by_site.get(r.id_site, [])[:10]],
            } for r in rows],
        }

    if intent == "list_unfiled_media":
        total = (await db.execute(text(
            "SELECT count(*) FROM cms_media WHERE id_org = :org AND is_deleted = false "
            "AND id_folder IS NULL"), p)).scalar()
        rows = (await db.execute(text(
            "SELECT media_name, media_type FROM cms_media WHERE id_org = :org "
            "AND is_deleted = false AND id_folder IS NULL "
            "ORDER BY created_at DESC LIMIT 30"), p)).all()
        return {"intent": intent, "count": total or 0,
                "media": [{"name": r.media_name, "type": r.media_type} for r in rows]}

    if intent in ("campaign_status", "campaign_report"):
        # Retail media §2.8 — résolution de la campagne par nom (façon playlist_details).
        # campaign_status sans filtre = vue d'ensemble de toutes les campagnes.
        # Portail annonceur (B1) : un user lié à un annonceur ne voit que SES campagnes
        # (même isolation que l'API — jamais celles des concurrents via l'assistant).
        adv_scope = None
        if id_user is not None:
            adv_scope = (await db.execute(text(
                "SELECT id_advertiser FROM cms_users WHERE id_user = :u"), {"u": id_user}
            )).scalar()
        name = str((filters or {}).get("campaign", "")).strip()
        params = {**p, **({"q": f"%{name}%"} if name else {}),
                  **({"adv": adv_scope} if adv_scope is not None else {})}
        camps = (await db.execute(text(
            "SELECT c.id_campaign, c.campaign_name, c.status, c.starts_on, c.ends_on, "
            "  c.daily_hours, c.sov_percent, c.pricing_model, c.priority, "
            "  a.advertiser_name "
            "FROM cms_campaigns c "
            "JOIN cms_advertisers a ON a.id_advertiser = c.id_advertiser "
            "WHERE c.id_org = :org AND c.is_deleted = false "
            + ("AND c.id_advertiser = :adv " if adv_scope is not None else "")
            + ("AND c.campaign_name ILIKE :q " if name else "")
            + "ORDER BY c.starts_on DESC LIMIT 50"),
            params)).all()

        today = date.today()

        def _eff(r) -> str:
            # Statut effectif — même règle que campaigns._effective_status
            if r.status != "approved":
                return r.status
            if today < r.starts_on:
                return "scheduled"
            if today > r.ends_on:
                return "completed"
            return "live"

        if not camps:
            return {"error": (f"Aucune campagne nommée « {name} »." if name
                              else "Aucune campagne retail media sur ce compte.")}
        if name and len(camps) > 1:
            return {"error": f"Plusieurs campagnes correspondent à « {name} »",
                    "candidates": [r.campaign_name for r in camps]}

        if intent == "campaign_status":
            if not name:  # vue d'ensemble
                return {"intent": intent, "count": len(camps), "campaigns": [{
                    "name": r.campaign_name, "advertiser": r.advertiser_name,
                    "status": _eff(r), "from": r.starts_on.isoformat(),
                    "until": r.ends_on.isoformat(),
                    "sov_percent": float(r.sov_percent),
                } for r in camps]}
            r = camps[0]
            q2 = {"cid": r.id_campaign}
            creatives = (await db.execute(text(
                "SELECT m.media_name, cc.status, cc.approval_status, cc.weight "
                "FROM cms_campaign_creatives cc "
                "JOIN cms_media m ON m.id_media = cc.id_media "
                "WHERE cc.id_campaign = :cid ORDER BY cc.sort_order LIMIT 50"), q2)).all()
            groups, players_map = await _org_name_maps(db, id_org)
            sites_map = {s.id_site: s.site_name for s in (await db.execute(text(
                "SELECT id_site, site_name FROM cms_sites WHERE id_org = :org"), p)).all()}
            sgroups_map = {r.id_site_group: r.group_name for r in (await db.execute(text(
                "SELECT id_site_group, group_name FROM cms_site_groups WHERE id_org = :org"), p)).all()}
            tnames = []
            for t in (await db.execute(text(
                    "SELECT target_type, target_id FROM cms_campaign_targets "
                    "WHERE id_campaign = :cid LIMIT 20"), q2)).all():
                if t.target_type == "org":
                    tnames.append("toute l'organisation")
                elif t.target_type == "site":
                    tnames.append(f"site {sites_map.get(t.target_id, f'#{t.target_id}')}")
                elif t.target_type == "site_group":
                    tnames.append(f"groupe de sites {sgroups_map.get(t.target_id, f'#{t.target_id}')}")
                elif t.target_type == "group":
                    tnames.append(f"groupe {groups.get(t.target_id, f'#{t.target_id}')}")
                elif t.target_type == "player":
                    tnames.append(players_map.get(t.target_id, f"player #{t.target_id}"))
                else:
                    tnames.append(t.target_type)
            return {
                "intent": intent, "campaign": r.campaign_name,
                "advertiser": r.advertiser_name, "status": _eff(r),
                "from": r.starts_on.isoformat(), "until": r.ends_on.isoformat(),
                "daily_hours": r.daily_hours,
                "sov_percent_sold": float(r.sov_percent),
                "pricing_model": r.pricing_model,
                "targets": tnames,
                "creatives": [{"media": c.media_name, "status": c.status,
                               "approval_status": c.approval_status,
                               "weight": c.weight} for c in creatives],
            }

        # campaign_report — montants € : réservé à qui a campaigns:report (comme l'API).
        if not name:
            return {"error": "Préciser filters.campaign (nom de la campagne)."}
        if id_user is None or not await rbac.check_permission(
                db, id_user, "campaigns", "report"):
            return {"error": "Permission campaigns:report requise pour consulter le "
                             "rapport annonceur d'une campagne."}
        camp_obj = (await db.execute(
            select(CmsCampaign).where(CmsCampaign.id_campaign == camps[0].id_campaign)
        )).scalar_one()
        try:
            tz = ZoneInfo(settings.SIGNFLOW_TZ)
        except (ZoneInfoNotFoundError, KeyError):
            tz = ZoneInfo("UTC")
        rep = await build_campaign_report(db, camp_obj, tz)
        return {
            "intent": intent,
            "campaign": rep["campaign"],
            "period": rep["period"],
            "totals": rep["totals"],
            "sov": rep["sov"],
            "amount": rep["amount"],
            "top_players": rep["per_player"][:5],
            "per_creative": rep["per_creative"][:10],
            "days_with_plays": len(rep["per_day"]),
        }

    if intent == "list_never_played_media":
        # Médias visuels jamais diffusés (aucune preuve PoP) — utile avant un ménage.
        rows = (await db.execute(text(
            "SELECT m.media_name, m.media_type, m.created_at FROM cms_media m "
            "WHERE m.id_org = :org AND m.is_deleted = false "
            "AND m.media_type IN ('video', 'image', 'document', 'html_package') "
            "AND NOT EXISTS (SELECT 1 FROM cms_proof_of_play pp "
            "                WHERE pp.id_media = m.id_media AND " + pop_counting.COUNTED_SQL_FOR("pp") + ") "
            "ORDER BY m.created_at LIMIT 100"), p)).all()
        return {"intent": intent, "count": len(rows),
                "media": [{"name": r.media_name, "type": r.media_type,
                           "uploaded_at": r.created_at.isoformat()} for r in rows]}

    # get_network_health_score
    row = (
        await db.execute(
            text(
                "SELECT count(*) AS total, "
                "       count(*) FILTER (WHERE status = 'online') AS online, "
                "       avg(disk_usage) AS avg_disk FROM cms_players WHERE id_org = :org"
            ),
            p,
        )
    ).one()
    total = row.total or 0
    online = row.online or 0
    if total == 0:
        return {"intent": intent, "score": None, "online_players": 0, "total_players": 0}
    score = round(100 * online / total)
    if row.avg_disk and row.avg_disk >= 85:  # pénalité légère si stockage globalement saturé
        score = max(0, score - 10)
    return {
        "intent": intent,
        "score": score,
        "online_players": online,
        "total_players": total,
    }
