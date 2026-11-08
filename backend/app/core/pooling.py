"""Dimensionnement des pools de connexions en fonction du nombre de processus backend.

🔑 **Le budget est GLOBAL, pas par processus.** PostgreSQL compte des connexions, pas des
processus : ce qu'il faut tenir constant, c'est le total. Garder des pools fixes en
multipliant les processus, c'est exactement le mode de défaillance décrit par
`assert_pool_budget_fits` — la configuration paraît saine, tout va bien au repos, et c'est
la rafale de reconnexions qui épuise la réserve. Une base qui refuse une connexion ne
dégrade pas, elle casse.

On répartit donc un budget fixe entre les processus, au lieu de multiplier une valeur fixe
par leur nombre.

⚠️ **Invariant tenu par un test** : à UN processus, la répartition rend EXACTEMENT les
valeurs historiques (10 / 20 / 5 / 10). Une installation qui reste mono-processus — toute
machine à un ou deux cœurs — ne voit donc strictement aucun changement. Un réglage qui se
serait mis à rétrécir les pools des installations existantes aurait été une régression
silencieuse, du genre qui ne se voit qu'un jour de pointe.

🔴 **INCIDENT DU 2026-08-11 — pourquoi il y a des PLANCHERS PAR POOL depuis le 12/08.**
La répartition au seul prorata historique laissait le pool BYPASSRLS s'effondrer à mesure
que les processus se multipliaient : à 8 processus pour un budget de 60, elle rendait
`BYPASSRLS 1 + 1 = 2`. Or ce pool n'a rien d'un pool de maintenance sur ce produit — c'est
celui qu'empruntent **toutes les WebSockets de players** (règle du projet : un endpoint
authentifié player passe par `get_db_worker`) **et `force_sync`**. Mesuré en production :
`QueuePool limit of size 1 overflow 1`, **502 échecs de force_sync**, des 500 sur
`/players/`, et surtout ce qui se voit chez le client — **4 écrans sur 8 n'ont pas
diffusé** une occurrence d'événement. Pendant ce temps PostgreSQL était à **24 connexions
sur 100** : ce n'est pas la base qui manquait de place, c'est notre propre arithmétique.

Le prorata `10/20/5/10` décrit un serveur où l'essentiel du trafic est l'interface web.
La réalité mesurée est l'inverse : les écrans se synchronisent en permanence, chacun ouvrant
une courte transaction (relevé le 12/08 : 8 connexions `signflow_worker` en
`idle in transaction`, transactions de 0 à 9 s, pour 8 écrans en ligne) ⇒ **le besoin
BYPASSRLS d'un processus suit le nombre d'écrans qui lui sont rattachés**, et un processus
à 2 connexions s'épuise dès que trois écrans se synchronisent ensemble.

⚠️ **Les planchers ne sont pas choisis au jugé, ils sont les valeurs MESURÉES** : `2 + 4`
est la configuration qui tourne proprement en production (0 échec), `1 + 1` est celle qui a
cassé. On prend donc la première comme plancher, on n'invente pas un nombre.
"""

from __future__ import annotations

# Connexions PostgreSQL que l'ENSEMBLE des processus backend a le droit de consommer.
# Défini ICI et pas dans `config.py` pour qu'il n'existe qu'une seule définition : le
# réglage pydantic ET l'entrypoint de l'image (qui plafonne le nombre de processus) la
# lisent au même endroit.
DEFAULT_CONNECTION_BUDGET = 60

# Valeurs historiques (avant P3.12) : elles servent de PLAFOND par processus. Au-delà, on
# ouvrirait des connexions dont on a mesuré qu'elles ne servent pas — le pic réel mesuré le
# 2026-08-08 sur une rafale de 400 reconnexions est de 31 connexions TOUTES origines
# confondues, pour un plafond théorique de 45 par processus.
_DEFAULTS = (10, 20, 5, 10)
_DEFAULT_TOTAL = sum(_DEFAULTS)

