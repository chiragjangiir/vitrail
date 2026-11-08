#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
#  SignFlow CMS — Demarrage dev / production (Linux / Ubuntu)
#  Usage    : ./demo-start.sh
#  Options  : ./demo-start.sh --quick    (DB + MinIO + Backend uniquement)
#             ./demo-start.sh --full     (+ Mailpit)
#             ./demo-start.sh --force    (recrée les containers)
# ════════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUICK=false
FULL=false
FORCE=false

for arg in "$@"; do
    case "$arg" in
        --quick) QUICK=true ;;
        --full)  FULL=true ;;
        --force) FORCE=true ;;
        *) echo "Option inconnue : $arg" >&2; exit 1 ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
cyan()   { printf "\033[36m%s\033[0m\n"  "$*"; }
green()  { printf "\033[32m%s\033[0m\n"  "$*"; }
yellow() { printf "\033[33m%s\033[0m\n"  "$*"; }
red()    { printf "\033[31m%s\033[0m\n"  "$*"; }
gray()   { printf "\033[90m%s\033[0m\n"  "$*"; }
white()  { printf "\033[97m%s\033[0m\n"  "$*"; }
step()   { cyan   "  [$1] $2"; }
ok()     { green  "      OK  $*"; }
info()   { gray   "      ..  $*"; }
warn()   { yellow "      !!  $*"; }
fail()   { red    "      ERR $*"; exit 1; }

cd "$SCRIPT_DIR"

# ── En-tete ───────────────────────────────────────────────────────────────────
clear
echo ""
cyan "  ╔══════════════════════════════════════════════════════╗"
cyan "  ║   SignFlow CMS  —  Demarrage                        ║"
cyan "  ╚══════════════════════════════════════════════════════╝"
echo ""

if $QUICK; then MODE="RAPIDE (DB + MinIO + Backend)"
elif $FULL; then MODE="COMPLET (+ Mailpit)"
else             MODE="STANDARD (Backend + Workers + Frontend)"
fi
yellow "  Mode : $MODE"
echo ""

# ── 1. Prerequisites ──────────────────────────────────────────────────────────
step 1 "Verification des prerequis"

# curl
if ! command -v curl >/dev/null 2>&1; then
    info "curl absent — installation..."
    sudo apt-get update -qq && sudo apt-get install -y -qq curl
fi
ok "curl $(curl --version 2>/dev/null | head -1 | awk '{print $2}')"

# Docker
if ! command -v docker >/dev/null 2>&1; then
    warn "Docker absent — installation via get.docker.com..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo ""
    yellow "  Docker installe. Ajout au groupe docker effectue."
    yellow "  Fermez ce terminal, ouvrez-en un nouveau et relancez :"
    yellow "      ./demo-start.sh $*"
    exit 0
fi

if ! docker info >/dev/null 2>&1; then
    if sudo docker info >/dev/null 2>&1; then
        warn "Docker accessible uniquement avec sudo — ajout de $USER au groupe docker..."
        sudo usermod -aG docker "$USER"
        yellow "  Fermez ce terminal, ouvrez-en un nouveau et relancez : ./demo-start.sh $*"
        exit 0
    else
        fail "Docker non demarre. Lancez : sudo systemctl start docker"
    fi
fi
DOCKER_VER=$(docker info --format "{{.ServerVersion}}" 2>/dev/null)
ok "Docker $DOCKER_VER"

# Docker Compose plugin
if ! docker compose version >/dev/null 2>&1; then
    warn "Docker Compose plugin absent — installation..."
    sudo apt-get update -qq && sudo apt-get install -y -qq docker-compose-plugin
fi
ok "Docker Compose $(docker compose version --short 2>/dev/null || echo 'ok')"

# ── 2. Configuration ──────────────────────────────────────────────────────────
step 2 "Verification configuration"

if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        cp ".env.example" ".env"
        warn ".env cree depuis .env.example — verifiez CMS_JWT_SECRET avant de continuer"
    else
        fail ".env absent et .env.example introuvable."
    fi
