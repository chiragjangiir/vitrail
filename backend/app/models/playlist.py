from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Optional

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsPlaylist(Base):
    """Playlist de contenus liée à un template (§XIII)."""

    __tablename__ = "cms_playlists"

    id_playlist: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    playlist_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    id_template: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_templates.id_template"), nullable=True
    )
    # wall_clock (défaut, déterministe) | loop (reprise depuis 0 à chaque reconnexion)
    sync_mode: Mapped[str] = mapped_column(
        String(20), server_default="wall_clock", default="wall_clock", nullable=False
    )
    # Rotation (imbriquée dans un programme via item sub_playlist) :
    # all (défaut = inline complet) | one_sequential | one_random (permutation seedée
    # sans remise). Le cycle est déroulé par le serveur au sync (ws.py).
    rotation_mode: Mapped[str] = mapped_column(
        String(20), server_default="all", default="all", nullable=False
    )
    # Nombre d'items diffusés par tour de boucle (rotation seulement).
    # SmallInteger et non Integer : la migration 0091 crée un SMALLINT, et c'est la base
    # qui fait foi (P2.6). Aucun effet fonctionnel — les deux portent des entiers — mais un
    # modèle qui décrit autre chose que le schéma déployé finit toujours par mentir sur un
    # détail qui compte.
    items_per_turn: Mapped[int] = mapped_column(
        SmallInteger, server_default="1", default=1, nullable=False
    )
    # « Pas de publicité entre les contenus » : quand cette playlist est imbriquée
    # comme sous-playlist, son bloc passe d'une traite (aucun créatif Retail Media
    # inséré dedans — le spot glisse avant/après le bloc). Sans effet quand la
    # playlist est le programme principal.
    no_ads_inside: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # Gouvernance §XVIII contenu (R14/R15) : nœud propriétaire de la playlist. NULL =
    # playlist d'organisation (comportement historique inchangé). Non NULL = seul un admin
    # du nœud (ou d'un ancêtre) l'édite ; lecture filtrée ; publication modérée si le nœud
    # exige l'approbation. Miroir de id_governance_node sur cms_schedules.
    id_governance_node: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_governance_nodes.id_node", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # Staging (#1, archi 2) : brouillon d'édition non publié. NULL = propre (pas de
    # brouillon). Les players lisent toujours cms_playlist_items (= publié). Liste de
    # {uid, id_media, sort_order, duration_ms, zone_index, transition_type, rules:[...]}.
    draft_items: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # Pendant de draft_items pour les RÉGLAGES de la playlist (rotation_mode,
    # items_per_turn, no_ads_inside) : décision Ed 2026-07-25 ④ — ils étaient appliqués
    # immédiatement alors que les items attendent « Publier ». NULL = rien en attente ;
    # sinon dict des seules clés modifiées, recopiées dans les colonnes à la publication.
    draft_settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user"), nullable=True
    )
    # ⚠️ `DateTime(timezone=True)` EXPLICITE : la colonne EST `timestamptz` en base, mais
    # sans ce type déclaré SQLAlchemy la traite en naïve et asyncpg REFUSE tout datetime
    # aware — c'est exactement ce qui rendait l'embargo média inutilisable (500 silencieux,
    # trouvé le 28/07). Le poser ici est indispensable AVANT `onupdate`.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # `onupdate` plutôt qu'une écriture manuelle : `updated_at` ne bougeait JAMAIS (mesuré
    # sur la prod le 2026-07-29 — **0 playlist sur 20**, alors que les médias l'entretiennent).
    # Une playlist a une dizaine de chemins de mutation (items, réordonnancement, règles,
    # réglages, publication, abandon) : les instrumenter un par un aurait garanti d'en
    # oublier un, et d'en oublier les futurs. Ici tout UPDATE de la ligne l'entretient.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"),
        onupdate=lambda: datetime.now(UTC), nullable=False,
    )


class CmsPlaylistItem(Base):
    """Élément d'une playlist : média + position dans le template."""

    __tablename__ = "cms_playlist_items"

    id_item: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_playlist: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_playlists.id_playlist"), nullable=False, index=True
    )
    # media (défaut) | sub_playlist (playlist imbriquée — 1 seul niveau)
    item_type: Mapped[str] = mapped_column(
        String(20), server_default="media", default="media", nullable=False
    )
    id_media: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_media.id_media"), nullable=True
    )
    id_child_playlist: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_playlists.id_playlist"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    # None = utilise la durée native du média. Pour un DOCUMENT multipage :
    # durée PAR PAGE (défaut 10 s) — la durée totale = par page × pages sélectionnées.
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Documents multipages : sélection de pages "2-5,8" (NULL = toutes, ordre respecté)
    doc_pages: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # Nb de pages résolues quand doc_pages est posé (dénormalisé pour les agrégats SQL ;
    # maintenu à l'écriture + re-calculé par le worker au replace du document).
    doc_page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Documents multipages : autoriser le visiteur à feuilleter au doigt (migr 0129).
    # L'autorisation appartient au CONTENU, la dalle tactile au PLAYER : le renderer rend ce
    # drapeau inerte sur un écran qui ne remonte aucun point de contact. false = comportement
    # historique, strictement inchangé.
    touch_navigation: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False, nullable=False
    )
    # Délai SANS interaction avant de quitter le document et reprendre la diffusion normale.
    # NULL = défaut du renderer. SmallInteger : la base fait foi (P2.6), la migration 0129
    # crée un SMALLINT.
    touch_resume_after_s: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    zone_index: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    # cut | fade | slide
    transition_type: Mapped[str] = mapped_column(
        String(20), server_default="cut", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"),
        onupdate=lambda: datetime.now(UTC), nullable=False,
    )


class CmsPlaylistItemRule(Base):
    """Règle de diffusion d'un item de playlist (heure LOCALE, § retours clients item 4).

    Miroir de `cms_schedule_rules` + portée `scope`. Un item sans règle = perpétuel.
    Évaluée via le noyau scheduling (services/scheduling.py). P1 = scope 'default'.
    """

    __tablename__ = "cms_playlist_item_rules"

    id_item_rule: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_item: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("cms_playlist_items.id_item", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # default (P1, tous les players) | player | player_group (P2, override par cible)
    scope: Mapped[str] = mapped_column(
        String(20), server_default="default", default="default", nullable=False
    )
    target_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # always | weekly | date_range
    rule_type: Mapped[str] = mapped_column(
        String(20), server_default="weekly", default="weekly", nullable=False
    )
    days_of_week: Mapped[Optional[list[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    time_start: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    time_end: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    date_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