# Planchers PAR POOL, en deçà desquels un processus ne peut plus faire son travail.
#   - applicatif 2 + 2 : servir une requête d'interface pendant qu'une autre est en vol ;
#   - BYPASSRLS  2 + 4 : la configuration mesurée SAINE en production (cf. en-tête). C'est
#     le pool des écrans : le sous-dimensionner ne ralentit pas le serveur, il fait
#     silencieusement rater des diffusions.
_FLOOR_APP_POOL, _FLOOR_APP_OVERFLOW = 2, 2
_FLOOR_WORKER_POOL, _FLOOR_WORKER_OVERFLOW = 2, 4

# Plancher par processus = somme des quatre. C'est lui qui borne le nombre de processus
# qu'un budget donné peut réellement soutenir (cf. `max_workers_for_budget`).
_MIN_PER_PROCESS = (
    _FLOOR_APP_POOL + _FLOOR_APP_OVERFLOW + _FLOOR_WORKER_POOL + _FLOOR_WORKER_OVERFLOW
)


def split_per_process(per_process: int) -> tuple[int, int, int, int]:
    """Répartit un budget par processus entre les quatre pools, au prorata historique.

    Chaque pool a un plancher : le prorata décide du partage tant qu'il reste au-dessus,
    jamais en dessous. Le reste de la division est donné à `max_overflow` applicatif :
    c'est le pool élastique, celui qui n'immobilise rien tant qu'il ne sert pas.
    """
    per_process = max(_MIN_PER_PROCESS, per_process)
    pool = max(_FLOOR_APP_POOL, per_process * _DEFAULTS[0] // _DEFAULT_TOTAL)
    wpool = max(_FLOOR_WORKER_POOL, per_process * _DEFAULTS[2] // _DEFAULT_TOTAL)
    wover = max(_FLOOR_WORKER_OVERFLOW, per_process * _DEFAULTS[3] // _DEFAULT_TOTAL)
    over = max(_FLOOR_APP_OVERFLOW, per_process - pool - wpool - wover)
    return pool, over, wpool, wover


def derive_pool_sizes(workers: int, budget: int) -> tuple[int, int, int, int]:
    """Tailles des quatre pools d'UN processus backend, pour `workers` processus.

    Rendre le budget entier au processus unique serait tentant, mais on plafonne aux
    valeurs historiques : au-delà, ce sont des connexions que la mesure dit inutiles, et
    elles seraient prises sur la réserve de Celery et de la maintenance.

    ⚠️ On ne descend JAMAIS sous les planchers pour faire rentrer le calcul. Si le budget
    ne peut pas les couvrir pour tous les processus, c'est `assert_pool_budget_fits` qui
    refuse le démarrage en nommant les leviers — un serveur qui part avec un pool
    inutilisable est pire qu'un serveur qui refuse de partir en le disant.
    """
    workers = max(1, workers)
    per_process = min(_DEFAULT_TOTAL, max(_MIN_PER_PROCESS, budget // workers))
    return split_per_process(per_process)


def max_workers_for_budget(budget: int) -> int:
    """Combien de processus backend ce budget de connexions peut réellement soutenir.

    Consulté par l'entrypoint de l'image AVANT que uvicorn ne forke : sans ce plafond, une
    machine à 16 cœurs demanderait 8 processus, le budget ne pourrait pas leur donner leur
    plancher, et la garde refuserait de démarrer — un serveur client qui ne redémarre plus
    après une mise à jour. On rend donc moins de processus plutôt qu'un service mort, et
    l'exploitant garde le levier : relever `CMS_DB_CONNECTION_BUDGET` (après avoir relevé
    `max_connections` côté PostgreSQL) rend les processus perdus.

    Jamais moins de 1 : un budget absurde doit produire un refus explicite de la garde, pas
    un nombre de processus nul.
    """
    return max(1, budget // _MIN_PER_PROCESS)
