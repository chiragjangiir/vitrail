#!/bin/sh
# SignFlow — provisioning de PREMIER BOOT (Raspberry Pi OS). Lancé une seule fois par un service
# systemd oneshot injecté dans l'image. Lit le payload déposé sur la partition boot, installe
# player-rpi (via son install.sh — réseau requis : apt/node/npm/electron), sème le config.json de
# provisioning, puis se désactive et redémarre sur le player.
set -u

# ── Traces : à l'ÉCRAN et sur DISQUE ──────────────────────────────────────────
# Constat terrain d'Ed (2026-08-09) : pendant l'installation, l'écran n'affiche qu'une
# invite de connexion immobile. Un technicien n'a aucun moyen de distinguer « ça travaille »
# de « c'est fini » ou de « c'est bloqué » — donc il redémarre, souvent au pire moment.
# Et quand ça échoue, il ne reste RIEN : journald est en mode volatile sur cette image
# (/var/log/journal existe mais est vide) ⇒ le journal du 1er boot disparaît au redémarrage.
LOG_FILE=/var/log/signflow-firstboot.log

# getty redessine son invite par-dessus tout ce qu'on écrit : on lui prend tty1 le temps
# de l'installation, et on le lui rend si l'on n'aboutit pas (sinon plus de console du tout).
# ⚠️ Un simple `stop` NE SUFFIT PAS : getty@.service porte Restart=always, donc systemd le
# relance aussitôt et l'invite revient se mêler aux messages (constaté par Ed le 2026-08-09).
# Il faut le masquer — mais un masque persistant qui survivrait à un plantage laisserait un
# RPi SANS console locale, définitivement. D'où `--runtime` : le masque vit dans /run et
# disparaît de lui-même au redémarrage, y compris après une coupure de courant.
CONSOLE=/dev/tty1
[ -c "$CONSOLE" ] 2>/dev/null || CONSOLE=/dev/null

log() {
    msg="[signflow-firstboot] $*"
    echo "$msg"                                       # journal systemd
    echo "$msg" >> "$LOG_FILE" 2>/dev/null || true    # trace qui SURVIT au redémarrage
    echo "$msg" > "$CONSOLE" 2>/dev/null || true      # écran du technicien
}

screen() { echo "$*" > "$CONSOLE" 2>/dev/null || true; }

give_console_back() {
    systemctl unmask --runtime getty@tty1.service 2>/dev/null || true
    systemctl start getty@tty1.service 2>/dev/null || true
}
# Filet : on a PRIS tty1 à getty. Toute sortie qui ne redémarre pas la machine doit le lui
# rendre, sinon on laisse un RPi sans aucune console — y compris sur les sorties « rien à
# faire » (payload absent, jeton invalide), faciles à oublier une par une.
trap give_console_back EXIT

# ⚠️ On ne prend tty1 qu'APRÈS avoir armé le filet ci-dessus : masquer d'abord laisserait
# une fenêtre où une sortie en erreur rendrait la console muette jusqu'au redémarrage.
systemctl mask --runtime getty@tty1.service 2>/dev/null || true
systemctl stop getty@tty1.service 2>/dev/null || true

screen ""
screen "==============================================="
screen "   Vitrail - installation du player en cours"
screen "   NE PAS ETEINDRE / DO NOT POWER OFF"
screen "==============================================="
screen ""
log "demarrage du provisioning (trace complete : $LOG_FILE)"

# Partition boot : /boot/firmware (RPi OS Bookworm+) ou /boot (anciennes).
PROV=/boot/firmware/signflow-provision.json
[ -f "$PROV" ] || PROV=/boot/signflow-provision.json
if [ ! -f "$PROV" ]; then
    log "signflow-provision.json absent — rien à faire."
    exit 0
fi

_j() { sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$PROV" | head -1; }
BACKEND=$(_j backend_url); TOKEN=$(_j token); REF=$(_j ref)

case "$TOKEN" in
    sfp_*) ;;
    *) log "token de provisioning (sfp_…) absent/invalide — abandon (édite $PROV)."; exit 0 ;;
esac
[ -n "$BACKEND" ] || { log "backend_url absent — abandon."; exit 0; }

SERVICE_USER=signflow
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    log "création de l'utilisateur $SERVICE_USER"
    useradd -m -s /bin/bash "$SERVICE_USER" 2>/dev/null || adduser --disabled-password --gecos "" "$SERVICE_USER"
fi

INSTALL=/opt/signflow/player-rpi/install.sh
if [ ! -f "$INSTALL" ]; then
    log "player-rpi/install.sh introuvable — abandon."
    exit 1
fi
sed -i 's/\r$//' "$INSTALL" 2>/dev/null || true

# ── Attendre que le réseau soit RÉELLEMENT utilisable ─────────────────────────
# `After=network-online.target` ne garantit ni le DNS ni une route qui fonctionne, et au
# PREMIER démarrage RPi OS redimensionne encore sa partition pendant ce temps. Mesuré le
# 2026-08-09 : l'installation a échoué au 1er boot deux fois sur deux, avec des journaux
# apt VIDES — donc avant même le premier apt, dans le `curl` de NodeSource — puis a réussi
# au 2e boot. On attend donc une vraie requête sortante plutôt que de parier dessus.
wait_network() {
    i=0
    while [ "$i" -lt 60 ]; do
        if curl -fsS --max-time 5 -o /dev/null "$BACKEND/health" 2>/dev/null; then
            log "reseau utilisable (serveur joignable) apres $((i * 5))s"
            return 0
        fi
        i=$((i + 1))
        [ $(( (i - 1) % 6 )) -eq 0 ] && log "attente du reseau... $((i * 5))s / 300s"
        sleep 5
    done
    return 1
}

