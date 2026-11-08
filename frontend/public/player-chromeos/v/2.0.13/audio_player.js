'use strict';

/**
 * audio_player.js — Runtime audio in-store avec ducking (§XIX.5).
 *
 * Reçoit la liste des paniers audio (audio_baskets) depuis player:sync et joue
 * un programme audio résultant du mix des paniers selon leurs ratios.
 *
 * Le PLAYER décide de la rotation (autonome, offline-safe) :
 *   - Paniers music/ambiance : musique de fond continue (rotation pondérée)
 *   - Paniers message/jingle/emergency : insérés selon le mix_ratio
 *       → 1 message tous les N items de musique, N = round(100 / mix_ratio_message)
 *   - Ducking : quand un message démarre, la musique est baissée via un GainNode
 *       (target_pct, fade_in_ms, fade_out_ms du ducking_config), remontée à la fin.
 *       emergency = ducking total (mute musique).
 *
 * Web Audio API : 2 chaînes GainNode (musique + message) vers la destination.
 */

class AudioRuntime {
  constructor() {
    this.ctx          = null;
    this.musicGain    = null;
    this.ambianceGain = null;   // gain de la couche ambiance (parallèle à la musique)
    this.messageGain  = null;
    this.musicEl      = null;   // <audio> musique courante
    this.ambianceEl   = null;   // <audio> ambiance courante (couche simultanée)
    this.messageEl    = null;   // <audio> message courant
    this.baskets      = [];
    this.musicBaskets = [];     // paniers music avec items (pondérés par mix_ratio, famille music)
    this.ambianceBaskets = [];  // paniers ambiance avec items (couche parallèle, famille ambiance)
    this.messageQueue = [];     // jingles 'tracks' insérés à la cadence (trigger_value morceaux)
    this._musicCount  = 0;      // compteur d'items musique joués (pour cadence messages)
    this._running     = false;
    this._volume      = 1.0;    // volume global 0..1 (maître)
    this._musicVol    = 1.0;    // trim de la famille music   0..1 (par-dessus le maître)
    this._ambVol      = 1.0;    // trim de la famille ambiance 0..1 (par-dessus le maître)
    this._duckFactor  = 1.0;    // facteur de ducking courant 0..1 (overlays) appliqué au fond
    this._nowPlaying  = null;   // { type, name } du média music/overlay en cours (Store Control Panel §19.3)
    this._nowPlayingAmbiance = null; // { type, name } de la couche ambiance en cours
    this._known       = new Map(); // id_basket -> panier (sticky, pour le Store Control Panel)
    this._emergencyPlaying = false; // annonce urgente en cours (toggle)
    this._triggeredId = null;       // id_basket du déclencheur en cours (emergency loop)
    this._overlayPriority = 0;      // priorité de l'overlay en cours (0=aucun,1=jingle,2=message,3=emergency)
    // Notifié à CHAQUE changement d'overlay (début/fin). Le takeover VOD s'y abonne : son son
    // doit se taire tant qu'un overlay parle, car les overlays passent par messageGain — le
    // ducking (qui n'agit que sur music/ambiance) ne peut PAS les baisser. Sans ce hook, VOD
    // et message/alerte se MELANGENT a plein volume (constate par Ed le 2026-07-19).
    this.onOverlayChange = null;
    this.minuteJingles = [];        // jingles en mode 'minutes' (déclenchés sur l'horloge)
    this._jingleClock = null;       // setTimeout du ticker minute pour les jingles 'minutes'
    this._basketOutput = 'auto';    // sortie audio des paniers : auto|hdmi|jack|usb
    this._appliedOutput = null;     // sortie réellement appliquée (évite de reconfigurer à chaque sync)
    this._fallback     = null;      // piste de secours (§17.5) : { id_media, media_name, url }
    this._fallbackEl   = null;      // <audio> boucle de secours en cours
    this._overlayPop   = null;      // PoP §XXIV : overlay en cours { id_media, started }
    this._musicPop     = null;      // PoP §XXIV : piste musique en cours { id_media, started }
    this._ambiancePop  = null;      // PoP §XXIV : piste ambiance en cours { id_media, started }
  }

