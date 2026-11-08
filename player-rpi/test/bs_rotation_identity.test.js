// Rotation BrightSign : le widget n'est plus JAMAIS roté (2026-08-14).
//
// MESURÉ SUR MATÉRIEL (XT1144) : roter le roHtmlWidget casse la géométrie du plan vidéo HW
// sur une source portrait (le plan lit un tampon large de 2160 avec la foulée de sortie 3840
// → striage 52,2/255) ; et pré-roter le fichier EN PLUS du widget compose les deux rotations
// (il ne reste que 32 % de la largeur). La rotation est donc GRAVÉE par le serveur dans une
// rendition paysage pré-rotée, et bsApplyRotation ne sert plus qu'à PURGER le sidecar
// sf_rotation.txt d'un device configuré avant ce changement (1 reboot de migration).
//
// Ce test extrait et EXÉCUTE la vraie fonction de signflow.js (jamais un portage) :
//   A. un device encore roté (sidecar rot270) reçoit set_rotation IDENTITY — la purge ;
//   B. quel que soit screen_rotation (right/left/normal/inverted), le widget ne reçoit
//      JAMAIS rot90/rot180/rot270 — c'est ça qui empêche la double rotation ;
//   C. device déjà en identity → aucune commande (pas de reboot en boucle) ;
//   D. anti-spam : la purge n'est demandée qu'une fois tant que le device n'a pas rebooté.
// A/B : restaurer l'ancien mapping { left: 'rot90', right: 'rot270' } fait rougir B (et A
// pour 'right', qui recevrait rot270 au lieu d'identity).
const assert = require('node:assert')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')

const SIGNFLOW = path.join(
  __dirname, '..', '..', 'frontend', 'public', 'player-chromeos', 'signflow.js')

function extractFn() {
  const src = fs.readFileSync(SIGNFLOW, 'utf8')
  const m = src.match(/function bsApplyRotation\(rotation\) \{[\s\S]*?\n {2}\}/)
  assert.ok(m, 'bsApplyRotation introuvable dans signflow.js')
  return m[0]
}

// Instancie la vraie fonction avec des doublures ; l'état `_bsRotationReq` persiste entre
// les appels d'une même instance (comme la closure du fichier réel).
function makeHarness({ deviceRotation }) {
  const cmds = []
  const factory = new Function(
    'IS_BS', '_bsDevice', 'bsCmd', 'console',
    `let _bsRotationReq = null;\n${extractFn()}\nreturn bsApplyRotation;`,
  )
  const dev = { rotation: deviceRotation }
  const fn = factory(true, dev, (cmd, params) => cmds.push({ cmd, params }), { log() {} })
  return { fn, cmds, dev }
}

test('A. device encore roté (sidecar rot270) → purge : set_rotation identity', () => {
  const { fn, cmds } = makeHarness({ deviceRotation: 'rot270' })
  fn('right')
  assert.strictEqual(cmds.length, 1)
  assert.strictEqual(cmds[0].cmd, 'set_rotation')
  assert.strictEqual(cmds[0].params.transform, 'identity')
})

test('B. le widget ne reçoit JAMAIS une rotation, quel que soit screen_rotation', () => {
  for (const rot of ['right', 'left', 'normal', 'inverted', undefined]) {
    // Device en identity : rien à faire. Device roté : purge identity. Dans les DEUX cas,
    // aucune commande rot90/rot180/rot270 ne doit partir — sinon la rendition pré-rotée
    // serait re-rotée par le widget (les 32 % mesurés).
    for (const devRot of ['identity', 'rot90', 'rot270']) {
      const { fn, cmds } = makeHarness({ deviceRotation: devRot })
      fn(rot)
      for (const c of cmds) {
        assert.strictEqual(c.params.transform, 'identity',
          `screen_rotation=${rot} device=${devRot} → le widget a reçu ${c.params.transform}`)
      }
    }
  }
})

test('C. device déjà en identity → aucune commande (pas de reboot)', () => {
  const { fn, cmds } = makeHarness({ deviceRotation: 'identity' })
  fn('right')
  fn('left')
  fn('normal')
  assert.strictEqual(cmds.length, 0)
})

test('D. anti-spam : une seule purge tant que le device n\'a pas rebooté', () => {
  const { fn, cmds } = makeHarness({ deviceRotation: 'rot90' })
  fn('left')
  fn('left')
  fn('right')
  assert.strictEqual(cmds.length, 1)   // les syncs suivants ne redemandent pas le reboot
})

test('E. /device.json pas encore lu (rotation absente) → on attend, aucune commande', () => {
  const { fn, cmds } = makeHarness({ deviceRotation: undefined })
  fn('right')
  assert.strictEqual(cmds.length, 0)
})
