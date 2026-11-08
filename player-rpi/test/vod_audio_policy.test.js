// Politique audio du takeover VOD (2026-07-19) — la VOD cede le passage aux overlays.
//
// Bug d'origine (Ed) : VOD sonore + message/alerte -> les deux sons se MELANGENT a plein
// volume, parce que les overlays passent par messageGain que le ducking ne touche pas.
// Regle : la VOD se tait tant qu'un overlay parle (jingle, SPOT DE CAMPAGNE, message,
// alerte) et reprend le son a la fin.
//
// Ce test rejoue la logique de _vodAudioPolicy contre un runtime audio simule, en couvrant
// les transitions (overlay qui DEMARRE pendant la VOD, et qui se TERMINE).
//
// Usage : node player-rpi/test/vod_audio_policy.test.js

let fail = 0;
function check(label, cond, detail) {
  console.log(`${cond ? 'OK  ' : 'ECHEC'} ${label}${cond ? '' : '  -> ' + JSON.stringify(detail)}`);
  if (!cond) fail++;
}

// ── Runtime simule : reproduit l'API reelle (getOverlayPriority + onOverlayChange) ──
function makeAudio() {
  return {
    _prio: 0,
    duckCalls: [],
    onOverlayChange: null,
    getOverlayPriority() { return this._prio; },
    duckForVisualOverlay(on) { this.duckCalls.push(on); },
    // Simule un debut/fin d'overlay comme le fait _playOverlay / restore().
    setOverlay(prio) { this._prio = prio; if (this.onOverlayChange) this.onOverlayChange(prio); },
  };
}

// ── Portage fidele de _vodAudioPolicy (meme logique que les 7 renderers) ────────
function makeVod(audio) {
  const st = { media: { muted: false }, wantsSound: false, hasAudio: true, ducked: false };
  const duck = (on) => { if (on !== st.ducked) { audio.duckForVisualOverlay(on); st.ducked = on; } };
  const policy = () => {
    const prio = audio.getOverlayPriority() || 0;
    const audible = st.wantsSound && prio === 0;
    st.media.muted = !audible;
    duck(audible && st.hasAudio);
  };
  audio.onOverlayChange = () => { if (st.media) policy(); };
  return { st, policy };
}

// ── 1. Aucun overlay : son + ducking (comportement nominal, deja valide par Ed) ──
{
  const a = makeAudio(); const v = makeVod(a);
  v.st.wantsSound = true; v.policy();
  check('musique seule : VOD sonore', v.st.media.muted === false, v.st.media);
  check('musique seule : ducking actif', v.st.ducked === true, a.duckCalls);
}

// ── 2. Son decoche : muette et AUCUN ducking (on ne baisse pas pour du silence) ──
{
  const a = makeAudio(); const v = makeVod(a);
  v.st.wantsSound = false; v.policy();
  check('son decoche : VOD muette', v.st.media.muted === true, v.st.media);
  check('son decoche : pas de ducking', v.st.ducked === false, a.duckCalls);
}

// ── 3. Media sans piste audio : pas de ducking (musique baissee pour rien) ──────
{
  const a = makeAudio(); const v = makeVod(a);
  v.st.wantsSound = true; v.st.hasAudio = false; v.policy();
  check('media muet : pas de ducking', v.st.ducked === false, a.duckCalls);
}

// ── 4. Overlay DEJA en cours au lancement de la VOD ─────────────────────────────
for (const [prio, nom] of [[1, 'jingle / spot de campagne'], [2, 'message'], [3, 'alerte']]) {
  const a = makeAudio(); a._prio = prio; const v = makeVod(a);
  v.st.wantsSound = true; v.policy();
  check(`${nom} deja en cours : VOD muette`, v.st.media.muted === true, v.st.media);
  check(`${nom} deja en cours : pas de ducking`, v.st.ducked === false, a.duckCalls);
}

// ── 5. Overlay qui DEMARRE pendant une VOD sonore -> elle se tait ───────────────
{
  const a = makeAudio(); const v = makeVod(a);
  v.st.wantsSound = true; v.policy();
  check('avant message : VOD sonore', v.st.media.muted === false, v.st.media);
  a.setOverlay(2);   // un message part
  check('message pendant VOD : VOD muette', v.st.media.muted === true, v.st.media);
  check('message pendant VOD : musique remontee', v.st.ducked === false, a.duckCalls);
}

// ── 6. Fin de l'overlay -> la VOD reprend le son (le coeur de la regle d'Ed) ────
{
  const a = makeAudio(); a._prio = 2; const v = makeVod(a);
  v.st.wantsSound = true; v.policy();
  check('pendant le message : muette', v.st.media.muted === true, v.st.media);
  a.setOverlay(0);   // fin du message
  check('apres le message : le son revient', v.st.media.muted === false, v.st.media);
  check('apres le message : ducking retabli', v.st.ducked === true, a.duckCalls);
}

// ── 7. Fin d'overlay alors que le son n'avait PAS ete demande -> reste muette ───
{
  const a = makeAudio(); a._prio = 2; const v = makeVod(a);
  v.st.wantsSound = false; v.policy();
  a.setOverlay(0);
  check('son decoche : reste muette apres l overlay', v.st.media.muted === true, v.st.media);
  check('son decoche : jamais de ducking', a.duckCalls.filter(Boolean).length === 0, a.duckCalls);
}

process.exit(fail ? 1 : 0);
