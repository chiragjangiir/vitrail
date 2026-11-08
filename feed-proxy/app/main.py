"""SignFlow Feed Proxy (§XXV.3) — agrégation des feeds socials / financiers / météo.

Isole les connecteurs qui ne sont pas de simples RSS : APIs OAuth sociales (Instagram, X,
LinkedIn, Facebook, TikTok — tokens dans Vault/env) et sources publiques (crypto via
CoinGecko, météo via Open-Meteo, bourse via Stooq). Tout est normalisé vers un FeedItem commun
que le worker `fetch_feed` du backend ingère dans `cms_feed_items`.

Contrat : `POST /proxy/feed {type, org_id, config}` → `{status, items:[...], note?}`.
Dégradation gracieuse (§25.3) : si une source est injoignable / sans credentials, on renvoie
`status != ok` avec `items: []` — le backend conserve alors les items déjà en base (pas d'écran
vide). Les connecteurs publics ne requièrent AUCUN compte ; les socials propriétaires renvoient
`needs_credentials` tant qu'aucun token OAuth n'est configuré (décision business : enregistrer une
app développeur par plateforme).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger("feed-proxy")

app = FastAPI(
    title="SignFlow Feed Proxy",
    version="0.2.0",
    description="Micro-service d'agrégation de flux (§XXV.3) — connecteurs socials/financiers/météo.",
    docs_url="/docs",
)

_UA = {"User-Agent": "SignFlow-FeedProxy/0.2 (+https://signflow)"}
_SOCIAL_TYPES = ("instagram", "facebook_page", "twitter_x", "linkedin", "tiktok")


class ProxyRequest(BaseModel):
    type: str
    org_id: int | None = None
    config: dict[str, Any] = {}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "feed-proxy"}


def _item(guid: str, **kw) -> dict:
    """FeedItem normalisé (mêmes clés que cms_feed_items + champs numériques data_chart)."""
    base = {
        "guid": str(guid)[:2000], "title": None, "description": None, "image_url": None,
        "link_url": None, "author": None, "published_at": None, "categories": None,
        "value_num": None, "value_unit": None, "change_pct": None, "series": None,
    }
    base.update(kw)
    return base


# ── Connecteurs PUBLICS (aucun compte / clé) ─────────────────────────────────

async def _crypto(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    """Cours crypto via CoinGecko (markets) — value_num=prix, change_pct=24 h, series=sparkline 7 j."""
    coins = cfg.get("coins") or (["bitcoin"] if not cfg.get("query") else [cfg["query"]])
    cur = (cfg.get("currency") or "usd").lower()
    resp = await client.get(
        "https://api.coingecko.com/api/v3/coins/markets",
        params={
            "vs_currency": cur, "ids": ",".join(coins), "sparkline": "true",
            "price_change_percentage": "24h", "order": "market_cap_desc",
        },
        headers=_UA,
    )
    resp.raise_for_status()
    out: list[dict] = []
    for c in resp.json() or []:
        spark = ((c.get("sparkline_in_7d") or {}).get("price")) or []
        # downsample ~32 points pour la sparkline
        if len(spark) > 32:
            step = len(spark) / 32.0
            spark = [spark[int(i * step)] for i in range(32)]
        out.append(_item(
            f"crypto:{c.get('id')}",
            title=c.get("name"), description=(c.get("symbol") or "").upper(),
            image_url=c.get("image"), link_url=f"https://www.coingecko.com/en/coins/{c.get('id')}",
            value_num=c.get("current_price"), value_unit=cur.upper(),
            change_pct=c.get("price_change_percentage_24h"),
            series=[round(float(x), 6) for x in spark] or None,
            published_at=datetime.now(timezone.utc).isoformat(),
        ))
    return out


async def _weather(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    """Météo via Open-Meteo (gratuit, sans clé). `location` (géocodé) ou `lat`/`lon`."""
    lat, lon = cfg.get("lat"), cfg.get("lon")
    place = cfg.get("location")
    if (lat is None or lon is None) and place:
        geo = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": place, "count": 1}, headers=_UA,
        )
        results = (geo.json() or {}).get("results") or []
        if results:
            lat, lon = results[0].get("latitude"), results[0].get("longitude")
            place = results[0].get("name") or place
    if lat is None or lon is None:
        return []
    resp = await client.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            "hourly": "temperature_2m", "forecast_days": 1,
        },
        headers=_UA,
    )
    resp.raise_for_status()
    data = resp.json() or {}
    cur = data.get("current", {})
    units = data.get("current_units", {})
    hourly = (data.get("hourly", {}) or {}).get("temperature_2m") or []
    series = [round(float(x), 1) for x in hourly[:24]] or None
    label = place or f"{lat:.2f},{lon:.2f}"
    now = datetime.now(timezone.utc).isoformat()
    out = [_item(
        f"weather:{label}:temp", title=f"{label} — temperature",
        description="Temperature", value_num=cur.get("temperature_2m"),
        value_unit=units.get("temperature_2m") or "°C", series=series, published_at=now,
    )]
    if cur.get("relative_humidity_2m") is not None:
        out.append(_item(f"weather:{label}:humidity", title=f"{label} — humidity",
                         description="Humidity", value_num=cur.get("relative_humidity_2m"),
                         value_unit=units.get("relative_humidity_2m") or "%", published_at=now))
    if cur.get("wind_speed_10m") is not None:
        out.append(_item(f"weather:{label}:wind", title=f"{label} — wind",
                         description="Wind", value_num=cur.get("wind_speed_10m"),
                         value_unit=units.get("wind_speed_10m") or "km/h", published_at=now))
    return out


async def _financial(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    """Cours bourse via Stooq (CSV public, sans clé). `query`/`account` = symbole(s) ex. 'aapl.us'."""
    syms = cfg.get("coins") or [s.strip() for s in (cfg.get("query") or cfg.get("account") or "").split(",") if s.strip()]
    if not syms:
        return []
    out: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    for sym in syms[:20]:
        try:
            resp = await client.get("https://stooq.com/q/l/",
                                    params={"s": sym, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                                    headers=_UA)
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()
            if len(lines) < 2:
                continue
            cols = lines[0].split(","); vals = lines[1].split(",")
            row = dict(zip(cols, vals))
            close = row.get("Close"); open_ = row.get("Open")
            if not close or close == "N/D":
                continue
            close_f = float(close)
            chg = None
            try:
                if open_ and open_ != "N/D":
                    chg = round((close_f - float(open_)) / float(open_) * 100, 2)
            except (ValueError, ZeroDivisionError):
                chg = None
            out.append(_item(
                f"fin:{sym}", title=sym.upper(), description="Stock",
                value_num=close_f, value_unit=(cfg.get("currency") or "").upper() or None,
                change_pct=chg, link_url=f"https://stooq.com/q/?s={sym}", published_at=now,
            ))
        except Exception as exc:  # noqa: BLE001
            logger.info("financial %s échec: %s", sym, exc)
    return out


# ── Connecteurs SOCIAUX (OAuth — Vault/env) ──────────────────────────────────

def _social_token(org_id: int | None, ftype: str) -> str | None:
    """Token OAuth d'une plateforme sociale pour une org. v1 = lookup env
    (`FEEDPROXY_<TYPE>_TOKEN[_<ORG>]`). Brancher HashiCorp Vault ici (hvac) en prod."""
    key = f"FEEDPROXY_{ftype.upper()}_TOKEN"
    return os.environ.get(f"{key}_{org_id}") or os.environ.get(key)


async def _social(client: httpx.AsyncClient, ftype: str, req: ProxyRequest) -> dict:
    """Connecteur social générique. Sans token → needs_credentials (dégradation gracieuse).
    Avec token → l'intégration de l'API plateforme reste à câbler (requiert app review/clé par
    plateforme — non validable sans compte développeur, cf. README/EVOLUTIONS)."""
    token = _social_token(req.org_id, ftype)
    if not token:
        return {"status": "needs_credentials", "items": [],
                "note": f"{ftype}: aucun token OAuth configuré (Vault/env). Enregistrer une app "
                        f"développeur {ftype} et fournir FEEDPROXY_{ftype.upper()}_TOKEN."}
    return {"status": "not_implemented", "items": [],
            "note": f"{ftype}: token présent mais connecteur API non câblé (nécessite l'app review "
                    f"de la plateforme — à compléter avec des credentials de test)."}


_PUBLIC = {"crypto": _crypto, "weather_widget": _weather, "financial": _financial}


@app.post("/proxy/feed")
async def proxy_feed(req: ProxyRequest) -> dict:
    ftype = req.type
    cfg = req.config or {}
    try:
        async with httpx.AsyncClient(timeout=float(cfg.get("timeout_s") or 15), follow_redirects=True) as client:
            if ftype in _PUBLIC:
                items = await _PUBLIC[ftype](client, cfg)
                return {"status": "ok", "items": items}
            if ftype in _SOCIAL_TYPES:
                return await _social(client, ftype, req)
            return {"status": "unsupported", "items": [], "note": f"type inconnu: {ftype}"}
    except httpx.HTTPError as exc:
        logger.warning("proxy_feed %s erreur réseau: %s", ftype, exc)
        return {"status": "error", "items": [], "note": f"{type(exc).__name__}: {str(exc)[:200]}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("proxy_feed %s échec", ftype)
        return {"status": "error", "items": [], "note": str(exc)[:200]}