  // ── Proof of Play audio (§XXIV) ─────────────────────────────────────────────
  // Chaque lecture réelle (musique, ambiance, message/jingle/emergency) remonte une
  // preuve {id_media, durée réellement jouée} par le MÊME pipeline signé que le visuel
  // (bridge window.signflow.reportPlay → file offline + signature device + /pop/batch).
  // id_playlist = null : la preuve est rattachée au média seul (panier audio §XIX).
  // La durée est mesurée du démarrage RÉEL ('playing') à la fin (ended/arrêt/préemption)
  // → un overlay coupé ou une emergency en boucle remontent leur durée réelle.
  // La boucle de secours §17.5 n'émet PAS de preuve (loop sans fin, contenu de repli).
  _reportPop(idMedia, startedMs) {
    try {
      if (idMedia == null || !startedMs) return;
      if (!window.signflow || typeof window.signflow.reportPlay !== 'function') return;
      window.signflow.reportPlay({
        id_media: idMedia,
        id_playlist: null,
        duration_ms: Math.max(0, Math.round(Date.now() - startedMs)),
        played_at: new Date(startedMs).toISOString(),
      });
    } catch (e) { /* best-effort */ }
  }

  /** Flush idempotent d'un slot de lecture ('_overlayPop'|'_musicPop'|'_ambiancePop') :
   *  émet la preuve si armée puis désarme — appelable à la fin naturelle ET aux arrêts. */
  _flushPop(slot) {
    const p = this[slot];
    this[slot] = null;
    if (p) this._reportPop(p.id_media, p.started);
  }

  _ensureContext() {
    if (this.ctx) return;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    this.ctx = new Ctx();
    this.musicGain    = this.ctx.createGain();
    this.ambianceGain = this.ctx.createGain();
    this.messageGain  = this.ctx.createGain();
    this.musicGain.connect(this.ctx.destination);
    this.ambianceGain.connect(this.ctx.destination);
    this.messageGain.connect(this.ctx.destination);
    // Les gains portent TOUT le volume (maître × famille × ducking) — fiable, car
    // element.volume est ignoré par Chromium une fois l'élément routé dans le graphe
    // Web Audio (createMediaElementSource). Initialisés depuis l'état courant.
    this._applyGains();
  }

  /** Piste de secours (§17.5) jouée en boucle quand aucun panier musical n'a de
   *  contenu. Appelée avant setBaskets à chaque sync. */
  setFallback(audio) {
    this._fallback = (audio && audio.url) ? audio : null;
  }

  /** Applique une nouvelle configuration de paniers (depuis player:sync). */
  setBaskets(baskets) {
    this.baskets = baskets || [];
    // Mémorise tous les paniers vus (sticky) → le Store Control Panel peut les
    // ré-activer même après qu'un panier soit passé inactif côté serveur.
    for (const b of this.baskets) this._known.set(b.id_basket, b);
    this._recompute();
  }

