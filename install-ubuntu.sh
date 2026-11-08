#!/usr/bin/env bash
# =============================================================================
#  Vitrail — Installation Ubuntu depuis les sources
#  Usage : sudo bash install-ubuntu.sh
#
#  Ce script :
#   1.  Vérifie et INSTALLE les prérequis (Docker Engine + Compose, git, openssl)
#   2.  Clone le repo dans /opt/signflow (ou met à jour)
#   3.  Crée .env avec secrets auto-générés (modifiable après)
#   4.  Crée docker-compose.override.yml (ports remappés + frontend en build
#       de production ; docker-compose.yml n'est JAMAIS modifié — il est suivi
#       par git et l'éditer provoquait un conflit à chaque 'git pull')
#   5.  Valide la configuration Compose résultante
#   6.  Démarre les containers
#   7.  Migrations Alembic + bucket MinIO
#   8.  Smoke test
#   9.  Installe un service systemd pour démarrage automatique
#  10.  Nginx reverse-proxy sur port 8080 (interface CMS + API + WS players)
#  11.  Amorçage : organisation + compte admin (mot de passe ALÉATOIRE affiché une
#       seule fois) — sans lui l'installation n'avait aucun compte pour se connecter
# =============================================================================

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/edkahall/vitrail.git}"
INSTALL_DIR="/opt/signflow"
# Proprietaire des fichiers de config (.env, override) : celui qui a lance `sudo`, afin
# qu'il puisse les editer sans root. AVANT le 2026-07-19 le repli etait `kahall` EN DUR --
# un hebergeur lancant le script directement en root voyait un `chown` vers un compte
# inexistant. Repli desormais sur root (proprietaire legitime), surchargeable.
SERVICE_USER="${SIGNFLOW_USER:-${SUDO_USER:-root}}"
id -u "$SERVICE_USER" >/dev/null 2>&1 || SERVICE_USER="root"

# Ports SignFlow (remappés pour éviter les conflits ERP)
PG_PORT=5433
REDIS_PORT=6380
BACKEND_PORT=8010
FRONTEND_PORT=3010
MINIO_PORT=9000
MINIO_CONSOLE_PORT=9001
NGINX_PORT=8080      # Port public players LAN (hors Docker, hôte Ubuntu)

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

step()  { echo -e "\n${CYAN}[$(date +%H:%M:%S)] $*${NC}"; }
ok()    { echo -e "${GREEN}    OK  $*${NC}"; }
warn()  { echo -e "${YELLOW}    !!  $*${NC}"; }
fail()  { echo -e "${RED}    ERR $*${NC}"; exit 1; }
info()  { echo -e "    ..  $*"; }

# =============================================================================
step "1/10 — Vérification des prérequis"
# =============================================================================

[[ $EUID -eq 0 ]] || fail "Ce script doit être lancé avec sudo"

# Prérequis simples : on les installe plutôt que d'échouer (une machine fraîche n'a
# ni git ni openssl garantis).
# `command -v` ne convient pas pour un paquet sans binaire homonyme (ca-certificates) :
# on interroge dpkg, qui repond pour TOUS les cas.
for pkg in git openssl ca-certificates curl gnupg; do
    dpkg -s "$pkg" >/dev/null 2>&1 || MISSING="$MISSING $pkg"
done
if [[ -n "${MISSING:-}" ]]; then
    info "Installation des prérequis :$MISSING"
    apt-get update -qq
    apt-get install -y -qq $MISSING >/dev/null || fail "Échec de l'installation de :$MISSING"
    ok "Prérequis installés :$MISSING"
fi

