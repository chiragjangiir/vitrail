#!/bin/sh
# SignFlow — applier de configuration pour un player **Debian/RPi cloné** (master OS + player déjà
# installés). Donne son IDENTITÉ + son RÉSEAU à CETTE machine à partir d'un bundle signflow-config.json
# (généré par le CMS), puis vérifie, affiche les points de contrôle, et propose le reboot.
# ⚠️ Tourne SUR LE PLAYER (vu par le technicien) → toutes les chaînes affichées sont en ANGLAIS
# (règle « player = anglais uniquement »). Les commentaires de code restent en français (dev).
#
#   sudo sf-configure.sh [/chemin/signflow-config.json]
#
# Sans argument : cherche le bundle sur une clé USB montée. À lancer EN ROOT (nmcli + hostname).
# NE réinstalle RIEN : le player est déjà là (via le clone). Idempotent (relançable).
#
# Deux formats de bundle acceptés (clés OPTIONNELLES additives : "resolution" = "LxH" forcée via
# display_config.json ; "net_wifi_ssid"/"net_wifi_psk" = connexion Wi-Fi nmcli ;
# "timezone" = fuseau IANA pose via timedatectl — reference = fuseau du site CMS) :
#   • LEGACY (1 machine, objet plat) :
#     { "player_name":"Boutique Lyon", "backend_url":"https://...:8443", "token":"sfp_...",
#       "net_mode":"static"|"dhcp", "net_ip":"192.168.1.50", "net_prefix":24,
#       "net_gateway":"192.168.1.1", "net_dns":"192.168.1.1,8.8.8.8",
#       "resolution":"1920x1080", "net_wifi_ssid":"…", "net_wifi_psk":"…" }
#   • LOT v2 (§XXIX.10, préparer N machines avec 1 clé) :
#     { "version":2, "mode":"per_machine"|"shared", "backend_url":"https://...:8443", "os":"linux",
#       "players":[ {"player_name":"…","token":"sfp_…","net_mode":"…","net_ip":"…","net_prefix":24,
#                    "net_gateway":"…","net_dns":"…","resolution":"…"}, … ],   // per_machine
#       "token":"sfp_…", "count":15,
#       "resolution":"…", "net_wifi_ssid":"…", "net_wifi_psk":"…" }           // shared (COMMUN)
set -u

