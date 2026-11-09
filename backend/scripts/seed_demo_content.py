#!/usr/bin/env python3
"""Contenu de démonstration NEUTRE — pour essayer Vitrail ou refaire les captures du manuel.

Remplit l'organisation d'un org-admin existant via l'API REST (les vrais endpoints, donc les
vrais workers : vignettes, analyse des médias…) avec un réseau fictif complet : sites, players,
médias, modèle multi-zones, playlists, paniers audio, programmes, gouvernance, événement, VOD,
annonceurs, campagne et demande de validation.

Tout est GÉNÉRÉ sur place (images Pillow, vidéo et sons ffmpeg) : aucune photo, marque, musique
ou donnée réelle — le résultat peut être publié tel quel.

Usage (dans le conteneur backend, après bootstrap.py) :
    docker compose exec -T backend python3 /app/scripts/seed_demo_content.py [--email admin@…] [--lang en|fr]

Sans --email, le premier org-admin trouvé est utilisé. `--lang` choisit la langue des contenus
(noms, visuels générés) — `en` par défaut ; les captures du manuel français se font avec `fr`.
Le script n'est PAS idempotent : à lancer une fois sur une installation de démonstration.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
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
from app.services.media import upload_file  # noqa: E402

API = os.environ.get("SEED_API", "http://localhost:8000/api/v1")
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

BRAND = "Maison Aurore"  # enseigne FICTIVE

# Couleurs des visuels, communes aux deux langues (même rendu d'une série de captures à l'autre).
COLORS = [("#1E3A8A", "#2563EB"), ("#92400E", "#F59E0B"), ("#78350F", "#D97706"), ("#3F2A1D", "#8B5E3C"),
          ("#065F46", "#10B981"), ("#111827", "#374151"), ("#581C87", "#A855F7"), ("#9F1239", "#EF4444")]

# Tous les libellés visibles, par langue. Une clé absente d'une langue = KeyError immédiate,
# jamais un mélange silencieux des deux langues sur une capture.
TEXT = {
    "fr": {
        "visuals": [
            ("Bienvenue", "Bienvenue chez Maison Aurore", "Boulangerie · Café · Épicerie fine"),
            ("Petit-déjeuner", "Formule petit-déjeuner", "Café + viennoiserie — 4,50 €"),
            ("Pain du jour", "Le pain du jour", "Levain naturel, cuit sur place"),
            ("Carte des cafés", "Nos cafés", "Espresso · Cappuccino · Latte · Filtre"),
            ("Offre de saison", "Offre de saison", "-20 % sur les tartes aux fruits"),
            ("Horaires", "Horaires d'ouverture", "Lun–Sam 7h–20h · Dim 8h–13h"),
            ("Nouveautés", "Nouveau en magasin", "Épicerie fine et produits locaux"),
            ("Fidélité", "Carte fidélité", "Le 10e café offert"),
        ],
        "audio": ["Ambiance matin", "Ambiance après-midi", "Ambiance soir", "Jingle accueil"],
        "video_file": "Nouvelle collection", "video_title": "Nouvelle collection",
        "site_group": ("Région Nord", "Sites du nord"),
        "players": ["Vitrine Bastille", "Comptoir Bastille", "Vitrine Part-Dieu", "Caisse Part-Dieu",
                    "Vitrine Bordeaux", "Vitrine Lille"],
        "player_group": ("Vitrines", "Écrans de vitrine"),
        "gov": ("Siège", "Région Nord", "Région Sud"),
        "template": "Vitrine avec bandeau", "zones": ("Principal", "Colonne", "Bandeau"),
        "playlists": ("Matinée", "Journée", "Promotions"), "multizone": "Vitrine multi-zones",
        "baskets": ("Musique d'ambiance", "Jingles"),
        "schedules": ("Matinée vitrines", "Journée tous écrans", "Ambiance magasins"),
        "event": "Opération déstockage", "vod": "Film de la collection",
        "advertisers": ("Verger du Val", "Service marketing", "Brûlerie des Quais"),
        "campaign": "Jus pressés — printemps",
        "draft": "Promotion d'été (à valider)", "draft_note": "Merci de valider les visuels de la promotion.",
    },
    "en": {
        "visuals": [
            ("Welcome", "Welcome to Maison Aurore", "Bakery · Café · Delicatessen"),
            ("Breakfast", "Breakfast deal", "Coffee + pastry — €4.50"),
            ("Bread of the day", "Bread of the day", "Natural sourdough, baked on site"),
            ("Coffee menu", "Our coffees", "Espresso · Cappuccino · Latte · Filter"),
            ("Seasonal offer", "Seasonal offer", "20% off fruit tarts"),
            ("Opening hours", "Opening hours", "Mon–Sat 7am–8pm · Sun 8am–1pm"),
            ("New in store", "New in store", "Fine foods and local products"),
            ("Loyalty", "Loyalty card", "Your 10th coffee is on us"),
        ],
        "audio": ["Morning ambience", "Afternoon ambience", "Evening ambience", "Welcome jingle"],
        "video_file": "New collection", "video_title": "New collection",
        "site_group": ("North region", "Northern sites"),
        "players": ["Bastille window", "Bastille counter", "Part-Dieu window", "Part-Dieu checkout",
                    "Bordeaux window", "Lille window"],
        "player_group": ("Windows", "Shop-window screens"),
        "gov": ("Head office", "North region", "South region"),
        "template": "Window with ticker", "zones": ("Main", "Side", "Ticker"),
        "playlists": ("Morning", "All day", "Promotions"), "multizone": "Multi-zone window",
        "baskets": ("Background music", "Jingles"),
        "schedules": ("Morning windows", "All day, all screens", "In-store ambience"),
        "event": "Clearance sale", "vod": "Collection film",
        "advertisers": ("Val Orchard", "Marketing team", "Quayside Roasters"),
        "campaign": "Fresh juices — spring",
        "draft": "Summer promotion (to approve)", "draft_note": "Please approve the promotion visuals.",
    },
}
AUDIO_FREQ = [220, 247, 196, 523]
# Version AFFICHÉE par OS — celle de la dernière release, pour un parc qui a l'air à jour.
PLAYER_VERSION = {"linux": "1.5.27", "rpi": "1.6.23", "windows": "1.6.26", "android": "2.5.36",
                  "chromeos": "2.0.22"}
# Décodage vidéo tel qu'un player le remonte (sinon la carte affiche « Inconnu »).
DECODE = {"linux": "vaapi", "rpi": "v4l2", "windows": "d3d11", "android": "mediacodec",
          "chromeos": "chromium-native"}
PLAYERS_LAYOUT = [("linux", 0), ("rpi", 0), ("windows", 1), ("android", 1), ("linux", 2), ("chromeos", 3)]


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


def render_visual(title: str, subtitle: str, colors) -> Image.Image:
    img = _gradient((1920, 1080), *colors)
    d = ImageDraw.Draw(img)
    big = ImageFont.truetype(FONT_BOLD, 110)
    small = ImageFont.truetype(FONT, 56)
    brand = ImageFont.truetype(FONT_BOLD, 40)
    d.text((140, 380), title, font=big, fill="white")
    d.text((140, 540), subtitle, font=small, fill=(255, 255, 255, 220))
    d.text((140, 900), BRAND.upper(), font=brand, fill=(255, 255, 255))
    return img


def make_video(path: Path, title: str) -> None:
    # 10 s, 1080p : dégradé animé + titre — généré, aucune source externe.
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "gradients=s=1920x1080:c0=0x1E3A8A:c1=0x10B981:speed=0.02:d=10",
        "-vf", f"drawtext=fontfile={FONT_BOLD}:text='{BRAND} — {title}':"
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


async def _players_alive(players: list[tuple[int, str]], screens: list[Image.Image]) -> None:
    """Donne au parc fictif l'allure d'un parc vivant — démo seulement.

    Statut, version de la dernière release selon l'OS, IP, et une CAPTURE D'ÉCRAN : celle que le
    player remonterait (le visuel qu'il diffuse). Sans elle, la page Players affiche une icône
    grisée « Inconnu » partout. Écrite au même endroit que le vrai envoi d'un player
    (`screenshots/<id>/latest.png` + `last_screenshot_at`). Le dernier player reste HORS LIGNE,
    sans capture : un parc réel n'est jamais 100 % en ligne, et la page doit le montrer.
    """
    engine = create_async_engine(os.environ["DATABASE_WORKER_URL"])
    async with engine.begin() as conn:
        for n, (pid, os_) in enumerate(players):
            offline = n == len(players) - 1
            if not offline and screens:
                buf = io.BytesIO()
                screens[n % len(screens)].resize((960, 540)).save(buf, "PNG")
                await upload_file(buf.getvalue(), f"screenshots/{pid}/latest.png", "image/png")
            await conn.execute(text(
                "UPDATE cms_players SET status = :st, last_seen_at = now(), player_version = :v, "
                "ip_address = CAST(:ip AS inet), last_screenshot_at = CASE WHEN :shot THEN now() END, "
                "capabilities = CAST(:caps AS jsonb) "
                "WHERE id_player = :id"
            ), {"st": "offline" if offline else "online", "v": PLAYER_VERSION.get(os_, "1.0.0"),
                "ip": f"192.168.10.{20 + n}", "shot": not offline, "id": pid,
                "caps": json.dumps({"hw_decode": DECODE.get(os_, "vaapi"), "hw_decode_active": True})})
    await engine.dispose()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--lang", choices=sorted(TEXT), default="en")
    args = ap.parse_args()
    T = TEXT[args.lang]

    user = asyncio.run(_admin(args.email))
    token = create_access_token(user.id_user, extra={"org": user.id_org, "roles": ["CMS_ORG_ADMIN"],
                                                       "locale": user.locale or "en"})
    api = Api(token)
    print(f"Organisation #{user.id_org}, compte {user.email}, contenus en {args.lang}")
    work = Path(tempfile.mkdtemp(prefix="vitrail-demo-"))

    # ── Médias ────────────────────────────────────────────────────────────────────────
    print("Médias…")
    images, audios, rendered = [], [], []
    for (name, title, sub), colors in zip(T["visuals"], COLORS):
        img = render_visual(title, sub, colors)
        rendered.append(img)
        p = work / f"{name}.jpg"
        img.save(p, "JPEG", quality=88)
        m = api.post("/media/upload", files={"file": (p.name, p.read_bytes(), "image/jpeg")})
        if m:
            images.append(m["id_media"])
    vpath = work / f"{T['video_file']}.mp4"
    make_video(vpath, T["video_title"])
    video = api.post("/media/upload", files={"file": (vpath.name, vpath.read_bytes(), "video/mp4")})
    for name, freq in zip(T["audio"], AUDIO_FREQ):
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
    sg = api.post("/site-groups/", json={"group_name": T["site_group"][0], "description": T["site_group"][1]})
    if sg:
        for sid in sites[2:] + sites[:1]:
            api.post(f"/site-groups/{sg['id_site_group']}/sites", json={"id_site": sid})

    players: list[tuple[int, str]] = []
    for nm, (os_, site) in zip(T["players"], PLAYERS_LAYOUT):
        p = api.post("/players/", json={"player_name": nm, "player_os": os_,
                                        "id_site": sites[site] if site < len(sites) else None})
        if p:
            players.append((p["id_player"], os_))
    player_ids = [pid for pid, _ in players]
    grp = api.post("/player-groups/", json={"group_name": T["player_group"][0],
                                            "description": T["player_group"][1]})
    if grp:
        for pid in player_ids[::2]:
            api.post(f"/player-groups/{grp['id_group']}/players", json={"id_player": pid})

    # ── Gouvernance ───────────────────────────────────────────────────────────────────
    root = api.post("/governance/nodes", json={"node_name": T["gov"][0]})
    if root:
        api.post("/governance/nodes", json={"node_name": T["gov"][1], "parent_id": root["id_node"]})
        api.post("/governance/nodes", json={"node_name": T["gov"][2], "parent_id": root["id_node"]})

    # ── Modèle, playlists ─────────────────────────────────────────────────────────────
    print("Contenus…")
    z = T["zones"]
    tpl = api.post("/templates", json={"template_name": T["template"], "layout": {
        "layout_type": "custom", "canvas_width": 1920, "canvas_height": 1080, "zones": [
            {"index": 0, "x": 0, "y": 0, "w": 1440, "h": 900, "label": z[0]},
            {"index": 1, "x": 1440, "y": 0, "w": 480, "h": 900, "label": z[1]},
            {"index": 2, "x": 0, "y": 900, "w": 1920, "h": 180, "label": z[2]}]}})
    pls = []
    names = T["playlists"]
    for nm, ids in [(names[0], images[:4]), (names[1], images[2:8]),
                    (names[2], images[4:6] + ([video["id_media"]] if video else []))]:
        pl = api.post("/playlists", json={"playlist_name": nm})
        if pl:
            api.post(f"/playlists/{pl['id_playlist']}/items/bulk", json={"id_medias": ids})
            api.post(f"/playlists/{pl['id_playlist']}/publish")
            pls.append(pl["id_playlist"])
    if tpl:
        pl = api.post("/playlists", json={"playlist_name": T["multizone"], "id_template": tpl["id_template"]})
        if pl:
            for zi, mid in [(0, images[0]), (0, images[4]), (1, images[3]), (2, images[5])]:
                api.post(f"/playlists/{pl['id_playlist']}/items", json={"id_media": mid, "zone_index": zi})
            api.post(f"/playlists/{pl['id_playlist']}/publish")

    # ── Paniers audio ─────────────────────────────────────────────────────────────────
    music = api.post("/audio-baskets", json={"basket_name": T["baskets"][0], "basket_type": "music"})
    if music:
        api.post(f"/audio-baskets/{music['id_basket']}/items/bulk", json={"id_medias": audios[:3]})
    jingle = api.post("/audio-baskets", json={"basket_name": T["baskets"][1], "basket_type": "jingle"})
    if jingle and len(audios) > 3:
        api.post(f"/audio-baskets/{jingle['id_basket']}/items/bulk", json={"id_medias": audios[3:]})

    # ── Programmes, événement, VOD ────────────────────────────────────────────────────
    print("Diffusion…")
    week = [0, 1, 2, 3, 4, 5]
    sch = T["schedules"]
    if len(pls) >= 2 and grp:
        api.post("/schedules", json={"schedule_name": sch[0], "id_playlist": pls[0], "priority": 10,
                                     "rules": [{"rule_type": "weekly", "days_of_week": week,
                                                "time_start": "07:00:00", "time_end": "11:00:00"}],
                                     "targets": [{"target_type": "player_group", "target_id": grp["id_group"]}]})
        api.post("/schedules", json={"schedule_name": sch[1], "id_playlist": pls[1],
                                     "rules": [{"rule_type": "always"}],
                                     "targets": [{"target_type": "site", "target_id": s} for s in sites]})
    if music and sites:
        api.post("/schedules", json={"schedule_name": sch[2], "schedule_kind": "audio",
                                     "baskets": [{"id_basket": music["id_basket"], "mix_ratio": 100}],
                                     "rules": [{"rule_type": "always"}],
                                     "targets": [{"target_type": "site", "target_id": s} for s in sites]})
    if len(pls) >= 3:
        api.post("/events", json={"event_name": T["event"], "event_type": "manual",
                                  "id_playlist": pls[2], "priority": 50,
                                  "target_config": {"target_type": "org"}})
    if video and player_ids:
        api.post("/vod", json={"vod_name": T["vod"], "id_medias": [video["id_media"]],
                               "target_mode": "players", "id_players": player_ids[:2]})

    # ── Retail media ──────────────────────────────────────────────────────────────────
    print("Retail media…")
    a = T["advertisers"]
    adv = api.post("/advertisers/", json={"advertiser_name": a[0], "contact_name": a[1],
                                          "contact_email": "marketing@example.com"})
    api.post("/advertisers/", json={"advertiser_name": a[2], "contact_email": "contact@example.com"})
    if adv and images:
        today = date.today()
        camp = api.post("/campaigns/", json={
            "id_advertiser": adv["id_advertiser"], "campaign_name": T["campaign"],
            "starts_on": today.isoformat(), "ends_on": (today + timedelta(days=30)).isoformat(),
            "sov_percent": 15, "targets": [{"target_type": "org"}]})
        if camp:
            api.post(f"/campaigns/{camp['id_campaign']}/creatives", json={"id_media": images[4], "duration_ms": 10000})
    # Une validation porte sur un BROUILLON : playlist non publiée, soumise telle quelle.
    draft = api.post("/playlists", json={"playlist_name": T["draft"]})
    if draft and len(images) > 7:
        api.post(f"/playlists/{draft['id_playlist']}/items/bulk", json={"id_medias": [images[4], images[7]]})
        api.post("/approvals/", json={"resource_type": "playlist", "resource_id": draft["id_playlist"],
                                      "notes": T["draft_note"]})

    asyncio.run(_players_alive(players, rendered))
    print("Terminé.")


if __name__ == "__main__":
    main()
