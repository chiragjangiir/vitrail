# SPIKE — Décodage HW Intel/Linux via mpv, activable par player

🇬🇧 [English version](SPIKE_mpv_hwdecode_linux.md)

> Statut : **DESIGN** (2026-06-09). Fait suite à la note « Décodage HW Intel/Linux via mpv »
> et au verdict : **VA-API inaccessible dans Electron stock sur
> Intel/Linux** (frame pool non allouable, NE PAS re-tenter les flags — cf. `vaapi_profiles.js`),
> alors que **mpv décode le 4K H.264 en HW VAAPI** sur le même hardware. Déclencheur : remontée
> client possible (vidéo lourde sur parc Intel). But : offrir le décodage HW **en option activable
> par player**, sans casser la chaîne Chromium existante.

## 1. Contrainte de départ

| Player | Décodage vidéo | Voie HW |
|--------|----------------|---------|
| RPi 4/5 | HW | V4L2 (cage, déjà câblé) |
| Windows | HW | D3D11 (par défaut) |
| **Intel/Linux (NUC, riri, fifi)** | **SW (~FHD30)** | **VAAPI — mais SEULEMENT hors Electron → mpv** |

mpv (`--hwdec=vaapi --vo=gpu`) joue le 4K H.264 fluide sur ce HW (`intel_gpu_top` : moteur Video ~70 %).
Le player-linux tourne sous **X11 + openbox + lightdm** (≠ RPi sous cage/Wayland). C'est important :
le z-order de deux fenêtres X11 se pilote (openbox/wmctrl/`_NET_WM_STATE_ABOVE`).

## 2. Surface d'intégration actuelle (ce que mpv doit reprendre)

Tout est aujourd'hui attaché à l'élément `<video>` du renderer (`player-linux/src/renderer/player.js`) :

| Fonction | Couplage `<video>` actuel | Équivalent mpv |
|----------|---------------------------|----------------|
| Lecture vidéo | `createElement('video')`, `src`, `autoplay` | `loadfile <path|url>` via IPC |
| Source offline-first | `signflow://<cache_key>` (protocole Electron) | **chemin disque** `contentStore.fileFor(key).path` OU URL MinIO http (mpv lit les deux) |
| LAN sync — report | `_activeVideo.currentTime` | propriété mpv `time-pos` (IPC `get_property`) |
| LAN sync — nudge | `_activeVideo.playbackRate = 1.05/0.95` | propriété mpv `speed` |
| LAN sync — resync dur | `_activeVideo.currentTime = …` | commande mpv `seek <t> absolute` |
| Fin d'item | `video.onended` → `scheduleAdvance` | événement mpv `end-file` |
| Mute contenu | `video.muted` | propriété mpv `mute` |
| Sortie audio (Windows) | `setSinkId` | mpv `--audio-device` |
| Sous-titres §7 | `<track>` WebVTT injectés | mpv `sub-add <url>` (WebVTT supporté) |
| Overlay maintenance | lit `_activeVideo.currentTime/duration` | `time-pos` / `duration` mpv |
| Précache #2a | double-buffer `<video>` caché | **non mappable** sur 1 instance mpv (cf. limites v1) |
| Résolution jouée (overlay) | `videoWidth×videoHeight` | propriétés mpv `dwidth/dheight` |

Images, PDF, pages web, templates, barre de statut, **overlay** = restent rendus par **Chromium**.
mpv ne reprend QUE la vidéo.

## 3. Architecture retenue — **Option A** (mpv fenêtre sœur + IPC)

Rappel des pistes de la note EVOLUTIONS :
- **(A) mpv fenêtre X11 plein écran pilotée par Electron en IPC** ← **RETENUE**
- (B) mpv `--vo=gpu` hors-écran → dma-buf réinjecté dans Chromium (propre mais interop GL/EGL lourde, hors budget)
- (C) player vidéo pur non-Electron (perd templates/images/web — trop limitant pour le parc actuel)

