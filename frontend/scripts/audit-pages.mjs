/**
 * Audit visuel REJOUABLE de toutes les pages du CMS.
 *
 * Écrit après le défaut de `/settings/updates` trouvé par Ed sur une capture (2026-08-10) : la
 * liste des versions tombait à 74 px pendant que le panneau du parc gardait 350 px de vide. Ce
 * genre de défaut ne se voit ni dans le code ni dans un test fonctionnel — il se MESURE sur la
 * page rendue, à une hauteur d'écran donnée. Le faire à l'œil une fois ne protège de rien : ce
 * script existe pour être relancé.
 *
 * Ce qu'il cherche, et pourquoi chaque contrôle existe :
 *
 *  1. DEBORDEMENT_H       — la fenêtre défile horizontalement (règle : jamais).
 *  2. COUPE               — du contenu dépasse un conteneur en `overflow:hidden` qui ne défile
 *                           PAS ⇒ inatteignable, sans barre pour le dire. Mode de panne vécu sur
 *                           `/events` (20/07) : la page ne débordait pas, elle COUPAIT.
 *  3. LISTE_ECRASEE       — conteneur de défilement de moins de 120 px alors qu'il cache du
 *                           contenu ⇒ le défaut de `/settings/updates`.
 *  4. OBSTRUE             — un élément interactif dont le centre renvoie un AUTRE élément :
 *                           quelque chose passe par-dessus. Vécu 3 fois (bulle d'aide sur le pied
 *                           des tiroirs, cloche du portail, bas du panneau de filtres du parc).
 *  5. CLE_I18N            — un libellé rendu sous sa forme `namespace.cle` ⇒ traduction absente
 *                           du bon namespace. Vécu sur `/media` (28/07) et l'IAM (31/07).
 *  6. HORS_ECRAN          — élément interactif dont le centre tombe sous le bas de la fenêtre
 *                           alors que la page est verrouillée ⇒ cliquable nulle part.
 *
 * Usage :
 *   SF_TOKEN=<jwt org-admin>  node scripts/audit-pages.mjs [--base URL] [--shots DIR] [--page /x]
 *
 * Le jeton se forge côté serveur (aucun mot de passe saisi) — cf. RUNBOOK. Sans `--shots`, aucune
 * image n'est écrite : la sortie texte suffit à décider.
 */
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'

const arg = (n, d) => {
  const i = process.argv.indexOf(n)
  return i > -1 ? process.argv[i + 1] : d
}
const BASE = arg('--base', process.env.SF_BASE ?? 'http://localhost:8080')
const TOKEN = process.env.SF_TOKEN
const SHOTS = arg('--shots', null)
const ONLY = arg('--page', null)
// Deux hauteurs : la nominale FHD, et la hauteur RÉELLE d'un navigateur plein écran sur un écran
// FHD (barre de titre + onglets + barre d'adresse + favoris ≈ 130 px). C'est la seconde qui décrit
// ce que voit un utilisateur — la première seule laisserait passer les défauts d'Ed.
const TAILLES = [{ w: 1920, h: 1080 }, { w: 1920, h: 950 }]

if (!TOKEN) {
  console.error('SF_TOKEN manquant (jeton org-admin). Rien mesuré — je ne devine pas.')
  process.exit(2)
}
if (SHOTS) mkdirSync(SHOTS, { recursive: true })

const PAGES = [
  '/dashboard', '/media', '/media/tags', '/url-display', '/feeds', '/promo', '/templates',
  '/playlists', '/schedules', '/events', '/vod', '/audio-baskets', '/players', '/sites',
  '/governance', '/campaigns', '/campaigns/advertisers', '/approvals', '/reports',
  '/reports/executive', '/reports/noc', '/reports/geo', '/reports/content', '/reports/audience',
  '/reports/proof-of-play', '/settings/updates', '/settings/firmware', '/settings/iam',
  '/settings/notifications', '/settings/messaging', '/settings/ai-keys', '/settings/licence',
  '/settings/server', '/settings/players/provisioning', '/settings/profile', '/settings/security',
  '/studio', '/help',
]

