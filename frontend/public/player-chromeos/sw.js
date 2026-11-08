'use strict';

// ── Service Worker SignFlow (ChromeOS PWA) — Phase B offline §3.9 ─────────────
//
// Deux rôles :
//  1. App shell : précache (index/js/css/manifest/icon) → démarrage HORS LIGNE.
//     Stratégie network-first (frais quand online, repli cache offline) pour que les
//     correctifs du player se propagent au prochain chargement online.
//  2. Médias : sert les octets mis en cache par la page (download-then-play, cf. bridge
//     signflow.js) sous un chemin synthétique same-origin `…/__sf_media__/<cache_key>`,
//     avec support des requêtes Range (206) pour le `<video>`. Stratégie cache-first
//     (un cache_key désigne un objet immuable). La PAGE télécharge (CORS MinIO) ; le SW
//     ne fait que servir — pas de fetch réseau média ici (l'URL locale n'a pas de source).

// ⚠️ Le nom est VERSIONNÉ, et c'est ce qui purge les copies périmées : `activate` supprime tout
// cache absent de {SHELL_CACHE, MEDIA_CACHE}. v1 → v2 le 2026-08-12, parce que les fichiers PLATS
// précachés y dormaient depuis fin juillet : depuis l'épinglage (28/07) le loader charge
// `v/<ver>/` et n'emprunte plus le chemin plat, donc ces entrées ne se rafraîchissaient JAMAIS.
// Un player qui retombait sur le plat exécutait ainsi un renderer de juillet (2.0.8), en silence.
// ⛔ MEDIA_CACHE n'est PAS renommé : il porte les médias téléchargés, le vider forcerait tout le
// parc à les retirer.
const SHELL_CACHE = 'signflow-shell-v2';
const MEDIA_CACHE = 'signflow-media-v1';   // DOIT rester aligné avec signflow.js
const MEDIA_MARK  = '/__sf_media__/';

const SHELL_ASSETS = [
  './', './index.html', './signflow.js', './player.js', './audio_player.js',
  './style.css', './manifest.webmanifest', './icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // addAll échoue en bloc si UN asset manque → on tolère les absences (best-effort).
    await Promise.all(SHELL_ASSETS.map((a) => cache.add(a).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names.filter((n) => n !== SHELL_CACHE && n !== MEDIA_CACHE).map((n) => caches.delete(n)),
    );
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  let url;
  try { url = new URL(req.url); } catch { return; }

  // Cross-origin (MinIO, etc.) ET WebSocket : non interceptés → réseau direct.
  if (url.origin !== self.location.origin) return;

  // Média mis en cache par la page.
  if (url.pathname.includes(MEDIA_MARK)) {
    event.respondWith(serveMedia(req, url));
    return;
  }

  // App API (/api/…) : jamais en cache (données live) → réseau direct.
  if (url.pathname.startsWith('/api/')) return;

  // Hors scope du SW → laisser passer.
  const scopePath = new URL(self.registration.scope).pathname;
  if (!url.pathname.startsWith(scopePath)) return;

  // App shell (navigation + assets) : network-first, repli cache (offline).
  event.respondWith((async () => {
    const cache = await caches.open(SHELL_CACHE);
    try {
      const net = await fetch(req);
      // Rafraîchit le cache shell des GET réussis (hors média déjà filtré).
      if (req.method === 'GET' && net && net.ok) {
        const key = req.mode === 'navigate' ? './index.html' : req;
        cache.put(key, net.clone()).catch(() => {});
      }
      return net;
    } catch {
      const key = req.mode === 'navigate' ? './index.html' : req;
      // 🔑 `ignoreMethod` : sans lui, `Cache.match` REFUSE toute requête non-GET et rend
      // `undefined` — même quand le fichier est en cache. La sonde HEAD du loader sur
      // `v/<ver>/signflow.js` recevait donc « offline 504 » hors ligne, concluait que la version
      // épinglée n'existait pas, et dégradait vers le chemin plat. Une version PRÉSENTE était
      // déclarée absente (mécanisme mesuré le 2026-08-12).
      const cached = await cache.match(key, { ignoreSearch: true, ignoreMethod: true });
      return cached || new Response('offline', { status: 504 });
    }
  })());
});

// Sert un média depuis MEDIA_CACHE. La page stocke la réponse MinIO complète sous le chemin
// `…/__sf_media__/<key>` ; on la renvoie TELLE QUELLE.
//
// ⚠️ FAIBLE RAM + COMPAT roHtmlWidget BrightSign : on renvoie la réponse cachée VERBATIM
// (statut 200, en-têtes MinIO d'origine, corps = ReadableStream du cache → zéro copie en RAM,
// le Cache API lit la SD au fur et à mesure que le <video> consomme). On IGNORE l'en-tête Range :
// le <video> reçoit un 200 complet (légal — le serveur a le droit d'ignorer Range) et lit en
// progressif ; la lecture signage est linéaire (pas de seek). C'est le motif SW-cache le plus
// compatible. Historique : `arrayBuffer()` par Range = OOM du widget (« reconnecting » + skip) ;
// un slicer 206 streaming (byte-correct) ne se RENDAIT PAS dans le <video> du roHtmlWidget
// (écran noir, item suivant) → on simplifie au maximum. cf. project-brightsign.
async function serveMedia(req, url) {
  const cache = await caches.open(MEDIA_CACHE);
  const full = await cache.match(url.pathname);
  if (!full) {
    // Pas encore (ou plus) en cache : le download-then-play de la page n'a pas fini, ou le
    // média a été évincé. La page garde l'URL MinIO en repli tant que non caché → ce chemin
    // local ne devrait être demandé qu'après bascule. 504 = signal « réessaie le streaming ».
    return new Response('media not cached', { status: 504 });
  }
  return full;
}
