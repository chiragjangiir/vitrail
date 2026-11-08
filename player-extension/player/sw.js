'use strict';

// ── Service Worker Vitrail (ChromeOS PWA) — Phase B offline §3.9 ─────────────
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

const SHELL_CACHE = 'signflow-shell-v1';
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
      const cached = await cache.match(key, { ignoreSearch: true });
      return cached || new Response('offline', { status: 504 });
    }
  })());
});

// Sert un média depuis MEDIA_CACHE avec support Range (206). La page stocke la réponse
// complète sous le chemin `…/__sf_media__/<key>` ; on tranche ici selon l'en-tête Range.
async function serveMedia(req, url) {
  const cache = await caches.open(MEDIA_CACHE);
  const full = await cache.match(url.pathname);
  if (!full) {
    // Pas encore (ou plus) en cache : le download-then-play de la page n'a pas fini, ou le
    // média a été évincé. La page garde l'URL MinIO en repli tant que non caché → ce chemin
    // local ne devrait être demandé qu'après bascule. 504 = signal « réessaie le streaming ».
    return new Response('media not cached', { status: 504 });
  }
  const range = req.headers.get('range');
  if (!range) return full;

  const buf = await full.arrayBuffer();
  const size = buf.byteLength;
  const m = /bytes=(\d+)-(\d*)/.exec(range);
  let start = m ? parseInt(m[1], 10) : 0;
  let end = m && m[2] ? parseInt(m[2], 10) : size - 1;
  if (isNaN(start) || start >= size) {
    return new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${size}` } });
  }
  end = Math.min(end, size - 1);
  const chunk = buf.slice(start, end + 1);
  return new Response(chunk, {
    status: 206,
    headers: {
      'Content-Range':  `bytes ${start}-${end}/${size}`,
      'Accept-Ranges':  'bytes',
      'Content-Length': String(chunk.byteLength),
      'Content-Type':   full.headers.get('Content-Type') || 'application/octet-stream',
    },
  });
}