**Pourquoi A** : préserve 100 % de la chaîne Chromium (templates, images, web, sous-titres des
autres types, overlay) ; mpv n'intercepte que les items vidéo ; le coût est le **z-order** entre
2 fenêtres (le seul vrai risque, isolé en Phase 0).

### 3.1 Schéma de fonctionnement

```
┌─ openbox (X11) ───────────────────────────────────────────┐
│  Fenêtre Electron (kiosk, fullscreen)   ── UI, images,     │
│     ▲ z-order piloté                       web, templates, │
│     │                                      overlay, status │
│  Fenêtre mpv (fullscreen, --no-border)  ── VIDÉO HW VAAPI  │
│     ▲ remontée AU-DESSUS pendant un item vidéo,            │
│       redescendue pour image/web/template/overlay          │
└────────────────────────────────────────────────────────────┘
        main.js  ──spawn + JSON IPC (socket UNIX)──► mpv --idle
```

- Item **vidéo** → main: `loadfile`, puis remonte mpv au-dessus (`wmctrl`/`_NET_WM_STATE_ABOVE` ou
  `mpv --ontop` + Electron `setAlwaysOnTop(false)`).
- Item **non-vidéo** → main: redescend mpv (Electron repasse au-dessus), Chromium rend l'item.
- **Overlay** demandé → redescendre mpv le temps de l'affichage (limite v1, cf. §6).

### 3.2 Le toggle (activable par player)

- Clé `display_config.video_renderer` : `'auto' | 'chromium' | 'mpv'`. **Défaut `auto` = chromium**
  (comportement actuel inchangé). `mpv` = route la vidéo vers mpv.
- **Garde de capacité** : l'UI n'offre l'option `mpv` que si le player a remonté
  `capabilities.mpv_vaapi = true` (détecté à l'install : binaire mpv présent + `vainfo` liste un
  profil H.264/HEVC decode). Sinon option grisée + tooltip « mpv/VAAPI indisponible ».
- **Gating plateforme** : proposé **uniquement** sur `player_os = linux-x64` (Intel). RPi (V4L2) et
  Windows (D3D11) gardent Chromium — pas de toggle.
- Cohérent avec `gpu_enabled` (commit `1d82f6f`) : même mécanique display_config + garde plateforme front.

## 4. Découpage renderer — abstraction `VideoSurface`

Pour ne pas dupliquer toute la logique de lecture/sync, on introduit une abstraction côté renderer :

```
VideoSurface (interface)
 ├─ HtmlVideoSurface   → wrappe l'actuel <video> (comportement par défaut, zéro régression)
 └─ MpvSurface         → proxy IPC vers mpv (via window.signflow.mpv.* exposé par preload)

API : load(src, {seekMs, subtitles, muted}), play(), pause(), get currentTime(),
      get duration(), set playbackRate(r), seek(ms), get videoSize(),
      on('ready'|'ended'|'error', cb), release()
```

`reportPlaybackPos`, le nudge LAN, `onLanSwitch`, l'overlay et `_getContentFP` parlent à
`VideoSurface` au lieu de `_activeVideo` directement. **`_activeVideo` devient
`_activeSurface`** ; `HtmlVideoSurface` garde exactement le code actuel (refactor mécanique, testable
sans mpv). Le choix d'implémentation se fait à `playCurrentItem` selon `video_renderer` + type d'item.

