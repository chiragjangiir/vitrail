#!/usr/bin/env python3
"""Contenu de démonstration NEUTRE — pour essayer Vitrail ou refaire les captures du manuel.

Remplit l'organisation d'un org-admin existant via l'API REST (les vrais endpoints, donc les
vrais workers : vignettes, analyse des médias…) avec un réseau fictif complet : sites, players,
médias, modèle multi-zones, playlists, paniers audio, programmes, gouvernance, événement, VOD,
annonceurs, campagne et demande de validation.

Tout est GÉNÉRÉ sur place (images Pillow, vidéo et sons ffmpeg) : aucune photo, marque, musique
ou donnée réelle — le résultat peut être publié tel quel.

Usage (dans le conteneur backend, après bootstrap.py) :
    docker compose exec -T backend python3 /app/scripts/seed_demo_content.py [--email admin@…]

Sans --email, le premier org-admin trouvé est utilisé. Le script n'est PAS idempotent :
à lancer une fois sur une installation de démonstration.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "/app")

import httpx  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.models.role import CmsRole, CmsUserRoleAssignment  # noqa: E402
from app.models.user import CmsUser  # noqa: E402

API = os.environ.get("SEED_API", "http://localhost:8000/api/v1")
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

BRAND = "Maison Aurore"  # enseigne FICTIVE

VISUALS = [
    ("Bienvenue", "Bienvenue chez Maison Aurore", "Boulangerie · Café · Épicerie fine", ("#1E3A8A", "#2563EB")),
    ("Petit-déjeuner", "Formule petit-déjeuner", "Café + viennoiserie — 4,50 €", ("#92400E", "#F59E0B")),
    ("Pain du jour", "Le pain du jour", "Levain naturel, cuit sur place", ("#78350F", "#D97706")),
    ("Carte des cafés", "Nos cafés", "Espresso · Cappuccino · Latte · Filtre", ("#3F2A1D", "#8B5E3C")),
    ("Offre de saison", "Offre de saison", "-20 % sur les tartes aux fruits", ("#065F46", "#10B981")),
    ("Horaires", "Horaires d'ouverture", "Lun–Sam 7h–20h · Dim 8h–13h", ("#111827", "#374151")),
    ("Nouveautés", "Nouveau en magasin", "Épicerie fine et produits locaux", ("#581C87", "#A855F7")),
    ("Fidélité", "Carte fidélité", "Le 10e café offert", ("#9F1239", "#EF4444")),
]
AUDIO = [("Ambiance matin", 220), ("Ambiance après-midi", 247), ("Ambiance soir", 196), ("Jingle accueil", 523)]


def _gradient(size, c1, c2) -> Image.Image:
    w, h = size
    a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
    img = Image.new("RGB", size)
    px = ImageDraw.Draw(img)
    for x in range(w):
        t = x / (w - 1)
        px.line([(x, 0), (x, h)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    return img


def make_visual(path: Path, title: str, subtitle: str, colors) -> None:
    img = _gradient((1920, 1080), *colors)
    d = ImageDraw.Draw(img)
    big = ImageFont.truetype(FONT_BOLD, 110)
    small = ImageFont.truetype(FONT, 56)
    brand = ImageFont.truetype(FONT_BOLD, 40)
    d.text((140, 380), title, font=big, fill="white")
    d.text((140, 540), subtitle, font=small, fill=(255, 255, 255, 220))
    d.text((140, 900), BRAND.upper(), font=brand, fill=(255, 255, 255))
    img.save(path, "JPEG", quality=88)


def make_video(path: Path) -> None:
    # 10 s, 1080p : dégradé animé + titre — généré, aucune source externe.
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "gradients=s=1920x1080:c0=0x1E3A8A:c1=0x10B981:speed=0.02:d=10",
        "-vf", f"drawtext=fontfile={FONT_BOLD}:text='{BRAND} — Nouvelle collection':"
               "fontcolor=white:fontsize=90:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "10", str(path),
    ], check=True)


def make_audio(path: Path, freq: int) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration=20", "-af", "volume=0.3",
        "-c:a", "libmp3lame", "-b:a", "128k", str(path),
    ], check=True)


class Api:
    def __init__(self, token: str) -> None:
        self.c = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=120)

    def post(self, path: str, **kw):
        r = self.c.post(path, **kw)
        if r.status_code >= 300:
            print(f"  !! POST {path} -> {r.status_code} {r.text[:300]}")
            return None
        return r.json() if r.content else {}

    def get(self, path: str, **kw):
        r = self.c.get(path, **kw)
        return r.json() if r.status_code < 300 else None


async def _admin(email: str | None) -> CmsUser:
    engine = create_async_engine(os.environ["DATABASE_WORKER_URL"])
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        q = (select(CmsUser)
             .join(CmsUserRoleAssignment, CmsUserRoleAssignment.id_user == CmsUser.id_user)
             .join(CmsRole, CmsRole.id_role == CmsUserRoleAssignment.id_role)
             .where(CmsRole.role_key == "CMS_ORG_ADMIN", CmsUser.is_active.is_(True)))
        if email:
            q = q.where(CmsUser.email == email)
        user = (await db.execute(q.order_by(CmsUser.id_user).limit(1))).scalar_one_or_none()
    await engine.dispose()
    if user is None:
        raise SystemExit("Aucun org-admin actif trouvé — lancez d'abord bootstrap.py.")
    return user


async def _players_online(ids: list[int]) -> None:
    """Donne au parc fictif l'allure d'un parc vivant (statut, version, IP) — démo seulement."""
    engine = create_async_engine(os.environ["DATABASE_WORKER_URL"])
    async with engine.begin() as conn:
        for n, pid in enumerate(ids):
            await conn.execute(text(
                "UPDATE cms_players SET status = :st, last_seen_at = now(), "
                "player_version = :v, ip_address = CAST(:ip AS inet) WHERE id_player = :id"
            ), {"st": "offline" if n == len(ids) - 1 else "online",
                "v": "1.6.25", "ip": f"192.168.10.{20 + n}", "id": pid})
    await engine.dispose()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    args = ap.parse_args()

    user = asyncio.run(_admin(args.email))
    token = create_access_token(user.id_user, extra={"org": user.id_org, "roles": ["CMS_ORG_ADMIN"],
                                                       "locale": user.locale or "en"})
    api = Api(token)
    print(f"Organisation #{user.id_org}, compte {user.email}")
    work = Path(tempfile.mkdtemp(prefix="vitrail-demo-"))

    # ── Médias ────────────────────────────────────────────────────────────────────────
    print("Médias…")
    images, audios = [], []
    for name, title, sub, colors in VISUALS:
        p = work / f"{name}.jpg"
        make_visual(p, title, sub, colors)
        m = api.post("/media/upload", files={"file": (p.name, p.read_bytes(), "image/jpeg")})
        if m:
            images.append(m["id_media"])
    vpath = work / "Nouvelle collection.mp4"
    make_video(vpath)
    video = api.post("/media/upload", files={"file": (vpath.name, vpath.read_bytes(), "video/mp4")})
    for name, freq in AUDIO:
        p = work / f"{name}.mp3"
        make_audio(p, freq)
        m = api.post("/media/upload", files={"file": (p.name, p.read_bytes(), "audio/mpeg")})
        if m:
            audios.append(m["id_media"])
    time.sleep(20)  # laisse les workers produire vignettes et métadonnées

    # ── Sites, groupes, players ───────────────────────────────────────────────────────
    print("Parc…")
    sites = []
    for nm, city, lat, lon, num in [("Paris Bastille", "Paris", 48.853, 2.369, "001"),
                                    ("Lyon Part-Dieu", "Lyon", 45.760, 4.859, "002"),
                                    ("Bordeaux Centre", "Bordeaux", 44.841, -0.574, "003"),
                                    ("Lille Grand-Place", "Lille", 50.637, 3.063, "004")]:
        s = api.post("/sites", json={"site_name": nm, "address": city, "country": "FR",
                                     "site_number": num, "latitude": lat, "longitude": lon,
                                     "timezone": "Europe/Paris"})
        if s:
            sites.append(s["id_site"])
    sg = api.post("/site-groups/", json={"group_name": "Région Nord", "description": "Sites du nord"})
    if sg:
        for sid in sites[2:] + sites[:1]:
            api.post(f"/site-groups/{sg['id_site_group']}/sites", json={"id_site": sid})

    players = []
    for nm, os_, site in [("Vitrine Bastille", "linux", 0), ("Comptoir Bastille", "rpi", 0),
                          ("Vitrine Part-Dieu", "windows", 1), ("Caisse Part-Dieu", "android", 1),
                          ("Vitrine Bordeaux", "linux", 2), ("Vitrine Lille", "chromeos", 3)]:
        p = api.post("/players/", json={"player_name": nm, "player_os": os_,
                                        "id_site": sites[site] if site < len(sites) else None})
        if p:
            players.append(p["id_player"])
    grp = api.post("/player-groups/", json={"group_name": "Vitrines", "description": "Écrans de vitrine"})
    if grp:
        for pid in players[::2]:
            api.post(f"/player-groups/{grp['id_group']}/players", json={"id_player": pid})

    # ── Gouvernance ───────────────────────────────────────────────────────────────────
    root = api.post("/governance/nodes", json={"node_name": "Siège"})
    if root:
        api.post("/governance/nodes", json={"node_name": "Région Nord", "parent_id": root["id_node"]})
        api.post("/governance/nodes", json={"node_name": "Région Sud", "parent_id": root["id_node"]})

    # ── Modèle, playlists ─────────────────────────────────────────────────────────────
    print("Contenus…")
    tpl = api.post("/templates", json={"template_name": "Vitrine avec bandeau", "layout": {
        "layout_type": "custom", "canvas_width": 1920, "canvas_height": 1080, "zones": [
            {"index": 0, "x": 0, "y": 0, "w": 1440, "h": 900, "label": "Principal"},
            {"index": 1, "x": 1440, "y": 0, "w": 480, "h": 900, "label": "Colonne"},
            {"index": 2, "x": 0, "y": 900, "w": 1920, "h": 180, "label": "Bandeau"}]}})
    pls = []
    for nm, ids in [("Matinée", images[:4]), ("Journée", images[2:8]),
                    ("Promotions", images[4:6] + ([video["id_media"]] if video else []))]:
        pl = api.post("/playlists", json={"playlist_name": nm})
        if pl:
            api.post(f"/playlists/{pl['id_playlist']}/items/bulk", json={"id_medias": ids})
            api.post(f"/playlists/{pl['id_playlist']}/publish")
            pls.append(pl["id_playlist"])
    if tpl:
        pl = api.post("/playlists", json={"playlist_name": "Vitrine multi-zones",
                                          "id_template": tpl["id_template"]})
        if pl:
            for z, mid in [(0, images[0]), (0, images[4]), (1, images[3]), (2, images[5])]:
                api.post(f"/playlists/{pl['id_playlist']}/items", json={"id_media": mid, "zone_index": z})
            api.post(f"/playlists/{pl['id_playlist']}/publish")

    # ── Paniers audio ─────────────────────────────────────────────────────────────────
    music = api.post("/audio-baskets", json={"basket_name": "Musique d'ambiance", "basket_type": "music"})
    if music:
        api.post(f"/audio-baskets/{music['id_basket']}/items/bulk", json={"id_medias": audios[:3]})
    jingle = api.post("/audio-baskets", json={"basket_name": "Jingles", "basket_type": "jingle"})
    if jingle and len(audios) > 3:
        api.post(f"/audio-baskets/{jingle['id_basket']}/items/bulk", json={"id_medias": audios[3:]})

    # ── Programmes, événement, VOD ────────────────────────────────────────────────────
    print("Diffusion…")
    week = [0, 1, 2, 3, 4, 5]
    if len(pls) >= 2 and grp:
        api.post("/schedules", json={"schedule_name": "Matinée vitrines", "id_playlist": pls[0], "priority": 10,
                                     "rules": [{"rule_type": "weekly", "days_of_week": week,
                                                "time_start": "07:00:00", "time_end": "11:00:00"}],
                                     "targets": [{"target_type": "player_group", "target_id": grp["id_group"]}]})
        api.post("/schedules", json={"schedule_name": "Journée tous écrans", "id_playlist": pls[1],
                                     "rules": [{"rule_type": "always"}],
                                     "targets": [{"target_type": "site", "target_id": s} for s in sites]})
    if music and sites:
        api.post("/schedules", json={"schedule_name": "Ambiance magasins", "schedule_kind": "audio",
                                     "baskets": [{"id_basket": music["id_basket"], "mix_ratio": 100}],
                                     "rules": [{"rule_type": "always"}],
                                     "targets": [{"target_type": "site", "target_id": s} for s in sites]})
    if len(pls) >= 3:
        api.post("/events", json={"event_name": "Opération déstockage", "event_type": "manual",
                                  "id_playlist": pls[2], "priority": 50,
                                  "target_config": {"target_type": "org"}})
    if video and players:
        api.post("/vod", json={"vod_name": "Film de la collection", "id_medias": [video["id_media"]],
                               "target_mode": "players", "id_players": players[:2]})

    # ── Retail media ──────────────────────────────────────────────────────────────────
    print("Retail media…")
    adv = api.post("/advertisers/", json={"advertiser_name": "Verger du Val", "contact_name": "Service marketing",
                                          "contact_email": "marketing@example.com"})
    api.post("/advertisers/", json={"advertiser_name": "Brûlerie des Quais", "contact_email": "contact@example.com"})
    if adv and images:
        today = date.today()
        camp = api.post("/campaigns/", json={
            "id_advertiser": adv["id_advertiser"], "campaign_name": "Jus pressés — printemps",
            "starts_on": today.isoformat(), "ends_on": (today + timedelta(days=30)).isoformat(),
            "sov_percent": 15, "targets": [{"target_type": "org"}]})
        if camp:
            api.post(f"/campaigns/{camp['id_campaign']}/creatives", json={"id_media": images[4], "duration_ms": 10000})
    # Une validation porte sur un BROUILLON : playlist non publiée, soumise telle quelle.
    draft = api.post("/playlists", json={"playlist_name": "Promotion d'été (à valider)"})
    if draft and len(images) > 7:
        api.post(f"/playlists/{draft['id_playlist']}/items/bulk", json={"id_medias": [images[4], images[7]]})
        api.post("/approvals/", json={"resource_type": "playlist", "resource_id": draft["id_playlist"],
                                      "notes": "Merci de valider les visuels de la promotion."})

    asyncio.run(_players_online(players))
    print("Terminé.")


if __name__ == "__main__":
    main()