RED='\033[31m'; GRN='\033[32m'; YEL='\033[33m'; CYN='\033[36m'; BLD='\033[1m'; RST='\033[0m'
die() { printf "  ${RED}✗ %s${RST}\n" "$1" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "Run as root: sudo sf-configure.sh"

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
PYHELPER=""
cleanup() { [ -n "$PYHELPER" ] && rm -f "$PYHELPER" 2>/dev/null; }
trap cleanup EXIT

# ── 1) Trouver le bundle ──────────────────────────────────────────────────────
BUNDLE="${1:-}"
if [ -z "$BUNDLE" ]; then
    for d in /media/*/* /media/* /run/media/*/* /mnt/*/* /mnt/* .; do
        [ -f "$d/signflow-config.json" ] && { BUNDLE="$d/signflow-config.json"; break; }
    done
fi
[ -n "$BUNDLE" ] && [ -f "$BUNDLE" ] || die "signflow-config.json not found (USB key inserted? otherwise pass the path as argument)."
BUNDLE_DIR=$(dirname "$BUNDLE")
CONSUMED="$BUNDLE_DIR/consumed.json"
printf "  ${CYN}Bundle: %s${RST}\n" "$BUNDLE"

# ── 1b) Détecter le format (lot v2 vs legacy plat) ────────────────────────────
IS_V2=0
grep -q '"version"[[:space:]]*:[[:space:]]*2' "$BUNDLE" 2>/dev/null && IS_V2=1

# Variables d'identité à renseigner (par l'un des deux chemins ci-dessous).
NAME=""; BACKEND=""; TOKEN=""
NET_MODE=""; NET_IP=""; NET_PREFIX=""; NET_GW=""; NET_DNS=""
RESOLUTION=""; WIFI_SSID=""; WIFI_PSK=""; TIMEZONE=""
BATCH_TOTAL=""; BATCH_DONE=""; BATCH_MODE=""

# ── 2) Sélectionner l'identité de CETTE machine ───────────────────────────────
if [ "$IS_V2" = "1" ]; then
    [ -n "$PY" ] || die "python3 required for batch format (install python3 on the master)."
    # Helper python embarqué (parse robuste du tableau + consommation).
    PYHELPER=$(mktemp)
    cat > "$PYHELPER" <<'PYEOF'
import json, sys
action = sys.argv[1]; bundle = sys.argv[2]
consumed_path = sys.argv[3] if len(sys.argv) > 3 else ""
b = json.load(open(bundle))
players = b.get("players") or []
def load_consumed():
    try: return set(json.load(open(consumed_path)).get("consumed", []))
    except Exception: return set()
def g(p, k): return str(p.get(k, "") or "")
if action == "info":
    cons = load_consumed()
    done = sum(1 for p in players if p.get("token") in cons)
    print("MODE=" + str(b.get("mode", "per_machine")))
    print("BACKEND=" + str(b.get("backend_url", "") or ""))
    print("TOTAL=" + str(len(players)))
    print("DONE=" + str(done))
    print("TOKEN=" + str(b.get("token", "") or ""))     # shared
    print("COUNT=" + str(b.get("count", "") or ""))      # shared
    print("RESOLUTION=" + str(b.get("resolution", "") or ""))     # shared (commun)
    print("WIFI_SSID=" + str(b.get("net_wifi_ssid", "") or ""))   # shared (commun)
    print("WIFI_PSK=" + str(b.get("net_wifi_psk", "") or ""))
    print("TIMEZONE=" + str(b.get("timezone", "") or ""))    # shared (commun)
elif action == "list":
    cons = load_consumed()
    for i, p in enumerate(players):
        mark = "OK" if p.get("token") in cons else "  "
        print("   [%s] %s) %s" % (mark, i, g(p, "player_name") or "?"))
elif action == "autopick":
    cons = load_consumed()
    for i, p in enumerate(players):
        if p.get("token") not in cons:
            print(i); break
elif action == "get":
    p = players[int(sys.argv[4])]
    print("PLAYER_NAME=" + g(p, "player_name"))
    print("TOKEN=" + g(p, "token"))
    print("NET_MODE=" + g(p, "net_mode"))
    print("NET_IP=" + g(p, "net_ip"))
    print("NET_PREFIX=" + g(p, "net_prefix"))
    print("NET_GW=" + g(p, "net_gateway"))
    print("NET_DNS=" + g(p, "net_dns"))
    print("RESOLUTION=" + g(p, "resolution"))
    print("WIFI_SSID=" + g(p, "net_wifi_ssid"))
    print("WIFI_PSK=" + g(p, "net_wifi_psk"))
    print("TIMEZONE=" + g(p, "timezone"))
elif action == "consume":
    cons = load_consumed(); cons.add(sys.argv[4])
    json.dump({"consumed": sorted(cons)}, open(consumed_path, "w"))
PYEOF
    _pyval() { printf '%s\n' "$1" | sed -n "s/^$2=//p" | head -1; }

    INFO=$("$PY" "$PYHELPER" info "$BUNDLE" "$CONSUMED") || die "unreadable v2 bundle (invalid JSON?)."
    BATCH_MODE=$(_pyval "$INFO" MODE); BACKEND=$(_pyval "$INFO" BACKEND)
    BATCH_TOTAL=$(_pyval "$INFO" TOTAL); BATCH_DONE=$(_pyval "$INFO" DONE)

    if [ "$BATCH_MODE" = "shared" ]; then
        TOKEN=$(_pyval "$INFO" TOKEN)
        # Réglages COMMUNS du lot partagé (résolution/Wi-Fi identiques pour tous les players).
        RESOLUTION=$(_pyval "$INFO" RESOLUTION); TIMEZONE=$(_pyval "$INFO" TIMEZONE)
        WIFI_SSID=$(_pyval "$INFO" WIFI_SSID); WIFI_PSK=$(_pyval "$INFO" WIFI_PSK)
        printf "  ${CYN}Shared-token batch (shared mode).${RST}\n"
        printf "  ${BLD}Name of THIS player: ${RST}"
        read NAME 2>/dev/null || NAME=""
        [ -n "$NAME" ] || die "Name required in shared mode."
    else
        # per_machine : auto-pick de la 1re entrée libre, override manuel possible.
        [ "${BATCH_DONE:-0}" -lt "${BATCH_TOTAL:-0}" ] 2>/dev/null \
            || die "All players in this batch are already configured (${BATCH_DONE}/${BATCH_TOTAL})."
        printf "  ${BLD}Batch players${RST} (OK = already configured):\n"
        "$PY" "$PYHELPER" list "$BUNDLE" "$CONSUMED"
        AUTO=$("$PY" "$PYHELPER" autopick "$BUNDLE" "$CONSUMED")
        printf "  ${CYN}Auto -> #%s.${RST} Press Enter to accept, or type a number: " "$AUTO"
        read IDX 2>/dev/null || IDX=""
        [ -n "$IDX" ] || IDX="$AUTO"
        case "$IDX" in ''|*[!0-9]*) die "Invalid selection." ;; esac
        VARS=$("$PY" "$PYHELPER" get "$BUNDLE" "$CONSUMED" "$IDX") || die "Entry #$IDX unreadable."
        NAME=$(_pyval "$VARS" PLAYER_NAME); TOKEN=$(_pyval "$VARS" TOKEN)
        NET_MODE=$(_pyval "$VARS" NET_MODE); NET_IP=$(_pyval "$VARS" NET_IP)
        NET_PREFIX=$(_pyval "$VARS" NET_PREFIX); NET_GW=$(_pyval "$VARS" NET_GW)
        NET_DNS=$(_pyval "$VARS" NET_DNS)
        RESOLUTION=$(_pyval "$VARS" RESOLUTION); TIMEZONE=$(_pyval "$VARS" TIMEZONE)
        WIFI_SSID=$(_pyval "$VARS" WIFI_SSID); WIFI_PSK=$(_pyval "$VARS" WIFI_PSK)
    fi
else
    # ── LEGACY : objet plat (1 machine), parse sans jq ────────────────────────
    _str() { sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$BUNDLE" | head -1; }
    _num() { sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$BUNDLE" | head -1; }
    NAME=$(_str player_name); BACKEND=$(_str backend_url); TOKEN=$(_str token)
    NET_MODE=$(_str net_mode); NET_IP=$(_str net_ip); NET_PREFIX=$(_num net_prefix)
    NET_GW=$(_str net_gateway); NET_DNS=$(_str net_dns)
    RESOLUTION=$(_str resolution); TIMEZONE=$(_str timezone)
    WIFI_SSID=$(_str net_wifi_ssid); WIFI_PSK=$(_str net_wifi_psk)
fi

[ -n "$NET_MODE" ] || NET_MODE=dhcp
[ -n "$BACKEND" ] || die "backend_url missing from bundle."
case "$TOKEN" in sfp_*) ;; *) die "provisioning token (sfp_...) missing/invalid in bundle." ;; esac

# ── 3) Compte cible (celui qui fait tourner le player) ────────────────────────
# Le player Electron tourne sous un user desktop (openbox). On repère son ~/.config/signflow-player.
CFG_DIR=""; TARGET_USER=""
for h in /home/*; do
    [ -d "$h/.config/signflow-player" ] && { CFG_DIR="$h/.config/signflow-player"; TARGET_USER=$(basename "$h"); break; }
done
if [ -z "$CFG_DIR" ]; then
    TARGET_USER=$(getent passwd 1000 | cut -d: -f1); [ -n "$TARGET_USER" ] || TARGET_USER=signflow
    CFG_DIR="/home/$TARGET_USER/.config/signflow-player"
    mkdir -p "$CFG_DIR"
fi
printf "  ${CYN}Player account: %s${RST}\n" "$TARGET_USER"

# ── 4) Hostname = nom du player (player-linux enregistre os.hostname()) ────────
# Assainir : lettres/chiffres/tiret, pas d'espace (contrainte hostname).
HOST=$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g; s/--*/-/g; s/^-//; s/-$//')
[ -n "$HOST" ] || HOST="signflow-player"
hostnamectl set-hostname "$HOST" 2>/dev/null || { echo "$HOST" > /etc/hostname; hostname "$HOST" 2>/dev/null; }
# /etc/hosts cohérent
grep -q "127.0.1.1" /etc/hosts 2>/dev/null \
    && sed -i "s/^127.0.1.1.*/127.0.1.1\t$HOST/" /etc/hosts \
    || echo "127.0.1.1	$HOST" >> /etc/hosts

# ── 5) config.json du player (token de provisioning sfp_ → player_token) ──────
printf '{\n  "backend_url": "%s",\n  "player_token": "%s"\n}\n' "$BACKEND" "$TOKEN" > "$CFG_DIR/config.json"
# état PROPRE par clone : la clé de signature PoP, les verrous ET le contenu caché du master ne
# doivent PAS être partagés (sinon un clone diffuse le contenu périmé du master jusqu'à la resync).
rm -f "$CFG_DIR/pop_key.json" "$CFG_DIR/pop_queue.json" "$CFG_DIR"/Singleton* 2>/dev/null
rm -rf "$CFG_DIR/content_store" 2>/dev/null

# ── 5b) Résolution forcée (optionnelle) → display_config.json (le player l'applique au boot,
# même hors ligne ; le serveur la resynchronisera ensuite via player:sync). Merge si possible.
RES_APPLIED="(unchanged)"
if [ -n "$RESOLUTION" ]; then
    DC="$CFG_DIR/display_config.json"
    if [ -n "$PY" ]; then
        "$PY" - "$DC" "$RESOLUTION" <<'PYRES' && RES_APPLIED="$RESOLUTION"
import json, sys
path, res = sys.argv[1], sys.argv[2]
try: dc = json.load(open(path))
except Exception: dc = {}
dc["screen_resolution"] = res
json.dump(dc, open(path, "w"), indent=2)
PYRES
    else
        printf '{\n  "screen_resolution": "%s"\n}\n' "$RESOLUTION" > "$DC" && RES_APPLIED="$RESOLUTION"
    fi
fi
chown -R "$TARGET_USER:$TARGET_USER" "$CFG_DIR" 2>/dev/null || true

# -- 5c) OS time zone (optional, additive key "timezone") -----------------------
# The offline auto-power pilot and all local wall-clock features follow THIS clock
# (reference = the site time zone in the CMS). Runs as root: timedatectl direct.
TZ_APPLIED="(unchanged)"
if [ -n "$TIMEZONE" ]; then
    if timedatectl set-timezone "$TIMEZONE" 2>/dev/null; then
        TZ_APPLIED="$TIMEZONE"
    else
        TZ_APPLIED="${RED}invalid/unknown time zone: $TIMEZONE${RST}"
    fi
fi

# ── 6) Réseau via NetworkManager (nmcli) ──────────────────────────────────────
# Connexion de la 1re interface filaire active (défaut « Wired connection 1 »).
WIRED_DEV=$(nmcli -t -f DEVICE,TYPE dev 2>/dev/null | awk -F: '$2=="ethernet"{print $1; exit}')
CON=$(nmcli -t -f NAME,DEVICE con show --active 2>/dev/null | awk -F: -v d="$WIRED_DEV" '$2==d{print $1; exit}')
[ -n "$CON" ] || CON=$(nmcli -t -f NAME,TYPE con show 2>/dev/null | awk -F: '$2=="802-3-ethernet"{print $1; exit}')
NET_APPLIED="(unchanged)"
if [ -n "$CON" ]; then
    if [ "$NET_MODE" = "static" ] && [ -n "$NET_IP" ]; then
        [ -n "$NET_PREFIX" ] || NET_PREFIX=24
        DNS_NM=$(printf '%s' "$NET_DNS" | tr ',' ' ')
        nmcli con mod "$CON" ipv4.method manual ipv4.addresses "$NET_IP/$NET_PREFIX" \
            ipv4.gateway "$NET_GW" ipv4.dns "$DNS_NM" ipv6.method ignore 2>/dev/null \
            && NET_APPLIED="static $NET_IP/$NET_PREFIX gw $NET_GW" || NET_APPLIED="${RED}nmcli failed${RST}"
    else
        nmcli con mod "$CON" ipv4.method auto 2>/dev/null && NET_APPLIED="dhcp"
    fi
    nmcli con up "$CON" >/dev/null 2>&1 || true
    sleep 3
fi

# ── 6b) Wi-Fi (optionnel, best-effort) : connexion nmcli — utile lots partagés / sites sans filaire.
WIFI_APPLIED=""
if [ -n "$WIFI_SSID" ]; then
    if nmcli dev wifi connect "$WIFI_SSID" password "$WIFI_PSK" >/dev/null 2>&1; then
        WIFI_APPLIED="$WIFI_SSID (connected)"
    else
        WIFI_APPLIED="${YEL}$WIFI_SSID (connect failed — no Wi-Fi adapter?)${RST}"
    fi
fi

# ── 7) Vérification + affichage des points de contrôle ────────────────────────
CUR_IP=$(ip -4 -br addr show "$WIRED_DEV" 2>/dev/null | awk '{print $3}' | head -1)
[ -n "$CUR_IP" ] || CUR_IP=$(ip -4 -br addr 2>/dev/null | grep -v ' lo ' | awk '{print $3}' | head -1)
TOKEN_OK=$(grep -q "$TOKEN" "$CFG_DIR/config.json" 2>/dev/null && echo YES || echo NO)
HEALTH="?"
if command -v curl >/dev/null 2>&1; then
    curl -fsS -m 8 "${BACKEND%/}/health" >/dev/null 2>&1 && HEALTH="${GRN}OK${RST}" || HEALTH="${RED}UNREACHABLE${RST}"
fi

OK=1
[ "$TOKEN_OK" = "YES" ] || OK=0
[ -n "$CUR_IP" ] || OK=0

# Consommation du lot v2 per_machine : marquer l'entrée AVANT l'attente d'étiquetage (si le tech
# coupe le courant pendant l'étiquetage, l'entrée est déjà réservée ; le serveur max_uses=1 backstoppe).
CONSUME_NOTE=""
if [ "$OK" = "1" ] && [ "$IS_V2" = "1" ] && [ "$BATCH_MODE" != "shared" ]; then
    if "$PY" "$PYHELPER" consume "$BUNDLE" "$CONSUMED" "$TOKEN" 2>/dev/null; then
        BATCH_DONE=$((BATCH_DONE + 1))
    else
        CONSUME_NOTE=" ${YEL}(read-only key: consumed.json not written — server backstop active)${RST}"
    fi
fi

printf '\n'
printf "  ${BLD}=== Assignment of THIS player ===${RST}\n"
printf "  ==========================================================\n"
printf "  ${BLD}> NAME: %s${RST}\n" "$NAME"
if [ "$IS_V2" = "1" ] && [ "$BATCH_MODE" != "shared" ]; then
    printf "  Batch                : ${BLD}%s / %s configured${RST}%b\n" "$BATCH_DONE" "$BATCH_TOTAL" "$CONSUME_NOTE"
fi
printf "  Hostname             : %s\n" "$HOST"
printf "  Backend              : %s  [health: %b]\n" "$BACKEND" "$HEALTH"
printf "  Provisioning token   : %s... (%s)  [written: %s]\n" "$(printf '%s' "$TOKEN" | cut -c1-12)" "sfp_" "$TOKEN_OK"
printf "  Network              : %b\n" "$NET_APPLIED"
[ -n "$WIFI_APPLIED" ] && printf "  Wi-Fi                : %b\n" "$WIFI_APPLIED"
printf "  Resolution           : %s\n" "$RES_APPLIED"
printf "  Time zone            : %b\n" "$TZ_APPLIED"
printf "  Current IP           : %s\n" "${CUR_IP:-(none)}"
printf "  Player account       : %s\n" "$TARGET_USER"
printf "  ==========================================================\n"

if [ "$OK" = "1" ]; then
    printf "  ${GRN}${BLD}Configuration OK.${RST}\n\n"
    printf "  ${BLD}>> Write the label \"%s\" on the player, remove the USB key,${RST}\n" "$NAME"
    printf "  ${BLD}   then press Enter to reboot the player. <<${RST}\n"
    read _ 2>/dev/null || true
    reboot
else
    printf "  ${RED}${BLD}Configuration INCOMPLETE${RST} — check the items in red above (token / network).\n"
    printf "  Nothing was rebooted. Fix and rerun: sudo sf-configure.sh\n"
    exit 2
fi
