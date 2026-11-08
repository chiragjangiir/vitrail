"""Plage de validité (dates début/fin) au niveau programme — cms_schedules

Revision ID: 0036
Revises: 0035
Create Date: 2026-06-04 22:30:00.000000

Un programme (schedule) peut désormais porter une enveloppe de dates :
  - valid_from  : première date d'activité (NULL = pas de borne basse)
  - valid_until : dernière date d'activité incluse (NULL = pas de borne haute)
Cette enveloppe s'applique PAR-DESSUS les règles de récurrence (AND) : le
programme n'est diffusé que si la date du jour est dans [valid_from, valid_until]
ET qu'une règle horaire matche. Dates en heure locale (SIGNFLOW_TZ).
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_schedules", sa.Column("valid_from", sa.Date(), nullable=True))
    op.add_column("cms_schedules", sa.Column("valid_until", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("cms_schedules", "valid_until")
    op.drop_column("cms_schedules", "valid_from")
