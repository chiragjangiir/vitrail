"""Catalogue international de sources d'actualité RSS pour l'AI Assistant (§XXVII v2).

Permet à l'agent de résoudre un nom de source (« BFM Info », « BBC », « CNN ») en une URL
RSS sans que l'utilisateur ait à la connaître. Couvre les pays majeurs par continent. Si la
source n'est pas au catalogue, l'agent demande l'URL exacte (jamais d'URL inventée).

Chaque entrée : clé canonique → {name, url, country, lang, aliases}. Le matching est
insensible à la casse sur le nom canonique ET les alias.
"""

from __future__ import annotations

# country = code ISO ; lang = locale de la source.
FEED_CATALOG: dict[str, dict] = {
    # ── Europe ────────────────────────────────────────────────────────────────
    "bfmtv": {"name": "BFMTV", "url": "https://www.bfmtv.com/rss/news-24-7/",
              "country": "FR", "lang": "fr", "aliases": ["bfm", "bfm info", "bfm tv"]},
    "france_info": {"name": "France Info", "url": "https://www.francetvinfo.fr/titres.rss",
                    "country": "FR", "lang": "fr", "aliases": ["franceinfo", "france info"]},
    "le_monde": {"name": "Le Monde", "url": "https://www.lemonde.fr/rss/une.xml",
                 "country": "FR", "lang": "fr", "aliases": ["lemonde", "monde"]},
    "lequipe": {"name": "L'Équipe", "url": "https://www.lequipe.fr/rss/actu_rss.xml",
                "country": "FR", "lang": "fr", "aliases": ["equipe", "l'equipe", "sport fr"]},
    "bbc_news": {"name": "BBC News", "url": "http://feeds.bbci.co.uk/news/rss.xml",
                 "country": "GB", "lang": "en", "aliases": ["bbc", "bbc news"]},
    "the_guardian": {"name": "The Guardian", "url": "https://www.theguardian.com/world/rss",
                     "country": "GB", "lang": "en", "aliases": ["guardian"]},
    "sky_news": {"name": "Sky News", "url": "https://feeds.skynews.com/feeds/rss/home.xml",
                 "country": "GB", "lang": "en", "aliases": ["sky", "sky news"]},
    "tagesschau": {"name": "Tagesschau", "url": "https://www.tagesschau.de/index~rss2.xml",
                   "country": "DE", "lang": "de", "aliases": ["tagesschau", "ard"]},
    "spiegel": {"name": "Der Spiegel", "url": "https://www.spiegel.de/schlagzeilen/tops/index.rss",
                "country": "DE", "lang": "de", "aliases": ["spiegel", "der spiegel"]},
    "ansa": {"name": "ANSA", "url": "https://www.ansa.it/sito/ansait_rss.xml",
             "country": "IT", "lang": "it", "aliases": ["ansa"]},
    "rainews": {"name": "Rai News", "url": "https://www.rainews.it/rss/tutti",
                "country": "IT", "lang": "it", "aliases": ["rai", "rai news"]},
    "el_pais": {"name": "El País",
                "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
                "country": "ES", "lang": "es", "aliases": ["el pais", "pais"]},
    "rtve": {"name": "RTVE", "url": "https://api2.rtve.es/rss/temas_noticias.xml",
             "country": "ES", "lang": "es", "aliases": ["rtve"]},
    # ── Amériques ─────────────────────────────────────────────────────────────
    "cnn": {"name": "CNN", "url": "http://rss.cnn.com/rss/edition.rss",
            "country": "US", "lang": "en", "aliases": ["cnn"]},
    "nyt": {"name": "The New York Times",
            "url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
            "country": "US", "lang": "en", "aliases": ["nyt", "new york times", "nytimes"]},
    "fox_news": {"name": "Fox News", "url": "https://moxie.foxnews.com/google-publisher/latest.xml",
                 "country": "US", "lang": "en", "aliases": ["fox", "fox news"]},
    "cbc": {"name": "CBC News", "url": "https://www.cbc.ca/cmlink/rss-topstories",
            "country": "CA", "lang": "en", "aliases": ["cbc"]},
    "g1": {"name": "G1 (Globo)", "url": "https://g1.globo.com/rss/g1/",
           "country": "BR", "lang": "pt", "aliases": ["g1", "globo"]},
    # ── Asie / Moyen-Orient / Océanie ─────────────────────────────────────────
    "nhk": {"name": "NHK", "url": "https://www.nhk.or.jp/rss/news/cat0.xml",
            "country": "JP", "lang": "ja", "aliases": ["nhk"]},
    "toi": {"name": "Times of India",
            "url": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
            "country": "IN", "lang": "en", "aliases": ["times of india", "toi"]},
    "al_jazeera": {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml",
                   "country": "QA", "lang": "en", "aliases": ["al jazeera", "aljazeera"]},
    "abc_au": {"name": "ABC News (Australia)",
               "url": "https://www.abc.net.au/news/feed/51120/rss.xml",
               "country": "AU", "lang": "en", "aliases": ["abc australia", "abc au"]},
}


def find_source(query: str) -> dict | None:
    """Résout un nom de source (canonique ou alias, insensible à la casse) → entrée, ou None."""
    q = (query or "").strip().lower()
    if not q:
        return None
    for key, entry in FEED_CATALOG.items():
        if q == key or q == entry["name"].lower() or q in [a.lower() for a in entry["aliases"]]:
            return entry
    # Match partiel : la requête est contenue dans le nom ou un alias.
    for entry in FEED_CATALOG.values():
        hay = [entry["name"].lower()] + [a.lower() for a in entry["aliases"]]
        if any(q in h or h in q for h in hay):
            return entry
    return None
