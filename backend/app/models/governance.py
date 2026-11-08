from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CmsGovernanceNode(Base):
    """Nœud de l'arbre de gouvernance hiérarchique (§XVIII.3).

    Indépendant de l'arbre d'organisations. `path` matérialisé ("1.5.23")
    pour les requêtes de sous-arbre rapides.
    """

    __tablename__ = "cms_governance_nodes"

    id_node: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_org: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_organizations.id_org"), nullable=False, index=True
    )
    parent_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("cms_governance_nodes.id_node", ondelete="CASCADE"), nullable=True, index=True
    )
    node_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 0=national, 1=régional, 2=département…
    node_level: Mapped[int] = mapped_column(Integer, server_default="0", default=0, nullable=False)
    # national | regional | department | store | international | custom
    node_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    path: Mapped[str] = mapped_column(Text, server_default="", default="", nullable=False)
    # Gouvernance du CONTENU (R15/D, D7) : le contenu (playlists/médias) rattaché à ce nœud
    # passe-t-il par un modérateur avant diffusion ? Semé depuis le parent à la création,
    # surchargeable — mais SEUL un admin d'un ancêtre (ou org-admin) peut la décocher, sinon
    # un nœud se dispenserait lui-même de modération.
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, server_default="true", default=True, nullable=False
    )
    # RESTRICTIONS d'écriture des règles, une par FAMILLE (= par type de règle) :
    # item_count | time_budget | time_window | preemptive. `true` = le niveau supérieur
    # décide, l'admin du nœud ne touche pas à ce paramètre (décision Ed 2026-07-26 : la
    # granularité par famille permet de déléguer le nombre de contenus sans déléguer la
    # préemption). ⚠️ **Clé absente = restreinte** : on n'ouvre que par un `false` explicite.
    # Valeur EFFECTIVE = OU logique sur le nœud et tous ses ancêtres ⇒ une restriction posée
    # en haut ne se lève jamais en dessous. Comme `requires_approval`, une case ne se modifie
    # que depuis un ancêtre STRICT — un nœud qui lèverait sa propre contrainte la viderait de
    # son sens.
    rules_locked: Mapped[dict] = mapped_column(
        JSONB,
        server_default=text(
            "'{\"item_count\": true, \"time_budget\": true, "
            "\"time_window\": true, \"preemptive\": true}'::jsonb"
        ),
        default=lambda: {f: True for f in ("item_count", "time_budget", "time_window", "preemptive")},
        nullable=False,
    )
    # Plafonds imposés aux DESCENDANTS (« le département peut monter jusqu'à 4 »). Portés par
    # le nœud et non par une règle : ils décrivent le droit des autres, pas la diffusion de ce
    # nœud — avant, poser un plafond obligeait à créer une règle de diffusion dont le nœud
    # n'avait aucun besoin. Plusieurs ancêtres peuvent en poser : le plus petit gagne.
    max_for_children: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Durée maximale d'UN contenu (secondes). S'applique aussi au nœud lui-même, par héritage :
    # sans elle, le « N par tour » compte des items et pas du temps, et une compilation de 3 h
    # livrée en un seul fichier accapare la boucle (attaque décrite par Ed).
    max_item_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CmsGovernanceAssignment(Base):
    """Player / groupe / site rattaché à un nœud de gouvernance (§XVIII.3)."""

    __tablename__ = "cms_governance_assignments"

    id_node: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_governance_nodes.id_node", ondelete="CASCADE"), primary_key=True
    )
    # player | group | site
    target_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    target_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class CmsGovernanceNodeAdmin(Base):
    """Utilisateur administrateur d'un nœud de gouvernance (§XVIII Phase 2, immutabilité).

    Un admin du nœud peut éditer les schedules rattachés au nœud ET à son sous-arbre.
    L'org_admin contourne. Un schedule sans nœud reste éditable par schedules:edit.
    """

    __tablename__ = "cms_governance_node_admins"

    id_node: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_governance_nodes.id_node", ondelete="CASCADE"), primary_key=True
    )
    id_user: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_users.id_user", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CmsDelegationRule(Base):
    """Contrainte de délégation par nœud (budget temps/items, fréquence…) (§XVIII.3).

    L'application runtime (compiled-schedule, budgets, préemption) = Phase 2.
    Ici on persiste la configuration (CRUD).
    """

    __tablename__ = "cms_delegation_rules"
    # D5 (2026-07-24) : une seule règle par TYPE et par nœud → résultat déterministe.
    # Sans cela, deux règles du même type se lisaient sans ORDER BY (la dernière gagnait),
    # alors que la liste affichée était triée : l'écran ne montrait pas laquelle gagnait.
    __table_args__ = (
        UniqueConstraint("id_node", "rule_type", name="uq_delegation_rule_node_type"),
    )

    id_rule: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_node: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cms_governance_nodes.id_node", ondelete="CASCADE"), nullable=False, index=True
    )
    # time_budget | item_count | time_window | preemptive
    # (frequency_cap / position_lock / priority_band retirés — D3, 2026-07-24)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"), default=dict, nullable=False)
    # true = terminer le contenu en cours avant coupure ; false = coupure stricte
    soft_cut: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