# ── Attendre que l'HORLOGE soit juste ─────────────────────────────────────────
# LA cause réelle de l'échec du 1er boot, mesurée le 2026-08-09 :
#     curl: (60) SSL certificate problem: certificate is not yet valid
# « not yet valid », pas « expired » : l'horloge était EN RETARD. Un Raspberry Pi n'a pas
# d'horloge temps réel ; au démarrage il repart de la date de l'image (18 juin ici) et tant
# que NTP n'a pas synchronisé, tout certificat émis depuis est refusé — donc le `curl` de
# NodeSource échoue, avant même le premier apt (d'où des journaux apt entièrement vides).
# Au 2e boot l'heure était apprise, et l'installation passait : voilà pourquoi le défaut
# semblait aléatoire.
# ⚠️ Attendre le RÉSEAU ne suffit pas et c'est trompeur : notre propre serveur répondait
# « joignable en 0s » (son certificat, plus ancien, passait encore) pendant que celui de
# NodeSource était rejeté. Un contrôle qui vise à côté rassure au lieu d'alerter.
wait_clock() {
    i=0
    while [ "$i" -lt 60 ]; do
        if [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = "yes" ]; then
            log "horloge synchronisee : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
            return 0
        fi
        i=$((i + 1))
        [ $(( (i - 1) % 6 )) -eq 0 ] && log "attente de l'horloge (NTP)... $((i * 5))s / 300s — date vue : $(date -u '+%Y-%m-%d %H:%M')"
        sleep 5
    done
    return 1
}

if ! wait_clock; then
    log "ECHEC : horloge non synchronisee apres 5 min (date vue : $(date -u))."
    log "        sans heure juste, TOUTE connexion HTTPS est refusee (certificats)."
    screen ""
    screen "  !! ECHEC : horloge systeme non synchronisee (NTP)."
    screen "  Verifier l'acces reseau vers un serveur de temps, puis REDEMARRER."
    screen "  Details : $LOG_FILE"
    screen ""
    exit 1
fi

if ! wait_network; then
    log "ECHEC : serveur injoignable apres 5 min ($BACKEND)."
    log "        verifier le cable reseau / le Wi-Fi, puis redemarrer : nouvel essai automatique."
    screen ""
    screen "  !! ECHEC : serveur injoignable ($BACKEND)"
    screen "  Verifier le reseau puis REDEMARRER (nouvel essai automatique)."
    screen "  Details : $LOG_FILE"
    screen ""
    give_console_back
    exit 1
fi

log "installation de player-rpi (plusieurs minutes, ne pas eteindre)…"
screen "  -> installation de Node, Electron et du player (plusieurs minutes)..."
# La sortie de l'installeur est CAPTURÉE : sans elle, un échec ne laisse aucune cause
# lisible — c'est précisément ce qui a rendu le premier diagnostic impossible.
if ! bash "$INSTALL" "$SERVICE_USER" >> "$LOG_FILE" 2>&1; then
    log "install.sh a échoué — le service réessaiera au prochain boot (non désactivé)."
    log "        30 dernieres lignes ci-dessous :"
    tail -30 "$LOG_FILE" > "$CONSOLE" 2>/dev/null || true
    screen ""
    screen "  !! ECHEC de l'installation. Trace : $LOG_FILE"
    screen "  Redemarrer pour un nouvel essai automatique."
    screen ""
    give_console_back
    exit 1
fi
log "installation terminee"

# Config de provisioning lue par le player Electron.
#
# DEUX ÉCARTS mesurés le 2026-08-09 sur un RPi réel, qui rendaient ce canal totalement
# inopérant : l'image s'installait parfaitement et le player affichait « Setup required ».
#
#  1. LE RÉPERTOIRE. Electron lit `app.getPath('userData')`, c'est-à-dire
#     ~/.config/<name de package.json> = « signflow-player-rpi ». Ce script écrivait dans
#     « signflow-player » (sans le suffixe) : le fichier existait, le player ne l'ouvrait
#     jamais. On DÉRIVE donc le nom du package.json plutôt que de le réécrire à la main —
#     deux définitions finissent toujours par diverger.
#  2. LA CLÉ. Les players Electron rpi/linux lisent `config.player_token` et l'envoient
#     comme `org_token` à /players/register (voir main.js). Ce script écrivait « org_token »,
#     clé que seul le player WINDOWS sait lire. Le jeton était donc invisible.
PKG=/opt/signflow/player-rpi/package.json
APP_NAME=$(sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$PKG" 2>/dev/null | head -1)
if [ -z "$APP_NAME" ]; then
    # Mieux vaut s'arrêter que d'écrire dans ~/.config/ et laisser un player muet.
    log "nom d'application illisible dans $PKG — abandon (le player ne serait pas provisionné)."
    exit 1
fi
CFG_DIR="/home/$SERVICE_USER/.config/$APP_NAME"
mkdir -p "$CFG_DIR"
cat > "$CFG_DIR/config.json" <<JSON
{
  "backend_url": "$BACKEND",
  "player_token": "$TOKEN",
  "player_name": "${REF:-rpi-player}"
}
JSON
chown -R "$SERVICE_USER":"$SERVICE_USER" "$CFG_DIR" 2>/dev/null || true
log "config de provisioning écrite → $CFG_DIR/config.json (application « $APP_NAME »)"

# Désactivation du service (idempotence) + reboot sur le player.
systemctl disable signflow-firstboot.service 2>/dev/null || true
log "provisioning terminé — redémarrage sur le player."
screen ""
screen "==============================================="
screen "   Installation TERMINEE - redemarrage dans 5s"
screen "   Le player va demarrer automatiquement."
screen "==============================================="
screen ""
sync
sleep 5
reboot