  /** Recalcule les pools music/jingle + (re)démarre ou arrête le runtime. */
  _recompute() {
    // Deux familles de fond, jouées EN PARALLÈLE sur 2 pistes distinctes :
    //   - music    : piste musicEl/musicGain
    //   - ambiance : piste ambianceEl/ambianceGain (couche simultanée, ex. chants d'oiseaux)
    // Au sein d'une famille, la sélection pondère PAR PANIER selon mix_ratio (% de
    // diffusion), puis un item par son poids. Les 2 budgets sont séparés (≤100 chacun,
    // déjà appliqué côté serveur).
    this.musicBaskets = this.baskets.filter(
      (b) => b.basket_type === 'music' && (b.items || []).length > 0,
    );
    this.ambianceBaskets = this.baskets.filter(
      (b) => b.basket_type === 'ambiance' && (b.items || []).length > 0,
    );

    // Cadence "tous les N morceaux" : UNIQUEMENT les jingles en mode 'tracks'.
    // Les messages sont déclenchés à la demande (boutons), jamais insérés en auto.
    // L'emergency n'est jamais en rotation (déclenché à la demande).
    this.messageQueue = this.baskets.filter(
      (b) => b.basket_type === 'jingle' && (b.trigger_mode || 'tracks') === 'tracks'
        && (b.items || []).length > 0
    );

    // Jingles en mode 'minutes' : déclenchés sur l'horloge (calage type wall-clock).
    this.minuteJingles = this.baskets.filter(
      (b) => b.basket_type === 'jingle' && b.trigger_mode === 'minutes'
        && (b.items || []).length > 0,
    );
    this._startJingleClock();

    const hasFallback = !!this._fallback;
    // Rien à jouer du tout (aucun panier ET aucune piste de secours) → arrêt complet.
    if (this.baskets.length === 0 && !hasFallback) {
      this.stop();
      return;
    }
    // De la musique redevient disponible → couper la boucle de secours et reprendre.
    if (this.musicBaskets.length > 0 && this._fallbackEl) {
      this._stopFallbackLoop();
      if (this._running) this._playNextMusic();
    }
    if (!this._running) {
      this.start();
    } else {
      if (this.musicBaskets.length === 0 && hasFallback && !this._fallbackEl && !this.musicEl) {
        // Déjà actif mais plus de musique → démarrer la boucle de secours.
        this._playFallbackOrSilence();
      }
      // Piste ambiance (couche parallèle, indépendante de la musique) : démarrer si des
      // paniers ambiance sont apparus, arrêter s'ils ont tous disparu.
      if (this.ambianceBaskets.length > 0 && !this.ambianceEl) {
        this._playNextAmbiance();
      } else if (this.ambianceBaskets.length === 0 && this.ambianceEl) {
        this._stopAmbiance();
      }
    }
  }

  /**
   * Ticker calé sur les frontières de minute (comme le wall-clock vidéo).
   * À chaque minute, un jingle 'minutes' est dû si (minutes_depuis_minuit % N == 0)
   * → "toutes les 15 min" tombe à :00/:15/:30/:45, "toutes les heures" à :00.
   * Collision : le jingle le plus RARE (plus grand intervalle) gagne ; pas d'empilement.
   */
  _startJingleClock() {
    this._stopJingleClock();
    if (!this.minuteJingles || this.minuteJingles.length === 0) return;
    const tick = () => {
      const now = new Date();
      const mins = now.getHours() * 60 + now.getMinutes();
      const due = this.minuteJingles.filter((b) => mins % Math.max(1, b.trigger_value || 60) === 0);
      if (due.length && this._running && !this._emergencyPlaying && !this.messageEl) {
        due.sort((a, b) => (b.trigger_value || 0) - (a.trigger_value || 0)); // le plus rare gagne
        this._playMessage(due[0], () => {});
      }
      const n = new Date();
      this._jingleClock = setTimeout(tick, (60 - n.getSeconds()) * 1000 - n.getMilliseconds() + 50);
    };
    const n = new Date();
    this._jingleClock = setTimeout(tick, (60 - n.getSeconds()) * 1000 - n.getMilliseconds() + 50);
  }

  _stopJingleClock() {
    if (this._jingleClock) { clearTimeout(this._jingleClock); this._jingleClock = null; }
  }

  // ── Store Control Panel LAN (§19.3) ────────────────────────────────────────

  /** Active/désactive un panier en local (override runtime jusqu'au prochain sync). */
  setActiveBasket(idBasket, on) {
    if (on) {
      const b = this._known.get(idBasket);
      if (b && !this.baskets.some((x) => x.id_basket === idBasket)) this.baskets.push(b);
    } else {
      this.baskets = this.baskets.filter((x) => x.id_basket !== idBasket);
    }
    this._recompute();
  }

  /** Modifie le ratio de mix d'un panier en local. */
  setBasketRatio(idBasket, ratio) {
    const b = this.baskets.find((x) => x.id_basket === idBasket) || this._known.get(idBasket);
    if (b) b.mix_ratio = ratio;
    this._recompute();
  }

  /** Liste des paniers connus + état actif courant (pour /control/baskets). */
  getControlBaskets() {
    return [...this._known.values()].map((b) => ({
      id_basket:   b.id_basket,
      basket_name: b.basket_name,
      basket_type: b.basket_type,
      mix_ratio:   b.mix_ratio ?? 0,
      min_ratio:   b.min_ratio ?? 0,
      max_ratio:   b.max_ratio ?? 100,
      active:      this.baskets.some((x) => x.id_basket === b.id_basket),
    }));
  }

