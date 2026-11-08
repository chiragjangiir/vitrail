# SPIKE — Players offline-first / Local Content Store (download-then-play)

> Spike de design (2026-06-07). Cadre l'épopée d'`EVOLUTIONS.md § « Players offline-first / Local Content Store »` dans le **code réel** et tranche les décisions d'archi **avant de coder**. Même démarche que `SPIKE_scheduling_targeting_core.md`.
>
> **Verdict : GO**, par phases, en commençant par le **store + download manager mono-player (Linux/RPi)** avec **repli streaming gracieux** (zéro régression). Q5 (quarantaine/purge) déjà livré (migr 0031).

---

## 1. Objectif

Passer les players **Electron** (linux / rpi / windows) du modèle **streaming** (chaque média lu depuis MinIO via URL signée, octets en cache HTTP Chromium) au modèle **download-then-play** (octets téléchargés dans un **store local sur disque**, diffusion depuis le disque).

**Pourquoi :**
- **Résilience offline** (le player tient une coupure réseau au-delà du cache HTTP volatil).
- **Sync LAN robuste** : un mur ne doit pas dépendre d'un fetch réseau à chaque frontière d'item.
- **Règle les seeks de contention de l'AOpen** (mur synchronisé → 4 players re-fetchent au même instant à chaque frontière ; cf. note terrain mur 4 écrans). Avec un store local, plus de fetch aux frontières.
- **Fondation Q4** = preuve de distribution (utile Retail Media).

## 2. État actuel (vérifié dans le code, 2026-06-07)