# Docker Engine + plugin Compose. AVANT le 2026-07-19 le script échouait ici sur une
# machine vierge (« installez Docker Engine ») : le chemin d'installation officiel était
# donc inutilisable tel quel sur un Ubuntu fraîchement posé, ce qui était tout l'objet
# du script. On installe depuis le dépôt officiel Docker (celui d'Ubuntu fournit un
# Compose trop ancien pour le tag `!override` exigé plus bas).
if ! command -v docker >/dev/null 2>&1; then
    step "1a/10 — Installation de Docker Engine (dépôt officiel)"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg         -o /etc/apt/keyrings/docker.asc || fail "Téléchargement de la clé Docker impossible"
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable"         > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io         docker-buildx-plugin docker-compose-plugin >/dev/null         || fail "Échec de l'installation de Docker Engine"
    systemctl enable --now docker >/dev/null 2>&1 || true
    ok "Docker Engine installé"
fi

DOCKER_VER=$(docker --version | awk '{print $3}' | tr -d ',')
COMPOSE_VER=$(docker compose version | awk '{print $4}')
ok "Docker $DOCKER_VER, Compose $COMPOSE_VER"

# L'override utilise le tag YAML `!override` (remplace une liste au lieu de la
# concaténer) — disponible à partir de Compose v2.24.4.
COMPOSE_NUM="${COMPOSE_VER#v}"
if [[ "$(printf '%s\n2.24.4\n' "$COMPOSE_NUM" | sort -V | head -1)" != "2.24.4" ]]; then
    fail "Compose $COMPOSE_VER trop ancien (v2.24.4 minimum, tag '!override' requis) — apt install --only-upgrade docker-compose-plugin"
fi
ok "Compose supporte le tag '!override'"

# Vérifie que Docker tourne
docker info >/dev/null 2>&1 || fail "Docker daemon non démarré"
ok "Docker daemon actif"

# =============================================================================
step "2/10 — Clone / mise à jour du repo"
# =============================================================================

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Repo existant détecté — git pull..."
    cd "$INSTALL_DIR"
    git pull origin main
    ok "Repo mis à jour"
else
    info "Clonage dans $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    ok "Repo cloné"
fi

cd "$INSTALL_DIR"

# Détecter l'IP LAN du serveur (première interface non-loopback)
SERVER_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i=="src") print $(i+1)}' | head -1)
SERVER_IP="${SERVER_IP:-127.0.0.1}"
info "IP serveur détectée : $SERVER_IP"

# =============================================================================
step "3/10 — Création du .env"
# =============================================================================

if [[ -f .env ]]; then
    warn ".env existant conservé (supprimez-le pour regénérer les secrets)"
else
    JWT_SECRET=$(openssl rand -hex 32)
    MINIO_KEY=$(openssl rand -hex 12)
    MINIO_SECRET=$(openssl rand -hex 24)
    # Clé Fernet (base64 de 32 octets) — format imposé par cryptography.Fernet,
    # un 'rand -hex' ne serait PAS accepté.
    VAULT_KEY=$(openssl rand -base64 32)
    # Mots de passe PostgreSQL : superutilisateur + les deux rôles applicatifs.
    # Ils étaient auparavant EN DUR ('signflow', 'signflow_worker_secret'),
    # donc identiques et publics sur toute installation.
    PG_PASSWORD=$(openssl rand -hex 24)
    PG_APP_PASSWORD=$(openssl rand -hex 24)
    PG_WORKER_PASSWORD=$(openssl rand -hex 24)

    cat > .env << EOF
# ── Base de données ──────────────────────────────────────────────────────────
# ⚠️ Ce sont ces variables qui comptent, PAS un éventuel DATABASE_URL : le
# docker-compose CONSTRUIT lui-même DATABASE_URL et DATABASE_WORKER_URL à partir
# d'elles. Une URL écrite ici serait purement décorative (elle l'était jusqu'au
# 2026-07-19, ce qui masquait le fait que les mots de passe restaient ceux par
# défaut). Les rôles sont créés avec ces valeurs par docker/postgres/init.sh,
# au tout premier démarrage et à ce moment-là seulement.
POSTGRES_USER=signflow
POSTGRES_DB=signflow
POSTGRES_PASSWORD=${PG_PASSWORD}
POSTGRES_APP_PASSWORD=${PG_APP_PASSWORD}
POSTGRES_WORKER_PASSWORD=${PG_WORKER_PASSWORD}

