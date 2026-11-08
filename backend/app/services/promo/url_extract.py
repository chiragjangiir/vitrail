"""Extraction des données produit depuis une page e-commerce (Phase 5, §8 du plan).

PUR (aucune I/O). Parse par ordre de fiabilité : JSON-LD (schema.org/Product) → Open Graph →
repli DOM (title/meta description). Sortie normalisée {name, brand, price, currency, image_url,
description} pour **pré-remplir** le formulaire promo — l'utilisateur valide et assume les
droits (cf. §8 juridique : aide à la saisie, jamais un crawl de masse).
"""

from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin

_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_META_RE = re.compile(r"<meta\b[^>]*?>", re.I)
_ATTR_RE = re.compile(r'([a-zA-Z:_-]+)\s*=\s*"([^"]*)"')
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

_FIELDS = ("name", "brand", "price", "currency", "image_url", "description")


def _clean(v) -> str | None:
    if v is None:
        return None
    s = unescape(str(v)).strip()
    return s or None


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def _iter_products(obj):
    """Rend les nœuds @type Product d'un objet JSON-LD (gère listes + @graph)."""
    if isinstance(obj, list):
        for it in obj:
            yield from _iter_products(it)
        return
    if not isinstance(obj, dict):
        return
    if "@graph" in obj:
        yield from _iter_products(obj["@graph"])
    t = obj.get("@type")
    types = t if isinstance(t, list) else [t]
    if any(isinstance(x, str) and x.lower() == "product" for x in types):
        yield obj


def _fill_from_ld(data: dict, node: dict) -> None:
    if data["name"] is None:
        data["name"] = _clean(node.get("name"))
    if data["description"] is None:
        data["description"] = _clean(node.get("description"))
    if data["brand"] is None:
        brand = node.get("brand")
        data["brand"] = _clean(brand.get("name")) if isinstance(brand, dict) else _clean(brand)
    if data["image_url"] is None:
        img = _first(node.get("image"))
        data["image_url"] = _clean(img.get("url")) if isinstance(img, dict) else _clean(img)
    offers = _first(node.get("offers"))
    if isinstance(offers, dict):
        if data["price"] is None:
            data["price"] = _clean(offers.get("price") or offers.get("lowPrice"))
        if data["currency"] is None:
            data["currency"] = _clean(offers.get("priceCurrency"))


def _parse_metas(html: str) -> dict:
    """{clé og/meta → contenu} (property ou name)."""
    out: dict = {}
    for tag in _META_RE.findall(html):
        attrs = dict(_ATTR_RE.findall(tag))
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key and "content" in attrs and key not in out:
            out[key] = _clean(attrs["content"])
    return out


def extract_product(html: str, base_url: str = "") -> dict:
    """Extrait les champs produit d'une page HTML (JSON-LD > OG > DOM)."""
    data = dict.fromkeys(_FIELDS)

    # 1) JSON-LD (le plus fiable)
    for block in _LD_RE.findall(html or ""):
        try:
            obj = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        for node in _iter_products(obj):
            _fill_from_ld(data, node)

    # 2) Open Graph / meta (comble les manques)
    m = _parse_metas(html or "")
    if data["name"] is None:
        data["name"] = m.get("og:title")
    if data["image_url"] is None:
        data["image_url"] = m.get("og:image") or m.get("og:image:secure_url")
    if data["description"] is None:
        data["description"] = m.get("og:description") or m.get("description")
    if data["price"] is None:
        data["price"] = m.get("product:price:amount") or m.get("og:price:amount")
    if data["currency"] is None:
        data["currency"] = m.get("product:price:currency") or m.get("og:price:currency")
    if data["brand"] is None:
        data["brand"] = m.get("product:brand") or m.get("og:brand")

    # 3) Repli DOM : <title>
    if data["name"] is None:
        mt = _TITLE_RE.search(html or "")
        if mt:
            data["name"] = _clean(mt.group(1))

    # Résout une image relative en URL absolue.
    if data["image_url"] and base_url:
        data["image_url"] = urljoin(base_url, data["image_url"])
    return data