| Brique | Réalité code |
|---|---|
| Payload serveur | `ws._resolve_sync_payload` → items avec **`url`** (`get_signed_url(storage_key, 86400)` = 24 h), **`checksum_sha256`**, `duration`, sous-titres (`url` signée), audio baskets (`url`). Variante rendition résolue par `_resolve_variant_key` (storage_key de la rendition). |
| Intégrité | **`checksum_sha256` déjà dans le payload** par item → vérification de download **gratuite**. `file_size_bytes` existe sur `cms_media` + renditions (`file_meta`) → exposable pour QoS/disque. |
| Manifeste offline | `player.js::saveSync(payload)` persiste le **manifeste** (localStorage) ; `loadSync()` au boot → le player rejoue le **programme** hors-ligne, mais **pas les octets** (les `url` MinIO signées sont mortes hors-ligne / après 24 h). |
| Lecture média | `player.js` : `video.src = media.url` (stream direct MinIO). **Précache** double-buffer (`precacheNext`/`clearPreload`, conteneur caché) = réchauffe le cache HTTP du suivant. |
| Position / resync | `main.js::lastSyncState` `{id_playlist,currentIndex,currentOffsetMs,syncedAt}` → reprise gracieuse wall-clock. |
| Purge Q5 | `main.js` handler `player:purge_media` → `session.clearCache()` (**cache HTTP**, best-effort). `_blockedMedia` (payload + offline) → `playCurrentItem` saute les ids bloqués même offline. |
| Stockage | `app.getPath('userData')` (config.json, display_config.json, capabilities.json, logs/). **Pas de store de contenu.** |
| Capabilities / heartbeat | `capabilities` (decode + display_modes) fusionnées dans `player:status` → le backend **remplace** le dict (pattern à réutiliser pour l'inventaire Q4 : un seul objet). |

**Conclusion** : le manifeste + checksums + file_size + précache + position existent déjà. Ce qui manque = **les octets sur disque** et **un download manager**. Le changement est **surtout côté player** ; le serveur change **peu** (exposer `file_size`, et plus tard un set épinglé + alertes).

## 3. Architecture cible

```
┌─ main.js (Node) ──────────────────────────────────────────────┐
│  ContentStore (<userData>/content_store/)                      │
│   - fichiers nommés par checksum : <sha256>.<ext>              │
│   - index.json : {id_media|variant_key -> {checksum,size,      │
│                    last_used, pinned, status}}                  │
│   - écriture atomique : .part -> fsync -> rename               │
│   - vérif checksum après download (sinon rejet + re-DL)        │
│  DownloadManager                                               │
│   - file d'attente (épinglé d'abord, look-ahead ensuite)       │
│   - HTTP range résumable, N concurrents, token-bucket (Q3)     │
│   - fenêtres autorisées = TimeRule du noyau scheduling (Q3)    │
│  protocol signflow:// (registerFileProtocol/protocol.handle)   │
│   - sert les octets locaux au renderer AVEC support Range      │
│     (seek vidéo pour la sync) ; 404 si pas encore en cache     │
└───────────────────────────────────────────────────────────────┘
        │ IPC (preload)                       ▲
        ▼                                     │ 'cache:status' (inventaire Q4)
┌─ player.js (renderer) ────────────────────────────────────────┐
│  resolveSrc(media) :                                           │
│    local prêt  -> signflow://media/<checksum>                  │
│    sinon        -> media.url (REPLI STREAMING gracieux)        │
│  (précache inchangé, mais pointe sur le local quand prêt)      │
│  LAN : barrière de readiness par empreinte + garde d'index (Q1)│
└───────────────────────────────────────────────────────────────┘
```

**Principe de non-régression** : tant qu'un octet n'est pas en cache local vérifié, le renderer **streame** (`media.url`). Le store se remplit en fond ; au sync suivant, les items prêts basculent sur `signflow://`. **Le player streaming actuel ne casse jamais.**

## 4. Décisions de conception à trancher (avec reco)

1. **Mécanisme de service local des octets au renderer** →
   **Reco : `protocol.handle('signflow', …)` (Electron ≥ 25) renvoyant un `fs.ReadStream`** (ou `registerFileProtocol` en repli). Gère le **Range** nativement (indispensable au seek vidéo de la sync), pas de port réseau (vs serveur localhost), pas de galère `file://`+CORS. *Alternative écartée : serveur HTTP localhost (un port de plus, sécurité) ; `file://` (Range/seek capricieux sous Chromium).*
2. **Nommage du store** →
   **Reco : content-addressed (`<checksum_sha256>.<ext>`)** + `index.json` (mapping id_media/variant_key → checksum). Dédup automatique (même octet partagé entre playlists), immutable, intégrité triviale, une rendition ré-encodée = nouveau checksum = nouveau fichier (l'ancien s'évince). *Alternative écartée : nommage par id_media (re-DL silencieux si le contenu change sous le même id).*
3. **Set épinglé (jamais évincé)** →
   **Reco P0 : tout le manifeste courant est épinglé** (simple). **P1+ : le serveur calcule un `pinned:[…]`** (programme courant + look-ahead schedules/events) envoyé dans le payload → le cache manager protège ce set et évince le reste LRU. *Le noyau scheduling fournit déjà le « qui+quand » pour le look-ahead.*
4. **Changements serveur P0** →
   **Reco : minimal** — ajouter **`file_size_bytes`** par item au payload (planning disque + token-bucket Q3). Le reste du payload est déjà suffisant (url + checksum). Pas de migration. (Le `pinned`, les alertes disque, l'inventaire viennent en P1/P4.)
5. **Cible matérielle & ordre** →
   **Reco : Linux/RPi d'abord** (store fichier Node trivial, parc domicile NUC/RPi + bureau riri/fifi pour la sync), **puis Windows (AOpen)** (même code Node, valide le gain anti-seek), **puis Android** (MediaCodec + scoped storage, store via OkHttp + `FileProvider`/protocole WebView — chantier distinct), **ChromeOS = Cache API/Service Worker** (modèle différent, à la construction du PWA).

## 5. Plan de phasage

- **P0 — Store + download mono-player (Linux/RPi)** *(cœur, livrable autonome)*
  `ContentStore` + `DownloadManager` (séquentiel, sans QoS) + protocole `signflow://` + `resolveSrc` avec **repli streaming** + **purge Q5 = vraie suppression fichier** + IPC `cache:status` minimal. **Critère** : couper le réseau après remplissage → le player continue ; mur NUC+RPi sans re-fetch aux frontières.
- **P1 — Cache manager / éviction (Q2)** : watermarks 85/70 %, LRU sur non-épinglé, `pinned` serveur, **alerte serveur « disque insuffisant pour la playlist assignée »** (pas de drop silencieux). Réutilise le canal d'alerte decode-health.
- **P2 — Barrière sync-readiness LAN (Q1)** : signalement `ready_for <empreinte>` sur le canal LAN (UDP `sync_lan.js`/`LanSyncController`), le maître ne lance `switch_at`/wall-clock que quand tous les membres attendus sont prêts ; **garde d'index** (n'avance N+1 que si tous l'ont) ; **timeout/dégradé** (slave éteint ne gèle pas le mur → alerte « désynchronisé »). Validation parc bureau (riri/fifi) + domicile.
- **P3 — QoS / fenêtres download (Q3)** : fenêtres = `TimeRule` du noyau scheduling, plafond bande passante (token-bucket), N concurrents, look-ahead programmes à venir, downloads résumables (HTTP range), bypass urgence. Préserve la ligne client aux heures d'ouverture.
- **P4 — Inventaire UI (Q4)** : le player remonte `{cache:[{id,checksum,size,last_used,status}], disk_free}` dans le heartbeat (même objet capabilities) → UI par player (disque, prêt/partiel/manquant) + vue inverse par playlist/campagne (preuve de distribution).
- **Portage** : Windows (P0 rejoué), puis Android (store natif), puis ChromeOS (Service Worker).

## 6. Points durs / risques

- **Seek vidéo via `signflow://`** : valider que le Range fonctionne pour le `currentTime` de la sync LAN (sinon nudge/seek cassé). → tester tôt en P0.
- **Atomicité** : ne jamais servir un `.part`. Écriture `.part` → checksum → `rename`. Un crash en cours = re-DL.
- **Usure carte SD (RPi)** : le store sur SD use le flash. → privilégier SSD USB (déjà le cas RPi SSD chiffré LUKS) ou limiter la réécriture (content-addressed aide : pas de re-DL si checksum identique).
- **Disque AOpen 4 Go RAM / stockage limité** : watermarks + alerte indispensables (P1).
- **Empreinte LAN (Q1)** : liste de membres **autoritative** (devrait-être-là vs online) — réutiliser l'appartenance groupe serveur, pas l'auto-découverte UDP seule.
- **Transition de parc** : P0 doit coexister avec des players encore en streaming (déploiement progressif) → le serveur n'impose rien, le player bascule local **quand** il a l'octet.

## 7. Verdict

**GO.** L'épopée est bien cadrée, le payload porte déjà checksum + (bientôt) file_size, le pattern capabilities/scheduling/quarantaine est réutilisable. Le risque est **maîtrisé par le repli streaming** (P0 ne peut pas régresser). Démarrer par **P0 sur Linux/RPi**, valider le mur NUC+RPi (anti-seek), puis dérouler P1→P4 et le portage.