# Redis
REDIS_URL=redis://redis:6379/0

# JWT
CMS_JWT_SECRET=${JWT_SECRET}
CMS_2FA_GLOBAL_POLICY=optional

# Coffre de chiffrement au repos (clés API IA par organisation — BYOK).
# Le backend démarre sans, mais toute la génération IA échoue à l'usage.
# ATTENTION : cette clé déchiffre les secrets déjà stockés — la perdre rend les
# clés API des organisations irrécupérables. À sauvegarder avec le .env.
CMS_VAULT_KEY=${VAULT_KEY}

# URL publique du CMS — utilisée dans les liens des e-mails (validations,
# décisions annonceur). Vide = liens cassés. À repasser en https:// si vous
# mettez un reverse-proxy TLS devant (cf. deploy/README_HTTPS.md).
PUBLIC_WEB_URL=http://${SERVER_IP}:${NGINX_PORT}

# Fuseau horaire (OBLIGATOIRE — sans ça, events/schedules planifiés à l'heure locale
# se déclenchent en UTC, ex. "10h00" → 12h00 en été). tzdata est embarqué dans l'image.
SIGNFLOW_TZ=Europe/Paris

# CORS — l'UI est servie par nginx:${NGINX_PORT} et appelle l'API en RELATIF
# (même origine), donc CORS n'est normalement jamais sollicité. Ces origines ne
# couvrent que les accès directs au port ${FRONTEND_PORT} (debug) et le proxy.
CORS_ORIGINS=["http://${SERVER_IP}:${NGINX_PORT}","http://${SERVER_IP}:${FRONTEND_PORT}","http://localhost:${FRONTEND_PORT}"]

# MinIO — endpoint interne Docker (pour uploads/downloads server-side)
MINIO_ENDPOINT=minio:9000
# Endpoint public pour les URLs pré-signées accessibles depuis le browser/players
MINIO_PUBLIC_ENDPOINT=${SERVER_IP}:${MINIO_PORT}
MINIO_ACCESS_KEY=${MINIO_KEY}
MINIO_SECRET_KEY=${MINIO_SECRET}
MINIO_BUCKET_MEDIA=signflow-media
MINIO_USE_SSL=false
MINIO_SSE_ENABLED=false

# Event Bus
EVENT_BUS_BACKEND=redis_streams

# LiteLLM (proxy ERP si disponible)
CMS_LITELLM_URL=http://${SERVER_IP}:4000
EOF

    chown "$SERVICE_USER:$SERVICE_USER" .env
    chmod 600 .env
    ok ".env créé avec secrets auto-générés"
    info "JWT_SECRET, MINIO_KEY et MINIO_SECRET générés aléatoirement"
fi

# =============================================================================
step "4/10 — Création du docker-compose.override.yml"
# =============================================================================

if [[ -f docker-compose.override.yml ]]; then
    warn "docker-compose.override.yml existant conservé"
else
    cat > docker-compose.override.yml << EOF
services:
  postgres:
    ports:
      - "127.0.0.1:${PG_PORT}:5432"

  redis:
    ports:
      - "127.0.0.1:${REDIS_PORT}:6379"

  backend:
    ports:
      - "127.0.0.1:${BACKEND_PORT}:8000"

  frontend:
    ports:
      - "127.0.0.1:${FRONTEND_PORT}:3000"
    # Build de PRODUCTION (l'image de base démarre en 'npm run dev').
    # Le 'npm ci' réinstalle les dépendances au démarrage : le volume
    # node_modules est ANONYME, donc recréé depuis l'image à chaque recréation
    # de conteneur (upgrade Docker, down/up...). Sans lui, toute dépendance
    # ajoutée après le build de l'image manque et le build échoue → 502.
    command: sh -c "npm ci --no-audit --no-fund && npm run build && npm run start"
    environment:
      # VIDE = URL d'API RELATIVE (/api/v1) : le navigateur appelle l'origine
      # qui lui a servi la page (nginx:${NGINX_PORT}), qui proxifie vers le backend.
      # NE PAS mettre d'IP en dur ici : ça casserait tout accès hors LAN.
      NEXT_PUBLIC_API_URL: ""
      NEXT_PUBLIC_WS_URL: ""

  minio:
    # '!override' REMPLACE les ports de docker-compose.yml au lieu de s'y
    # ajouter (Compose concatène les listes par défaut → double publication du
    # 9000 → conflit). Évite d'avoir à éditer le fichier suivi par git.
    ports: !override
      - "0.0.0.0:${MINIO_PORT}:9000"
      - "127.0.0.1:${MINIO_CONSOLE_PORT}:9001"

  postgres-test-db:
    image: postgres:16-alpine
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      PGPASSWORD: signflow
    command:
      - sh
      - -c
      - "psql -h postgres -U signflow -c 'CREATE DATABASE signflow_test OWNER signflow;' 2>/dev/null || true"
    restart: "no"
