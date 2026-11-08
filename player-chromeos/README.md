# SignFlow Player — ChromeOS PWA (§3.9)

> ⚠️ **Le code vit dans `frontend/public/player-chromeos/`, PAS ici.** Ce dossier ne contient
> plus que cette documentation. Il hébergeait jusqu'au 2026-07-19 une copie `src/` supposée
> être la source, en réalité **abandonnée depuis des mois** (961 lignes d'écart sur
> `signflow.js`, 445 sur `player.js`) : Next sert `public/` directement, c'est donc cette
> copie-là qui tourne sur les Chromebox **et sur les BrightSign** (leur `bootstrap.html` charge
> les mêmes fichiers). Le doublon a été supprimé — il a coûté des correctifs appliqués au
> mauvais endroit. **Tout correctif du renderer ChromeOS/BrightSign se fait dans
> `frontend/public/player-chromeos/`.**

Player de digital signage SignFlow porté en **Progressive Web App** pour Chromebox /
Chromebook en **kiosk managé** (console Google Admin) ou PWA plein écran.

## Principe

La coque native Electron (`main.js` + `preload.js`) est remplacée par une PWA :
- `frontend/public/player-chromeos/signflow.js` — **bridge** : expose le même contrat `window.signflow` que le preload
  Electron, mais alimenté par un **WebSocket navigateur** (`/api/v1/ws/player?token=…`) au
  lieu de l'IPC Electron. Provisioning, heartbeat `player:status`, reconnexion backoff +
  watchdog liveness.
- `frontend/public/player-chromeos/player.js`, `frontend/public/player-chromeos/audio_player.js`, `frontend/public/player-chromeos/style.css` — **réutilisés VERBATIM** depuis
  `player-linux/src/renderer/`. `player.js` n'expose pas `window.signflow.mpv` → la vidéo
  passe par le `<video>` Chromium (ChromeOS décode en HW nativement).
- `frontend/public/player-chromeos/index.html` — coque + écran de setup (fallback navigateur hors kiosk).
- `frontend/public/player-chromeos/manifest.webmanifest` + `frontend/public/player-chromeos/icon.svg` — installabilité PWA / kiosk.

> Ces fichiers ont été DÉRIVÉS de `player-linux/src/renderer/` mais ont diverge depuis
> (branches BrightSign, cache local, VOD LAN…). **Ne plus les écraser par une copie du
> renderer Electron** : appliquer les correctifs des deux côtés, comme pour les autres
> surfaces de rendu (le parc en compte 7).

## Périmètre par phase (cf. `docs/PLAN_PORTAGE_CHROMEOS.md`)

| Phase | Contenu | État |
|-------|---------|------|
| **A** | Coque PWA + WS + rendu vidéo/image/web/PDF + audio in-store (Web Audio) | **fait** |
| **B** | Service Worker (app shell offline) + Cache API médias (download-then-play) | **fait** |
| C1 | Routage audio `AudioContext.setSinkId` (brique partagée Windows/BrightSign) | à faire |
| C2 | Store Control Panel médié backend (pas de serveur HTTP embarqué) | à faire |
| C3 | RS232 via WebSerial API | à faire |
| D | LAN sync UDP = **impossible en sandbox PWA** (players non frame-locked) | limite assumée |

En Phase A, les hooks LAN (`onLanAdjust/onLanSwitch/onLanRelease`, `reportPlaybackPos`),
offline (`onStoreUpdate`) et control panel (`onControlApply`) sont stubés (jamais déclenchés).
L'**overlay de maintenance** (`toggle_overlay`) est pleinement supporté.

## Déploiement (servi par le frontend Next, `public/`)

La PWA est servie en statique par Next depuis `frontend/public/player-chromeos/`, qui est la
**source unique** (plus de copie de déploiement). Next sert `public/` à la racine → l'URL
publique est :

```
http://cms.example.com:8080/player-chromeos/index.html
```

Mise à jour sur Ubuntu prod : `git pull` suffit (fichiers statiques, **pas** de purge `.next`
ni de restart frontend nécessaire en `npm run dev`).

Re-synchroniser la copie après un changement de source :
```
```

## Provisioning / kiosk

1. Créer le player dans le CMS et récupérer son **token player** (depuis le container
   **backend**, cf. règles d'or). Un token de provisioning d'org `sfp_…` est aussi accepté
   (le bridge l'échange via `POST /players/register`).
2. **Kiosk managé (Google Admin)** : Devices > Chrome > Apps &
   extensions > **Kiosks** > ajouter une **web app par URL**, avec le token en query :
   ```
   http://cms.example.com:8080/player-chromeos/index.html?token=<JWT_PLAYER>
   ```
   Le bridge lit `?token=` (et `?backend=` optionnel ; sinon = origine de la page), persiste
   en localStorage et purge l'URL. Activer la policy **« Autoriser la lecture automatique »**
   (sinon l'audio in-store attend un geste utilisateur — un tap suffit).
3. **Fallback navigateur** (sans Admin) : ouvrir l'URL sans token → écran de setup pour saisir
   backend + token, puis F11 plein écran.

## Offline (Phase B)

> ⚠️ **Prérequis contexte sécurisé** : les Service Workers ne s'enregistrent qu'en **HTTPS**
> (ou `http://localhost`). Sur l'actuel `http://cms.example.com:8080`,
> `navigator.serviceWorker` est `undefined` → Phase B **inactive**, dégradation **gracieuse**
> (streaming Phase A inchangé, log `[SW] non supporté`). Phase B s'allume dès la mise en
> **HTTPS** du frontend (Caddy/Let's Encrypt ou Cloudflare Tunnel — déjà au roadmap infra).

- **`frontend/public/player-chromeos/sw.js`** (Service Worker) : précache l'app shell (index/js/css/manifest) en
  **network-first** (frais online, repli cache offline → démarrage hors ligne) ; sert les
  médias cachés sous `…/__sf_media__/<cache_key>` en **cache-first avec support Range (206)**
  pour le `<video>`.
- **Store côté page** (dans `signflow.js`) : à chaque `player:sync`, les médias déjà cachés
  voient leur url réécrite vers le chemin local (servi par le SW) ; les manquants sont
  téléchargés en fond (**download-then-play**), puis `store-update` → `player.js` patche en
  place. Cache API pour les octets, IndexedDB (`signflow-store`) pour la meta + **éviction LRU
  par budget** (8 Go soft ; les médias du sync courant sont épinglés). Le boot offline rejoue
  le dernier sync depuis localStorage (urls locales persistées).
- ⚠️ **Prérequis CORS** : le téléchargement cacheable fait un `fetch()` cross-origin vers MinIO
  → MinIO doit renvoyer `Access-Control-Allow-Origin` (défaut MinIO = `*`, donc OK en général).
  Si CORS absent : repli **gracieux** = l'url MinIO de streaming est conservée (online marche,
  pas d'offline pour cet asset). Alternative robuste (+ règle le média WAN) = proxy backend
  same-origin — noté dans `EVOLUTIONS.md`.

## Limites assumées

- Pas de LAN sync frame-locked (sandbox PWA = pas d'UDP) — Phase D, non résoluble.
- `screenshot`/`reboot_os` natifs indisponibles (reload en repli).
- Chiffrement at-rest des médias cachés (Cache API/IndexedDB) : non implémenté (cf. règle
  sécurité ChromeOS du CLAUDE.md) — à traiter avant prod.
