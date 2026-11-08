"""Proof of Play : drapeau « écran coupé » (preuve non comptabilisée).

Un Proof of Play atteste un AFFICHAGE (§XXIV). Or la lecture d'une playlist et
l'alimentation de l'écran suivent deux fenêtres indépendantes : les programmations
(`cms_schedules`, fenêtre horaire propre) d'un côté, les heures d'ouverture du site
+ marges lead/lag (auto-power) de l'autre. Quand elles diffèrent, le player continue
de jouer alors que sa sortie vidéo est coupée — et émettait jusqu'ici des preuves
SIGNÉES d'une diffusion que personne n'a pu voir.

Constaté en prod le 2026-07-23 (site Domicile) : ouverture décalée à 08:25, écran
allumé à 08:10 (lead 15 min), programmations en 08:00–19:00 ⇒ 10 minutes d'antenne
attestée sur écran éteint le matin, et 15 minutes d'écran allumé sur l'écran de repli
le soir (contenu arrêté à 19:00, extinction à 19:15).

Décision Ed (2026-07-23) : écran coupé = pas de diffusion, ni pour le contenu standard
ni pour les campagnes Retail Media. La lecture, elle, CONTINUE (la boucle reste ancrée
sur le wall-clock : la sync LAN et la position du contenu restent intactes au
rallumage) — seul le COMPTAGE change.

La preuve est conservée et marquée plutôt que rejetée : « le player a bien joué ce
média, mais l'écran était coupé » est une information d'exploitation, et la chaîne
Merkle reste continue (elle couvre toutes les lignes insérées, la vérification ne
filtre donc JAMAIS sur ce drapeau).

⚠️ Ne concerne que le VISUEL : écran éteint ≠ haut-parleurs éteints. Un magasin peut
couper ses écrans en gardant la musique, et un player audio-only n'a parfois aucun
écran — neutraliser l'audio fausserait la facturation Retail Media Audio.

Revision ID: 0102
Revises: 0101
"""

from alembic import op

revision: str = "0102"
down_revision: str | None = "0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table partitionnée par RANGE sur played_at (migr 0007) : l'ALTER sur la table
    # parente se propage aux partitions existantes et futures.
    op.execute(
        "ALTER TABLE cms_proof_of_play "
        "ADD COLUMN screen_off BOOLEAN NOT NULL DEFAULT false"
    )
    # Les lectures de comptage filtrent systématiquement `screen_off = false` ; l'index
    # partiel ne porte que les lignes marquées (rares par nature) pour les diagnostics
    # « qu'a-t-on joué dans le vide ? » sans alourdir le chemin nominal.
    op.execute(
        "CREATE INDEX ix_pop_screen_off ON cms_proof_of_play (id_org, played_at) "
        "WHERE screen_off"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pop_screen_off")
    op.execute("ALTER TABLE cms_proof_of_play DROP COLUMN screen_off")
