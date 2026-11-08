"""VOD — ciblage par SITE entier (cible dynamique) en plus du player-par-player.

Une config VOD ciblait jusqu'ici une LISTE FIGÉE de players (`cms_vod_config_players`),
tous du même site. On ajoute un second mode, DYNAMIQUE :

- `target_mode = 'players'` (défaut, comportement historique) : la cible est la liste
  explicite de `cms_vod_config_players` ;
- `target_mode = 'site'` : la cible est **tous les players du site `id_site`**, résolus à
  la lecture. Un player ajouté au site plus tard hérite automatiquement du pré-cache VOD
  (et des triggers), sans rouvrir la config. `cms_vod_config_players` est alors vide.

`id_site` devient donc AUTORITAIRE en mode 'site' (il était jusqu'ici un simple miroir du
site commun des players affectés) — d'où le CHECK : pas de mode 'site' sans site.

Rétro-compat : toutes les lignes existantes prennent 'players', leur cible ne bouge pas.

Revision ID: 0096
Revises: 0095
"""

from alembic import op

revision: str = "0096"
down_revision: str | None = "0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cms_vod_configs ADD COLUMN target_mode VARCHAR(16) "
        "NOT NULL DEFAULT 'players'"
    )
    # Un ciblage de site sans site serait une cible vide silencieuse (la classe de bug
    # exacte de l'audit du 2026-07-18 : cible acceptée puis jamais résolue).
    op.execute(
        "ALTER TABLE cms_vod_configs ADD CONSTRAINT ck_cms_vod_configs_target_mode "
        "CHECK (target_mode IN ('players', 'site') "
        "AND (target_mode <> 'site' OR id_site IS NOT NULL))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cms_vod_configs DROP CONSTRAINT ck_cms_vod_configs_target_mode")
    op.execute("ALTER TABLE cms_vod_configs DROP COLUMN target_mode")