  /** True s'il existe un panier emergency jouable (compat ancien bouton générique). */
  hasEmergencyBasket() {
    return this.baskets.some(
      (b) => b.basket_type === 'emergency' && (b.items || []).length > 0,
    );
  }

  /** Priorité de préemption par type : emergency > message > jingle > (music/ambiance). */
  _typePriority(type) {
    return type === 'emergency' ? 3 : type === 'message' ? 2 : type === 'jingle' ? 1 : 0;
  }

  /** True si un overlay de ce type peut jouer maintenant (préempte une priorité inférieure). */
  _canPlayOverlay(type) {
    if (!this.messageEl) return true;
    return this._typePriority(type) > this._overlayPriority;
  }

  /** Paniers déclencheurs nommés (emergency/message) jouables → boutons du téléphone. */
  getControlTriggers() {
    return this.baskets
      .filter((b) => ['emergency', 'message'].includes(b.basket_type) && (b.items || []).length > 0)
      .map((b) => ({ id_basket: b.id_basket, basket_name: b.basket_name, basket_type: b.basket_type }));
  }

  /**
   * Déclenche un panier nommé (bouton du téléphone).
   *  - emergency : boucle jusqu'au 2e appui (toggle), musique coupée.
   *  - message   : un seul passage, musique baissée puis reprise.
   */
  triggerBasket(idBasket) {
    const basket = this.baskets.find(
      (b) => b.id_basket === idBasket && (b.items || []).length > 0,
    );
    if (!basket) return false;
    const isEmergency = basket.basket_type === 'emergency';

    // Re-appui sur l'emergency en cours → arrêt (toggle)
    if (isEmergency && this._triggeredId === idBasket) { this.stopTrigger(); return false; }

    // Préemption : emergency interrompt tout (y compris une autre emergency → changement
    // d'alerte). Sinon on n'interrompt qu'un overlay de priorité strictement inférieure.
    if (this.messageEl) {
      if (isEmergency || this._typePriority(basket.basket_type) > this._overlayPriority) this.stopTrigger();
      else return false;
    }

    if (!this._running) this.start();
    this._ensureContext();
    if (this.ctx.state === 'suspended') this.ctx.resume();

    if (isEmergency) {
      this._emergencyPlaying = true;
      this._triggeredId = idBasket;
      this._playMessage(basket, () => { this._emergencyPlaying = false; this._triggeredId = null; });
      if (this.messageEl) this.messageEl.loop = true;   // boucle jusqu'au stop
    } else {
      this._playMessage(basket, () => {});              // message : un passage
    }
    return true;
  }

  /** Arrête le déclencheur (emergency) en cours et remonte la musique. */
  stopTrigger() {
    this._flushPop('_overlayPop');   // PoP : annonce interrompue (durée réelle, boucle emergency incluse)
    if (this.messageEl) {
      try { this.messageEl.onended = null; this.messageEl.onerror = null; this.messageEl.loop = false; this.messageEl.pause(); } catch {}
      this.messageEl = null;
    }
    this._duckBackground(1.0, 300);
    this._nowPlaying = this._musicName ? { type: 'music', name: this._musicName } : null;
    this._emergencyPlaying = false;
    this._triggeredId = null;
    this._overlayPriority = 0;
    this._notifyOverlay();
  }

  // Compat ancien bouton générique (déclenche/arrête le premier emergency)
  stopEmergency() { this.stopTrigger(); }
  triggerEmergency() {
    const b = this.baskets.find((x) => x.basket_type === 'emergency' && (x.items || []).length > 0);
    return b ? this.triggerBasket(b.id_basket) : false;
  }
  toggleEmergency() {
    if (this._emergencyPlaying) { this.stopTrigger(); return false; }
    return this.triggerEmergency();
  }

