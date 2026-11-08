"""Retail Media — dossier médiathèque par annonceur + opt-out player (Ed 2026-07-09)

Revision ID: 0075
Revises: 0074

1. `cms_advertisers.id_folder` → dossier `Annonceurs/<nom>` de la médiathèque
   (arborescence cms_media_folders existante, path matérialisé). Backfill : pour
   chaque org ayant des annonceurs, création d'un dossier racine « Annonceurs »
   puis d'un sous-dossier par annonceur non supprimé. Le picker de créatifs
   filtre par défaut sur le sous-arbre du dossier de l'annonceur.
2. `cms_players.campaigns_optout` → player exclu des campagnes (écran caisse,
   back-office…) : retiré de TOUTE résolution de cible campagne (diffusion S3
   et inventaire/occupation S2), même si son site/groupe/org est ciblé.
"""

from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cms_advertisers
            ADD COLUMN id_folder BIGINT
                REFERENCES cms_media_folders(id_folder) ON DELETE SET NULL
        """
    )
    op.execute(
        "ALTER TABLE cms_players ADD COLUMN campaigns_optout BOOLEAN NOT NULL DEFAULT false"
    )

    # Backfill : racine « Annonceurs » par org concernée + un sous-dossier par annonceur.
    op.execute(
        """
        DO $$
        DECLARE
            v_org BIGINT;
            v_root BIGINT;
            v_adv RECORD;
            v_folder BIGINT;
        BEGIN
            FOR v_org IN SELECT DISTINCT id_org FROM cms_advertisers WHERE is_deleted = false
            LOOP
                SELECT id_folder INTO v_root FROM cms_media_folders
                 WHERE id_org = v_org AND parent_id IS NULL AND folder_name = 'Annonceurs'
                 LIMIT 1;
                IF v_root IS NULL THEN
                    INSERT INTO cms_media_folders (id_org, parent_id, folder_name, depth, path)
                    VALUES (v_org, NULL, 'Annonceurs', 0, '')
                    RETURNING id_folder INTO v_root;
                    UPDATE cms_media_folders SET path = v_root::text WHERE id_folder = v_root;
                END IF;
                FOR v_adv IN SELECT id_advertiser, advertiser_name FROM cms_advertisers
                              WHERE id_org = v_org AND is_deleted = false AND id_folder IS NULL
                LOOP
                    INSERT INTO cms_media_folders (id_org, parent_id, folder_name, depth, path)
                    VALUES (v_org, v_root, v_adv.advertiser_name, 1, '')
                    RETURNING id_folder INTO v_folder;
                    UPDATE cms_media_folders
                       SET path = (SELECT path FROM cms_media_folders WHERE id_folder = v_root)
                                  || '.' || v_folder::text
                     WHERE id_folder = v_folder;
                    UPDATE cms_advertisers SET id_folder = v_folder
                     WHERE id_advertiser = v_adv.id_advertiser;
                END LOOP;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_players DROP COLUMN campaigns_optout")
    op.execute("ALTER TABLE cms_advertisers DROP COLUMN id_folder")
