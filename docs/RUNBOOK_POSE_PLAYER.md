# Runbook — poser un player SignFlow en clientèle

**Éprouvé de bout en bout le 2026-08-09** sur les trois canaux : Raspberry Pi (carte SD, machine
nue), Windows 11 (WinRM, machine déjà installée), Linux/RPi (SSH, machine déjà en service).

> **Ce document dit comment POSER un player chez un client.**
> À ne pas confondre avec :
> - `installer/RUNBOOK_TEST_HW.md` — comment **tester** les canaux (recette interne) ;
> - `docs/RUNBOOK_POSE_ANDROID_TV.md` — la pose sur **boîtier Android TV**, qui a ses propres
>   pièges (Device Owner, launcher, factory reset) ;
> - `docs/RUNBOOK_DIAGNOSTIC.md` — quand un player **déjà posé** ne va pas.

---

## 1. Le principe, en une phrase

Le CMS génère un **payload** — l'URL du serveur + un **jeton `sfp_` à usage unique** — et
**pré-crée le player** côté serveur. Le device s'y **ré-attache** à son premier contact, échange
le jeton contre un JWT permanent, et apparaît *online*.

```
CMS ──payload (sfp_)──> [ carte SD | WinRM | SSH | ADB ] ──> player ──register──> online
```

⚠️ **Un jeton consommé ne resert pas.** Si une pose échoue après l'enregistrement, il faut
**regénérer un payload** — sinon l'essai suivant échouera pour une raison sans rapport avec la
vraie cause, et vous chercherez au mauvais endroit.

---

## 2. À préparer une seule fois (poste du technicien)

### 2.1 La clé opérateur

Dans le CMS, en **org-admin** : **Provisioning → « Clé opérateur »** → générer → copier la clé
`sfk_…` (affichée **une seule fois**). Puis, sur le poste :

```bash
signflow-provision --cms https://<votre-serveur>:8443 --key sfk_… --save-config
```

