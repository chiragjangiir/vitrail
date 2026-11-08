"""Plafonds de dépense BYOK : registre de dépense + plafonds par org et par utilisateur.

Le CMS enregistrait `cms_generation_jobs.cost_usd` mais **rien ne bloquait**. En BYOK c'est
l'argent du CLIENT : une boucle ou un import massif se voit sur SA facture, pas sur la nôtre.

🔴 POURQUOI UN REGISTRE DÉDIÉ, ET PAS UNE SOMME SUR `cms_generation_jobs`.

C'est l'implémentation évidente, et elle donnerait un plafond qui **a l'air** de fonctionner.
Mesuré le 2026-08-07 : sur les **cinq** chemins qui appellent réellement un fournisseur
payant, **quatre** sont invisibles ou faux dans cette table.

  · `POST /generation/image` (synchrone) — n'écrit **aucune ligne de job**, le coût n'atterrit
    que dans `media_metadata`. Or l'image est la génération la plus répétée : c'est
    exactement le cas de la boucle qu'un plafond doit arrêter.
  · `promo.py` ×2 (fond + détourage) — écrit des jobs à `cost_usd = 0` alors que l'appel fal
    est bien facturé. La table ment déjà sur ce coût-là.
  · la réponse **vocale de Jeanine** (ElevenLabs, `messaging_gateway`) — aucun job, aucune
    trace de coût. Un client peut la solliciter par messagerie sans aucune limite.
  · seuls les jobs asynchrones (vidéo / audio / campagne) y sont correctement comptés.

`cms_generation_jobs` est une FILE DE TRAVAIL, pas un livre de comptes. On sépare les deux :
tout chemin qui dépense écrit ici, et le plafond ne lit que ça.

🔑 RÉSERVATION, PAS CONSTAT. La ligne est écrite **avant** l'appel fournisseur, sur
l'estimation (`estimated_usd`), puis corrigée au montant réel (`actual_usd`) une fois l'appel
rendu — ou **relâchée** si l'appel n'a jamais eu lieu. Sans réservation, deux générations
lancées ensemble lisent la même somme avant que l'une ou l'autre n'ait écrit, et **passent
toutes les deux** sous un plafond qui n'en tient qu'une.

Périodes CALENDAIRES en **UTC** : jour, semaine ISO (lundi), mois. ⚠️ Volontairement
distinctes de `assistant_quota.period_start` (weekly|monthly sur les TOKENS de l'assistant,
autre réglage, autre unité) : les faire partager une fonction les forcerait à s'accorder sur
une sémantique qu'elles ne partagent pas.

NULL = pas de plafond (même convention que `ai_quota_tokens`) ⇒ **aucune organisation ne
change de comportement au déploiement**.

Revision ID: 0126
Revises: 0125
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0126"
down_revision: str | None = "0125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cms_ai_spend",
        sa.Column("id_spend", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "id_org", sa.BigInteger,
            sa.ForeignKey("cms_organizations.id_org", ondelete="CASCADE"), nullable=False,
        ),
        # SET NULL : supprimer un compte ne doit pas effacer la dépense qu'il a engagée —
        # elle reste sur la facture du client (même règle que le journal d'audit).
        sa.Column(
            "id_user", sa.BigInteger,
            sa.ForeignKey("cms_users.id_user", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("provider", sa.String(20), nullable=False),   # fal | elevenlabs
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),       # image|video|music|voice|promo
        # Montant RÉSERVÉ à la mise en file. Jamais NULL : c'est lui qui tient le plafond
        # tant que l'appel n'a pas rendu.
        sa.Column("estimated_usd", sa.Numeric(10, 4), nullable=False),
        # Montant RÉEL, écrit au retour du fournisseur. NULL = pas encore rendu.
        sa.Column("actual_usd", sa.Numeric(10, 4), nullable=True),
        # reserved : compte pour le plafond, sur l'estimation
        # settled  : compte pour le plafond, sur le montant réel
        # released : ne compte plus (l'appel n'a pas eu lieu, aucun argent dépensé)
        sa.Column("status", sa.String(10), nullable=False, server_default="reserved"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # ⚠️ Nom NU : la convention `ck_%(table_name)s_%(constraint_name)s` préfixe déjà — un nom
    # qui contient le préfixe le DOUBLE (`ck_cms_ai_spend_ck_cms_ai_spend_…`). La contrainte
    # fonctionnerait, mais le `downgrade` viserait un nom inexistant : il échouerait le jour
    # du rollback, le seul jour où il sert (défaut constaté sur la 0124 le 2026-08-06).
    op.create_check_constraint(
        "status", "cms_ai_spend",
        "status IN ('reserved', 'settled', 'released')",
    )
    # L'agrégat est TOUJOURS « une organisation, depuis un instant » : c'est l'index qui
    # porte le chemin chaud du contrôle, exécuté avant chaque génération.
    op.create_index("ix_cms_ai_spend_org_time", "cms_ai_spend", ["id_org", "created_at"])
    op.create_index("ix_cms_ai_spend_user_time", "cms_ai_spend", ["id_user", "created_at"])

    # Table TENANT-SCOPED : RLS + FORCE dès la création. `FORCE` n'est pas décoratif — une
    # politique ne s'applique PAS au propriétaire sans lui (mesuré le 29/07), et c'est
    # précisément le filet qu'on a vu tomber sur une install client tournant en superuser.
    # Les droits eux-mêmes viennent d'`ALTER DEFAULT PRIVILEGES` (migr 0002/0044).
    op.execute("ALTER TABLE cms_ai_spend ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cms_ai_spend FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY cms_ai_spend_org_isolation ON cms_ai_spend "
        "USING (id_org = current_setting('app.current_org_id', true)::bigint)"
    )

    # Lien job -> réservation : c'est le WORKER qui connaît le montant réel, il doit donc
    # pouvoir retrouver la ligne à solder. Sans ce lien, la réservation resterait à
    # l'estimation pour toujours — un plafond qui dérive de la réalité dans les deux sens.
    op.add_column("cms_generation_jobs",
                  sa.Column("id_spend", sa.BigInteger, nullable=True))

    # Plafonds — NULL = aucun plafond. Portés par l'ORGANISATION : le plafond « par
    # utilisateur » est une même valeur appliquée à chaque compte de l'org (c'est ce qui
    # arrête la boucle d'UNE personne sans exiger un réglage compte par compte).
    op.add_column("cms_organizations",
                  sa.Column("ai_spend_cap_usd", sa.Numeric(10, 2), nullable=True))
    op.add_column("cms_organizations",
                  sa.Column("ai_user_spend_cap_usd", sa.Numeric(10, 2), nullable=True))
    op.add_column("cms_organizations",
                  sa.Column("ai_spend_cap_period", sa.String(8),
                            nullable=False, server_default="month"))
    op.create_check_constraint(
        "ai_spend_cap_period", "cms_organizations",
        "ai_spend_cap_period IN ('day', 'week', 'month')",
    )


def downgrade() -> None:
    # ⚠️ Nom NU ICI AUSSI : la convention s'applique également à `drop_constraint`, qui
    # redoublait le préfixe (`ck_cms_organizations_ck_cms_organizations_…`). Mesuré en
    # exécutant réellement le downgrade — c'est la seule façon de le voir.
    op.drop_constraint("ai_spend_cap_period", "cms_organizations", type_="check")
    op.drop_column("cms_organizations", "ai_spend_cap_period")
    op.drop_column("cms_organizations", "ai_user_spend_cap_usd")
    op.drop_column("cms_organizations", "ai_spend_cap_usd")
    op.drop_column("cms_generation_jobs", "id_spend")
    op.drop_index("ix_cms_ai_spend_user_time", table_name="cms_ai_spend")
    op.drop_index("ix_cms_ai_spend_org_time", table_name="cms_ai_spend")
    op.drop_table("cms_ai_spend")