const me = await (await fetch(`${BASE}/api/v1/users/me`, {
  headers: { Authorization: `Bearer ${TOKEN}` },
})).json()
if (!me?.id_user) {
  console.error('Le jeton ne resout aucun utilisateur — sonde invalide, rien mesure.')
  process.exit(2)
}

const navigateur = await chromium.launch({ channel: 'chrome' })
let total = 0
let temoinFait = false

/** Mesure exécutée DANS la page. Renvoie une liste de constats nommés. */
const SONDE = () => {
  const out = []
  const vis = (e) => {
    const r = e.getBoundingClientRect()
    if (r.width < 2 || r.height < 2) return false
    const s = getComputedStyle(e)
    return s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0.05
  }
  const nom = (e) => {
    const t = (e.innerText || e.getAttribute('aria-label') || e.getAttribute('placeholder') || '')
      .trim().replace(/\s+/g, ' ').slice(0, 40)
    return `${e.tagName.toLowerCase()}${e.className && typeof e.className === 'string'
      ? '.' + e.className.split(/\s+/).filter(Boolean).slice(0, 3).join('.') : ''}${t ? ` « ${t} »` : ''}`
  }
  // 🔑 Un élément hors de la fenêtre n'est PAS forcément perdu : s'il vit dans un conteneur qui
  // défile, il suffit de faire défiler. Sans cette distinction la sonde criait 991 fois sur des
  // lignes de tableau parfaitement atteignables — un bruit qui aurait noyé les vrais constats.
  // ⚠️ Un élément défilé HORS de son conteneur garde un rectangle : son centre tombe alors sur ce
  // qui est dessous, et `elementFromPoint` accuse un recouvrement qui n'existe pas. Deuxième faux
  // positif de la même famille que les tiroirs fermés — on ne juge que ce qui est réellement
  // dans le cadre de tous ses conteneurs.
  const rogne = (e, x, y) => {
    for (let p = e.parentElement; p; p = p.parentElement) {
      const s = getComputedStyle(p)
      if (s.overflow === 'visible' && s.overflowX === 'visible' && s.overflowY === 'visible') continue
      const r = p.getBoundingClientRect()
      if (x < r.left || x > r.right || y < r.top || y > r.bottom) return true
    }
    return false
  }
  const atteignable = (e) => {
    for (let p = e.parentElement; p; p = p.parentElement) {
      const s = getComputedStyle(p)
      if (/auto|scroll/.test(s.overflowY) && p.scrollHeight > p.clientHeight + 2) return true
      if (/auto|scroll/.test(s.overflowX) && p.scrollWidth > p.clientWidth + 2) return true
    }
    const d0 = document.documentElement
    return d0.scrollHeight > d0.clientHeight + 2 || d0.scrollWidth > d0.clientWidth + 2
  }

  // 1. Débordement horizontal de la fenêtre.
  const d = document.documentElement
  if (d.scrollWidth > d.clientWidth + 1) {
    out.push({ type: 'DEBORDEMENT_H', detail: `${d.scrollWidth} px de contenu pour ${d.clientWidth} px` })
  }

  // Coupures VOULUES, à ne pas confondre avec une coupure subie :
  //  · troncature typographique (`text-overflow: ellipsis`, `line-clamp`) — le « … » le dit ;
  //  · `.sf-scroll-host` — le libellé défile au survol, il DOIT dépasser ;
  //  · une carte Leaflet — ses tuiles dépassent son cadre par construction ;
  //  · un fond décoratif (aucun texte, aucun élément interactif) — il n'y a rien à atteindre.
  const coupureVoulue = (e) => {
    const s = getComputedStyle(e)
    if (s.textOverflow === 'ellipsis' || s.webkitLineClamp !== 'none') return true
    if (e.closest('.sf-scroll-host, .leaflet-container, .sf-fleet-map')) return true
    const utile = (e.innerText || '').trim().length > 0 ||
      e.querySelector('button, a[href], input, select, textarea, [role="button"]')
    return !utile
  }

  const tous = [...document.querySelectorAll('body *')].filter(vis)

  for (const e of tous) {
    const s = getComputedStyle(e)
    const cacheV = e.scrollHeight > e.clientHeight + 2
    const cacheH = e.scrollWidth > e.clientWidth + 2
    const defileV = /auto|scroll/.test(s.overflowY)
    const defileH = /auto|scroll/.test(s.overflowX)
    if ((cacheV || cacheH) && coupureVoulue(e)) continue

    // 2. Contenu coupé sans possibilité de le rejoindre.
    if (cacheV && s.overflowY === 'hidden' && e.clientHeight > 40) {
      out.push({
        type: 'COUPE',
        detail: `${nom(e)} : ${e.scrollHeight} px de contenu dans ${e.clientHeight} px, overflow-y:hidden`,
      })
    }
    if (cacheH && s.overflowX === 'hidden' && e.clientWidth > 80 && e.scrollWidth > e.clientWidth + 24) {
      out.push({
        type: 'COUPE',
        detail: `${nom(e)} : ${e.scrollWidth} px de large dans ${e.clientWidth} px, overflow-x:hidden`,
      })
    }
    // 3. Conteneur de défilement écrasé.
    if (cacheV && defileV && e.clientHeight < 120) {
      out.push({
        type: 'LISTE_ECRASEE',
        detail: `${nom(e)} : ${e.clientHeight} px visibles pour ${e.scrollHeight} px de contenu`,
      })
    }
    if (cacheH && defileH && e.clientWidth < 120) {
      out.push({
        type: 'LISTE_ECRASEE',
        detail: `${nom(e)} : ${e.clientWidth} px de large pour ${e.scrollWidth} px de contenu`,
      })
    }
  }

  // 4 + 6. Éléments interactifs obstrués ou hors écran.
  const inter = [...document.querySelectorAll('button, a[href], input, select, textarea, [role="button"]')]
    .filter(vis)
  const deja = new Set()
  for (const e of inter) {
    const r = e.getBoundingClientRect()
    const x = Math.round(r.left + r.width / 2)
    const y = Math.round(r.top + r.height / 2)
    // ⚠️ Un élément à DROITE de la fenêtre est presque toujours un tiroir fermé (`translate-x-full`
    // le range hors champ sans le démonter) : 280 faux positifs à la première passe. Seul le
    // dépassement VERTICAL décrit un vrai « on ne peut pas y arriver ».
    if (x > innerWidth - 1 || x < 0) continue
    if (y > innerHeight - 1 || y < 0) {
      if (!atteignable(e)) {
        out.push({ type: 'HORS_ECRAN', detail: `${nom(e)} centre en y=${y}, fenetre ${innerWidth}x${innerHeight}` })
      }
      continue
    }
    if (rogne(e, x, y)) continue
    const top = document.elementFromPoint(x, y)
    if (!top || top === e || e.contains(top) || top.contains(e)) continue
    // On nomme l'obstacle une seule fois : un recouvrement en cache toujours plusieurs.
    const cle = nom(top)
    if (deja.has(cle)) continue
    deja.add(cle)
    out.push({ type: 'OBSTRUE', detail: `${nom(e)} recouvert par ${cle}` })
  }

  // 5. Clés i18n rendues brutes.
  const marcheur = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  const brutes = new Set()
  for (let n = marcheur.nextNode(); n; n = marcheur.nextNode()) {
    const t = (n.nodeValue || '').trim()
    // `a.b` en minuscules, sans espace ni accent : la forme exacte d'une clé non résolue.
    if (/^[a-z][a-z0-9_]*(\.[a-z0-9_]+){1,3}$/.test(t) && t.length > 5 && !/\.(js|css|png|webp|json|md|com|net|org|io)$/.test(t)) {
      brutes.add(t)
    }
  }
  for (const b of brutes) out.push({ type: 'CLE_I18N', detail: b })

  return out
}

