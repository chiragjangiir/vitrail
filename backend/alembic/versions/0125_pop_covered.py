"""Proof of Play : drapeau « recouvert » (preuve non comptabilisée).

Pendant de `screen_off` (migr 0102), pour une autre façon de ne rien montrer.

Depuis P3.6 (migr 0124), un spot de campagne peut RECOUVRIR tout l'écran par-dessus un
template multi-zones. Les autres zones ne sont volontairement pas suspendues — les
suspendre décalerait leur wall-clock et désynchroniserait l'écran au retour — donc
chaque item qui démarre sous le spot appelle `reportPlay` : on atteste la diffusion
d'un contenu que personne ne voit.

⚠️ Le même mécanisme vaut pour le takeover VOD : en multi-zones, `showVodPlayNow`
coupe le son des zones (`_mzSetMuted(true)`) mais `_mzScheduleAdvance` n'a AUCUNE garde
`_vodSuspended` — les zones continuent d'avancer sous un overlay opaque, parfois
plusieurs minutes (mesuré le 2026-08-07). Le mono-zone, lui, est sain : le takeover y
fait `clearTimeout(itemTimer)`, plus rien ne démarre donc plus rien n'est émis.

Chiffré sur la playlist réelle d'Ed : ~11 % du temps de cycle (12 min de boucle dont
81 s de spots).

⛔ Ce n'est PAS une fraude annonceur : les spots ne sont injectés que dans la zone 0,
jamais un spot facturé n'est masqué par un autre. Le coût est ailleurs — ces preuves
gonflent le DÉNOMINATEUR du SOV (antenne totale de l'écran) ⇒ le SOV servi ressort
sous-évalué ⇒ fausse alerte de sous-diffusion, visible par un annonceur.

Décision Ed (2026-08-06) : marquer ces preuves et les exclure des comptages, en les
gardant dans les vues forensiques — exactement le patron `screen_off`.

⚠️ Différence de NATURE avec `screen_off`, qui justifie une colonne distincte plutôt
qu'un drapeau fourre-tout :
  · `screen_off` est calculé PAR LE SERVEUR (lui seul connaît les heures d'ouverture) ;
  · `covered` est déclaré PAR LE PLAYER — lui seul sait qu'un overlay le recouvrait.
Un exploitant qui lit « non comptée » a besoin de savoir laquelle des deux causes ;
et une seule colonne rendrait impossible de dire « écran allumé, mais zone masquée ».

Le drapeau n'entre PAS dans le message signé de la preuve (comme `screen_off`). Le
player est déjà la racine de confiance de l'existence même des preuves : qui voudrait
dissimuler de l'antenne n'aurait qu'à ne rien émettre. Aucune surface d'attaque neuve.

La preuve reste insérée, signée et dans la chaîne Merkle : la vérification d'intégrité
ne filtre JAMAIS sur ce drapeau (une racine partielle est indiscernable d'une chaîne
altérée — même règle que le 23/07).

Revision ID: 0125
Revises: 0124
"""

from alembic import op

revision: str = "0125"
down_revision: str | None = "0124"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table partitionnée par RANGE sur played_at (migr 0007) : l'ALTER sur la table
    # parente se propage aux partitions existantes et futures.
    op.execute(
        "ALTER TABLE cms_proof_of_play "
        "ADD COLUMN covered BOOLEAN NOT NULL DEFAULT false"
    )
    # Index partiel, comme ix_pop_screen_off : seules les lignes marquées le portent
    # (le chemin nominal — les preuves comptées — n'est pas alourdi).
    op.execute(
        "CREATE INDEX ix_pop_covered ON cms_proof_of_play (id_org, played_at) "
        "WHERE covered"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pop_covered")
    op.execute("ALTER TABLE cms_proof_of_play DROP COLUMN covered")
