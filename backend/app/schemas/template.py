from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ZoneConfig(BaseModel):
    index: int
    x: int
    y: int
    w: int
    h: int
    label: str = ""


class LayoutConfig(BaseModel):
    # full | split_h | split_v | sidebar_r | custom
    layout_type: str = "full"
    # Résolution du canvas (px). Les zones sont en px sur ce canvas ; le player les positionne
    # en % → un template s'adapte à tout écran de MÊME ratio (FHD↔4K) ; portrait/LED = ratio dédié.
    canvas_width: int = 1920
    canvas_height: int = 1080
    zones: list[ZoneConfig] = []


class TemplateCreate(BaseModel):
    template_name: str
    description: str | None = None
    layout: LayoutConfig
    # P3.6 — où s'affiche un spot de campagne sur un écran MULTI-ZONES (migr 0124).
    # `fullscreen` = le spot recouvre tout l'écran (seul mode cohérent avec la
    # tarification au SOV) · `zone` = il s'insère dans la zone principale, les autres
    # continuent (menu board). Sans effet sur un template mono-zone.
    campaign_placement: Literal["fullscreen", "zone"] = "fullscreen"
    # Gouvernance §XVIII (migr 0112) : nœud propriétaire. None = template d'organisation.
    id_governance_node: int | None = None


class TemplateUpdate(BaseModel):
    template_name: str | None = None
    description: str | None = None
    layout: LayoutConfig | None = None
    # P3.6 — où s'affiche un spot de campagne sur un écran MULTI-ZONES (migr 0124).
    # `fullscreen` = le spot recouvre tout l'écran (seul mode cohérent avec la
    # tarification au SOV) · `zone` = il s'insère dans la zone principale, les autres
    # continuent (menu board). Sans effet sur un template mono-zone.
    campaign_placement: Literal["fullscreen", "zone"] | None = None
    # `model_fields_set` distingue « non fourni » de « détaché (null) » — le second est
    # réservé à un admin d'un nœud PARENT (N2).
    id_governance_node: int | None = None


class TemplateRead(BaseModel):
    model_config = {"from_attributes": True}

    id_template: int
    id_org: int
    template_name: str
    description: str | None
    layout: dict
    preview_url: str | None
    campaign_placement: str = "fullscreen"
    id_governance_node: int | None = None
    # Gouverné par un nœud qu'on n'administre pas → toute mutation part en 403. Sans ce
    # drapeau, l'éditeur s'ouvrait en ÉCRITURE sur une maquette nationale : on déplaçait
    # ses zones et on ne l'apprenait qu'au clic « Enregistrer » (audit du menu Templates,
    # 2026-07-28). Calculé par la LISTE **et** par le DÉTAIL — ne le calculer que d'un côté
    # laisse le lien direct mentir, c'est le défaut corrigé pour les médias le matin même.
    governed_readonly: bool = False
    created_at: datetime
    updated_at: datetime