  /** État audio courant (pour /control/status). */
  getStatus() {
    return {
      running:           this._running,
      volume:            Math.round(this._volume * 100),
      music_volume:      Math.round(this._musicVol * 100),
      ambiance_volume:   Math.round(this._ambVol * 100),
      // True seulement si les DEUX familles sont actives → la SPA montre alors les
      // 2 curseurs de volume par famille (sinon le volume général suffit).
      families_present:  (this.musicBaskets || []).length > 0 && (this.ambianceBaskets || []).length > 0,
      now_playing:       this._nowPlaying,
      now_playing_ambiance: this._nowPlayingAmbiance,
      has_emergency:     this.hasEmergencyBasket(),
      emergency_playing: this._emergencyPlaying,
      triggers:          this.getControlTriggers(),
      triggered_id:      this._triggeredId,
      basket_output:     this._basketOutput,
      baskets:           this.getControlBaskets(),
    };
  }

  start() {
    if (this._running) return;
    if ((this.musicBaskets || []).length === 0 && (this.ambianceBaskets || []).length === 0
        && this.messageQueue.length === 0 && !this._fallback) return;
    this._ensureContext();
    if (this.ctx.state === 'suspended') this.ctx.resume();
    this._running = true;
    this._playNextMusic();
    this._playNextAmbiance();   // couche ambiance en parallèle (no-op si aucun panier ambiance)
  }

  /** Mémorise la sortie choisie (pour l'affichage du statut). Le ROUTAGE réel se fait
   *  au niveau OS (PipeWire/wpctl, côté main.js) car setSinkId Chromium ne route pas
   *  fiablement sur RPi. */
  setBasketOutput(role) {
    this._basketOutput = role || 'auto';
  }

  /** Redémarre le runtime (stop + recompute) → les nouveaux flux partent sur le sink
   *  par défaut courant (après un changement de sortie OS). */
  restart() {
    this.stop();
    this._recompute();
  }

  /** Tirage d'un panier pondéré par mix_ratio (le % de diffusion). */
  _pickWeightedBasket(baskets) {
    const total = baskets.reduce((s, b) => s + Math.max(1, b.mix_ratio || 0), 0);
    let r = Math.random() * total;
    for (const b of baskets) { r -= Math.max(1, b.mix_ratio || 0); if (r <= 0) return b; }
    return baskets[baskets.length - 1];
  }

  stop() {
    // PoP : preuves des lectures en cours (durée réelle à l'arrêt) avant de tout couper.
    this._flushPop('_overlayPop'); this._flushPop('_musicPop'); this._flushPop('_ambiancePop');
    this._running = false;
    this._stopFallbackLoop();
    if (this.musicEl)   { try { this.musicEl.pause(); } catch {} this.musicEl = null; }
    this._stopAmbiance();
    if (this.messageEl) { try { this.messageEl.pause(); } catch {} this.messageEl = null; }
    this._stopJingleClock();
  }

  setVolume(pct) {
    this._volume = Math.max(0, Math.min(100, pct)) / 100;
    this._applyGains();
  }

  /** Volume d'une famille de fond (music|ambiance) — trim fin par-dessus le maître.
   *  amplitude finale = volume_maître × volume_famille × ducking. */
  setFamilyVolume(family, pct) {
    const v = Math.max(0, Math.min(100, pct)) / 100;
    if (family === 'music') this._musicVol = v;
    else if (family === 'ambiance') this._ambVol = v;
    else return;
    this._applyGains();
  }

  /** Applique les gains : fond (music/ambiance) = maître × famille × ducking ;
   *  overlay (message/jingle/emergency) = maître. ms>0 → rampe (utilisé par le ducking). */
  _applyGains(ms = 0) {
    if (!this.ctx) return;
    const now = this.ctx.currentTime;
    const set = (g, target) => {
      if (!g) return;
      g.gain.cancelScheduledValues(now);
      if (ms > 0) {
        g.gain.setValueAtTime(g.gain.value, now);
        g.gain.linearRampToValueAtTime(target, now + ms / 1000);
      } else {
        g.gain.setValueAtTime(target, now);
      }
    };
    set(this.musicGain,    this._volume * this._musicVol * this._duckFactor);
    set(this.ambianceGain, this._volume * this._ambVol   * this._duckFactor);
    set(this.messageGain,  this._volume);
  }

  _pickWeighted(items) {
    // items déjà dupliqués par poids → tirage uniforme
    return items[Math.floor(Math.random() * items.length)];
  }

