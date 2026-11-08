#!/bin/sh
# Entrypoint des images backend : derive le nombre de processus uvicorn de la machine.
#
# POURQUOI ICI et pas dans le compose : le compose ne sait pas compter les coeurs. Et pas
# dans l'application non plus : uvicorn forke ses processus AVANT d'importer le code, la
# valeur doit donc etre connue au lancement.
#
# Mesure du 2026-08-08 (400 reconnexions simultanees, cf. deploy/loadtest/) : un processus
# unique CLOUE UN SEUL COEUR a 101 % pendant que le reste de la machine est inoccupe -- 4 %
# sur un serveur a 16 coeurs. Le mur n'a jamais ete la machine, c'etait la serialisation.
# Repartir sur les coeurs divise le delai de reconnexion par 2,5 a 3,8.
#
# `nproc - 1` : on laisse un coeur a l'encodage video, a PostgreSQL et au systeme. Le
# plafond de 8 evite qu'un serveur a 32 coeurs ouvre 32 pools pour un gain deja plat.
# ⚠️ Les pools ne sont PAS multiplies par ce nombre : le budget de connexions est GLOBAL
# et se repartit entre les processus (cf. app/core/pooling.py) -- sinon la garde
# fail-fast de session.py refuserait le demarrage, et elle aurait raison.
#
# Une valeur posee par l'exploitant est TOUJOURS respectee : on ne calcule que le silence.
set -e

# « auto » et la valeur vide veulent dire « calcule-le ». ⚠️ Ce detour n'est pas cosmetique :
# le compose ne sait pas laisser une variable ABSENTE tout en lui donnant un defaut, et une
# variable presente serait lue par pydantic comme un choix EXPLICITE de l'exploitant --
# ce qui desactiverait en silence la repartition automatique des pools.
# On normalise donc TOUJOURS, quelle que soit la commande : ainsi « auto » n'atteint jamais
# l'application, qui attend un entier (celery-beat partage cette image).
case "${WEB_CONCURRENCY:-}" in
    ''|*[!0-9]*)
        if [ "${1:-}" = "uvicorn" ]; then
            # `nproc` reflete les coeurs visibles du conteneur (cpuset/quota compris).
            cores=$(nproc 2>/dev/null || echo 1)
            workers=$((cores - 1))
            [ "$workers" -lt 1 ] && workers=1
            [ "$workers" -gt 8 ] && workers=8
            echo "[entrypoint] $cores coeur(s) detecte(s) -> WEB_CONCURRENCY=$workers"

            # 🔴 INCIDENT DU 2026-08-11 : les coeurs ne sont pas la seule limite. Le budget
            # de connexions PostgreSQL est GLOBAL et se repartit entre les processus ; au
            # dela d'un certain nombre, chacun n'obtient plus un pool utilisable. Une
            # machine a 16 coeurs demandait 8 processus, le pool BYPASSRLS -- celui des
            # WebSockets de players -- tombait a 2 connexions, et des ecrans rataient
            # silencieusement leurs diffusions.
            #
            # On plafonne donc AVANT le fork. Le calcul vit dans app/core/pooling.py :
            # une seule definition, partagee avec le reglage pydantic. Si ce plafond ne
            # peut pas etre lu, on garde la valeur des coeurs et on le DIT : la garde
            # fail-fast de session.py refusera alors le demarrage en nommant les leviers,
            # ce qui est bruyant -- jamais un demarrage avec des pools inutilisables.
            cap=$(python -c 'import os, sys
sys.path.insert(0, "/app")
from app.core.pooling import DEFAULT_CONNECTION_BUDGET, max_workers_for_budget
raw = os.environ.get("CMS_DB_CONNECTION_BUDGET", "").strip()
budget = int(raw) if raw.isdigit() else DEFAULT_CONNECTION_BUDGET
print(max_workers_for_budget(budget))' 2>/dev/null) || cap=""
            case "$cap" in
                ''|*[!0-9]*)
                    echo "[entrypoint] AVERTISSEMENT : plafond de connexions illisible, on garde $workers processus"
                    ;;
                *)
                    if [ "$workers" -gt "$cap" ]; then
                        echo "[entrypoint] budget de connexions -> plafond a $cap processus (au lieu de $workers)"
                        workers="$cap"
                    fi
                    ;;
            esac
        else
            workers=1
        fi
        export WEB_CONCURRENCY="$workers"
        ;;
esac

exec "$@"