> Bénéfice transverse : cette abstraction rendrait aussi le portage futur (autre moteur) trivial,
> et clarifie le renderer (aujourd'hui `_activeVideo` est touché en ~15 endroits).

## 5. Points faciles (mpv > Electron)

- **offline-first** : mpv lit le **chemin disque** du cache directement (`fileFor().path`) → pas de
  `signflow://`, pas de souci de Range. Repli URL MinIO http si non caché. **Plus simple** qu'Electron.
- **Sous-titres** : `sub-add` WebVTT natif mpv.
- **Audio dual** : vidéo dans mpv, **paniers audio restent dans Electron (Web Audio)** → les deux se
  mixent au niveau PipeWire/Pulse. Le routage sortie = `--audio-device` mpv.
- **Décodage** : `--hwdec=vaapi --vo=gpu --gpu-context=x11egl` (à figer en Phase 0).

## 6. Limites assumées v1 (à documenter dans la matrice)

1. **UI Electron non composée sur la vidéo mpv** (fenêtres séparées) : overlay maintenance,
   barre de statut, écran de repli. Parades : l'overlay **redescend mpv** le temps de l'affichage ;
   l'indicateur **« Reconnecting » est doublé via l'OSD natif mpv** (`show-text`, visible par-dessus
   la vidéo) — ✅ implémenté. Reste : un écran de repli "no content" en mpv mode passerait derrière
   (rare, le contenu mpv couvre).
2. **Transitions / précache #2a** : 1 instance mpv → pas de double-buffer vidéo→vidéo ; petit gap au
   changement d'item (loadfile). Option future : 2e instance mpv préchargée.
3. **Templates avec vidéo intégrée** (vidéo DANS un template HTML) : restent en Chromium (mpv ne gère
   que la vidéo plein écran). Le toggle ne s'applique qu'aux items vidéo plein écran.
4. **Intel/Linux x64 uniquement.**

## 7. Plan par phases

| Phase | Contenu | Où valider |
|-------|---------|-----------|
| **0 — PoC (jetable)** ✅ **PASSÉE 2026-06-09 (riri, UHD600 Gemini Lake)** | Lever les 3 inconnues AVANT toute intégration. **(a) décode** ✅ mpv joue H.264 1080p en VAAPI (`Using hardware decoding (vaapi)`, dmabuf EGL ; HEVC+VP9 aussi dispo). **(c) IPC** ✅ 6/6 via `mpv-poc-ipc.mjs` : loadfile/hwdec-current=vaapi/dwidth+dheight+codec/time-pos/`speed` (nudge LAN)/`seek` (resync LAN). **(b) z-order** ✅ avec **raise explicite `wmctrl -a <titre>`** sur la fenêtre cible à chaque bascule. **Scripts** : `player-linux/scripts/mpv-poc.sh <video>` + `mpv-poc-ipc.mjs` + `mpv-poc-zorder.sh` (confirmation lente étiquetée). Prérequis : `sudo apt install -y mpv socat wmctrl`. Lancer en session graphique avec `DISPLAY=:0` (depuis SSH OK, pas besoin de XAUTHORITY pour le user qui possède la session). | **riri/fifi** (scripts jetables) |
| **1 — Détection + toggle** | `install.sh` : `apt install mpv` + détection `vainfo` decode → `capabilities.mpv_vaapi`. Backend remonte la capa. Front : option `video_renderer=mpv` (garde capa + os) + i18n. | local + riri |
| **2 — Rendu mpv (sans LAN)** ✅ **FAIT + VALIDÉ HW (riri, 2026-06-09)** | `mpv_controller.js` (process mpv `--idle` + IPC JSON + raise/lower wmctrl + cleanup orphelin) ; main.js wiring (ipcMain + résolution `signflow://`→disque + lifecycle) ; preload bridge ; renderer = branche mpv dans `renderItem` (mode `video_renderer=mpv`), `mpvHide()` pour les items non-vidéo. **Approche pragmatique** : pas de classe `VideoSurface` formelle — branche mpv vs `<video>` dans `renderItem` (l'avance reste timer-driven → mpv = simple surface d'affichage, régression nulle sur le chemin Chromium). **Validé** : vidéo routée vers mpv, `hwdec-current=vaapi`, moteur GPU Video (VCS) ~28%, cache offline résolu, plein écran fluide au-dessus du kiosk, mpv CPU ~5%. Commit `4fb68e1`. | **riri** ✅ |
| **3 — LAN sync** ✅ **CODÉ (commit `f6f5196`)**, ⏳ valider HW | Re-câblé via abstraction renderer (`videoActive`/`videoOffsetMs`/`setVideoRate`/`seekVideoMs` → `<video>` ou mpv) : poll `time-pos` ~250ms extrapolé, nudge `speed`, resync `seek`. `onLanSwitch` #2b déjà agnostique. **À valider** : mur riri+fifi en mpv + LAN, drift via `[LAN] Rate nudge`. | riri/fifi (mur) |
| **4 — Finitions** ✅ **CODÉ (commit `f6f5196`)**, ⏳ valider HW | Overlay redescend mpv puis re-remonte ; résolution jouée + position = dims/time-pos mpv ; **repli `<video>` Chromium si mpv KO** (`renderVideoChromium`). Transitions fade non appliquées à mpv (cut, limite assumée). | parc |

> Règle projet respectée : **le chemin Chromium par défaut reste intact** (régression nulle tant
> que `video_renderer != mpv`). RPi/Windows non touchés.

## 8. Risques & parades

| Risque | Parade |
|--------|--------|
| **Z-order kiosk** | ✅ **RÉSOLU en Phase 0** : le player-linux n'est PAS always-on-top (`fullscreen:true` simple sous Openbox) → pas de bataille. Mécanisme retenu = **raise explicite `wmctrl -a <titre-fenêtre>`** sur la cible à chaque bascule (mpv reçoit un `--title` unique). ⚠️ **NE PAS se fier à la propriété mpv `ontop`** (`_NET_WM_STATE_ABOVE`) : elle ne restacke pas une fenêtre déjà mappée une fois le kiosk repassé devant. Dépendance runtime : `wmctrl` (à installer via install.sh). |
| mpv absent / VAAPI KO sur un player | garde de capacité (option non offerte) + repli runtime sur `<video>` si spawn mpv échoue |
| Drift LAN moins fin via IPC (latence socket) | `time-pos` mpv est précis ; IPC UNIX socket <1ms ; garder la même dead-zone/nudge |
| 2e chemin de rendu à maintenir | abstraction `VideoSurface` isole le coût ; chromium reste la référence |

## 9. Verdict

**✅ CHANTIER VALIDÉ SUR HW (riri+fifi, UHD600, 2026-06-09).** Phases 0→4 livrées et validées :
décodage HW VAAPI (VCS ~28%), sync LAN via mpv (drift ~50ms = skew NTP, comme Chromium),
**reboot serveur DOWN → boot-cache offline en mpv HW + sync LAN sans serveur + audio OK**, mode mpv
remonte `hw_decode_active=true` (badge « Matériel » + lève le plafond rendition → **4K sur écran 4K**),
repli Chromium si mpv KO, overlay + « Reconnecting » via OSD mpv. Activable par player
(`display_config.video_renderer=mpv`, gardé `mpv_vaapi`+linux-x64). Commits `ec3232c`→`e44469d`.
**Reste optionnel** : transitions fade sur mpv (cut pour l'instant), doc matrice « best practices »,
validation 4K réelle (écran 4K requis ; riri/fifi = écrans 1080).

### (historique) Phase 0
**GO sur Option A — Phase 0 ✅ PASSÉE SUR HW (riri, UHD600, 2026-06-09).** Les 3 inconnues sont
levées : décode VAAPI réel, IPC complet (dont nudge `speed` + resync `seek`), z-order fiable via
`wmctrl -a`. Le reste est du câblage encadré par l'abstraction `VideoSurface`. **Prochaine étape =
Phase 1** (détection mpv/VAAPI à l'install → `capabilities.mpv_vaapi` + dépendances `mpv socat wmctrl`
dans install.sh ; toggle front `video_renderer` gardé capa+os).

**Dépendances runtime confirmées** (Debian 12) : `mpv` (0.35.1 stock OK), `socat` (IPC depuis bash),
`wmctrl` (raise z-order). À ajouter dans `install.sh`.

**Décision produit à confirmer** : accepte-t-on les limites v1 (overlay/transitions, §6) en échange du
décodage HW, ou faut-il viser l'option B (dma-buf, sans limites mais gros interop GL) ? Recommandation :
**A avec limites documentées** — l'overlay est ponctuel et les transitions vidéo→vidéo rares en signage.
