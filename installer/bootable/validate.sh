#!/bin/sh
# SignFlow — validateur matériel (live boot Alpine). POSIX/busybox.
# Valide le MATÉRIEL d'une machine candidate (CPU/RAM/stockage/GPU/réseau) puis écrit un rapport
# sur la clé USB (partition FAT « SIGNFLOW ») et affiche le verdict à l'écran.
#
# Config optionnelle : un fichier `signflow-check.conf` à la racine de la clé avec :
#   BACKEND=https://cms.example.com
#   PROFILE=fhd            # ou 4k

set -u

# ── Seuils par profil ─────────────────────────────────────────────────────────
PROFILE="fhd"
BACKEND="https://cms.example.com"

REQ_CORES_FHD=2;  REQ_RAM_FHD=2;  REQ_DISK_FHD=8
REQ_CORES_4K=4;   REQ_RAM_4K=4;   REQ_DISK_4K=16

RED='\033[31m'; GRN='\033[32m'; YEL='\033[33m'; CYN='\033[36m'; BLD='\033[1m'; RST='\033[0m'

CHECKS=""       # lignes "STATUS|Nom|Détail"
HARD_FAIL=0; ANY_FAIL=0; ANY_WARN=0
MODLOOP_STATE="init"   # renseigné par ensure_modloop (diagnostic modules noyau)

add() {  # $1=status $2=nom $3=détail $4=hard(0/1)
    CHECKS="${CHECKS}$1|$2|$3
"
    [ "$1" = "FAIL" ] && { ANY_FAIL=1; [ "${4:-0}" = "1" ] && HARD_FAIL=1; }
    [ "$1" = "WARN" ] && ANY_WARN=1
}

# ── Trouver la clé USB (partition FAT « SIGNFLOW ») ────────────────────────────
# En boot diskless, Alpine a DÉJÀ monté le média de boot (souvent en lecture seule). On réutilise
# ce montage (remount rw) plutôt que de re-monter le périphérique (occupé).
USB_MNT=""
writable_here() {  # $1 = point de montage ; remonte rw + teste l'écriture
    mount -o remount,rw "$1" 2>/dev/null
    if ( echo x > "$1/.sfw" ) 2>/dev/null; then rm -f "$1/.sfw" 2>/dev/null; return 0; fi
    return 1
}
find_usb() {
    # 1) média de boot déjà monté (vfat) et qui porte nos fichiers → on l'utilise
    while read -r _dev mnt fstype _rest; do
        case "$fstype" in vfat|msdos) ;; *) continue;; esac
        [ -e "$mnt/boot/modloop-lts" ] || [ -e "$mnt/signflow-check.conf" ] || continue
        if writable_here "$mnt"; then USB_MNT="$mnt"; return 0; fi
    done < /proc/mounts
    # 2) sinon : n'importe quel vfat monté et inscriptible
    while read -r _dev mnt fstype _rest; do
        case "$fstype" in vfat|msdos) ;; *) continue;; esac
        if writable_here "$mnt"; then USB_MNT="$mnt"; return 0; fi
    done < /proc/mounts
    # 3) pas monté : tente de monter par label puis par type
    for dev in $(blkid 2>/dev/null | grep -i 'LABEL="SIGNFLOW"' | cut -d: -f1) \
               $(blkid 2>/dev/null | grep -i 'TYPE="vfat"' | cut -d: -f1); do
        mkdir -p /media/sfusb 2>/dev/null
        if mount -o rw "$dev" /media/sfusb 2>/dev/null; then USB_MNT=/media/sfusb; return 0; fi
    done
    return 1
}

load_conf() {
    [ -n "$USB_MNT" ] && [ -f "$USB_MNT/signflow-check.conf" ] || return 0
    . "$USB_MNT/signflow-check.conf" 2>/dev/null || true
    [ -n "${PROFILE:-}" ] && PROFILE="$PROFILE"
    [ -n "${BACKEND:-}" ] && BACKEND="$BACKEND"
}