else
    ok ".env present"
    if ! grep -qE "^MINIO_PUBLIC_ENDPOINT\s*=\s*\S" ".env"; then
        warn "MINIO_PUBLIC_ENDPOINT absent du .env -- vignettes et lecture video seront cassees !"
        warn "Ajoutez : MINIO_PUBLIC_ENDPOINT=localhost:9000 (dev) ou IP_SERVEUR:9000 (prod)"
    fi
fi

if [[ -f "docker-compose.override.yml" ]]; then
    ok "Override detecte (ports remappes)"
    HAS_OVERRIDE=true
else
    warn "docker-compose.override.yml absent — ports standard (5432/6379/8000)"
    warn "Si une autre stack tourne aussi sur ce serveur, creez l'override avec les ports remappes."
    HAS_OVERRIDE=false
fi

# ── 3. Demarrage des containers ───────────────────────────────────────────────
step 3 "Demarrage des services"

# ⚠️ TOUT SERVICE DE PRODUCTION DOIT FIGURER ICI.
# `demo-stop.sh` fait un `docker compose down` : il arrête TOUT. Si un service
# manque de ces listes, il reste éteint après un cycle stop/start — sans le
# moindre message. Vécu le 2026-07-20 : `litellm` absent de la liste, donc arrêté
# depuis un cycle précédent, et personne ne l'a vu parce que RIEN n'échoue tant
# qu'on ne réindexe pas la documentation de l'assistant. L'étape 7bis ci-dessous
# compare désormais les services DÉFINIS aux services DÉMARRÉS.
BASE_SERVICES="postgres redis minio postgres-test-db backend"
WORKER_SERVICES="celery-worker celery-media celery-beat celery-screenshot frontend"
# litellm  = proxy LLM (assistant §XXVII + indexation de la doc)
# feed-proxy = récupération des flux §XXV
PROD_SERVICES="litellm feed-proxy"
# Services de confort, hors production : mailpit (SMTP de test), ollama (LLM local)
EXTRA_SERVICES="mailpit ollama"

if $QUICK; then
    SERVICES="$BASE_SERVICES"
elif $FULL; then
    SERVICES="$BASE_SERVICES $WORKER_SERVICES $PROD_SERVICES $EXTRA_SERVICES"
else
    SERVICES="$BASE_SERVICES $WORKER_SERVICES $PROD_SERVICES"
fi

info "Services : $SERVICES"

FORCE_FLAG=""
$FORCE && FORCE_FLAG="--force-recreate"

echo ""
# shellcheck disable=SC2086
docker compose up -d $FORCE_FLAG $SERVICES \
    || warn "Certains containers ont eu des erreurs — verifiez : docker compose logs --tail 20"

# Port effectif du backend
BACKEND_PORT=$(docker compose port backend 8000 2>/dev/null | grep -oE '[0-9]+$' | head -1 || echo "8000")

# ── 4. Health check backend ───────────────────────────────────────────────────
echo ""
step 4 "Attente du backend (max 60s)"

MAX_WAIT=60
ELAPSED=0
HEALTHY=false

while [[ $ELAPSED -lt $MAX_WAIT ]]; do
    CODE=$(curl -s --max-time 3 -o /dev/null -w "%{http_code}" \
           "http://localhost:$BACKEND_PORT/health" 2>/dev/null || echo "000")
    if [[ "$CODE" == "200" ]]; then HEALTHY=true; break; fi
    gray "      [${ELAPSED}s] Backend en demarrage..."
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

if $HEALTHY; then ok "Backend healthy (http://localhost:$BACKEND_PORT/health)"
else              warn "Backend non healthy apres ${ELAPSED}s — verifiez : docker compose logs backend --tail 30"
fi

# ── 5. Migrations Alembic + bucket MinIO ─────────────────────────────────────
echo ""
step 5 "Migrations Alembic + bucket MinIO"

if $HEALTHY; then
    info "Alembic upgrade head..."
    docker compose exec -T backend alembic upgrade head 2>&1 | grep -v "^$" || true
    ok "Migrations appliquees"

    info "Creation bucket signflow-media..."
    docker compose exec -T backend python /app/scripts/create_bucket.py 2>&1 || true
    ok "Bucket MinIO pret"