→ plus rien à ressaisir ensuite. La clé est **scopée provisioning** (créer un payload, lire l'état
d'un player) — elle ne donne **pas** les droits org-admin — et elle est révocable depuis le CMS.

⚠️ **La clé `sfk_` expire** (défaut **90 jours**, réglable jusqu'à 730 à la création). Un
`--save-config` qui échoue avec « Authentification CMS refusée » des mois plus tard, c'est
probablement elle : en regénérer une dans le CMS.

> *Alternative sans clé* : `--token <JWT org-admin>`, mais il **expire en 15 minutes**. À éviter
> sur le terrain.

### 2.2 L'outil

- **Technicien sans Python** : copier **un seul fichier**, `installer/dist/signflow-provision.exe`
  (~13 Mo). Rien d'autre à installer.

  ⚠️ **Vérifier la fraîcheur de l'exe distribué** : `signflow-provision --selftest` doit afficher
  « code du 2026-08-16 » (ou plus récent). Un exe plus ancien ne contient pas les correctifs du
  2026-08-09 (canal SSH qui n'écrivait aucune config). Reconstruire :
  `cd installer && pyinstaller --clean signflow-provision.spec`.
- **Poste avec Python** : `cd installer && pip install -r requirements.txt`, puis
  `python -m signflow_provision …`.

Vérifier les canaux disponibles : `signflow-provision --selftest`.

---

## 3. Quel canal choisir

| Situation | Canal | Geste humain requis sur place |
|---|---|---|
| **Raspberry Pi neuf** (rien dessus) | Carte SD | insérer la carte, allumer — **c'est tout** |
| **PC Windows déjà installé** | WinRM | ouvrir WinRM une fois (§5.1) |
| **Linux / RPi déjà en service** | SSH | aucun si SSH est déjà ouvert |
| **Boîtier Android** | ADB | activer le débogage USB → `docs/RUNBOOK_POSE_ANDROID_TV.md` |
| **BrightSign** | ZIP sur carte SD | copier le `config.json` produit à la racine d'une SD déjà préparée (ZIP du CMS) |

**Règle générale** : l'outil ne peut pas ouvrir la porte à votre place. Un **foothold** (WinRM,
SSH, ADB, accès physique à la SD) doit exister ; tout le reste est automatisé.

---

## 4. Raspberry Pi neuf — carte SD

### 4.1 Construire l'image (une fois par version de player, pas par machine)

Sur une machine avec Docker (le build a besoin du mode privilégié : loop + device-mapper) :

```bash
cd installer/image-rpi && mkdir -p out cache
docker run --rm --privileged \
  -v "$PWD:/work/src:ro" -v "$(git rev-parse --show-toplevel):/work/repo:ro" \
  -v "$PWD/out:/work/out" -v "$PWD/cache:/work/cache" \
  alpine:3.20 sh /work/src/build.sh
```

En fin de build, **noter le mot de passe affiché** — il est généré aléatoirement et écrit dans
`out/signflow-rpi.credentials.txt` :

```
- compte système : signflow / <mot de passe>
```

> `RPI_PASSWORD=…` permet d'en imposer un. Ce compte sert au **dépannage sur site** (SSH), il a
> `sudo`. Sans lui, une machine en échec serait inspectable par personne.

### 4.2 Injecter le payload (une fois par machine)

Générer le payload depuis le CMS (**Provisioning → Générer un payload**, `os = rpi`), puis le
placer dans la partition **boot** de l'image, sous le nom `signflow-provision.json`, à la place du
fichier d'exemple.

> La partition boot est en FAT : elle est lisible sous Windows après le flash, si vous préférez
> flasher d'abord et éditer ensuite.

### 4.3 Flasher

**Raspberry Pi Imager** (choisir « image personnalisée ») ou `dd`.

⚠️ **Avant tout `dd`, vérifier trois fois la lettre du disque.** Une erreur écrase un disque de
données sans confirmation. Contrôles minimaux : le périphérique doit être en **USB**, faire la
**taille de la carte**, et **ne pas être monté**.

### 4.4 Sur site

> **Insérer la carte. Brancher réseau et écran. Allumer. Ne rien faire.**

L'écran affiche :

```
===============================================
   SignFlow - installation du player en cours
   NE PAS ETEINDRE / DO NOT POWER OFF
===============================================
[signflow-firstboot] attente de l'horloge (NTP)...
[signflow-firstboot] reseau utilisable (serveur joignable)
  -> installation de Node, Electron et du player (plusieurs minutes)...
```

puis **« Installation TERMINEE - redemarrage dans 5s »**. La machine redémarre **seule** et le
player démarre en kiosque. Compter **~10 minutes**, internet requis.

**Aucune question n'est posée. Aucun clavier n'est nécessaire. Aucun second démarrage.**

En cas d'échec, l'écran affiche la cause et les dernières lignes du journal, puis rend la main.
**Redémarrer suffit à relancer un essai** : le service reste armé tant qu'il n'a pas réussi.

---

## 5. PC Windows déjà installé — WinRM

### 5.1 Ouvrir le foothold (une fois, sur la machine cible, PowerShell administrateur)

```powershell
Set-NetConnectionProfile -NetworkCategory Private   # sinon Enable-PSRemoting échoue
Enable-PSRemoting -Force
New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' `
  -Name LocalAccountTokenFilterPolicy -PropertyType DWord -Value 1 -Force
```

> La 1ʳᵉ ligne n'est pas décorative : sur une machine fraîche le réseau est classé « Public » et
> `Enable-PSRemoting` refuse. La 3ᵉ non plus : sans elle, le compte admin **local** reçoit par le
> réseau un jeton bridé, et les écritures dans `%APPDATA%` échouent. L'outil affiche
> `admin=True/False` — **si c'est `False`, cette clé n'a pas pris.**

### 5.2 Déposer les sources du player

Copier le dossier `player-windows/` sur la machine, par exemple dans `C:\signflow\player-windows`.

### 5.3 Poser, depuis le poste du technicien

```bash
signflow-provision --ref "PC Accueil" --os windows \
  --winrm 192.168.1.32 --winrm-user Administrateur --winrm-password '…' \
  --source 'C:\signflow\player-windows' --start-task
```

L'outil installe **Node.js s'il manque**, pose Electron, écrit la config, démarre la tâche
planifiée et **attend le passage online** avant de rendre la main.

- `--windows-user <compte>` si le **compte kiosk** diffère du compte WinRM (c'est son `%APPDATA%`
  qui reçoit la configuration).
- Sans `--source`, l'outil suppose le player **déjà installé** et ne dépose que la configuration.

> Un `UserWarning` pywinrm sur la conversion d'un message PowerShell est **cosmétique** — ignorer
> si le player passe online.

---

## 6. Linux ou Raspberry Pi déjà en service — SSH

```bash
signflow-provision --ref "Vitrine Lyon" --os rpi --ssh signflow@192.168.1.20
```

L'outil relance l'installeur présent sur la machine, écrit la configuration **dans le répertoire
que le player lit réellement**, puis **relance le player** pour qu'il la prenne en compte.

- `--player-user <compte>` si le player tourne sous un autre compte que `signflow`.
- L'authentification passe par le binaire `ssh` : prévoir une **clé** (un mot de passe interactif
  ne peut pas être fourni à l'outil).

**Prérequis du canal SSH** : le player doit être installé sous `/opt/signflow/player-rpi` ou
`/opt/signflow/player-linux`, et le compte du player avoir son home sous `/home/<compte>` —
ces chemins sont codés dans le driver. Sinon le canal s'arrête en le disant.

---

## 7. Vérifier que la pose a réussi

Ne pas se contenter du message de l'outil. Trois preuves :

1. **Le CMS** : le player est **online**, avec le bon OS, et il n'y a **qu'une seule ligne**
   (pas de doublon).
2. **Le jeton a été consommé** : dans le `config.json` du player, `player_token` commence par
   `eyJ…` (un JWT) et **plus** par `sfp_`. S'il commence encore par `sfp_`, l'enregistrement n'a
   pas eu lieu. ⚠️ Sur **Windows**, avant enregistrement la clé s'appelle `org_token` (le player
   la remplace par `player_token` en s'enregistrant) — la preuve est donc « le `org_token` sfp_
   a disparu au profit d'un `player_token` eyJ… », pas « player_token commence encore par sfp_ ».
3. **L'écran** diffuse (ou affiche le repli si aucun contenu n'est programmé).

---

## 8. Pièges (tous rencontrés en réel)

**Re-provisionner un player existant sans `--reattach <id>` crée un DOUBLON.** Récupérer l'`id`
dans le CMS → Players. À noter : un `--dry-run` **crée aussi** un player côté CMS.

**La clé d'hôte SSH change à chaque réinstallation.** Le refus qui suit (`REMOTE HOST
IDENTIFICATION HAS CHANGED`) est le système qui fait son travail. Retirer l'ancienne empreinte :
`ssh-keygen -R <ip>`. ⚠️ Tant qu'elle n'est pas retirée, OpenSSH **désactive aussi
l'authentification par mot de passe** — on croit à un mauvais mot de passe alors que c'est la clé.

**Un Raspberry Pi n'a pas d'horloge.** Au premier démarrage il repart de la date de l'image ; tant
que NTP n'a pas synchronisé, **toute connexion HTTPS est refusée** (« certificate is not yet
valid »). L'image gère l'attente — mais si un site bloque NTP, l'installation échouera et le dira.

**Une machine sans réseau au bon moment échoue proprement** : le message le dit, et un
redémarrage relance l'essai. Ne pas réinstaller la carte pour autant.

**Windows n'a aucun pilote virtio.** Sur une VM, utiliser un disque **SATA** et une carte réseau
**e1000e**, sinon l'installateur ne voit pas le disque et la machine n'a pas de réseau.

---

## 9. Si ça ne marche pas

**Raspberry Pi** — se connecter en SSH avec le compte du build (`signflow` + le mot de passe de
`signflow-rpi.credentials.txt`, il a `sudo`) :

```bash
cat /var/log/signflow-firstboot.log     # tout le déroulé, y compris la sortie de l'installeur
tail -f /var/log/signflow-player.log    # le player une fois installé
```

> Ce journal **survit au redémarrage**, contrairement au journal systemd de cette image. C'est la
> première chose à lire.

**Windows** — vérifier que la tâche existe et que la configuration est au bon endroit :

```powershell
Get-ScheduledTask 'SignFlow Player'
Get-Content "$env:APPDATA\signflow-player-windows\config.json"
```

**Tous OS** — si le player reste sur « Setup required » alors que la configuration existe, c'est
qu'il **ne lit pas le fichier que vous regardez**. Le répertoire est
`~/.config/<nom du paquet>` sur linux/rpi (`signflow-player-rpi`, `signflow-player`), et
`%APPDATA%\signflow-player-windows` sur Windows. Le nom est **dérivé du `package.json`** du player
(`app.getPath('userData')`) — jamais réécrit à la main.

Pour la suite, voir `docs/RUNBOOK_DIAGNOSTIC.md`.