ensure_modloop() {
    # CORRECTIF CLÉ : notre média custom (fichiers copiés sur FAT32) ne déclenche pas la découverte
    # native du modloop par l'initramfs Alpine → /lib/modules absent → AUCUN module noyau (NIC, GPU…)
    # chargeable. On monte le modloop nous-mêmes (comme le fait l'initramfs : squashfs → bind).
    kr=$(uname -r 2>/dev/null)
    [ -f "/lib/modules/$kr/modules.dep" ] && return 0     # déjà monté par l'initramfs → rien à faire
    ml=""
    for base in "$USB_MNT" /media/* /media/*/.. ; do
        [ -f "$base/boot/modloop-lts" ] && { ml="$base/boot/modloop-lts"; break; }
    done
    [ -n "$ml" ] || { MODLOOP_STATE="introuvable"; return 1; }
    modprobe squashfs 2>/dev/null; modprobe loop 2>/dev/null
    mkdir -p /.smodloop 2>/dev/null
    if ! mount -o loop,ro -t squashfs "$ml" /.smodloop 2>/dev/null; then
        MODLOOP_STATE="mount-echec"; return 1
    fi
    mkdir -p /lib/modules 2>/dev/null
    if [ -d "/.smodloop/modules/$kr" ]; then
        mount --bind /.smodloop/modules /lib/modules 2>/dev/null
    elif [ -d "/.smodloop/$kr" ]; then
        mount --bind /.smodloop /lib/modules 2>/dev/null
    fi
    if [ -f "/lib/modules/$kr/modules.dep" ]; then
        MODLOOP_STATE="monte-par-validateur"
        # coldplug complet : charge les pilotes de tous les périphs présents (réseau, GPU…)
        for m in /sys/bus/*/devices/*/modalias; do
            [ -e "$m" ] && modprobe -q "$(cat "$m" 2>/dev/null)" 2>/dev/null
        done
        return 0
    fi
    MODLOOP_STATE="bind-echec"; return 1
}

