// Snapshot du renderer ChromeOS dans un dossier VERSIONNÉ (§XXX #4 — épinglage).
//
// Le player charge la version de renderer à laquelle il est ÉPINGLÉ (résolue au boot via
// GET /updates/renderer-version), PAS « la dernière servie » — sinon une MAJ serveur mettrait le parc
// à jour au prochain reboot, involontairement. `index.html` (loader) charge donc les scripts depuis
// ./v/<version>/ au lieu du chemin plat.
//
// Ce script copie les 4 fichiers de renderer dans public/player-chromeos/v/<CHROMEOS_PLAYER_VERSION>/.
// La version = constante `CHROMEOS_PLAYER_VERSION` de signflow.js (source de vérité). Les snapshots
// s'ACCUMULENT (on garde les versions antérieures pour le rollback / les players encore épinglés
// dessus) ; l'élagage des très vieilles versions est une tâche du process de release (LOT 3).
//
// Le dossier vit SOUS le scope du Service Worker (/player-chromeos/) → il est mis en cache et le pin
// survit à un reboot hors-ligne. Lancé en pre-build/pre-dev (cf. package.json) et à chaque changement
// de renderer.
import { copyFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const CROS = join(here, '..', 'public', 'player-chromeos')
const FILES = ['ed25519.js', 'signflow.js', 'audio_player.js', 'player.js']

const js = readFileSync(join(CROS, 'signflow.js'), 'utf8')

// Une version par plateforme SERVIE : ChromeOS ET BrightSign chargent LE MÊME signflow.js (la version
// rapportée dépend de SF_OS au runtime), mais leurs constantes de version diffèrent
// (CHROMEOS_PLAYER_VERSION vs BS_PLAYER_VERSION). On snapshote donc un dossier v/<ver>/ POUR CHAQUE —
// mêmes fichiers, nom de dossier = la version que ce type de player rapporte et sur laquelle il s'épingle.
const versions = new Set()
for (const name of ['CHROMEOS_PLAYER_VERSION', 'BS_PLAYER_VERSION']) {
  const m = js.match(new RegExp(`const\\s+${name}\\s*=\\s*'([^']+)'`))
  if (m) versions.add(m[1])
  else console.warn(`snapshot-renderer: ${name} introuvable dans signflow.js (ignore)`)
}
if (versions.size === 0) {
  console.error('snapshot-renderer: aucune constante de version trouvee dans signflow.js')
  process.exit(1)
}
for (const version of versions) {
  const dest = join(CROS, 'v', version)
  // Une version publiée est IMMUABLE : si le dossier existe déjà (committé), on ne l'écrase PAS
  // — sinon chaque build/prebuild régénérerait v/<version courante>/ avec le signflow.js du moment
  // (contenu qui change sous un même numéro → viole l'épinglage, et salit l'arbre git en prod).
  // Pour livrer un changement de code, on BUMPE la version → un dossier neuf est créé ici.
  if (existsSync(dest)) {
    console.log(`snapshot-renderer: v/${version}/ existe déjà — conservé (immuable)`)
    continue
  }
  mkdirSync(dest, { recursive: true })
  for (const f of FILES) copyFileSync(join(CROS, f), join(dest, f))
  console.log(`snapshot-renderer: player-chromeos/v/${version}/ (${FILES.length} fichiers)`)
}
