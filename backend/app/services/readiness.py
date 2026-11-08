"""Look-ahead Phase 3 — prévision de « sync-readiness » (ETA de diffusion).

Estime, par player, la DATE à laquelle il aura fini de télécharger le contenu programmé
à venir, compte tenu de ses contraintes de download (plafond de bande passante +
fenêtres horaires autorisées). Permet à l'UI d'afficher « ce programme sera diffusable
le … » et de signaler un contenu qui n'arrivera PAS à temps pour sa date de diffusion.

Partie PURE (`forecast_readiness`) sans I/O DB → testable unitairement ; l'orchestrateur
`player_readiness` résout le contenu via le noyau look-ahead (`upcoming_media`) + la taille
de la variante réellement servie + l'état caché remonté par le player.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import CmsMedia, CmsMediaRendition
from app.models.player import CmsPlayer
from app.services.player_timezone import player_tz_name
from app.services.prefetch import upcoming_media
from app.services.scheduling import local_now

# Borne de simulation : au-delà, on considère que le contenu n'arrive pas (fenêtres trop
# étroites / débit trop bas) → ready_at = None (non joignable dans un horizon raisonnable).
_SIM_HORIZON_DAYS = 400


def _hm(v) -> int | None:
    """"HH:MM" → minutes depuis minuit (None si invalide)."""
    try:
        h, m = str(v).split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def _parse_windows(windows) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for w in (windows or []):
        s, e = _hm((w or {}).get("start")), _hm((w or {}).get("end"))
        if s is not None and e is not None:
            out.append((s, e))
    return out


def _day_slices(d: date, windows: list[tuple[int, int]]) -> list[tuple[datetime, datetime]]:
    """Créneaux concrets [start, end] du jour `d`. Une fenêtre overnight (start>end) court
    de `d start` à `d+1 end` (attribuée à son jour de DÉBUT → pas de double comptage)."""
    slices = []
    for s, e in windows:
        start = datetime.combine(d, time(s // 60, s % 60))
        end = datetime.combine(d if s <= e else d + timedelta(days=1), time(e // 60, e % 60))
        slices.append((start, end))
    slices.sort()
    return slices


def _advance(cursor: datetime, dl_seconds: float, windows: list[tuple[int, int]]) -> datetime | None:
    """Avance `cursor` de `dl_seconds` de temps de download EFFECTIF (= passé DANS une
    fenêtre). Sans fenêtre = download continu. None si pas terminé dans l'horizon."""
    if dl_seconds <= 0:
        return cursor
    if not windows:
        return cursor + timedelta(seconds=dl_seconds)
    remaining = dl_seconds
    cur = cursor
    end_limit = cursor + timedelta(days=_SIM_HORIZON_DAYS)
    d = cursor.date()
    while cur < end_limit:
        for start, end in _day_slices(d, windows):
            if end <= cur:
                continue
            seg_start = max(cur, start)
            usable = (end - seg_start).total_seconds()
            if usable <= 0:
                continue
            if usable >= remaining:
                return seg_start + timedelta(seconds=remaining)
            remaining -= usable
            cur = end
        d += timedelta(days=1)
    return None


@dataclass(frozen=True)
class DownloadItem:
    key: object
    size_bytes: int
    play_at: datetime | None  # date de diffusion la plus proche (None = inconnue)


@dataclass(frozen=True)
class ReadinessEntry:
    key: object
    ready_at: datetime | None  # None = non joignable dans l'horizon ; == now si débit illimité
    on_time: bool              # ready_at <= play_at (ou play_at inconnu / illimité)
    network_bound: bool        # débit illimité → ETA non estimable (dépend du réseau)


def forecast_readiness(
    items: list[DownloadItem], bytes_per_sec: float, windows, now: datetime
) -> list[ReadinessEntry]:
    """Simule le download SÉRIE (file unique du player) des `items` (déjà ordonnés par
    priorité = play_at croissant) au débit `bytes_per_sec` à travers les `windows`.

    `bytes_per_sec` <= 0 = illimité → ready_at = now (network-bound, non estimable).
    Le curseur s'accumule d'un item à l'autre (un seul lien, téléchargements séquentiels).
    """
    wins = _parse_windows(windows)
    unlimited = not (bytes_per_sec and bytes_per_sec > 0)
    cursor = now
    out: list[ReadinessEntry] = []
    for it in items:
        if unlimited or not it.size_bytes:
            out.append(ReadinessEntry(it.key, now, True, unlimited))
            continue
        cursor_after = _advance(cursor, it.size_bytes / bytes_per_sec, wins)
        if cursor_after is None:
            out.append(ReadinessEntry(it.key, None, False, False))
            continue  # cursor inchangé : un item injoignable ne « consomme » pas la suite
        cursor = cursor_after
        on_time = it.play_at is None or cursor <= it.play_at
        out.append(ReadinessEntry(it.key, cursor, on_time, False))
    return out


