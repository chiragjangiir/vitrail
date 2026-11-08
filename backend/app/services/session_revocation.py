"""Révocation des sessions ouvertes (P1.1, migration 0122).

LE PROBLÈME. Changer le mot de passe de quelqu'un ne fermait aucune de ses sessions :
un JWT est valable tant qu'il n'a pas expiré, et rien ne disait « ce jeton est plus
vieux que la coupure ». Un compte compromis, un départ, une reprise en main d'un
serveur client : le mot de passe changeait, l'accès continuait.

LE MÉCANISME. `cms_users.sessions_valid_from` porte l'instant de la dernière coupure ;
tout jeton utilisateur émis avant est refusé. Deux règles font tout le travail :

  · **la borne est tronquée à la seconde**, parce que `iat` compte des secondes
    entières. Sans ça, un jeton émis dans la même seconde que la coupure paraît plus
    vieux qu'elle et se fait refuser — l'utilisateur se reconnecte, reçoit un jeton
    déjà « périmé », se fait refuser à nouveau : boucle. La comparaison est donc
    STRICTE (`iat < borne`) et un jeton de la seconde même survit. C'est un choix
    assumé : la fenêtre est d'une seconde, la boucle serait permanente ;

  · **l'absence d'`iat` vaut « antérieur »**. Un jeton sans date d'émission a
    forcément été émis avant que ce mécanisme n'existe, donc avant toute borne
    possible. Tant qu'un compte n'a jamais été révoqué (`sessions_valid_from` NULL),
    rien ne change pour lui — c'est l'état de tout le parc au déploiement.

LE PIÈGE QUI FAIT LA TAILLE DU CHANTIER. Borner les seuls jetons d'ACCÈS rendrait la
révocation **décorative** : l'accès reçoit un 401, l'intercepteur du front rafraîchit,
`/auth/refresh` rend un jeton d'accès neuf dont l'`iat` est postérieur à la borne, et
la session survit à sa propre révocation. Le jeton de rafraîchissement porte donc lui
aussi son `iat`, et `/auth/refresh` applique la même comparaison. Une révocation à
moitié faite est pire que pas de révocation : elle fait croire qu'un accès est coupé.
"""

from datetime import datetime, timezone

from app.models.user import CmsUser


def revocation_bound(now: datetime | None = None) -> datetime:
    """L'instant à écrire dans `sessions_valid_from`, **tronqué à la seconde**.

    Le seul constructeur légitime de cette valeur : la poser à la main sans troncature
    est le défaut décrit en tête de module (reconnexion en boucle).
    """
    return (now or datetime.now(timezone.utc)).replace(microsecond=0)


def token_predates_revocation(user: CmsUser, payload: dict) -> bool:
    """Ce jeton a-t-il été émis avant la dernière coupure des sessions de ce compte ?

    Répond False dès que le compte n'a jamais été révoqué — le cas de tout le parc.
    """
    bound = user.sessions_valid_from
    if bound is None:
        return False

    # Colonne TIMESTAMPTZ : la valeur revient aware. La ceinture-bretelle ne coûte
    # rien et évite un TypeError si un chemin de test la pose naïve.
    if bound.tzinfo is None:
        bound = bound.replace(tzinfo=timezone.utc)

    issued_at = payload.get("iat")
    if issued_at is None:
        # Émis avant l'existence même de la borne ⇒ antérieur à n'importe laquelle.
        return True
    try:
        issued = datetime.fromtimestamp(int(issued_at), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        # `iat` illisible : on ne peut pas prouver que le jeton est postérieur à la
        # coupure, et c'est une coupure — la défaillance est FERMÉE.
        return True
    return issued < bound