  /** Choix du prochain item d'un panier : aléatoire pondéré si shuffle, sinon
   *  ordre séquentiel (sort_order) via un curseur persistant par panier. */
  _pickBasketItem(basket) {
    const items = basket.items || [];
    if (items.length === 0) return null;
    if (basket.shuffle) {
      const pool = items.flatMap((it) => Array(Math.max(1, it.weight || 1)).fill(it));
      return this._pickWeighted(pool);
    }
    if (!this._seqCursor) this._seqCursor = {};
    const key = basket.id_basket;
    const idx = (this._seqCursor[key] || 0) % items.length;
    this._seqCursor[key] = idx + 1;
    return items[idx];
  }

  /** Démarre (si pas déjà en cours) la boucle de secours §17.5. Occupe le slot
   *  musicEl → les jingles la duckent comme une musique normale. No-op sans piste. */
  _playFallbackOrSilence() {
    if (this._fallbackEl || !this._fallback || !this._fallback.url) return;
    const el = new Audio(this._fallback.url);
    el.crossOrigin = 'anonymous';
    el.loop = true;
    el.volume = 1;   // volume porté par le gain (element.volume ignoré après le graphe Web Audio)
    this._fallbackEl = el;
    this.musicEl = el;
    this._musicName = this._fallback.media_name || 'Fallback';
    this._nowPlaying = { type: 'fallback', name: this._musicName };
    this._musicSrc = null;   // le fallback occupe le slot music → on suit son node ici
    try {
      this._musicSrc = this.ctx.createMediaElementSource(el);
      this._musicSrc.connect(this.musicGain);
    } catch {}
    el.onerror = () => { this._stopFallbackLoop(); setTimeout(() => this._playNextMusic(), 3000); };
    el.play().catch(() => {});
  }

  /** Coupe la boucle de secours si active (libération complète + déconnexion du node). */
  _stopFallbackLoop() {
    if (!this._fallbackEl) return;
    try { this._fallbackEl.loop = false; } catch {}
    this._releaseAudioEl(this._fallbackEl, this._musicSrc);   // libère + déconnecte (anti-fuite)
    if (this.musicEl === this._fallbackEl) this.musicEl = null;
    this._fallbackEl = null;
    this._musicSrc = null;
  }

  _playNextMusic() {
    if (!this._running) return;
    if ((this.musicBaskets || []).length === 0) {
      // Aucun fond musical : piste de secours en boucle (§17.5) si configurée,
      // et on tente quand même les jingles périodiques par-dessus.
      this._playFallbackOrSilence();
      setTimeout(() => this._maybePlayMessage(() => {}), 1000);
      return;
    }
    // Du contenu musical existe → la boucle de secours n'a plus lieu d'être.
    this._stopFallbackLoop();
    // 1) panier pondéré par mix_ratio (% de diffusion), 2) item : aléatoire pondéré si
    //    shuffle, sinon ordre séquentiel (sort_order) avec curseur par panier.
    const basket = this._pickWeightedBasket(this.musicBaskets);
    const item = this._pickBasketItem(basket);
    if (!item || !item.url) { setTimeout(() => this._playNextMusic(), 1000); return; }

    this._musicName = item.media_name || 'Music';
    this._nowPlaying = { type: 'music', name: this._musicName };
    // CRUCIAL : libérer l'élément précédent (+ déconnecter son node source) AVANT d'en créer
    // un nouveau. Sinon, offline (pistes audio NON cachées → échec → retry), les <audio> +
    // MediaElementSourceNode s'accumulent jusqu'au plafond WebMediaPlayer (PARTAGÉ avec la
    // vidéo) → cascade « too many WebMediaPlayers » → OOM. C'était la vraie cause du gel RPi.
    this._flushPop('_musicPop');   // PoP : piste précédente pas terminée naturellement (erreur en cours)
    this._releaseAudioEl(this.musicEl, this._musicSrc);
    const el = new Audio(item.url);
    el.crossOrigin = 'anonymous';
    el.volume = 1;   // volume porté par musicGain (maître × music × ducking)
    this.musicEl = el;
    this._musicSrc = null;
    try {
      this._musicSrc = this.ctx.createMediaElementSource(el);
      this._musicSrc.connect(this.musicGain);
    } catch {
      // déjà connecté (rare) → lecture directe
    }
    // PoP §XXIV : preuve armée au démarrage RÉEL ('playing'), émise à la fin (durée réelle).
    el.addEventListener('playing', () => {
      if (this.musicEl === el) this._musicPop = { id_media: item.id_media, started: Date.now() };
    }, { once: true });
    el.onended = () => {
      this._flushPop('_musicPop');
      this._musicCount++;
      this._maybePlayMessage(() => this._playNextMusic());
    };
    // Back-off 3s sur erreur : limite le churn quand tout échoue (offline) — la libération
    // ci-dessus borne déjà à 1 élément, le back-off réduit le rythme de re-création.
    el.onerror = () => { setTimeout(() => this._playNextMusic(), 3000); };
    el.play().catch(() => { setTimeout(() => this._playNextMusic(), 3000); });
  }