for (const { w, h } of TAILLES) {
  const ctx = await navigateur.newContext({ viewport: { width: w, height: h }, locale: 'fr-FR' })
  await ctx.addInitScript(([tk, u]) => {
    localStorage.setItem('sf_access_token', tk)
    localStorage.setItem('sf_refresh_token', tk)
    localStorage.setItem('sf-auth', JSON.stringify({
      state: { user: u, accessToken: tk, refreshToken: tk, roles: u.roles ?? [] }, version: 0,
    }))
  }, [TOKEN, me])
  const page = await ctx.newPage()
  console.log(`\n═══ Fenetre ${w} x ${h} ═══`)

  for (const route of (ONLY ? [ONLY] : PAGES)) {
    let constats
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 45000 })
      // Garde : une session expirée renverrait la page de LOGIN et tout serait « propre ».
      await page.waitForTimeout(2500)
      if (new URL(page.url()).pathname.startsWith('/login')) {
        console.log(`  ${route.padEnd(34)} SONDE INVALIDE — renvoye sur /login`)
        total += 1
        continue
      }
      constats = await page.evaluate(SONDE)
    } catch (e) {
      console.log(`  ${route.padEnd(34)} ERREUR — ${String(e).split('\n')[0].slice(0, 90)}`)
      total += 1
      continue
    }
    if (SHOTS) {
      await page.screenshot({ path: `${SHOTS}/${route.replace(/\//g, '_') || '_root'}_${h}.png` })
    }
    // 🔑 TÉMOIN. Un audit qui rend « 0 constat » est indiscernable d'un audit aveugle : filtres
    // trop larges, page pas chargée, sélecteur qui ne matche plus. On injecte donc, sur la
    // première page propre, un défaut FABRIQUÉ (un cache opaque sur un bouton) et on exige que la
    // sonde le voie. Si elle ne le voit pas, le « 0 » du reste ne vaut rien et on le DIT.
    if (constats.length === 0 && !temoinFait) {
      temoinFait = true
      const vu = await page.evaluate(() => {
        const cible = [...document.querySelectorAll('button, a[href]')].find((e) => {
          const r = e.getBoundingClientRect()
          return r.width > 20 && r.height > 12 && r.top > 60 && r.bottom < innerHeight - 10
        })
        if (!cible) return 'aucune cible'
        const r = cible.getBoundingClientRect()
        const cache = document.createElement('div')
        cache.id = '__temoin__'
        Object.assign(cache.style, {
          position: 'fixed', left: `${r.left}px`, top: `${r.top}px`,
          width: `${r.width}px`, height: `${r.height}px`, background: '#f00', zIndex: '99999',
        })
        document.body.appendChild(cache)
        const x = Math.round(r.left + r.width / 2), y = Math.round(r.top + r.height / 2)
        const top = document.elementFromPoint(x, y)
        cache.remove()
        return top && top.id === '__temoin__' ? 'vu' : 'NON VU'
      })
      console.log(`  ${'(temoin : defaut fabrique)'.padEnd(34)} ${vu === 'vu'
        ? 'vu — la sonde n\'est pas aveugle' : `⚠️  ${vu} — le « 0 » du reste NE PROUVE RIEN`}`)
      if (vu !== 'vu') total += 1
    }
    if (constats.length === 0) {
      console.log(`  ${route.padEnd(34)} ok`)
      continue
    }
    total += constats.length
    console.log(`  ${route.padEnd(34)} ${constats.length} constat(s)`)
    for (const c of constats) console.log(`      ${c.type.padEnd(14)} ${c.detail}`)
  }
  await ctx.close()
}

await navigateur.close()
console.log(`\nTotal : ${total} constat(s).`)
process.exit(total > 0 ? 1 : 0)
