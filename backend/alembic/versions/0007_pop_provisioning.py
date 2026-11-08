"""Proof of Play + Provisioning — Sprint 1.6

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-30 00:00:00.000000

Crée :
  - cms_proof_of_play : table partitionnée RANGE par played_at
      Partitions mensuelles 2026-05 → 2026-12 + partition DEFAULT
      Chaîne Merkle : merkle_hash = sha256(prev_hash + id_player + id_media + played_at + duration_ms)
  - Provisioning tokens : pas de nouvelle table — utilise cms_api_keys existant
      (scopes=['player:register'], key_hash=sha256(raw_token))
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cms_proof_of_play (partitionnée RANGE par played_at) ──────────────────
    # BIGSERIAL non disponible sur une table partitionnée → séquence manuelle
    op.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS cms_proof_of_play_id_pop_seq"))

    op.execute(sa.text("""
        CREATE TABLE cms_proof_of_play (
            id_pop      BIGINT NOT NULL DEFAULT nextval('cms_proof_of_play_id_pop_seq'),
            id_org      BIGINT NOT NULL,
            id_player   BIGINT NOT NULL,
            id_playlist BIGINT,
            id_media    BIGINT,
            played_at   TIMESTAMPTZ NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            merkle_hash VARCHAR(64) NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id_pop, played_at)
        ) PARTITION BY RANGE (played_at)
    """))

    # Partitions mensuelles 2026
    for month_start, month_end, suffix in [
        ("2026-05-01", "2026-06-01", "2026_05"),
        ("2026-06-01", "2026-07-01", "2026_06"),
        ("2026-07-01", "2026-08-01", "2026_07"),
        ("2026-08-01", "2026-09-01", "2026_08"),
        ("2026-09-01", "2026-10-01", "2026_09"),
        ("2026-10-01", "2026-11-01", "2026_10"),
        ("2026-11-01", "2026-12-01", "2026_11"),
        ("2026-12-01", "2027-01-01", "2026_12"),
        ("2027-01-01", "2027-02-01", "2027_01"),
        ("2027-02-01", "2027-03-01", "2027_02"),
    ]:
        op.execute(sa.text(f"""
            CREATE TABLE cms_proof_of_play_{suffix}
                PARTITION OF cms_proof_of_play
                FOR VALUES FROM ('{month_start}') TO ('{month_end}')
        """))

    op.execute(sa.text("""
        CREATE TABLE cms_proof_of_play_default
            PARTITION OF cms_proof_of_play DEFAULT
    """))

    # Index sur les colonnes de requête fréquentes
    op.execute(sa.text(
        "CREATE INDEX ix_pop_player_at ON cms_proof_of_play (id_player, played_at)"
    ))
    op.execute(sa.text(
        "CREATE INDEX ix_pop_org_at ON cms_proof_of_play (id_org, played_at)"
    ))

    # RLS
    op.execute(sa.text("ALTER TABLE cms_proof_of_play ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE cms_proof_of_play FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("""
        CREATE POLICY cms_proof_of_play_org_isolation ON cms_proof_of_play
            AS PERMISSIVE FOR ALL
            USING (id_org = current_setting('app.current_org_id', true)::BIGINT)
    """))

    # Grants
    op.execute(sa.text("GRANT SELECT, INSERT ON cms_proof_of_play TO signflow_app"))
    op.execute(sa.text("GRANT ALL ON cms_proof_of_play TO signflow_worker"))
    op.execute(sa.text(
        "GRANT USAGE ON SEQUENCE cms_proof_of_play_id_pop_seq TO signflow_app"
    ))
    op.execute(sa.text(
        "GRANT USAGE ON SEQUENCE cms_proof_of_play_id_pop_seq TO signflow_worker"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS cms_proof_of_play CASCADE"))
    op.execute(sa.text("DROP SEQUENCE IF EXISTS cms_proof_of_play_id_pop_seq"))
