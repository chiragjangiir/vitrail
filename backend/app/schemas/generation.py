from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GenerateImageRequest(BaseModel):
    """Requête de génération d'image (§ génération de contenu — Phase 1)."""

    # Vide autorisé : les modèles d'ÉDITION (détourage) n'ont pas de prompt — l'endpoint
    # exige le prompt pour les autres modèles (refus 422 si vide et non `prompt_optional`).
    prompt: str = ""
    model: str | None = None              # id fal ; défaut = fal.DEFAULT_IMAGE_MODEL
    aspect_ratio: str = "16:9"               # 1:1 | 16:9 | 9:16 | 4:3 | 3:4 | custom
    width: int | None = None              # si aspect_ratio == custom
    height: int | None = None
    name: str | None = None               # nom du média (défaut = début du prompt)
    params: dict = Field(default_factory=dict)  # resolution, steps, seed, style… (pass-through)
    reference_media_ids: list[int] = Field(default_factory=list)  # image→image (input=image)


class GenerateVideoRequest(BaseModel):
    """Requête de génération vidéo (§ génération — Phase 3, asynchrone)."""

    prompt: str = Field(..., min_length=1)
    model: str | None = None              # id fal ; défaut = fal.DEFAULT_VIDEO_MODEL
    aspect_ratio: str = "16:9"
    name: str | None = None               # nom du média (défaut générique si vide)
    mute: bool = False                    # retire la bande audio du master (ffmpeg -an)
    params: dict = Field(default_factory=dict)  # ex. {"duration": "5"} (pass-through fal)
    reference_media_ids: list[int] = Field(default_factory=list)  # image→vidéo (input=image)


class GenerateAudioRequest(BaseModel):
    """Requête de génération audio (§ génération — Phase 2, asynchrone).

    provider sélectionnable (fal pour les tests, elevenlabs pour les clients) ; l'UI ne
    propose que les providers dont la clé existe. `prompt` = description (musique) ou
    texte à dire (voix)."""

    provider: Literal["fal", "elevenlabs"]
    kind: Literal["music", "voice"]
    prompt: str = Field(..., min_length=1)
    model: str | None = None
    name: str | None = None               # nom du média (défaut générique si vide)
    params: dict = Field(default_factory=dict)  # voice_id, model_id, music_length_ms…


class PromptAssistMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)


class PromptAssistRequest(BaseModel):
    """Demande d'aide à la rédaction de prompt (optionnel, non bloquant)."""

    kind: Literal["image", "video", "music", "voice"]
    model: str | None = None              # modèle visé (rend l'assistant model-aware)
    mode: Literal["one_shot", "conversational"] = "one_shot"
    intent: str | None = None             # one-shot : l'idée libre (FR/EN/…)
    messages: list[PromptAssistMessage] = Field(default_factory=list)  # conversationnel
    reference_media_ids: list[int] = Field(default_factory=list)  # i2i/i2v : réf présente
    # Annonceur visé (P3.4) : sa charte de marque entre dans le prompt comme atmosphère.
    # Absent = charte de l'organisation, si elle existe.
    advertiser_id: int | None = None


class PromptAssistResponse(BaseModel):
    ready: bool = True                    # False = l'agent attend des réponses (questions)
    questions: list[str] = Field(default_factory=list)
    prompt: str | None = None             # prompt optimisé (anglais), éditable
    negative_prompt: str | None = None    # si le modèle le supporte
    notes: str = ""                       # conseil dans la langue de l'utilisateur
    assisted: bool = True                 # False = repli brut (LLM indisponible / mode strict)
    supports_negative_prompt: bool = False  # pilote l'affichage du champ negative côté UI


class GenerationJobRead(BaseModel):
    model_config = {"from_attributes": True}

    id_job: int
    kind: str
    provider: str
    model: str
    prompt: str
    aspect_ratio: str | None = None
    status: str
    id_media: int | None = None
    cost_usd: float | None = None
    error_detail: str | None = None
    id_campaign: int | None = None
    created_at: datetime
    updated_at: datetime


# ── Campagne one-shot (§ génération — Phase 4) ──────────────────────────────────

class CampaignConcept(BaseModel):
    title: str
    prompt: str = Field(..., min_length=1)


CampaignType = Literal["image", "video", "voice", "music"]


class CampaignPlanRequest(BaseModel):
    """Demande de PLAN (Claude = directeur créatif). Aucune génération, aucun coût engagé."""

    brief: str = Field(..., min_length=1)
    n_concepts: int = Field(default=3, ge=1, le=6)
    types: list[CampaignType] = Field(default_factory=lambda: ["image"])
    model: str | None = None              # modèle image visé (défaut = fal image)


class CampaignPlanResponse(BaseModel):
    concepts: list[CampaignConcept]
    video_prompt: str | None = None
    voiceover: str | None = None
    music_prompt: str | None = None


class CampaignExecuteRequest(BaseModel):
    """Lance le fan-out multi-type : images (concepts × ratios) + vidéo + voix + musique."""

    brief: str = Field(..., min_length=1)
    types: list[CampaignType] = Field(default_factory=lambda: ["image"])
    concepts: list[CampaignConcept] = Field(default_factory=list)
    # Bloc IMAGE : formats + réf i2i optionnelle (photo produit → concepts).
    ratios: list[str] = Field(default_factory=lambda: ["16:9"])
    reference_media_ids: list[int] = Field(default_factory=list)
    model: str | None = None
    # Bloc VIDÉO : formats (1 clip par format) + réf i2v optionnelle.
    video_model: str | None = None
    video_ratios: list[str] = Field(default_factory=lambda: ["16:9"])
    video_reference_media_ids: list[int] = Field(default_factory=list)
    video_prompt: str | None = None
    video_negative_prompt: str | None = None  # transmis si le modèle vidéo le supporte
    video_mute: bool = False                  # retire la bande audio des vidéos générées
    voice_provider: str = "fal"
    voice_model: str | None = None
    voiceover: str | None = None
    music_provider: str = "fal"
    music_model: str | None = None
    music_prompt: str | None = None


class CampaignRead(BaseModel):
    model_config = {"from_attributes": True}

    id_campaign: int
    brief: str
    model: str
    ratios: list[str]
    status: str
    total_cost_usd: float | None = None
    created_at: datetime
    updated_at: datetime
    jobs_total: int = 0
    jobs_ready: int = 0
    jobs_failed: int = 0