  /** Libère un <audio> (handlers, src, requête réseau) + déconnecte son node Web Audio →
   *  empêche l'accumulation de WebMediaPlayers sur les retries (offline). */
  _releaseAudioEl(el, srcNode) {
    try { if (srcNode) srcNode.disconnect(); } catch {}
    if (!el) return;
    try { el.onended = null; el.onerror = null; el.pause(); el.removeAttribute('src'); el.load(); } catch {}
  }

  /** Boucle de la couche AMBIANCE — parallèle à la musique, sur sa propre piste
   *  (ambianceEl/ambianceGain). Sélection pondérée ENTRE paniers ambiance (mix_ratio),
   *  puis item (shuffle ou séquentiel). N'incrémente PAS le compteur musique et NE
   *  déclenche PAS de jingle/message (cadence portée par la musique). Pas de fallback. */
  _playNextAmbiance() {
    if (!this._running) return;
    if ((this.ambianceBaskets || []).length === 0) { this._stopAmbiance(); return; }
    const basket = this._pickWeightedBasket(this.ambianceBaskets);
    const item = this._pickBasketItem(basket);
    if (!item || !item.url) { setTimeout(() => this._playNextAmbiance(), 1000); return; }

    this._ambianceName = item.media_name || 'Ambiance';
    this._nowPlayingAmbiance = { type: 'ambiance', name: this._ambianceName };
    // Libère l'ambiance précédente (+ node source) avant d'en créer une — même raison que
    // _playNextMusic (anti-accumulation WebMediaPlayer offline).
    this._flushPop('_ambiancePop');   // PoP : piste précédente pas terminée naturellement (erreur en cours)
    this._releaseAudioEl(this.ambianceEl, this._ambianceSrc);
    const el = new Audio(item.url);
    el.crossOrigin = 'anonymous';
    el.volume = 1;   // volume porté par ambianceGain (maître × ambiance × ducking)
    this.ambianceEl = el;
    this._ambianceSrc = null;
    try {
      this._ambianceSrc = this.ctx.createMediaElementSource(el);
      this._ambianceSrc.connect(this.ambianceGain);
    } catch {
      // déjà connecté (rare) → lecture directe
    }
    el.addEventListener('playing', () => {
      if (this.ambianceEl === el) this._ambiancePop = { id_media: item.id_media, started: Date.now() };
    }, { once: true });
    el.onended = () => { this._flushPop('_ambiancePop'); this._playNextAmbiance(); };
    el.onerror = () => { setTimeout(() => this._playNextAmbiance(), 3000); };
    el.play().catch(() => { setTimeout(() => this._playNextAmbiance(), 3000); });
  }

  /** Coupe la piste ambiance si active. */
  _stopAmbiance() {
    this._flushPop('_ambiancePop');   // PoP : ambiance coupée (durée réelle)
    if (this.ambianceEl) {
      try { this.ambianceEl.onended = null; this.ambianceEl.onerror = null; this.ambianceEl.pause(); } catch {}
      this.ambianceEl = null;
    }
    this._nowPlayingAmbiance = null;
  }

  /** Décide s'il faut insérer un message/jingle après l'item musique courant. */
  _maybePlayMessage(done) {
    if (!this._running || this.messageQueue.length === 0) { done(); return; }
    // Un overlay prioritaire (emergency/message) en cours → pas de cadence par-dessus
    if (this.messageEl) { done(); return; }

    // Jingles 'tracks' dus à ce compteur ; collision → le plus rare (plus grand N) gagne
    const due = this.messageQueue.filter((b) => this._musicCount % Math.max(1, b.trigger_value || 5) === 0);
    if (due.length) {
      due.sort((a, b) => (b.trigger_value || 0) - (a.trigger_value || 0));
      this._playMessage(due[0], done);
      return;
    }
    done();
  }

