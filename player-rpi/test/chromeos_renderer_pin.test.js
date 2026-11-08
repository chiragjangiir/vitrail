// Le loader ChromeOS ne doit plus retomber sur un renderer de juillet (2026-08-12).
//
// DÉFAUT MESURÉ : un ChromeOS a passé trois semaines en 2.0.8 pendant que le serveur épinglait
// 2.0.17, en repassant deux fois par un déploiement qui le remontait (colonne `previous_version`
// des déploiements 161 et 175 : « 2.0.7 »). Deux moitiés, toutes deux porteuses :
//
//   ① la sonde du loader était un HEAD, et `Cache.match` IGNORE les requêtes non-GET → hors ligne,
//      une version épinglée PRÉSENTE dans le cache du Service Worker était déclarée ABSENTE, et le
//      loader dégradait vers le chemin plat ;
//   ② le chemin plat sert sa copie précachée, qui n'était jamais rafraîchie depuis l'épinglage du
//      28/07 — donc du code de juillet, sans que rien ne le signale.
//
// Ce test charge le VRAI bloc de `index.html` (jamais un portage) et le fait tourner sur des
// doublures. Il vérifie le CONTRAT, pas la mise en forme : la sonde doit être servable par un
// cache, et une dégradation doit se DIRE.
const assert = require('node:assert')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const INDEX = path.join(__dirname, '..', '..', 'frontend', 'public', 'player-chromeos', 'index.html')

function loaderSource() {
  const html = fs.readFileSync(INDEX, 'utf8')
  const m = html.match(/<script>\s*\(function \(\)[\s\S]*?\}\)\(\);\s*<\/script>/)
  assert.ok(m, 'bloc loader introuvable dans index.html')
  return m[0].replace(/<\/?script>/g, '')
}

// Exécute le loader avec des doublures et rend ce qu'il a FAIT (sondes émises, scripts injectés,
// stockage local final). `online` décide si les fetch aboutissent.
function run({ online, stored, pinFromServer }) {
  const store = new Map([
    ['signflow_backend_url', 'http://srv'],
    ['signflow_player_token', 'eyJhbGciOi.jwt.sig'],
  ])
  if (stored) store.set('signflow_renderer_version', stored)

  const probes = []          // { url, method }
  const scripts = []         // src injectés
  const timers = []

  const localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  }
  const fetchStub = (url, opts) => {
    probes.push({ url: String(url), method: (opts && opts.method) || 'GET' })
    if (!online) return Promise.reject(new Error('offline'))
    if (String(url).includes('/updates/renderer-version')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ version: pinFromServer }) })
    }
    // Le snapshot statique existe (cas nominal en ligne).
    return Promise.resolve({ ok: String(url).startsWith('v/') })
  }
  const document = {
    head: { appendChild: (s) => scripts.push(s.src) },
    createElement: () => ({ set src(v) { this._src = v }, get src() { return this._src } }),
    getElementById: () => ({ value: '', classList: { add() {}, remove() {} }, addEventListener() {} }),
  }
  const win = { signflow: null }

  const fn = new Function(
    'window', 'document', 'localStorage', 'location', 'fetch', 'URLSearchParams',
    'setTimeout', 'clearTimeout',
    loaderSource(),
  )
  fn(win, document, localStorage, { search: '' }, fetchStub, URLSearchParams,
     (cb) => { timers.push(cb); return timers.length }, () => {})

  return { probes, scripts, store, timers }
}

const flush = () => new Promise((r) => setImmediate(r))

test('hors ligne, la sonde de la version épinglée est servable par un cache (GET, pas HEAD)', async () => {
  const r = run({ online: false, stored: '2.0.18' })
  r.timers.forEach((cb) => cb())          // le filet des 4 s : bascule en mode hors ligne
  await flush(); await flush(); await flush()

  const versionProbes = r.probes.filter((p) => p.url.includes('signflow.js'))
  assert.ok(versionProbes.length > 0, 'aucune sonde de version émise')
  for (const p of versionProbes) {
    assert.strictEqual(p.method, 'GET',
      `sonde en ${p.method} sur ${p.url} : Cache.match ignore les requêtes non-GET, donc hors ` +
      'ligne cette sonde ne peut PAS être servie par le cache et déclare absente une version présente')
  }
})

test('une dégradation vers le chemin plat se DIT (sinon elle est indiscernable d’un retard)', async () => {
  const r = run({ online: false, stored: '2.0.18' })
  r.timers.forEach((cb) => cb())
  await flush(); await flush(); await flush()

  assert.strictEqual(r.store.get('signflow_renderer_degraded'), '2.0.18',
    'le loader a chargé le chemin plat sans signaler la version qu’il n’a pas pu charger')
  // Témoin : on a bien chargé le chemin PLAT (sinon l’assertion ci-dessus serait sans objet).
  assert.ok(r.scripts.length > 0 && r.scripts.every((s) => !s.startsWith('v/')),
    `scripts chargés depuis ${r.scripts[0]} : le cas dégradé n’a pas été atteint`)
})

test('en ligne, on charge la version épinglée et le drapeau de dégradation est EFFACÉ', async () => {
  const r = run({ online: true, stored: '2.0.8', pinFromServer: '2.0.18' })
  await flush(); await flush(); await flush()

  assert.ok(r.scripts.length > 0 && r.scripts.every((s) => s.startsWith('v/2.0.18/')),
    `scripts chargés depuis ${r.scripts[0]} au lieu de v/2.0.18/`)
  assert.strictEqual(r.store.get('signflow_renderer_degraded'), undefined,
    'un drapeau qui ne se lève jamais est inutile ; un drapeau qui ne retombe jamais est pire')
  // Le pin résolu est mémorisé pour le prochain démarrage hors ligne.
  assert.strictEqual(r.store.get('signflow_renderer_version'), '2.0.18')
})

test('le Service Worker sait répondre à une sonde non-GET depuis son cache', () => {
  const sw = fs.readFileSync(
    path.join(__dirname, '..', '..', 'frontend', 'public', 'player-chromeos', 'sw.js'), 'utf8')
  assert.match(sw, /ignoreMethod:\s*true/,
    'sans ignoreMethod, Cache.match rend undefined pour tout ce qui n’est pas un GET')
  // Le cache du shell doit être VERSIONNÉ : c’est son renommage qui purge les copies périmées
  // (`activate` supprime tout cache hors allowlist). Un nom figé les garde indéfiniment.
  assert.match(sw, /SHELL_CACHE = 'signflow-shell-v[2-9]/,
    'le cache du shell n’a pas été renommé : les copies plates de juillet survivraient')
})
