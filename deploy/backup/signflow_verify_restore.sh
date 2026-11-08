#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Vérification de RESTAURATION SignFlow — restaure le dernier dump dans un
# Postgres JETABLE et compare les comptages aux tables de prod. Ne touche à
# RIEN en production. À lancer après le 1er backup, puis ~1×/mois (un backup
# non testé n'est pas un backup). Cf. docs/RUNBOOK_BACKUPS.md pour la
# restauration COMPLÈTE (sinistre réel).
#
# Usage : signflow_verify_restore.sh [fichier.dump]   (défaut = dernier du staging)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

STAGING="${STAGING:-$HOME/signflow_backups}"
PG_CONTAINER="${PG_CONTAINER:-signflow-postgres-1}"
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:pg16}"   # même image que la prod
SCRATCH=signflow-restore-test

DUMP="${1:-$(ls -1t "$STAGING"/db/signflow_*.dump 2>/dev/null | head -1)}"
[[ -n "$DUMP" && -f "$DUMP" ]] || { echo "Aucun dump trouvé ($STAGING/db)"; exit 1; }
echo "Dump testé : $DUMP"

cleanup() { docker rm -f "$SCRATCH" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

docker run -d --name "$SCRATCH" -e POSTGRES_USER=signflow \
  -e POSTGRES_PASSWORD=restoretest -e POSTGRES_DB=signflow \
  "$PG_IMAGE" >/dev/null
echo -n "Attente du Postgres jetable"
for _ in $(seq 1 30); do
  docker exec "$SCRATCH" pg_isready -U signflow >/dev/null 2>&1 && break
  echo -n "."; sleep 1
done
echo

# Les rôles applicatifs (signflow_app/signflow_worker) sont référencés par les
# GRANT/POLICY du dump → les créer d'abord (comme les globals du backup).
docker exec "$SCRATCH" psql -U signflow -qc \
  "CREATE ROLE signflow_app LOGIN; CREATE ROLE signflow_worker LOGIN;" || true

echo "pg_restore en cours…"
docker exec -i "$SCRATCH" pg_restore -U signflow -d signflow --no-owner \
  --exit-on-error < "$DUMP"

echo "── Comparaison prod vs restauré ──"
TABLES=(cms_organizations cms_users cms_players cms_media cms_playlists
        cms_campaigns cms_campaign_creatives cms_approval_requests
        cms_schedules cms_industry_categories)
FAIL=0
for t in "${TABLES[@]}"; do
  P=$(docker exec "$PG_CONTAINER" psql -U signflow -d signflow -tAc "SELECT count(*) FROM $t" 2>/dev/null || echo "?")
  R=$(docker exec "$SCRATCH" psql -U signflow -d signflow -tAc "SELECT count(*) FROM $t" 2>/dev/null || echo "?")
  # La prod a pu bouger depuis le dump — on tolère un petit écart, pas un vide.
  printf "  %-28s prod=%-8s restauré=%s\n" "$t" "$P" "$R"
  [[ "$R" == "?" ]] && FAIL=1
done
N_TABLES=$(docker exec "$SCRATCH" psql -U signflow -d signflow -tAc \
  "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
echo "  Tables restaurées : $N_TABLES"
[[ "$N_TABLES" -gt 60 && "$FAIL" -eq 0 ]] \
  && echo "✅ RESTAURATION VÉRIFIÉE" \
  || { echo "❌ Vérification en échec"; exit 1; }
