"""Proof of Play — archivage & rotation (§XXIV, PLAN_POP_ARCHIVAL)

Revision ID: 0060
Revises: 0059
Create Date: 2026-07-02 00:00:00.000000

1. `cms_pop_archives` : index permanent (minuscule) d'une période de PoP sortie hors base.
   Porte le `merkle_root` de la période = preuve cryptographique compacte de tout le lot,
   conservée à vie même après expiration du blob froid (MinIO). RLS org_isolation.

2. Re-partitionnement `cms_proof_of_play` : MENSUEL (0007) → JOURNALIER. Décision Ed :
   rotation journalière réelle → le disque est rendu chaque jour par DROP de la partition
   du jour une fois archivée. Big-bang : les données sont minuscules à ce stade
   (~milliers de lignes) → on les met de côté (TEMP), on remplace les partitions
   mensuelles par des partitions JOUR (une par jour présent + une DEFAULT de sécurité),
   puis on réinsère. DDL Postgres transactionnel → tout ou rien (aucune perte possible).

   Les partitions jour sont possédées par `signflow_worker` pour que le worker `archive_pop`
   puisse les `DROP` après archivage (le DROP exige la propriété de la table enfant).
   La migration tourne en superuser `signflow` → bypass RLS pour la réinsertion.
"""

from datetime import date, timedelta

from alembic import op
from sqlalchemy import text

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels = None
depends_on = None


def _day_suffix(d: date) -> str:
    return d.strftime("%Y_%m_%d")


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. cms_pop_archives (héritant des DEFAULT PRIVILEGES 0044 → grants auto) ──
    op.execute(
        """
        CREATE TABLE cms_pop_archives (
            id_archive    BIGSERIAL PRIMARY KEY,
            id_org        BIGINT NOT NULL REFERENCES cms_organizations(id_org),
            period_start  DATE NOT NULL,
            period_end    DATE NOT NULL,
            row_count     BIGINT NOT NULL DEFAULT 0,
            merkle_root   VARCHAR(64),
            csv_key       TEXT NOT NULL,
            pdf_key       TEXT,
            bytes_csv     BIGINT,
            players       JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (id_org, period_start, period_end)
        )
        """
    )
    op.execute("CREATE INDEX idx_pop_archives_org ON cms_pop_archives (id_org, period_start DESC)")
    op.execute("ALTER TABLE cms_pop_archives ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY cms_pop_archives_org_isolation ON cms_pop_archives
            USING (id_org = current_setting('app.current_org_id', true)::bigint)
        """
    )

    # ── 2. Re-partitionnement mensuel → journalier ────────────────────────────
    # (a) mettre TOUTES les preuves de côté
    op.execute("CREATE TEMP TABLE _pop_hold ON COMMIT DROP AS SELECT * FROM cms_proof_of_play")

    # (b) supprimer les partitions existantes (mensuelles + default) — data safe dans _pop_hold
    children = conn.execute(text(
        "SELECT inhrelid::regclass::text FROM pg_inherits "
        "WHERE inhparent = 'cms_proof_of_play'::regclass"
    )).fetchall()
    for (child,) in children:
        op.execute(f"DROP TABLE {child}")

    # (c) DEFAULT de sécurité (rattrape tout jour sans partition dédiée)
    op.execute("CREATE TABLE cms_proof_of_play_default PARTITION OF cms_proof_of_play DEFAULT")
    op.execute("ALTER TABLE cms_proof_of_play_default OWNER TO signflow_worker")

    # (d) une partition JOUR par jour présent dans les données + [aujourd'hui .. +7]
    rng = conn.execute(text("SELECT min(played_at)::date, max(played_at)::date FROM _pop_hold")).fetchone()
    days: set[date] = set()
    if rng and rng[0] is not None:
        d, dmax = rng[0], rng[1]
        while d <= dmax:
            days.add(d)
            d += timedelta(days=1)
    today = date.today()
    for i in range(8):
        days.add(today + timedelta(days=i))

    for d in sorted(days):
        end = d + timedelta(days=1)
        tbl = f"cms_proof_of_play_{_day_suffix(d)}"
        op.execute(
            f"CREATE TABLE {tbl} PARTITION OF cms_proof_of_play "
            f"FOR VALUES FROM ('{d.isoformat()}') TO ('{end.isoformat()}')"
        )
        op.execute(f"ALTER TABLE {tbl} OWNER TO signflow_worker")

    # (e) réinsérer (superuser → bypass RLS ; routage vers les partitions jour, reste → default)
    op.execute("INSERT INTO cms_proof_of_play SELECT * FROM _pop_hold")
    # _pop_hold droppé automatiquement (ON COMMIT DROP)


def downgrade() -> None:
    # Retour à des partitions MENSUELLES (schéma 0007). Data préservée via TEMP hold.
    conn = op.get_bind()
    op.execute("CREATE TEMP TABLE _pop_hold ON COMMIT DROP AS SELECT * FROM cms_proof_of_play")
    children = conn.execute(text(
        "SELECT inhrelid::regclass::text FROM pg_inherits "
        "WHERE inhparent = 'cms_proof_of_play'::regclass"
    )).fetchall()
    for (child,) in children:
        op.execute(f"DROP TABLE {child}")
    op.execute("CREATE TABLE cms_proof_of_play_default PARTITION OF cms_proof_of_play DEFAULT")

    rng = conn.execute(text("SELECT min(played_at)::date, max(played_at)::date FROM _pop_hold")).fetchone()
    months: set[date] = set()
    if rng and rng[0] is not None:
        m = rng[0].replace(day=1)
        end = rng[1].replace(day=1)
        while m <= end:
            months.add(m)
            m = m.replace(year=m.year + 1, month=1) if m.month == 12 else m.replace(month=m.month + 1)
    cur = date.today().replace(day=1)
    for _ in range(4):
        months.add(cur)
        cur = cur.replace(year=cur.year + 1, month=1) if cur.month == 12 else cur.replace(month=cur.month + 1)

    for m in sorted(months):
        m_end = m.replace(year=m.year + 1, month=1) if m.month == 12 else m.replace(month=m.month + 1)
        tbl = f"cms_proof_of_play_{m.strftime('%Y_%m')}"
        op.execute(
            f"CREATE TABLE {tbl} PARTITION OF cms_proof_of_play "
            f"FOR VALUES FROM ('{m.isoformat()}') TO ('{m_end.isoformat()}')"
        )
    op.execute("INSERT INTO cms_proof_of_play SELECT * FROM _pop_hold")
    op.execute("DROP TABLE cms_pop_archives")
