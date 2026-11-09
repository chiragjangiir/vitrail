# Vitrail Player — Android

🇬🇧 [English version](README.md)

Application **native Kotlin** (pas Electron) pour Android 9+ (`minSdk 28`) — box Android TV,
écrans tactiles, téléphones. Package `app.vitrail.player`.

## Installation

- **Terrain (recommandé)** : `docs/RUNBOOK_POSE_PLAYER.md` — canal `signflow-provision` ADB
  (`--os android --ip <ip>`, APK poussé + provisionné en une commande).
- **Boîtiers Android TV / Google TV** : kiosque = passer
  **launcher** (sur Google TV `set-home-activity` ne suffit pas : désactiver les paquets HOME),
  `appops … REQUEST_INSTALL_PACKAGES allow` pour l'OTA, `adb tcpip 5555` avant tout.
  ⚠️ **Google TV sans Device Owner ≠ Android TV** : certains OS (Google TV grand public,
  ColorOS) refusent le Device Owner — critère n°1 du choix matériel.
- **Manuelle locale** : `./install.sh [--release] [--ip <ip>]` (build gradle + `adb install`
  + set-home-activity).

## Récupérer un boîtier (retirer le mode kiosque)

Une fois l'appli **Device Owner**, Android refuse de la désinstaller
(`DELETE_FAILED_DEVICE_POLICY_MANAGER`). Libérez d'abord le mode kiosque, puis désinstallez —
sans réinitialisation d'usine :

```bash
adb shell content call --uri content://app.vitrail.player.admin --method release_device_owner
#   Result: Bundle[{was_device_owner=true, released=true}]
adb uninstall app.vitrail.player
```

Seul **adb** (ou root) peut envoyer cette commande : toute appli installée sur le boîtier reçoit
une `SecurityException` (l'UID de l'appelant est vérifié). Disponible à partir du player 2.5.36
(release v1.0.4) ; une installation plus ancienne exige encore une réinitialisation d'usine.

## Décisions techniques à connaître

- **WebView + ExoPlayer** : la WebView (renderer partagé) rend tout le contenu non-vidéo ;
  une **TextureView ExoPlayer (media3)** sœur, au-dessus, décode en HW natif ce que la WebView
  ne tient pas (**HEVC, 4K@60**). L'écran idle est une **vue native** posée au-dessus des deux
  (la WebView de certaines box Amlogic ne compose pas en idle — les captures mentiraient).
- **Debug et release = deux apps distinctes** : le debug est suffixé `.debug`
  (`applicationIdSuffix`). Passer en release = installation à neuf (re-provisionner), puis
  `adb uninstall app.vitrail.player.debug`.
- **Signature release** : `keystore.properties` (gitignoré) qui pointe vers votre clé `.jks`.
  Sans lui, le build release sort **non signé** (non installable) — le build debug, lui, passe.
  **Pour un vrai parc, signez avec votre propre clé** (APK officiel = essais seulement) : la
  créer, la sauvegarder, compiler avec → [`docs/GUIDE.fr.md`, « Android : votre propre clé de signature »](../docs/GUIDE.fr.md#android--votre-propre-clé-de-signature).
  ⚠️ Perdre la clé = plus aucune mise à jour possible sans désinstaller chaque appareil
  (Android exige la même clé).
- **OTA par APK depuis le serveur** : le player télécharge le bundle
  (`player-bundles/android/<version>.apk`, **URL relative** résolue contre son `backend_url` —
  jamais d'URL MinIO pré-signée, elle expire) et installe via **`PackageInstaller`** :
  silencieux si l'app est **Device Owner**, sinon confirmation à l'écran.
- Le reste est à parité Electron : `ContentStore.kt` (offline-first), `LanSyncController` /
  `VodLanController` (UDP 7778/7779), `LocalControlServer` (nanohttpd — Store Control Panel
  LAN §19.3), `PopSigner` (Proof of Play Ed25519 — BouncyCastle bas-niveau, le JCE natif
  n'a Ed25519 qu'à partir d'API 33), `WatchdogWorker`, `BootReceiver` (relance au boot).

## Config

Pas de `config.json` : **`EncryptedSharedPreferences`** (`signflow_config`, AES-256, Android
Keystore). Clés : `backend_url`, `player_token` (`sfp_…` de provisioning, remplacé par un JWT
à l'enregistrement), `player_name`. Saisie via l'écran de setup au premier lancement, ou
injectée par `signflow-provision`.

## Logs / diagnostic

- `adb logcat -s SignFlow/Main` (+ tags `SignFlow/*` des autres contrôleurs).
- Version et état remontés au heartbeat CMS ; overlay de diagnostic on-device disponible.
