#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
#  Vitrail — Arret propre des services (Linux / Ubuntu)
#  Usage    : ./demo-stop.sh
#  Options  : ./demo-stop.sh --volumes   (supprime aussi les volumes Docker)
#             ./demo-stop.sh --prune     (nettoie images/reseaux orphelins)
# ════════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOLUMES=false
PRUNE=false

for arg in "$@"; do
    case "$arg" in
        --volumes) VOLUMES=true ;;
        --prune)   PRUNE=true ;;
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
cyan "  ║   Vitrail       —  Arret                            ║"
cyan "  ╚══════════════════════════════════════════════════════╝"
echo ""

if $VOLUMES; then
    red "  ATTENTION : mode --volumes — les donnees PostgreSQL et MinIO seront supprimees !"
    echo ""
    read -r -p "  Tapez OUI pour confirmer : " CONFIRM
    if [[ "$CONFIRM" != "OUI" ]]; then yellow "  Annule."; exit 0; fi
fi

# ── 1. Verification Docker ────────────────────────────────────────────────────
step 1 "Verification Docker"

command -v docker >/dev/null 2>&1 || fail "Docker introuvable."
docker info >/dev/null 2>&1       || fail "Docker non demarre."
DOCKER_VER=$(docker info --format "{{.ServerVersion}}" 2>/dev/null)
ok "Docker $DOCKER_VER"

# ── 2. Arret des containers ───────────────────────────────────────────────────
step 2 "Arret des containers Vitrail"

DOWN_ARGS=""
if $VOLUMES; then
    DOWN_ARGS="-v"
    info "docker compose down -v (volumes supprimes)"
else
    info "docker compose down (volumes conserves)"
fi

echo ""
# shellcheck disable=SC2086
docker compose down $DOWN_ARGS || warn "Arret avec erreur (peut etre normal si deja arrete)"
ok "Containers arretes"

# ── 3. Nettoyage optionnel ────────────────────────────────────────────────────
if $PRUNE; then
    echo ""
    step 3 "Nettoyage Docker (images/reseaux orphelins)"
    docker system prune -f
    ok "Nettoyage termine"
fi

# ── 4. Verification finale ────────────────────────────────────────────────────
echo ""
step 4 "Verification — containers Vitrail restants"
echo ""

REMAINING=$(docker compose ps --filter "status=running" --format "{{.Name}}" 2>/dev/null || true)
if [[ -n "$REMAINING" ]]; then
    warn "Ces containers sont encore actifs :"
    echo "$REMAINING" | while IFS= read -r c; do yellow "      $c"; done
else
    ok "Aucun container Vitrail actif"
fi

# ── Resume ────────────────────────────────────────────────────────────────────
echo ""
cyan "  ════════════════════════════════════════════════════════"
if $VOLUMES; then
    red   "   ARRET COMPLET — donnees supprimees"
    gray  "   La BDD sera reinitialisee au prochain demarrage"
else
    green "   ARRET PROPRE — donnees conservees"
fi
gray "   Relance : ./demo-start.sh"
cyan "  ════════════════════════════════════════════════════════"
echo ""
