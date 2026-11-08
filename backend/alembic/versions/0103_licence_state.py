"""Mémoire de la licence vue par ce serveur (item #5, S3).

Sans cette mémoire, l'application des règles d'expiration a un trou béant : le mode
lecture seule s'appuie sur le fichier de licence, donc **supprimer le fichier** ramène
le serveur à l'état « non licencié »… qui ne verrouille rien. Un client dont la licence
a expiré s'en affranchirait par un `rm licence.json`.

L'inverse est tout aussi inacceptable : faire verrouiller toute installation SANS licence
briquerait, au déploiement de cette version, chaque serveur existant qui n'a pas encore
reçu son fichier — y compris les nôtres. On se punirait soi-même au lieu de punir un
défaut de paiement.

D'où cette table à UNE ligne : dès qu'une licence valide est vue, le serveur s'en
souvient (identifiant, titulaire, date d'expiration). Ensuite :
  · fichier absent + AUCUNE mémoire  → installation jamais licenciée : bandeau, aucun
    verrou (cas d'un parc existant qu'on met à jour, et des bancs de dev) ;
  · fichier absent/invalide + mémoire → on retient la dernière expiration connue, donc
    la grâce puis le verrou s'appliquent comme si le fichier était toujours là ;
  · fichier valide → la mémoire est rafraîchie.

Ce n'est pas un dispositif anti-piratage — un self-hébergé avec les droits root peut
toujours modifier l'image. C'est ce qu'il faut pour que la règle tienne face à une
manipulation ordinaire, et pour que la traçabilité existe.

Revision ID: 0103
Revises: 0102
"""

from alembic import op

revision: str = "0103"
down_revision: str | None = "0102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cms_licence_state (
            -- Contrainte à UNE ligne : l'état est celui du SERVEUR, pas d'un tenant.
            id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            licence_id      VARCHAR(64)  NOT NULL,
            customer        VARCHAR(255) NOT NULL,
            -- NULL = licence perpétuelle (jamais d'expiration à mémoriser).
            expires_at      DATE,
            first_seen_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            last_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            -- Dernier palier de préavis notifié (30 / 15 / 7 / 1). Dédup edge-triggered :
            -- sans lui, la tâche quotidienne re-notifierait chaque jour et l'exploitant
            -- apprendrait à ignorer l'alerte — exactement ce qu'on veut éviter.
            -- Remis à NULL au dépôt d'une licence neuve (le cycle repart).
            warned_threshold SMALLINT
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cms_licence_state")
