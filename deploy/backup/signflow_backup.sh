#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Backup quotidien Vitrail → stockage distant (rclone : NAS, S3, SFTP…)
#
# Sauvegarde : dump Postgres (format custom) + rôles globaux + config (.env,
# overrides compose, version alembic) + MIROIR du volume MinIO (médias) avec
# corbeille 30 j (un fichier supprimé/écrasé côté serveur reste 30 j sur le stockage distant).
#
# Tourne sous un compte du groupe docker — AUCUN root requis : rclone en
# conteneur, volume MinIO monté read-only. Secrets HORS git :
#   ~/.config/signflow-backup/rclone.conf   (remote rclone nommé « backup », chmod 600)
#   ~/.config/signflow-backup/backup.env    (KUMA_PUSH_URL, TELEGRAM_CHAT_ID)
#
# Alerting : échec → message Telegram direct (bot du .env) ; succès →
# ping du push-monitor Uptime Kuma (dead man's switch : Kuma alerte si AUCUN
# backup ne s'est exécuté depuis 26 h). + alerte disque > 85 %.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/signflow}"
CONF_DIR="${CONF_DIR:-$HOME/.config/signflow-backup}"
STAGING="${STAGING:-$HOME/signflow_backups}"
REMOTE="${REMOTE:-backup:vitrail}"   # <remote rclone>:<chemin> — à adapter
KEEP_LOCAL_DAYS="${KEEP_LOCAL_DAYS:-7}"
KEEP_REMOTE_DAYS="${KEEP_REMOTE_DAYS:-30}"
DISK_ALERT_PCT="${DISK_ALERT_PCT:-85}"
PG_CONTAINER="${PG_CONTAINER:-signflow-postgres-1}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-signflow-backend-1}"
MINIO_VOLUME="${MINIO_VOLUME:-signflow_minio_data}"
RCLONE_IMG="${RCLONE_IMG:-rclone/rclone:1}"

STAMP=$(date +%Y%m%d_%H%M%S)
TODAY=$(date +%Y-%m-%d)

# Secrets locaux (jamais dans git)
# shellcheck disable=SC1091
[[ -f "$CONF_DIR/backup.env" ]] && source "$CONF_DIR/backup.env"
TG_TOKEN=$(grep -oP '^CMS_TELEGRAM_BOT_TOKEN=\K.*' "$APP_DIR/.env" 2>/dev/null || true)

tg_send() {  # message Telegram best-effort (réutilise le bot Jeanine)
  [[ -n "${TG_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]] || return 0
  curl -fsS -m 10 "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    -d chat_id="$TELEGRAM_CHAT_ID" --data-urlencode "text=$1" >/dev/null || true
}

STEP=init
trap 'echo "[$(date -Is)] FAILED at step $STEP"; tg_send "⚠️ SignFlow backup FAILED (étape : $STEP) — voir ~/signflow_backups/backup.log"' ERR

rclone_files() {  # rclone pour les fichiers du staging
  docker run --rm --user "$(id -u):$(id -g)" \
    -v "$CONF_DIR/rclone.conf:/config/rclone/rclone.conf:ro" \
    -v "$STAGING:$STAGING" \
    "$RCLONE_IMG" "$@"
}

echo "[$(date -Is)] backup start"
mkdir -p "$STAGING/db" "$STAGING/config"

# ── 1. Postgres : dump custom (pg_restore sélectif possible) + rôles globaux ──
STEP=pg_dump
docker exec "$PG_CONTAINER" pg_dump -U signflow -Fc signflow \
  > "$STAGING/db/signflow_${STAMP}.dump"
docker exec "$PG_CONTAINER" pg_dumpall -U signflow --globals-only \
  > "$STAGING/db/globals_${STAMP}.sql"
[[ -s "$STAGING/db/signflow_${STAMP}.dump" ]] || { echo "dump vide"; false; }

# ── 2. Config non versionnée (.env = secrets, overrides compose) ─────────────
STEP=config
docker exec "$BACKEND_CONTAINER" alembic current 2>/dev/null \
  > "$STAGING/config/alembic_${STAMP}.txt" || true
tar czf "$STAGING/config/config_${STAMP}.tgz" -C "$APP_DIR" \
  .env docker-compose.override.yml

# ── 3. Upload dumps + config vers le stockage distant ─────────────────────────────────────
STEP=upload_db
rclone_files copy "$STAGING/db" "$REMOTE/db" --log-level ERROR
rclone_files copy "$STAGING/config" "$REMOTE/config" --log-level ERROR

# ── 4. Miroir MinIO (médias) — incrémental ; suppressions gardées 30 j ───────
STEP=minio_sync
docker run --rm \
  -v "$CONF_DIR/rclone.conf:/config/rclone/rclone.conf:ro" \
  -v "$MINIO_VOLUME:/minio_data:ro" \
  "$RCLONE_IMG" sync /minio_data "$REMOTE/minio" \
  --backup-dir "$REMOTE/minio_deleted/$TODAY" \
  --transfers 4 --log-level ERROR

# ── 5. Rotations ──────────────────────────────────────────────────────────────
STEP=rotate
rclone_files delete --min-age "${KEEP_REMOTE_DAYS}d" "$REMOTE/db" --log-level ERROR || true
rclone_files delete --min-age "${KEEP_REMOTE_DAYS}d" "$REMOTE/config" --log-level ERROR || true
rclone_files delete --min-age "${KEEP_REMOTE_DAYS}d" "$REMOTE/minio_deleted" --log-level ERROR || true
rclone_files rmdirs "$REMOTE/minio_deleted" --leave-root --log-level ERROR || true
find "$STAGING" -type f -mtime "+${KEEP_LOCAL_DAYS}" -delete

# ── 6. Alerte disque (le serveur n'a qu'un disque — 86 % constaté le 12/07) ──
STEP=disk_check
USAGE=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if [[ "$USAGE" -gt "$DISK_ALERT_PCT" ]]; then
  tg_send "⚠️ SignFlow : disque serveur à ${USAGE}% (seuil ${DISK_ALERT_PCT}%)"
fi

# ── 7. Dead man's switch Uptime Kuma ─────────────────────────────────────────
STEP=kuma_push
SIZE=$(du -sh "$STAGING/db/signflow_${STAMP}.dump" | cut -f1)
[[ -n "${KUMA_PUSH_URL:-}" ]] && \
  curl -fsS -m 10 "${KUMA_PUSH_URL}?status=up&msg=dump_${SIZE}" >/dev/null || true

echo "[$(date -Is)] backup OK (dump ${SIZE}, disque ${USAGE}%)"
