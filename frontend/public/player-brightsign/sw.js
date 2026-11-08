// ── Service Worker SignFlow — BrightSign (roHtmlWidget Chromium) ─────────────
//
// Réutilise INTÉGRALEMENT la logique ChromeOS (app-shell + cache média
// download-then-play, support Range 206). Une seule source de vérité :
// on importe le SW ChromeOS, qui est agnostique du chemin (le service média
// `…/__sf_media__/<key>` est intercepté AVANT le contrôle de scope).
//
// Scope effectif = /player-brightsign/ (enregistré par signflow.js
// registerServiceWorker() → 'sw.js' relatif à la page brightsign).
// localMediaUrl() pose `/player-brightsign/__sf_media__/<key>` → same-origin,
// dans le scope → intercepté ici. allow_streaming reste le repli pendant que le
// cache se remplit (stream-then-cache, jamais d'écran noir).
//
// SW_REV: 2026-06-27b (serveMedia → réponse cachée verbatim). Bumper cette ligne à
// CHAQUE changement de la logique importée force le ré-install du SW sur les anciens
// Chromium (qui ne re-vérifient pas un importScripts identique octet-à-octet).
//
// ⚠️ VERIFY-ON-DEVICE : dépend du support Service Worker / Cache API du
// roHtmlWidget de la version de BrightSignOS. storage_path (autorun.brs) fournit
// le stockage persistant (SD). Si non supporté → registration échoue
// proprement → repli streaming (comportement inchangé).
importScripts('/player-chromeos/sw.js');