else
    warn "Backend non disponible — lancez 'make dev-init' manuellement apres demarrage."
fi

# ── 6. Smoke test API ─────────────────────────────────────────────────────────
echo ""
step 6 "Smoke test API"

FAIL=0
_check() {
    local label="$1" url="$2" expected="$3"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")
    if [[ "$code" == "$expected" ]]; then
        ok "  $label -> $code"
    else
        red "  FAIL $label -> $code (attendu $expected)"
        FAIL=$((FAIL + 1))
    fi
}

if $HEALTHY; then
    API="http://localhost:$BACKEND_PORT/api/v1"
    _check "GET /health"    "http://localhost:$BACKEND_PORT/health"  "200"
    _check "GET /players"   "$API/players/"                           "401"
    _check "GET /media"     "$API/media/"                             "401"
    _check "GET /templates" "$API/templates"                          "401"
    _check "GET /playlists" "$API/playlists/"                         "401"
    _check "GET /schedules" "$API/schedules"                          "401"

    echo ""
    if [[ $FAIL -eq 0 ]]; then ok "Smoke test : 6/6 OK"
    else                        red "Smoke test : $FAIL endpoint(s) en echec"
    fi
else
    warn "Backend non disponible — smoke test ignore"
fi

# ── 7. Statut des containers ──────────────────────────────────────────────────
echo ""
step 7 "Statut des containers"
echo ""
docker compose ps --format "table {{.Name}}\t{{.Status}}" | while IFS= read -r line; do
    if   echo "$line" | grep -q "healthy";    then green  "  $line"
    elif echo "$line" | grep -q "starting";   then yellow "  $line"
    elif echo "$line" | grep -q "Exited (0)"; then gray   "  $line"
    elif echo "$line" | grep -q "Exited\|Error"; then red "  $line"
    else white "  $line"
    fi
done

# ── 7bis. Services definis mais NON demarres ─────────────────────────────────
# Le vrai piege n'est pas qu'un service tombe : c'est qu'il reste eteint sans que
# rien ne le dise. On compare donc ce que le compose DEFINIT a ce qui TOURNE.
echo ""
step "7b" "Services definis mais non demarres"
DEFINED=$(docker compose config --services 2>/dev/null | sort)
RUNNING=$(docker compose ps --format "{{.Service}}" 2>/dev/null | sort -u)
MISSING=$(comm -23 <(echo "$DEFINED") <(echo "$RUNNING"))
if [[ -z "$MISSING" ]]; then
    ok "Tous les services definis sont demarres"
else
    echo ""
    for svc in $MISSING; do
        case "$svc" in
            mailpit|ollama|postgres-test-db)
                gray  "      -- $svc (hors production, normal)" ;;
            *)
                warn "$svc DEFINI mais NON demarre" ;;
        esac
    done
    echo ""
    gray  "      Pour en demarrer un : docker compose up -d <service>"
fi

# ── 8. Informations d'acces ───────────────────────────────────────────────────
MAILPIT_PORT=$(if $HAS_OVERRIDE; then echo "8026"; else echo "8025"; fi)
FRONTEND_PORT=$(if $HAS_OVERRIDE; then echo "3010"; else echo "3000"; fi)

echo ""
cyan "  ════════════════════════════════════════════════════════"
cyan "   SIGNFLOW PRET — Acces"
cyan "  ════════════════════════════════════════════════════════"
echo ""
white "   Backend API    : http://localhost:$BACKEND_PORT"
white "   API Docs       : http://localhost:$BACKEND_PORT/api/docs"
white "   MinIO Console  : http://localhost:9001  (minioadmin / minioadmin)"
if ! $QUICK; then
    white "   Frontend       : http://localhost:$FRONTEND_PORT"
fi
if $FULL; then
    white "   Mailpit        : http://localhost:$MAILPIT_PORT"
fi
echo ""
gray  "   Tests          : make test"
gray  "   Logs backend   : docker compose logs -f backend"
gray  "   Arret          : ./demo-stop.sh"
echo ""
