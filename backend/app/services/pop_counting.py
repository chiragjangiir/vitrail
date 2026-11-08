"""Proof of Play — définition UNIQUE de « preuve comptabilisée » (§XXIV).

Une preuve atteste qu'un média a DÉMARRÉ sur un player. Elle n'atteste pas pour autant
que quelqu'un a pu le voir. Deux causes, mesurées en production, séparent les deux :

  · `screen_off` (migr 0102) — la sortie vidéo était programmée éteinte (heures
    d'ouverture du site + marges auto-power). Calculé PAR LE SERVEUR, lui seul connaît
    le calendrier d'alimentation. Visuel uniquement (cf. `services/pop_screen`).
  · `covered`    (migr 0125) — la zone était RECOUVERTE par un overlay plein écran :
    spot de campagne P3.6, ou takeover VOD. Déclaré PAR LE PLAYER, lui seul sait qu'un
    overlay le masquait.

Doctrine constante : on ne jette JAMAIS la preuve, on neutralise le COMPTAGE. La ligne
reste insérée, signée, et dans la chaîne Merkle.

⚠️ APPROXIMATION ASSUMÉE, commune aux deux drapeaux : ils qualifient l'instant de DÉMARRAGE
du média, pas sa durée. Un item de 10 s qui commence 2 s avant un spot plein écran compte
ses 10 s d'antenne bien que 8 s aient été masquées ; à l'inverse un item qui démarre dans
les 2 dernières secondes d'un spot est entièrement exclu. Sur une boucle, les deux erreurs
se compensent largement. Découper une preuve en fractions vues/non vues casserait la chaîne
Merkle (une preuve = une ligne = un hash) pour un gain de précision qui ne change aucune
décision commerciale.

⛔ NE JAMAIS appliquer `COUNTED` aux chemins d'INTÉGRITÉ — `/pop/verify`, le calcul du
`merkle_root` d'un certificat, l'archivage. La chaîne couvre TOUTES les lignes insérées :
la filtrer ferait diverger le recalcul et produirait un faux « chaîne altérée ». Ces
chemins lisent tout et n'excluent que des COMPTEURS affichés.

Ce module existe parce que la condition vivait en QUATRE copies (endpoints analytics,
endpoints pop, services analytics, services campaign_report). Ajouter une seconde cause
à quatre endroits garantissait d'en oublier un — et un agrégat qui compte ce que les
autres excluent ne se voit pas : il donne juste un chiffre légèrement faux.
"""

from __future__ import annotations

from sqlalchemy import and_

from app.models.pop import CmsProofOfPlay

#: Les drapeaux qui retirent une preuve des comptages, dans l'ordre où ils sont apparus.
#: Énumérés ICI et nulle part ailleurs : l'archivage froid (`services/pop_archive`) en dérive
#: les colonnes qu'il lit ET celles qu'il écrit dans le CSV. C'est ce qui manquait — la liste
#: vivait en double dans `pop_worker` (un `SELECT` à 8 colonnes, une constante à 10), les deux
#: ont divergé quand `screen_off` puis `covered` sont arrivées, et les archives auraient rendu
#: une preuve écran coupé ou recouverte comme une diffusion normale. Une archive étant la SEULE
#: trace après le DROP de la partition, cette divergence-là ne se rattrape pas.
NON_COUNTING_FLAGS: tuple[str, ...] = ("screen_off", "covered")

#: Condition SQLAlchemy « cette preuve compte comme de l'antenne ».
COUNTED = and_(
    CmsProofOfPlay.screen_off.is_(False),
    CmsProofOfPlay.covered.is_(False),
)

#: Même condition en SQL brut, pour les rares lectures qui n'utilisent pas l'ORM
#: (assistant, worker de rollup). Sans préfixe de table : à composer avec un alias si
#: la requête en a un (`COUNTED_SQL_FOR("pp")`).
COUNTED_SQL = "NOT screen_off AND NOT covered"


def COUNTED_SQL_FOR(alias: str) -> str:
    """Même condition, qualifiée par l'alias de table de la requête appelante."""
    return f"NOT {alias}.screen_off AND NOT {alias}.covered"
