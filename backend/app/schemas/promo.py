from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Couleur de charte : hexadécimal seul. Refusée à la saisie (422) plutôt que nettoyée en silence —
# elle finit en CSS inline dans la page rendue par Chromium.
_HEX = r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"


class PromoSlotStyle(BaseModel):
    """Override de style d'un slot texte (Phase A). Valeurs **re-validées** au rendu (police ∈
    catalogue, couleur hex/thème, align enum, poids/taille bornés) → pas d'injection CSS."""
    font: str | None = None          # id de police (catalogue GET /promo/fonts)
    size_vh: float | None = None     # taille (vh) — sert de borne haute à l'auto-fit
    color: str | None = None         # hex #rrggbb / #rgb / #rrggbbaa, ou clé de thème
    weight: int | None = None        # graisse (snappée au poids embarqué le plus proche)
    align: str | None = None         # left | center | right


class PromoLayer(BaseModel):
    """Calque libre (Phase B) superposé au template. Valeurs **re-validées/sanitisées** au rendu
    (couleurs hex/none, police ∈ catalogue, nombres bornés) → pas d'injection CSS."""
    type: str                          # text | image | shape
    x: float = 10.0
    y: float = 10.0
    w: float = 30.0
    h: float = 20.0
    rotation: float = 0.0
    z: int = 0
    opacity: float = 1.0
    # texte
    text: str | None = None
    font: str | None = None            # id de police (catalogue)
    size_vh: float | None = None
    color: str | None = None
    weight: int | None = None
    align: str | None = None
    # image
    media_id: int | None = None
    fit: str | None = None             # contain | cover
    # forme
    shape: str | None = None           # rect | ellipse | line
    fill: str | None = None            # hex ou 'none'
    stroke: str | None = None          # hex ou 'none'
    stroke_width: float | None = None
    radius: float | None = None


class PromoInputs(BaseModel):
    """Saisie utilisateur du visuel promo (le contenu des mentions relève de sa responsabilité)."""
    slogan: str | None = None
    price: float | str | None = None
    original_price: float | str | None = None
    discount_pct: int | str | None = None
    currency: str | None = "EUR"
    mentions: str | None = None
    # Styling par slot (Phase A) : { slogan|price|original_price|mentions: PromoSlotStyle }.
    style_overrides: dict[str, PromoSlotStyle] | None = None
    # Calques libres (Phase B) superposés au template.
    layers: list[PromoLayer] | None = None


class PromoValidateRequest(BaseModel):
    template_id: str
    format: str = "16:9"
    inputs: PromoInputs = PromoInputs()


class PromoConformityError(BaseModel):
    field: str
    message: str


class PromoValidateResponse(BaseModel):
    valid: bool
    errors: list[PromoConformityError]


class PromoCutoutRequest(BaseModel):
    """Détourage produit : retire le fond d'une image et renvoie un PNG transparent."""
    source_media_id: int


class PromoBackgroundRequest(BaseModel):
    """Génère un fond promo par IA (FLUX) — propre, sans texte ni produit ni personne."""
    ambiance_id: str | None = None
    description: str | None = None
    focus: str | None = None          # left|right|top|bottom|center — zone à laisser vide
    format: str = "16:9"              # 16:9 | 9:16 → aspect ratio du fond
    name: str | None = None


class PromoExtractRequest(BaseModel):
    """Extraction des données produit depuis une URL e-commerce (aide à la saisie)."""
    url: str


class PromoExtractResponse(BaseModel):
    name: str | None = None
    brand: str | None = None
    price: str | None = None
    currency: str | None = None
    image_url: str | None = None
    description: str | None = None


class PromoImportImageRequest(BaseModel):
    """Importe une image externe (ex. photo produit d'une page) comme média."""
    url: str
    name: str | None = None


class PromoImageRequest(BaseModel):
    template_id: str
    format: str = "16:9"
    resolution: str = "fhd"          # fhd | 4k
    inputs: PromoInputs = PromoInputs()
    background_media_id: int | None = None
    product_media_id: int | None = None
    name: str | None = None
    # Annonceur pour lequel ce visuel est fait (P3.4) : sa charte l'emporte sur celle de l'org.
    # Absent = visuel de l'enseigne → charte de l'organisation.
    id_advertiser: int | None = None


class PromoVideoRequest(PromoImageRequest):
    """Vidéo promo ≤15 s : même composite, animé (Ken Burns + fade) par FFmpeg."""
    duration_s: float = 8.0          # borné 3..15 côté worker
    animation: str = "zoom_in"       # zoom_in | zoom_out | static


# ── Modèles promo réutilisables (Phase C) ──────────────────────────────────────────
class PromoSavedCreate(BaseModel):
    """Instantané nommé de l'état de l'éditeur (config = snapshot re-validé au rendu)."""
    name: str
    config: dict


class PromoSavedUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None


class PromoSavedRead(BaseModel):
    id_promo_template: int
    name: str
    config: dict
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PromoSavedListItem(BaseModel):
    id_promo_template: int
    name: str
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ── Chartes de marque (P3.4) ───────────────────────────────────────────────────────
class BrandKitUpsert(BaseModel):
    """Écriture d'une charte. Tout est facultatif sauf le nom : **une valeur absente signifie
    « la charte ne dit rien »**, et le thème du template garde alors la sienne."""
    kit_name: str = Field(min_length=1, max_length=120)
    accent: str | None = Field(default=None, pattern=_HEX)
    ink: str | None = Field(default=None, pattern=_HEX)
    paper: str | None = Field(default=None, pattern=_HEX)
    badge_bg: str | None = Field(default=None, pattern=_HEX)
    badge_ink: str | None = Field(default=None, pattern=_HEX)
    # Vérifiée contre le catalogue de l'org (built-in + custom) par l'endpoint → 422 si inconnue.
    font_family: str | None = Field(default=None, max_length=80)
    brand_name: str | None = Field(default=None, max_length=160)
    id_logo_media: int | None = None
    legal_mentions: str | None = None
    tone: str | None = Field(default=None, max_length=400)


class BrandKitRead(BrandKitUpsert):
    id_brand_kit: int
    id_advertiser: int | None = None
    advertiser_name: str | None = None
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