# ── Sondes ────────────────────────────────────────────────────────────────────
check_cpu() {
    cores=$(grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo 0)
    model=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ *//')
    [ "$PROFILE" = "4k" ] && need=$REQ_CORES_4K || need=$REQ_CORES_FHD
    [ "$cores" -ge "$need" ] 2>/dev/null && st=PASS || st=FAIL
    add "$st" "Coeurs CPU" "$cores (min $need) ${model:+- $model}" 1
}
check_ram() {
    kb=$(grep -m1 MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}')
    gb=$(awk "BEGIN{printf \"%.1f\", ${kb:-0}/1000000}")
    [ "$PROFILE" = "4k" ] && need=$REQ_RAM_4K || need=$REQ_RAM_FHD
    awk "BEGIN{exit !(${gb:-0} >= $need)}" && st=PASS || st=FAIL
    add "$st" "Memoire RAM" "$gb Go (min $need Go)" 1
}
check_disk() {
    # plus gros disque FIXE (exclut usb/loop/ram/rom)
    best=0; bestname=""
    for d in /sys/block/*; do
        n=$(basename "$d")
        case "$n" in loop*|ram*|sr*|zram*) continue;; esac
        [ "$(cat "$d/removable" 2>/dev/null)" = "1" ] && continue
        sec=$(cat "$d/size" 2>/dev/null || echo 0)
        gb=$(awk "BEGIN{printf \"%d\", $sec*512/1000000000}")
        [ "$gb" -gt "$best" ] 2>/dev/null && { best=$gb; bestname=$n; }
    done
    [ "$PROFILE" = "4k" ] && need=$REQ_DISK_4K || need=$REQ_DISK_FHD
    if [ "$best" -eq 0 ]; then
        add "FAIL" "Stockage interne" "aucun disque fixe détecté" 1
    else
        [ "$best" -ge "$need" ] 2>/dev/null && st=PASS || st=FAIL
        add "$st" "Stockage interne" "$best Go sur $bestname (min $need Go)" 1
    fi
}
check_gpu() {
    if [ -e /dev/dri/renderD128 ] || [ -e /dev/dri/card0 ]; then
        name=""
        for c in /sys/bus/pci/devices/*/class; do
            cl=$(cat "$c" 2>/dev/null)
            case "$cl" in 0x0300*|0x0380*)
                dev=$(dirname "$c")
                vd=$(cat "$dev/vendor" 2>/dev/null); pd=$(cat "$dev/device" 2>/dev/null)
                name="$vd:$pd"; break;; esac
        done
        add "PASS" "Decodage video (GPU)" "/dev/dri present ${name:+PCI $name}"
    else
        add "WARN" "Decodage video (GPU)" "pas de /dev/dri - decodage logiciel probable"
    fi
}
mod_state() {  # état compact du sous-système modules (pour la ligne WARN + photo écran)
    kr=$(uname -r 2>/dev/null)
    nm=$(grep -c '' /proc/modules 2>/dev/null || echo 0)
    ml=non; grep -q '/lib/modules' /proc/mounts 2>/dev/null && ml=oui
    dep=non; [ -f "/lib/modules/$kr/modules.dep" ] && dep=oui
    echo "lsmod=$nm modloop=$ml dep=$dep"
}
net_pci_summary() {  # résumé compact des périphs PCI de classe réseau (02xx) + driver lié
    out=""
    for c in /sys/bus/pci/devices/*/class; do
        cl=$(cat "$c" 2>/dev/null); case "$cl" in 0x02*) ;; *) continue;; esac
        dev=$(dirname "$c")
        vd=$(cat "$dev/vendor" 2>/dev/null); pd=$(cat "$dev/device" 2>/dev/null)
        drv="-"; [ -e "$dev/driver" ] && drv=$(basename "$(readlink "$dev/driver" 2>/dev/null)")
        out="${out}${out:+ ; }${vd#0x}:${pd#0x} drv=$drv"
    done
    [ -n "$out" ] && echo "$out" || echo "aucun periph PCI reseau"
}
write_net_diag() {  # dump complet (fichier sur la clé) pour le cas "pas d'interface" ; imprime son chemin
    [ -n "$USB_MNT" ] || return 0
    d="$USB_MNT/rapports"; mkdir -p "$d" 2>/dev/null
    f="$d/diag-net-$(date '+%Y%m%d-%H%M%S' 2>/dev/null || echo horodate).txt"
    {
        echo "Vitrail - diagnostic reseau (aucune interface detectee)"
        echo "Date: $(date 2>/dev/null)"
        echo "=== /sys/class/net ==="; ls -1 /sys/class/net 2>/dev/null
        echo "=== PCI classe reseau (02xx) : device  vendor:device  class  driver ==="
        for c in /sys/bus/pci/devices/*/class; do
            cl=$(cat "$c" 2>/dev/null); case "$cl" in 0x02*) ;; *) continue;; esac
            dev=$(dirname "$c")
            vd=$(cat "$dev/vendor" 2>/dev/null); pd=$(cat "$dev/device" 2>/dev/null)
            drv="-"; [ -e "$dev/driver" ] && drv=$(basename "$(readlink "$dev/driver" 2>/dev/null)")
            echo "$(basename "$dev")  ${vd}:${pd}  class=$cl  driver=$drv"
        done
        echo "=== modules charges (lsmod) ==="; lsmod 2>/dev/null
        echo "=== dmesg (reseau / firmware) ==="
        dmesg 2>/dev/null | grep -iE 'eth[0-9]|net|firmware|r8169|e1000|igb|igc|alx|tg3|realtek|link is|renamed' | tail -50
    } > "$f" 2>/dev/null
    sync
    echo "${f#"$USB_MNT/"}"
}
find_net_iface() {  # imprime la 1re interface PHYSIQUE (filaire préférée), sinon rien
    wired=""; other=""
    for i in /sys/class/net/*; do
        [ -e "$i" ] || continue
        n=$(basename "$i"); [ "$n" = "lo" ] && continue
        [ -e "$i/device" ] || continue          # exclut lo + interfaces virtuelles (bridge/veth)
        case "$n" in
            en*|eth*) [ -z "$wired" ] && wired="$n";;
            *)        [ -z "$other" ] && other="$n";;
        esac
    done
    [ -n "$wired" ] && { echo "$wired"; return 0; }
    [ -n "$other" ] && { echo "$other"; return 0; }
    return 1
}
check_network() {
    # Le driver PCI du NIC peut être sondé tardivement au boot (coldplug asynchrone) → une sonde
    # mono-passe donne un faux « aucune interface » sur une machine pourtant câblée. On force un
    # coldplug générique (par modalias, aucun nom de module en dur) puis on attend son apparition.
    iface=$(find_net_iface) || {
        for ma in /sys/bus/*/devices/*/modalias; do
            [ -e "$ma" ] && modprobe -q "$(cat "$ma" 2>/dev/null)" 2>/dev/null
        done
        # repli : charge explicitement les pilotes Ethernet courants (vieilles machines dont le
        # coldplug par modalias ne résout pas le module) — sans effet si le module est absent.
        modprobe -a r8169 e1000 e1000e igb igc alx atl1c atl1e tg3 via-rhine sky2 skge \
                 8139too 8139cp pcnet32 forcedeth ne2k-pci natsemi 2>/dev/null
        t=0
        while [ $t -lt 15 ]; do
            iface=$(find_net_iface) && break
            sleep 1; t=$((t+1))
        done
    }
    if [ -z "$iface" ]; then
        p=$(write_net_diag)
        add "WARN" "Interface reseau" "aucune interface physique - $(mod_state) modloop=$MODLOOP_STATE - PCI: $(net_pci_summary)${p:+ [detail: $p]}"
        return
    fi
    ip link set "$iface" up 2>/dev/null
    # attendre le LIEN (carrier) : un switch avec STP sans portfast peut bloquer le port ~30 s
    # → sans cette attente, le DHCP partait trop tôt et échouait (cas NUC).
    c=0; while [ $c -lt 25 ] && [ "$(cat "/sys/class/net/$iface/carrier" 2>/dev/null)" != "1" ]; do
        sleep 1; c=$((c+1))
    done
    if [ "$(cat "/sys/class/net/$iface/carrier" 2>/dev/null)" != "1" ]; then
        add "WARN" "Reseau (lien)" "$iface : pas de lien filaire (câble débranché / port mort ?)"; return
    fi
    # DHCP patient + jusqu'à 3 essais (le port peut encore être en train de converger)
    myip=""; n=0
    while [ $n -lt 3 ] && [ -z "$myip" ]; do
        udhcpc -i "$iface" -n -q -t 5 -T 3 >/dev/null 2>&1
        myip=$(ip -4 addr show "$iface" 2>/dev/null | grep -o 'inet [0-9.]*' | awk '{print $2}' | head -1)
        [ -z "$myip" ] && { n=$((n+1)); sleep 2; }
    done
    if [ -z "$myip" ]; then
        add "WARN" "Reseau (DHCP)" "$iface : lien OK mais pas d'adresse (serveur DHCP absent ?)"; return
    fi
    add "PASS" "Reseau (DHCP)" "$iface : $myip"
    host=$(echo "$BACKEND" | sed -e 's#https\?://##' -e 's#[:/].*##')
    if wget -q -T 8 --no-check-certificate -O /dev/null "$BACKEND/health" 2>/dev/null; then
        add "PASS" "Serveur SignFlow" "$host joignable (/health OK)"
    elif ping -c1 -W2 "$host" >/dev/null 2>&1; then
        add "WARN" "Serveur SignFlow" "$host répond au ping mais /health KO"
    else
        add "WARN" "Serveur SignFlow" "$host injoignable"
    fi
}

# ── Rapport ───────────────────────────────────────────────────────────────────
verdict() {
    if [ "$HARD_FAIL" = "1" ] || [ "$ANY_FAIL" = "1" ]; then echo "NON VALIDE"
    elif [ "$ANY_WARN" = "1" ]; then echo "VALIDE AVEC RESERVES"
    else echo "VALIDE"; fi
}

write_reports() {
    [ -n "$USB_MNT" ] || return 0
    dir="$USB_MNT/rapports"; mkdir -p "$dir" 2>/dev/null
    host=$(cat /proc/sys/kernel/hostname 2>/dev/null || echo machine)
    ts=$(date '+%Y%m%d-%H%M%S' 2>/dev/null || echo horodate)
    base="$dir/rapport-boot-$ts"
    v=$(verdict)
    {
        echo "Vitrail - Validation materielle (boot) - profil $PROFILE"
        echo "Date: $(date 2>/dev/null)"
        echo "----------------------------------------------------------"
        printf '%s\n' "$CHECKS" | while IFS='|' read -r s n d; do
            [ -z "$s" ] && continue
            printf '  %-5s %-26s %s\n' "$s" "$n" "$d"
        done
        echo "----------------------------------------------------------"
        echo "VERDICT: $v"
    } > "$base.txt" 2>/dev/null
    {
        vcol="#2E7D32"; [ "$v" = "NON VALIDE" ] && vcol="#C62828"; [ "$v" = "VALIDE AVEC RESERVES" ] && vcol="#E65100"
        echo "<!doctype html><meta charset=utf-8><title>Vitrail - $host</title>"
        echo "<body style='font-family:sans-serif;background:#F8F7F5;padding:24px;max-width:720px;margin:auto'>"
        echo "<h2>Vitrail - Validation materielle (boot)</h2><small>profil $PROFILE - $(date 2>/dev/null)</small>"
        echo "<table style='width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb'>"
        printf '%s\n' "$CHECKS" | while IFS='|' read -r s n d; do
            [ -z "$s" ] && continue
            col="#2E7D32"; [ "$s" = "FAIL" ] && col="#C62828"; [ "$s" = "WARN" ] && col="#E65100"; [ "$s" = "INFO" ] && col="#1565C0"
            echo "<tr><td style='padding:8px;border-bottom:1px solid #f1f1f1'><b style='color:$col'>$s</b></td><td style='padding:8px'>$n</td><td style='padding:8px'>$d</td></tr>"
        done
        echo "</table><div style='margin-top:16px;padding:12px;border-radius:8px;color:#fff;font-weight:600;background:$vcol'>VERDICT : $v</div></body>"
    } > "$base.html" 2>/dev/null
    sync
    REPORT_PATH="$base.txt"
}

print_console() {
    v=$(verdict)
    printf '\n'
    printf "  ${BLD}Vitrail - Validation materielle${RST}  (profil %s)\n" "$PROFILE"
    printf '  ----------------------------------------------------------\n'
    printf '%s\n' "$CHECKS" | while IFS='|' read -r s n d; do
        [ -z "$s" ] && continue
        c="$CYN"; [ "$s" = "PASS" ] && c="$GRN"; [ "$s" = "WARN" ] && c="$YEL"; [ "$s" = "FAIL" ] && c="$RED"
        printf "  ${c}%-5s${RST} %-26s %s\n" "$s" "$n" "$d"
    done
    printf '  ----------------------------------------------------------\n'
    vc="$GRN"; [ "$v" = "NON VALIDE" ] && vc="$RED"; [ "$v" = "VALIDE AVEC RESERVES" ] && vc="$YEL"
    printf "  ${vc}${BLD}VERDICT : %s${RST}\n\n" "$v"
    [ -n "${REPORT_PATH:-}" ] && printf "  Rapport ecrit sur la cle : %s\n\n" "${REPORT_PATH#"$USB_MNT/"}"
}

# ── Exécution ─────────────────────────────────────────────────────────────────
find_usb || true
load_conf
ensure_modloop || true
check_cpu
check_ram
check_disk
check_gpu
check_network
write_reports
print_console
# marqueur capté par le test QEMU (sur écran réel = console tty1, redondant/inoffensif)
echo "SIGNFLOW-DONE verdict=[$(verdict)] usb=[${USB_MNT:-none}] report=[${REPORT_PATH:-none}]" \
    > /dev/console 2>/dev/null || true
sync
[ "$USB_MNT" = "/media/sfusb" ] && umount /media/sfusb 2>/dev/null || true
