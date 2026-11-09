# Vitrail — Installeur terrain (§XXIX)

🇬🇧 [English version](README.md)

Outil CLI de provisioning « **1 payload, plusieurs canaux** ». Pose Vitrail sur un player par
un technicien, avec un minimum de gestes et zéro connaissance des détails par OS.

> **Statut : les 3 canaux réseau sont validés sur matériel (2026-08-09).**
> **Android (ADB)** ✅ validé HW (MINIX) · **Windows (WinRM)** ✅ validé HW (VM Win11 25H2 neuve)
> · **SSH** (Linux/RPi déjà installés) ✅ validé HW (RPi en service) · **BrightSign** (ZIP sur
> carte SD) = ⚠️ **encore JAMAIS validé matériellement au critère ONLINE** — le driver écrivait
> `provisioning_token` (illisible par l'autorun qui lit `token`), corrigé le 2026-08-16 ; à valider
> à la prochaine occasion sur un BrightSign du parc. ChromeOS/extension = hors périmètre.
>
> ⚠️ **Ce README a annoncé « validé HW » avant que ce le soit.** La validation du 2026-08-09 a
> trouvé **14 défauts** : aucun des trois canaux ne posait un player. La cause de l'illusion tient
> en une phrase — **on validait jusqu'à « le script s'est lancé », jamais jusqu'à « le player est
> online »**. Entre les deux, le canal SSH n'écrivait aucune configuration. ⇒ **le seul critère de
> validation d'un canal est le passage ONLINE du player**, jamais le code de retour d'un script.
>
> 👉 **Pour poser un player en clientèle : `docs/RUNBOOK_POSE_PLAYER.md`** (ce README décrit
> l'outil ; le runbook décrit les gestes).
>
> **Orientation (2026-07-05)** : le vrai besoin = **préparer/configurer des players vite et
> simplement** sur les OS cibles réels (Android, Debian 12, Windows 11, RPi, BrightSign). Méthode
> retenue = **master doré cloné (Clonezilla/PXE) + injection d'un bundle de config par machine**
> (token/nom/réseau), sur le modèle BrightSign généralisé. Le canal « boîtier x86 nu → appliance
> Alpine+Chromium » (greenfield x86) a été **abandonné** (énième type de player non demandé, trop
> fragile).

## Principe

```
auth CMS  →  payload (généré ou chargé)  →  driver OS  →  vérif online  →  rapport
```

Le **payload** (`signflow-provision.json`) porte : `ref`, `os`, `backend_url`, `token` (`sfp_`),
`network`, `options`. Il est généré par le CMS (page Provisioning → « Générer un payload », ou
via l'endpoint `POST /orgs/{id}/provisioning-payload`) et pré-crée le player côté CMS (offline) →
le device s'y **ré-attache** à l'enregistrement (verify déterministe, **zéro doublon**).

## Installation

```bash
cd installer
python -m pip install -r requirements.txt
# outil : python -m signflow_provision  (ou packagé en exe via PyInstaller)
```

## Authentification — clé opérateur (recommandé)

L'outil s'authentifie avec **soit** un JWT org-admin (`--token`, **expire en 15 min** → à re-copier
sans cesse), **soit** une **clé opérateur** `sfk_` longue durée / révocable / scopée provisioning
(recommandé). L'org-admin la génère **une fois** dans le CMS (**Provisioning → « Clé opérateur »**) :

```bash
# Config UNIQUE sur la machine du technicien
# (stockée dans %APPDATA%\signflow\provision.json sous Windows — cas nominal du technicien —,
#  ~/.signflow/provision.json sinon ; le chmod 600 n'a d'effet que sur POSIX)
signflow-provision --cms https://cms.example.com --key sfk_… --save-config
```

→ ensuite **plus aucun `--cms`/`--token`/`--key` à re-saisir**. Alternatives : variables
d'env `$SIGNFLOW_CMS` / `$SIGNFLOW_KEY`. La clé est **scopée provisioning** (créer un payload + lire
l'état d'un player) — jamais les droits org-admin généraux ; révocable depuis le CMS. ⚠️ Elle
**expire** (défaut **90 jours**, réglable jusqu'à 730 à la création) — une « Authentification CMS
refusée » des mois plus tard, c'est probablement elle.

## Usage

`signflow-provision` = l'exe PyInstaller ; en dev, `python -m signflow_provision`. Les exemples
supposent la clé configurée (`--save-config` ci-dessus) ; sinon, ajouter `--cms <url> --key sfk_…`.

```bash
# Android — crée un nouveau player, génère le payload et provisionne par ADB
signflow-provision --ref "Boutique Lyon - Vitrine" --os android \
  --ip 192.168.1.50 --apk app-release.apk

# Ré-attache à un player existant (reprovisioning sans doublon)
signflow-provision --os android --ip 192.168.1.50 --reattach 42 --apk app-release.apk

# Linux/RPi déjà installé (SSH)
signflow-provision --ref "NUC Réserve" --os linux --ssh signflow@192.168.1.60

# Windows déjà installé (WinRM) — dépose la config ; --source lance install.ps1
signflow-provision --ref "PC Accueil" --os windows \
  --winrm 192.168.1.70 --winrm-user Administrateur --winrm-password '***' \
  --source 'C:\signflow\player-windows' --start-task

# BrightSign (écrit config.json à copier sur la SD)
# ⚠️ le driver écrivait la clé `provisioning_token` au lieu de `token` (illisible par l'autorun) —
# corrigé le 2026-08-16 ; canal jamais validé HW au critère ONLINE à ce jour
signflow-provision --ref "Vitrine BS" --os brightsign --out ./sd-out

# Réutiliser un payload généré depuis l'UI (Provisioning → « Générer un payload »)
signflow-provision --payload signflow-provision.json --ip 192.168.1.50 --apk app-release.apk

# Répéter les gestes sans rien exécuter
signflow-provision ... --dry-run
```

Réseau OPT-IN : `--wifi-ssid/--wifi-psk` ou `--static-ip/--mask/--gw/--dns`.
Options écran : `--resolution 1920x1080 --rotation 90`.

**Diagnostic** (hors-ligne, sans CMS) — quels canaux sont utilisables ici :
```bash
signflow-provision --selftest
```

## Packaging en .exe (PyInstaller)

Pour un technicien **sans Python**, on gèle le CLI en un exe autonome (Windows) :

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --clean signflow-provision.spec
# → dist/signflow-provision.exe (~13 Mo, onefile)
dist\signflow-provision.exe --selftest      # vérifie les canaux embarqués
```

Le driver Windows importe `winrm` **paresseusement** (pour ne pas l'imposer aux autres OS) → le
spec force la collecte de la chaîne WinRM (`winrm`/`requests_ntlm`/`spnego`/`xmltodict`) en hidden
imports. **Installer `pywinrm` AVANT le build** pour que le canal Windows soit embarqué (sinon l'exe
marche pour Android/SSH/BrightSign mais pas WinRM — `--selftest` le signale). `adb` (Android) et
`ssh` (Linux/RPi) restent des outils système externes, non embarqués dans l'exe.

## Canaux par OS

| OS | Canal | Foothold à ouvrir par le technicien |
|---|---|---|
| **Android** | ADB sur IP | Débogage USB + clé ADB autorisée ; Device Owner ⇒ appareil factory-fresh **sans compte Google**. |
| **Linux / RPi** (installé) | SSH/SCP | SSH activé + identifiants. |
| **Windows** (installé) | WinRM/PSSession | WinRM activé (`Enable-PSRemoting -Force`) + compte **administrateur**. `pywinrm` requis côté outil. |
| **BrightSign** | Carte SD | Générer la SD complète depuis le CMS, y copier le `config.json` produit. ⚠️ Driver corrigé le 2026-08-16 (`provisioning_token` → `token`) ; jamais validé HW au critère ONLINE. |
| **Debian/Windows/RPi** (à préparer) | **master cloné + bundle de config** | Cloner un master OS+player, injecter un bundle (token/nom/réseau). |
| ChromeOS / extension | — | Hors périmètre (enrôlement Google / navigateur). |

## Sécurité

- Le payload contient un **token `sfp_`** → traiter le fichier/QR comme un **secret** (usage
  unique, TTL). Ne rien logger en clair côté CMS.
- L'outil manipule des identifiants device (ADB/SSH) → ne pas les stocker en dur.
- TLS vérifié par défaut (`--insecure` réservé au dev).

## Vérification de capacités (pré-install)

`signflow_check.py` — script **autonome, stdlib uniquement** (aucun pip) à lancer **sur une
machine candidate** (Linux / Windows / RPi / macOS) pour décider si elle peut faire tourner un
player. Rend un verdict **VALIDÉ · VALIDÉ AVEC RÉSERVES · NON VALIDÉ** (console + JSON + HTML).

```bash
python3 signflow_check.py --backend https://cms.example.com --profile fhd
python3 signflow_check.py --profile 4k --json rapport.json --html rapport.html
```

Vérifie : OS/arch supportés, cœurs CPU, RAM, disque libre, résolution écran, **décodage vidéo
matériel** (GPU / `/dev/dri` / V4L2), **synchro horloge (NTP)** — requise pour la sync LAN — et
la **joignabilité du backend** (DNS + TCP + `/health` + latence). Profils : `fhd` (1080p, défaut)
ou `4k` (exige plus de CPU/RAM + décodage matériel). Codes de sortie : 0 = validé, 1 = réserves,
2 = non validé (utilisable en script de déploiement).

**Exe Windows** (pour un technicien sans Python) :
```bash
pip install pyinstaller
pyinstaller --onefile --name signflow-check signflow_check.py
# → dist/signflow-check.exe (double-cliquable / en ligne de commande)
```
Sous Linux/RPi, `python3` est déjà présent → lancer le `.py` directement.

> **Android / BrightSign / ChromeOS** : on ne lance pas Python sur le device. Ces players
> **auto-rapportent leurs capacités** (décodage, résolution, disque) au CMS via `capabilities.json`
> à l'installation + le heartbeat `player:status` → visibles dans le drawer player / le dashboard NOC.

## Provisioning Android par intent

L'app Android accepte un **intent de provisioning** (pas de pilotage clavier) :

```
adb shell am start -n app.vitrail.player/.SetupActivity \
  -e backend_url https://cms.example.com -e token sfp_…
```

`SetupActivity` auto-remplit + auto-enregistre. Nécessite l'APK **release** ≥ la version qui
exporte `SetupActivity` (§XXIX).

## Provisioning Windows par WinRM

Windows n'a **pas d'autorun USB** (bloqué depuis Win7) : sur un PC **déjà installé**, le canal est
**WinRM**. Le driver reproduit à distance `player-windows/install.ps1` (si `--source` fourni) puis
dépose le `config.json` de provisioning que lit le player Electron :

```
%APPDATA%\signflow-player-windows\config.json
  { "backend_url": ..., "org_token": "<sfp_…>", "player_name": "<ref>" }
```

Au 1er lancement, le player s'auto-enregistre (`POST /players/register`), échange `org_token` →
token player et se **ré-attache** au player pré-créé côté CMS (zéro doublon).

**Foothold** (sur le poste cible, une fois) :
```powershell
Enable-PSRemoting -Force        # active WinRM (5985 http / 5986 https)
```

**Options du driver** : `--winrm host[:port]`, `--winrm-user`, `--winrm-password`,
`--winrm-transport {ntlm|basic|credssp|kerberos}` (défaut `ntlm`, chiffre le message sur 5985),
`--winrm-https` (5986), `--windows-user` (compte **kiosk** dont le `%APPDATA%` reçoit la config,
défaut = `--winrm-user`), `--source` (dossier `player-windows` distant → lance `install.ps1`),
`--start-task` ((re)démarre la tâche planifiée « SignFlow Player »).

> Sans `--source`, le driver **ne dépose que la config** (player supposé déjà installé). La config
> statique réseau n'est pas appliquée automatiquement sous Windows (MVP) — à venir via le **bundle
> de config**. Un **boîtier Windows vierge** = installer
> Windows + player une fois, en faire un **master cloné**, puis injecter le bundle par machine.
