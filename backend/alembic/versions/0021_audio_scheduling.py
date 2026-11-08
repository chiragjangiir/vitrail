"""Audio scheduling & events — extension du moteur de diffusion à l'audio (§XIX)

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-31 18:00:00.000000

Traite les paniers audio comme le pendant audio des playlists : ils sont
diffusés via le moteur de schedules/events existant (plages date/heure,
overrides), au lieu de l'assignation statique cms_player_basket_config.

- cms_schedules : + schedule_kind ('content'|'audio'), id_playlist nullable,
  + id_basket, + mix_ratio.
- cms_events    : + event_kind ('content'|'audio'), + id_basket, + mix_ratio.
- Migration de données : chaque cms_player_basket_config actif → un schedule
  'audio' avec une règle 'always' + un target 'player'. La table est conservée
  et repurposée comme couche d'overrides runtime du Store Control Panel (§19.3).

Résolution runtime : set-based (plusieurs paniers simultanés mixés), cf. ws.py.
"""

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cms_schedules : discriminateur + cible audio ───────────────────────────
    op.execute("ALTER TABLE cms_schedules ALTER COLUMN id_playlist DROP NOT NULL")
    op.execute(
        "ALTER TABLE cms_schedules ADD COLUMN schedule_kind VARCHAR(20) NOT NULL DEFAULT 'content'"
    )
    op.execute(
        "ALTER TABLE cms_schedules ADD COLUMN id_basket BIGINT REFERENCES cms_audio_baskets(id_basket)"
    )
    op.execute("ALTER TABLE cms_schedules ADD COLUMN mix_ratio SMALLINT")
    op.execute("CREATE INDEX idx_schedules_kind ON cms_schedules(schedule_kind)")

    # ── cms_events : discriminateur + cible audio ──────────────────────────────
    op.execute(
        "ALTER TABLE cms_events ADD COLUMN event_kind VARCHAR(20) NOT NULL DEFAULT 'content'"
    )
    op.execute(
        "ALTER TABLE cms_events ADD COLUMN id_basket BIGINT REFERENCES cms_audio_baskets(id_basket)"
    )
    op.execute("ALTER TABLE cms_events ADD COLUMN mix_ratio SMALLINT")

    # ── Migration : cms_player_basket_config actifs → schedules audio 'always' ──
    op.execute("""
        DO $$
        DECLARE
            r   RECORD;
            sid BIGINT;
        BEGIN
            FOR r IN
                SELECT pbc.id_player, pbc.id_basket, pbc.mix_ratio,
                       p.id_org, b.basket_name
                FROM cms_player_basket_config pbc
                JOIN cms_players p       ON p.id_player = pbc.id_player
                JOIN cms_audio_baskets b ON b.id_basket = pbc.id_basket
                WHERE pbc.is_active = true
            LOOP
                INSERT INTO cms_schedules
                    (id_org, schedule_name, id_playlist, schedule_kind, id_basket,
                     mix_ratio, priority, is_active, is_deleted, created_at, updated_at)
                VALUES
                    (r.id_org, 'Audio: ' || r.basket_name, NULL, 'audio', r.id_basket,
                     r.mix_ratio, 0, true, false, now(), now())
                RETURNING id_schedule INTO sid;

                INSERT INTO cms_schedule_rules (id_schedule, rule_type, created_at)
                VALUES (sid, 'always', now());

                INSERT INTO cms_schedule_targets (id_schedule, target_type, target_id, created_at)
                VALUES (sid, 'player', r.id_player, now());
            END LOOP;
        END $$;
    """)

    # La table est désormais la couche d'overrides runtime du Store Control Panel :
    # on la vide (les assignations permanentes vivent maintenant dans les schedules).
    op.execute("DELETE FROM cms_player_basket_config")


def downgrade() -> None:
    # Supprime les schedules audio créés (et leurs règles/targets via la logique applicative —
    # ici on retire d'abord les dépendances pour rester sûr)
    op.execute("""
        DELETE FROM cms_schedule_rules
        WHERE id_schedule IN (SELECT id_schedule FROM cms_schedules WHERE schedule_kind = 'audio')
    """)
    op.execute("""
        DELETE FROM cms_schedule_targets
        WHERE id_schedule IN (SELECT id_schedule FROM cms_schedules WHERE schedule_kind = 'audio')
    """)
    op.execute("DELETE FROM cms_schedules WHERE schedule_kind = 'audio'")

    op.execute("ALTER TABLE cms_events DROP COLUMN IF EXISTS mix_ratio")
    op.execute("ALTER TABLE cms_events DROP COLUMN IF EXISTS id_basket")
    op.execute("ALTER TABLE cms_events DROP COLUMN IF EXISTS event_kind")

    op.execute("DROP INDEX IF EXISTS idx_schedules_kind")
    op.execute("ALTER TABLE cms_schedules DROP COLUMN IF EXISTS mix_ratio")
    op.execute("ALTER TABLE cms_schedules DROP COLUMN IF EXISTS id_basket")
    op.execute("ALTER TABLE cms_schedules DROP COLUMN IF EXISTS schedule_kind")
    # NB : id_playlist reste nullable (pas de re-NOT NULL pour éviter d'échouer sur d'éventuels NULL)