async def _variant_size(db: AsyncSession, media: CmsMedia, target_height: int | None) -> int:
    """Taille (octets) de la variante réellement servie à ce player (rendition ou parent)."""
    from app.api.v1.endpoints.ws import _resolve_variant_key  # import local (évite le cycle)
    key = await _resolve_variant_key(db, media, target_height)
    if key == media.storage_key:
        return media.file_size_bytes or 0
    rend = (await db.execute(select(CmsMediaRendition).where(
        CmsMediaRendition.id_parent == media.id_media,
        CmsMediaRendition.storage_key == key,
    ))).scalar_one_or_none()
    return (rend.file_size_bytes if rend and rend.file_size_bytes else media.file_size_bytes) or 0


async def player_readiness(db: AsyncSession, id_player: int) -> dict:
    """Prévision de readiness d'un player : pour chaque média programmé à venir NON encore
    caché, estime sa date de disponibilité (ready_at) selon débit + fenêtres, et si elle
    arrive avant sa diffusion (play_at). Renvoie items triés + résumé."""
    from app.api.v1.endpoints.ws import _player_target_height  # import local (évite le cycle)

    player = (await db.execute(
        select(CmsPlayer).where(CmsPlayer.id_player == id_player)
    )).scalar_one_or_none()
    if not player:
        return {"reported": False, "items": [], "summary": {}}

    # Même horloge que le look-ahead qu'on prétend expliquer (P2.2) : la readiness compare
    # « quand ce média sera prêt » à « quand il passe », deux instants du fuseau de l'écran.
    now = local_now(await player_tz_name(db, id_player))
    upcoming = await upcoming_media(db, id_player, now)
    store = (player.capabilities or {}).get("store") or {}
    reported = bool(store)
    cached = set(store.get("cached_ids") or [])
    dc = player.display_config or {}
    # Débit effectif : plafond manuel s'il est posé, sinon débit MESURÉ remonté par le player
    # (opt-in `measure_bandwidth`), sinon illimité (ETA non estimable → network-bound).
    bw_kbps = dc.get("download_bandwidth_kbps") or 0
    measured_kbps = store.get("throughput_kbps") or 0
    if bw_kbps:
        effective_kbps, source = bw_kbps, "cap"
    elif measured_kbps:
        effective_kbps, source = measured_kbps, "measured"
    else:
        effective_kbps, source = 0, "unlimited"
    bytes_per_sec = float(effective_kbps) * 125 if effective_kbps else 0  # kbit/s → octets/s
    windows = dc.get("download_windows")

    target_height = await _player_target_height(db, player)

    # Médias à venir NON cachés (les cachés sont déjà prêts) → à télécharger, ordonnés par play_at.
    missing_ids = [mid for mid in upcoming if mid not in cached]
    medias = {m.id_media: m for m in (await db.execute(select(CmsMedia).where(
        CmsMedia.id_media.in_(missing_ids)
    ))).scalars().all()} if missing_ids else {}

    dl_items: list[DownloadItem] = []
    for mid in missing_ids:
        media = medias.get(mid)
        if not media:
            continue
        size = await _variant_size(db, media, target_height)
        dl_items.append(DownloadItem(key=mid, size_bytes=size, play_at=upcoming[mid]))
    dl_items.sort(key=lambda x: (x.play_at or now))

    forecast = forecast_readiness(dl_items, bytes_per_sec, windows, now)
    name_by_id = {mid: medias[mid].media_name for mid in medias}
    by_key = {f.key: f for f in forecast}

    items = []
    for it in dl_items:
        f = by_key[it.key]
        items.append({
            "id_media": it.key,
            "media_name": name_by_id.get(it.key),
            "size_bytes": it.size_bytes,
            "play_at": it.play_at.isoformat() if it.play_at else None,
            "ready_at": f.ready_at.isoformat() if f.ready_at else None,
            "on_time": f.on_time,
            "network_bound": f.network_bound,
        })

    late = [i for i in items if not i["on_time"]]
    ready_ats = [f.ready_at for f in forecast if f.ready_at is not None]
    overall_ready = max(ready_ats) if ready_ats else None
    return {
        "reported": reported,
        "bandwidth_kbps": bw_kbps or None,
        "measured_kbps": measured_kbps or None,
        "throughput_kbps": effective_kbps or None,   # débit retenu pour l'estimation
        "throughput_source": source,                  # cap | measured | unlimited
        "windows": windows or None,
        "summary": {
            "missing": len(items),
            "missing_bytes": sum(i["size_bytes"] for i in items),
            "late": len(late),
            "overall_ready_at": overall_ready.isoformat() if overall_ready else None,
            "network_bound": bool(dl_items) and not bytes_per_sec,
        },
        "items": items,
    }
