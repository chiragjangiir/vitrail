"""Retail Media AUDIO S2 (§2.8 + §XIX) — campagnes de spots audio annonceurs.

- `cms_campaigns.campaign_kind` : 'visual' (défaut) | 'audio'. Une campagne audio vend des
  **spots/heure** (`spots_per_hour`) insérés dans la rotation musicale des paniers §XIX
  (panier synthétique jingle/minutes compilé serveur — zéro modif player) ; `sov_percent`
  est ignoré pour l'audio.
- Plafond de spots/heure par écran : `campaign_audio_spots_cap` — héritage
  player > site > org (défaut org = 12, décision Ed 16/07).
- Tarif audio : `campaign_audio_spot_daily_rate` (€ par spot/heure par JOUR et par écran,
  miroir du visuel €/1 % SOV/jour) — héritage org > site > player ; devis indicatif,
  prix contractuel = champ manuel existant.

Revision ID: 0094
Revises: 0093
"""

from alembic import op

revision: str = "0094"
down_revision: str | None = "0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_campaigns ADD COLUMN campaign_kind VARCHAR(10) "
        "NOT NULL DEFAULT 'visual'"
    )
    op.execute("ALTER TABLE cms_campaigns ADD COLUMN spots_per_hour INTEGER")
    op.execute(
        "ALTER TABLE cms_organizations ADD COLUMN campaign_audio_spots_cap INTEGER "
        "NOT NULL DEFAULT 12"
    )
    op.execute(
        "ALTER TABLE cms_organizations ADD COLUMN campaign_audio_spot_daily_rate NUMERIC(10,4)"
    )
    op.execute("ALTER TABLE cms_sites ADD COLUMN campaign_audio_spots_cap INTEGER")
    op.execute(
        "ALTER TABLE cms_sites ADD COLUMN campaign_audio_spot_daily_rate NUMERIC(10,4)"
    )
    op.execute("ALTER TABLE cms_players ADD COLUMN campaign_audio_spots_cap INTEGER")
    op.execute(
        "ALTER TABLE cms_players ADD COLUMN campaign_audio_spot_daily_rate NUMERIC(10,4)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_players DROP COLUMN IF EXISTS campaign_audio_spot_daily_rate")
    op.execute("ALTER TABLE cms_players DROP COLUMN IF EXISTS campaign_audio_spots_cap")
    op.execute("ALTER TABLE cms_sites DROP COLUMN IF EXISTS campaign_audio_spot_daily_rate")
    op.execute("ALTER TABLE cms_sites DROP COLUMN IF EXISTS campaign_audio_spots_cap")
    op.execute(
        "ALTER TABLE cms_organizations DROP COLUMN IF EXISTS campaign_audio_spot_daily_rate"
    )
    op.execute("ALTER TABLE cms_organizations DROP COLUMN IF EXISTS campaign_audio_spots_cap")
    op.execute("ALTER TABLE cms_campaigns DROP COLUMN IF EXISTS spots_per_hour")
    op.execute("ALTER TABLE cms_campaigns DROP COLUMN IF EXISTS campaign_kind")