  _playMessage(basket, done) {
    const item = this._pickWeighted(
      (basket.items || []).flatMap((it) => {
        const w = Math.max(1, it.weight || 1);
        return Array(w).fill(it);
      })
    );
    if (!item || !item.url) { done(); return; }

    this._nowPlaying = { type: basket.basket_type, name: item.media_name || basket.basket_name };
    this._overlayPriority = this._typePriority(basket.basket_type);
    this._notifyOverlay();
    const duck = basket.ducking_config || {};
    const isEmergency = basket.basket_type === 'emergency';
    const targetPct = isEmergency ? 0 : (duck.target_pct ?? 20);
    const fadeInMs  = duck.fade_in_ms  ?? 500;
    const fadeOutMs = duck.fade_out_ms ?? 1500;

    const el = new Audio(item.url);
    el.crossOrigin = 'anonymous';
    el.volume = 1;   // volume porté par messageGain (= volume maître)
    this.messageEl = el;
    // PoP §XXIV : armé au démarrage réel, émis au restore/stopTrigger (durée réelle).
    this._flushPop('_overlayPop');   // filet : overlay précédent pas encore flushé
    el.addEventListener('playing', () => {
      if (this.messageEl === el) this._overlayPop = { id_media: item.id_media, started: Date.now() };
    }, { once: true });
    try {
      const src = this.ctx.createMediaElementSource(el);
      src.connect(this.messageGain);
    } catch {}

    // Ducking ON : baisse la musique
    if (duck.enabled || isEmergency) {
      this._duckBackground(targetPct / 100, fadeInMs);
    }

    const restore = () => {
      this._flushPop('_overlayPop');   // PoP : fin naturelle (ou erreur en cours de lecture)
      if (duck.enabled || isEmergency) this._duckBackground(1.0, fadeOutMs);
      this.messageEl = null;
      this._overlayPriority = 0;
      this._notifyOverlay();
      // Revenir à l'affichage du morceau musique en cours (ne pas rester figé sur le message)
      this._nowPlaying = this._musicName ? { type: 'music', name: this._musicName } : null;
      done();
    };
    el.onended = restore;
    el.onerror = restore;
    el.play().catch(restore);
  }

  /** Priorité de l'overlay en cours : 0=aucun, 1=jingle, 2=message, 3=alerte. */
  getOverlayPriority() { return this._overlayPriority || 0; }

  /** Prévient l'abonné (takeover VOD) que l'overlay courant a change. */
  _notifyOverlay() {
    try { if (this.onOverlayChange) this.onOverlayChange(this._overlayPriority || 0); } catch {}
  }

  /** Ducking pour un overlay VISUEL sonore (takeover VOD) : le son de la vidéo est porté
   *  par un <video> du renderer, PAS par ce runtime — il ne passe donc par aucun gain d'ici.
   *  Sans ce hook, la musique de fond et la vidéo se MÉLANGENT (constaté sur un player à la
   *  fois content et audio). Mêmes réglages que le ducking jingle (§XIX.5) pour un rendu
   *  homogène ; valeurs par défaut si aucun panier actif ne fournit de ducking_config. */
  duckForVisualOverlay(on, opts = {}) {
    const targetPct = opts.target_pct ?? 20;
    const fadeMs = on ? (opts.fade_in_ms ?? 500) : (opts.fade_out_ms ?? 800);
    this._duckBackground(on ? Math.max(0, Math.min(100, targetPct)) / 100 : 1.0, fadeMs);
  }

  /** Ducking : mémorise le facteur courant (0..1) et rampe les gains de FOND
   *  (music + ambiance) sur `ms` ms — recombiné avec le volume maître et de famille. */
  _duckBackground(factor, ms) {
    this._duckFactor = factor;
    this._applyGains(ms);
  }
}

// Singleton exposé pour player.js
window.signflowAudio = new AudioRuntime();
