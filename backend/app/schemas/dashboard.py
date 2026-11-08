"""Schémas du dashboard « Mission Control » (recompo 2026-07-18).

KPI cards (valeur courante + évolution hebdo + sparkline 8 jours, données réelles) et
fil d'activité récente (audit log). Tout est TENANT-SCOPED (RLS via l'org du compte).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class KpiCard(BaseModel):
    """Une carte KPI : chiffre courant + évolution vs 7 jours + petite courbe (8 points)."""

    key: str
    value: int
    # Variation en % entre aujourd'hui et il y a 7 jours (None si base 0 = incomparable).
    delta_pct: float | None = None
    # Série chronologique 8 points (le plus ancien → aujourd'hui) pour la sparkline.
    spark: list[int] = []


class DashboardSummary(BaseModel):
    generated_at: datetime
    players_online: KpiCard
    players_offline: KpiCard
    players_warning: KpiCard
    active_campaigns: KpiCard
    # value = nombre de preuves de diffusion sur les dernières 24 h.
    proof_of_play: KpiCard


class ActivityItem(BaseModel):
    """Une ligne du fil d'activité.

    ⚠️ Le champ `detail` de `cms_audit_log` n'est **volontairement pas exposé**. C'est un
    dictionnaire libre alimenté depuis une quarantaine d'endroits du code (~70 clés
    distinctes mesurées en production) ; le fil n'en affiche pas un octet. L'envoyer au
    navigateur, c'était publier par avance tout ce qu'un futur `detail={...}` un peu
    bavard y mettrait — sans qu'aucun écran ne le réclame (audit Dashboard 2026-07-28).
    Un besoin d'inspection passera par une liste blanche explicite, pas par le dict brut.
    """

    id: int
    action: str
    resource_type: str
    resource_id: str | None = None
    resource_name: str | None = None   # nom résolu de la ressource (None → le front garde "type #id")
    # True = la ressource n'existe plus, le nom vient du JOURNAL (seule trace qui lui survit).
    # L'écran l'annonce au lieu d'en faire un lien mort. Le dict `detail` reste non exposé :
    # seule la chaîne du nom en est extraite, côté serveur.
    resource_gone: bool = False
    user_name: str | None = None
    source: str = "cms"
    created_at: datetime


class ActivityFeed(BaseModel):
    items: list[ActivityItem] = []


class RecentMediaItem(BaseModel):
    id_media: int
    media_name: str
    media_type: str
    thumbnail_url: str | None = None


class MediaTypeGroup(BaseModel):
    media_type: str
    total: int
    items: list[RecentMediaItem] = []


class DashboardMedia(BaseModel):
    """Panneau latéral média : par type, total + jusqu'à 3 contenus récents."""

    groups: list[MediaTypeGroup] = []