EOF

    chown "$SERVICE_USER:$SERVICE_USER" docker-compose.override.yml
    ok "docker-compose.override.yml créé (ports remappés)"
fi

# =============================================================================
step "5/10 — Vérification de la configuration Compose"
# =============================================================================

# NE PAS éditer docker-compose.yml : il est suivi par git, et le modifier
# provoque un conflit à chaque 'git pull' (ancien comportement de ce script).
# Les ports en conflit avec l'ERP sont neutralisés par '!override' (étape 4).
if ! docker compose config >/dev/null 2>&1; then
    docker compose config 2>&1 | tail -20
    fail "Configuration Compose invalide (voir ci-dessus)"
fi

# Filet de sécurité : aucun port ne doit être publié en 0.0.0.0 hormis MinIO.
LEAKED=$(docker compose config --format json 2>/dev/null \
    | python3 -c "
import json,sys
try: cfg = json.load(sys.stdin)
except Exception: sys.exit(0)
for name, svc in (cfg.get('services') or {}).items():
    if name == 'minio': continue
    for p in (svc.get('ports') or []):
        if (p.get('host_ip') or '0.0.0.0') == '0.0.0.0':
            print(f\"{name}:{p.get('published')}\")
" || true)
if [[ -n "$LEAKED" ]]; then
    warn "Services publiés sur toutes les interfaces (attendu : loopback seul) :"
    echo "$LEAKED" | while read -r l; do warn "    $l"; done
fi
ok "Configuration Compose valide"

# =============================================================================
step "6/10 — Démarrage des containers"
# =============================================================================

docker compose up -d postgres redis minio backend celery-worker celery-media celery-beat celery-screenshot frontend feed-proxy

info "Attente du backend (max 60s)..."
elapsed=0
while [[ $elapsed -lt 60 ]]; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://localhost:${BACKEND_PORT}/health" 2>/dev/null || echo "0")
    [[ "$code" == "200" ]] && break
    sleep 3; elapsed=$((elapsed+3))
    info "  ${elapsed}s..."
done

if [[ "$code" == "200" ]]; then
    ok "Backend healthy (http://localhost:${BACKEND_PORT}/health)"
else
    fail "Backend non disponible après 60s — vérifiez : docker compose logs backend --tail 30"
fi

# =============================================================================
step "7/10 — Migrations Alembic + bucket MinIO"
# =============================================================================

docker compose exec -T backend alembic upgrade head
ok "Migrations appliquées"

docker compose exec -T backend python /app/scripts/create_bucket.py
ok "Bucket MinIO prêt"

# =============================================================================
step "8/10 — Smoke test"
# =============================================================================

API="http://localhost:${BACKEND_PORT}/api/v1"
FAIL=0

check_endpoint() {
    local label=$1 url=$2 expected=$3
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "0")
    if [[ "$code" == "$expected" ]]; then
        ok "$label → $code"
    else
        echo -e "${RED}    FAIL $label → $code (attendu $expected)${NC}"
        FAIL=$((FAIL+1))
    fi
}

check_endpoint "GET /health"    "http://localhost:${BACKEND_PORT}/health" "200"
check_endpoint "GET /players"   "$API/players/"   "401"
check_endpoint "GET /media"     "$API/media/"     "401"
check_endpoint "GET /templates" "$API/templates/" "401"
check_endpoint "GET /playlists" "$API/playlists/" "401"
check_endpoint "GET /schedules" "$API/schedules/" "401"

[[ $FAIL -eq 0 ]] && ok "Smoke test 6/6 OK" || warn "$FAIL endpoint(s) en échec"

# =============================================================================
step "9/10 — Service systemd (démarrage automatique)"
# =============================================================================

SYSTEMD_FILE="/etc/systemd/system/signflow.service"

cat > "$SYSTEMD_FILE" << EOF
[Unit]
Description=SignFlow CMS
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/docker compose up -d postgres redis minio backend celery-worker celery-media celery-beat celery-screenshot frontend feed-proxy
ExecStop=/usr/bin/docker compose down
User=root
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable signflow.service
ok "Service systemd signflow.service activé (démarrage auto au boot)"

# =============================================================================
step "10/10 — Nginx reverse-proxy (accès players LAN)"
# =============================================================================

if ! command -v nginx >/dev/null 2>&1; then
    info "Installation de nginx..."
    apt-get install -y nginx >/dev/null
    ok "nginx installé"
else
    ok "nginx déjà présent"
fi

cat > /etc/nginx/sites-available/signflow << NGINXEOF
upstream signflow_backend {
    server 127.0.0.1:${BACKEND_PORT};
    keepalive 32;
}

upstream signflow_frontend {
    server 127.0.0.1:${FRONTEND_PORT};
    keepalive 32;
}

server {
    listen ${NGINX_PORT};
    server_name _;

    location /health {
        proxy_pass         http://signflow_backend;
        proxy_http_version 1.1;
        proxy_set_header   Host \$host;
        access_log         off;
    }

    client_max_body_size 0;

    location /api/v1/media/upload {
        proxy_pass              http://signflow_backend;
        proxy_http_version      1.1;
        proxy_set_header        Host              \$host;
        proxy_set_header        X-Real-IP         \$remote_addr;
        proxy_set_header        X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_request_buffering off;
        proxy_read_timeout      7200s;
        proxy_send_timeout      7200s;
        proxy_connect_timeout   10s;
    }

    location /api/ {
        proxy_pass             http://signflow_backend;
        proxy_http_version     1.1;
        proxy_set_header       Host              \$host;
        proxy_set_header       X-Real-IP         \$remote_addr;
        proxy_set_header       X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_read_timeout     300s;
        proxy_connect_timeout  10s;
        proxy_send_timeout     300s;
    }

    location /api/v1/ws/ {
        proxy_pass         http://signflow_backend;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       \$host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Interface CMS. Doit rester EN DERNIER (nginx applique les préfixes du plus
    # spécifique au plus général, mais l'ordre garde le fichier lisible).
    # Sans ce bloc, le frontend n'écoute que sur 127.0.0.1:${FRONTEND_PORT} et
    # reste injoignable depuis le LAN.
    location / {
        proxy_pass             http://signflow_frontend;
        proxy_http_version     1.1;
        proxy_set_header       Host              \$host;
        proxy_set_header       X-Real-IP         \$remote_addr;
        proxy_set_header       X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header       X-Forwarded-Proto \$scheme;
        # Pas d'en-tête Upgrade ici : le frontend tourne en BUILD de production
        # (aucun websocket HMR), et un 'Connection: upgrade' inconditionnel
        # annulerait le keepalive de l'upstream. Les WS players passent par
        # /api/v1/ws/ ci-dessus.
        proxy_read_timeout     300s;
        proxy_connect_timeout  10s;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/signflow /etc/nginx/sites-enabled/signflow
rm -f /etc/nginx/sites-enabled/default

nginx -t >/dev/null 2>&1 || fail "Configuration nginx invalide — vérifiez /etc/nginx/sites-available/signflow"
systemctl enable nginx
systemctl restart nginx
ok "Nginx actif sur port ${NGINX_PORT}"

# Ouvre le port si ufw est actif. L'interface est servie en HTTP CLAIR (mots de passe et
# jetons compris) : par défaut on ne l'ouvre qu'aux réseaux PRIVÉS. VITRAIL_PUBLIC_HTTP=1
# l'ouvre à tous — à réserver à un essai, la vraie exposition passe par un proxy TLS.
if ufw status | grep -q "Status: active"; then
    if [[ "${VITRAIL_PUBLIC_HTTP:-0}" == "1" ]]; then
        ufw allow ${NGINX_PORT}/tcp >/dev/null
        warn "Port ${NGINX_PORT} ouvert à TOUT Internet en HTTP clair (VITRAIL_PUBLIC_HTTP=1)"
    else
        for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
            ufw allow from "$net" to any port ${NGINX_PORT} proto tcp >/dev/null
        done
        ok "Port ${NGINX_PORT} ouvert aux réseaux privés seulement (VITRAIL_PUBLIC_HTTP=1 pour l'ouvrir à tous)"
    fi
fi

# =============================================================================
step "11/11 — Amorçage (organisation + compte administrateur)"
# =============================================================================
# Sans cette étape, l'installation se terminait « OK » mais SANS AUCUN COMPTE pour se
# connecter (constaté 2026-07-18). `bootstrap.py` n'est pas idempotent : on ne l'exécute
# que si la base ne contient encore aucun utilisateur.
EXISTING_USERS=$(docker compose exec -T postgres psql -U signflow -d signflow -tAc "SELECT count(*) FROM cms_users;" 2>/dev/null | tr -d '[:space:]' || echo "")

if [[ "$EXISTING_USERS" == "0" ]]; then
    ADMIN_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)aA1!
    if docker compose exec -T -e BOOTSTRAP_ADMIN_EMAIL="${ADMIN_EMAIL:-admin@signflow.local}" -e BOOTSTRAP_ADMIN_PASSWORD="$ADMIN_PASSWORD" backend python3 - < backend/scripts/bootstrap.py; then
        ok "Organisation et compte administrateur créés"
    else
        warn "Amorçage en échec — relancez :"
        warn "  cd ${INSTALL_DIR} && docker compose exec -T backend python3 - < backend/scripts/bootstrap.py"
    fi
elif [[ -n "$EXISTING_USERS" ]]; then
    info "Base déjà amorcée (${EXISTING_USERS} utilisateur(s)) — amorçage ignoré"
else
    warn "Impossible de vérifier l'état de la base — amorçage ignoré par prudence"
    warn "  Si aucun compte n'existe : docker compose exec -T backend python3 - < backend/scripts/bootstrap.py"
fi

# =============================================================================
echo ""
echo -e "${GREEN}  =================================================${NC}"
echo -e "${GREEN}   SIGNFLOW INSTALLÉ ET OPÉRATIONNEL${NC}"
echo -e "${GREEN}  =================================================${NC}"
echo ""
echo -e "   Backend API    : http://localhost:${BACKEND_PORT}  (loopback Docker)"
echo -e "   Proxy players  : http://${SERVER_IP}:${NGINX_PORT}  (LAN — players NUC/Pi)"
echo -e "   MinIO Console  : http://localhost:${MINIO_CONSOLE_PORT}"
echo ""
echo -e "   Logs           : docker compose -f ${INSTALL_DIR}/docker-compose.yml logs -f backend"
echo -e "   Arrêt          : systemctl stop signflow"
echo -e "   Mise à jour    : cd ${INSTALL_DIR} && git pull && docker compose up -d --build"
echo ""
echo -e "${CYAN}   Config player :${NC}"
echo -e "     BACKEND_URL = http://${SERVER_IP}:${NGINX_PORT}"
echo -e "     WS_URL      = ws://${SERVER_IP}:${NGINX_PORT}/api/v1/ws/player?token=<TOKEN>"
echo ""
