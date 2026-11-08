"""Audio schedule multi-paniers + typage des groupes (§XIX)

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-31 20:00:00.000000

Un schedule audio devient un *programme* contenant plusieurs paniers (chacun avec
son ratio de mix) au lieu d'un seul. Les paniers déclencheurs (emergency) sont
exemptés du budget 100 % côté résolution.

- cms_schedule_baskets : (id_schedule, id_basket, mix_ratio) — paniers d'un schedule audio.
- cms_player_groups += group_type ('content'|'audio'|'mixed') pour cibler les bons groupes.
- Migration : chaque schedule audio 0021 (id_basket/mix_ratio mono-panier) → une ligne
  cms_schedule_baskets, puis on retire les colonnes id_basket/mix_ratio de cms_schedules.
  (cms_events conserve id_basket/mix_ratio : un event = un panier override.)
"""

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cms_schedule_baskets ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE cms_schedule_baskets (
            id_sb       BIGSERIAL PRIMARY KEY,
            id_schedule BIGINT NOT NULL REFERENCES cms_schedules(id_schedule) ON DELETE CASCADE,
            id_basket   BIGINT NOT NULL REFERENCES cms_audio_baskets(id_basket) ON DELETE CASCADE,
            mix_ratio   SMALLINT NOT NULL DEFAULT 50,
            UNIQUE (id_schedule, id_basket)
        )
    """)
    op.execute("CREATE INDEX idx_csb_schedule ON cms_schedule_baskets(id_schedule)")

    # ── Migration des schedules audio mono-panier (0021) → schedule_baskets ─────
    op.execute("""
        INSERT INTO cms_schedule_baskets (id_schedule, id_basket, mix_ratio)
        SELECT id_schedule, id_basket, COALESCE(mix_ratio, 50)
        FROM cms_schedules
        WHERE schedule_kind = 'audio' AND id_basket IS NOT NULL
    """)

    # Les colonnes mono-panier de cms_schedules ne servent plus
    op.execute("ALTER TABLE cms_schedules DROP COLUMN IF EXISTS id_basket")
    op.execute("ALTER TABLE cms_schedules DROP COLUMN IF EXISTS mix_ratio")

    # ── cms_player_groups.group_type ───────────────────────────────────────────
    op.execute(
        "ALTER TABLE cms_player_groups ADD COLUMN group_type VARCHAR(20) NOT NULL DEFAULT 'content'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_player_groups DROP COLUMN IF EXISTS group_type")
    op.execute("ALTER TABLE cms_schedules ADD COLUMN id_basket BIGINT REFERENCES cms_audio_baskets(id_basket)")
    op.execute("ALTER TABLE cms_schedules ADD COLUMN mix_ratio SMALLINT")
    # Restaure le premier panier de chaque schedule audio (best effort)
    op.execute("""
        UPDATE cms_schedules s
        SET id_basket = sb.id_basket, mix_ratio = sb.mix_ratio
        FROM (
            SELECT DISTINCT ON (id_schedule) id_schedule, id_basket, mix_ratio
            FROM cms_schedule_baskets ORDER BY id_schedule, id_sb
        ) sb
        WHERE s.id_schedule = sb.id_schedule
    """)
    op.execute("DROP TABLE IF EXISTS cms_schedule_baskets")
