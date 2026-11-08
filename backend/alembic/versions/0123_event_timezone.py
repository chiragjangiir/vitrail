"""Fuseau de référence d'un événement (P3.13, option ② tranchée par Ed le 2026-08-05).

Un événement porte **une seule ligne** et **un seul `activated_at`** : il ne peut donc pas
s'activer à l'heure locale de chaque écran. Plutôt que de laisser « 18 h » vouloir dire
« 18 h chez le serveur » sans que personne ne l'ait écrit, l'événement DÉCLARE son fuseau
de référence — l'ambiguïté est levée à la création, pas devinée à l'exécution.

**Colonne NULLABLE, sans défaut** : `NULL` = `SIGNFLOW_TZ`, c'est-à-dire exactement le
comportement d'aujourd'hui. Aucun événement existant ne change d'heure au déploiement —
un correctif de fuseau qui décale les diffusions en s'installant serait un incident, pas
un correctif.

Revision ID: 0123
Revises: 0122
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0123"
down_revision: str | None = "0122"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cms_events",
        sa.Column(
            "timezone",
            sa.String(64),
            nullable=True,
            comment=(
                "Fuseau IANA dans lequel s'évaluent les fenêtres horaires du trigger_config. "
                "NULL = SIGNFLOW_TZ (défaut mono-pays)."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("cms_events", "timezone")
