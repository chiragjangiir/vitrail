'use strict';

/**
 * sync_lan.js — Synchronisation inter-players en reseau local (§III.3).
 *
 * Transport : UDP broadcast 255.255.255.255:7778
 * (plus simple et fiable que multicast sur Linux/Windows/RPi)
 *
 * Election du leader (par ordre de priorite) :
 *   1. Le player marque `lan_sync_master: true` dans display_config (leader DESIGNE).
 *      → choisir la machine la plus puissante comme reference de timing stable.
 *   2. Sinon, fallback : player avec le plus petit id_player.
 *   Un masterPriority est diffuse dans chaque message ; l'election compare
 *   d'abord la priorite (1 = designe > 0 = normal), puis l'id_player (tie-break).
 *
 * Le leader diffuse sync_play toutes les SYNC_INTERVAL_MS.
 * Les slaves recoivent le message et corrigent si derive > DRIFT_THRESHOLD_MS.
 *
 * Isolation inter-groupes : champ "group" dans chaque message (filtre applicatif).
 */

const dgram = require('dgram');

const BROADCAST_ADDR   = '255.255.255.255';
const BROADCAST_PORT   = 7778;
const SYNC_INTERVAL_MS = 2000;   // Piste B : sync plus frequent pour un nudge fin
const DRIFT_THRESHOLD_MS = 40;   // seuil bas : le renderer gere la dead-zone via playbackRate
// Le leader broadcast toutes les 2s. Un peer absent depuis 20s (10 messages rates) est
// considere mort → reelection. Seuil RELEVE de 10s a 20s : aux frontieres d'item, un slave
// charge (transition video lourde) ratait des broadcasts pendant >10s → perdait le master de
// ses peers → s'elisait leader puis re-redevenait slave (flip-flop → oscillation de lecture
// amplifiee par le rattrapage d'item). 20s tolere ce jank ; failover encore acceptable.
const PEER_TIMEOUT_MS  = 20000;
// Hystérésis de PROMOTION (anti flip-flop, > PEER_TIMEOUT). On ne s'AUTO-promeut leader que
// si le leader LÉGITIME (priorité supérieure, ou égale + id plus petit) est resté silencieux
// plus longtemps que ce délai. Sans ça : à une coupure SERVEUR le master LAN reste vivant et
// diffuse, mais un slave chargé en frontière d'item (ou jank de reconnexion) rate ses
// broadcasts >PEER_TIMEOUT → le cleanup retire le master de ses peers → il s'auto-promeut
// leader → re-bascule slave dès qu'il revoit le master → oscillation de lecture. Avec la
// grâce, ce trou transitoire est toléré (le slave reste slave) ; seul un master VRAIMENT mort
// (silencieux > grâce) déclenche un failover.
const PROMOTION_GRACE_MS = 35000;
const CLEANUP_INTERVAL_MS = 5000;
// Ré-annonce périodique de présence (< PEER_TIMEOUT) : tout nœud (pas seulement le
// leader) doit se signaler régulièrement, sinon les followers disparaissent des listes
// de peers et l'élection devient impossible si le master tombe (ex. coupure serveur).
const ANNOUNCE_INTERVAL_MS = 3000;
// Fenêtre de DÉCOUVERTE avant de pouvoir conclure « je suis seul dans mon groupe ». Un nœud
// n'apprend l'existence de ses pairs que par leur annonce périodique : il faut donc avoir
// écouté au moins un intervalle d'annonce pour distinguer « seul » de « pas encore
// découvert ». Deux intervalles = tolère la perte d'un datagramme (broadcast UDP, Wi-Fi).
const DISCOVERY_WINDOW_MS = 2 * ANNOUNCE_INTERVAL_MS;
// Barrière de readiness (Q1) : le mur ne démarre une nouvelle empreinte de contenu
// (fp) que quand tous les membres qui PARLENT le protocole l'ont en cache. Filet de
// sécurité = timeout : au pire on démarre dégradé après ce délai (jamais de gel).
const BARRIER_TIMEOUT_MS = 25000;

class LanSyncController {
  /**
   * @param {number}  idPlayer    id_player de ce player
   * @param {string}  groupName   groupe LAN sync
   * @param {function} onSyncReceived  callback({id_playlist, start_index, start_offset_ms, source})
   * @param {boolean} isMaster    true = leader designe (lan_sync_master dans display_config)
   */
  constructor(idPlayer, groupName, onSyncReceived, isMaster = false) {
    this.idPlayer        = idPlayer;
    this.groupName       = groupName ?? 'default';
    this.onSyncReceived  = onSyncReceived;
    this.masterPriority  = isMaster ? 1 : 0;   // 1 = designe, 0 = normal
    this.socket          = null;
    this.isLeader        = false;
    // id_player -> { seenAt, priority }
    this.peers           = new Map();
    this.broadcastTimer  = null;
    this.cleanupTimer    = null;
    this.announceTimer   = null;
    this._getState       = null;
    this._onSwitchHint   = null;   // #2b : annonce de la prochaine bascule (slaves)
    // Barrière de readiness (Q1)
    this.myFp            = null;   // empreinte du contenu courant (set d'octets attendus)
    this.myReady         = false;  // true = j'ai tout le contenu de myFp en cache
    this._onBarrierRelease = null; // callback(fp) quand la barrière s'ouvre
    this._released       = new Set();    // fps déjà relâchés (ne pas re-déclencher)
    this._fpSeenAt       = new Map();    // fp -> 1re apparition (pour le timeout)
    this._lastLeaderMsgAt = 0;           // dernier message reçu d'un nœud qui me surpasse (hystérésis de promotion)
    this._startedAt      = 0;            // début d'écoute (fenêtre de découverte des pairs)
  }

  setStateGetter(fn) { this._getState = fn; }
  setSwitchHintHandler(fn) { this._onSwitchHint = fn; }
  setBarrierReleaseHandler(fn) { this._onBarrierRelease = fn; }

  /** Déclaré par main.js : empreinte du contenu courant + si tout est en cache local. */
  setReadiness(fp, ready) {
    const changed = (fp !== this.myFp) || (ready !== this.myReady);
    if (fp && !this._fpSeenAt.has(fp)) this._fpSeenAt.set(fp, Date.now());
    this.myFp = fp || null;
    this.myReady = !!ready;
    if (changed) {
      this._announce();        // re-annonce immédiate de mon état de readiness
      this._checkBarrier();
    }
  }

  start() {
    if (this.socket) return;

    // Départ de la fenêtre de découverte. Posé AVANT le bind (et pas dans son callback) : si
    // le bind échoue, la fenêtre expire quand même et le nœud bascule en solo — mode dégradé
    // voulu (LAN cassé ⇒ on diffuse seul plutôt que de rester figé), par un chemin explicite.
    this._startedAt = Date.now();

    this.socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });

    this.socket.on('error', (err) => {
      console.error('[LAN Sync] Socket error:', err.message);
    });

    this.socket.on('message', (buf, rinfo) => {
      try {
        const msg = JSON.parse(buf.toString());
        if (msg.group !== this.groupName) return;
        if (msg.id_player === this.idPlayer) return;
        this._handleMessage(msg, rinfo);
      } catch { /* ignore malformed */ }
    });

    this.socket.bind(BROADCAST_PORT, () => {
      try {
        this.socket.setBroadcast(true);
      } catch (e) {
        console.warn('[LAN Sync] setBroadcast failed:', e.message);
      }
      console.log(
        `[LAN Sync] Listening broadcast :${BROADCAST_PORT} group="${this.groupName}" ` +
        `master=${this.masterPriority === 1}`
      );
      this._announce();
    });

    this.cleanupTimer = setInterval(() => this._cleanupPeers(), CLEANUP_INTERVAL_MS);
    // Ré-annonce périodique : garde ce nœud visible des autres (followers compris) pour
    // une élection de leader robuste même sans serveur / si le master disparaît.
    this.announceTimer = setInterval(() => {
      this._announce();
      // L'élection n'était déclenchée QUE par le trafic des pairs (message reçu, ou pair
      // retiré au cleanup). Un player SEUL dans son groupe n'a ni l'un ni l'autre : il ne
      // devenait donc JAMAIS leader, `groupReady` n'était même jamais évalué, et sa barrière
      // ne s'ouvrait que par le filet anti-gel de BARRIER_TIMEOUT_MS (25 s) — le filet devenu
      // chemin nominal. Réélire au rythme de l'annonce ferme ce trou.
      this._electLeader();
      this._checkBarrier();
    }, ANNOUNCE_INTERVAL_MS);
  }

  _announce() {
    this._broadcast({
      type: 'sync_announce',
      id_player: this.idPlayer,
      group: this.groupName,
      priority: this.masterPriority,
      fp: this.myFp,
      ready: this.myReady,
    });
  }

  _broadcast(payload) {
    if (!this.socket) return;
    const msg = Buffer.from(JSON.stringify(payload));
    this.socket.send(msg, 0, msg.length, BROADCAST_PORT, BROADCAST_ADDR, (err) => {
      if (err) console.error('[LAN Sync] Broadcast error:', err.message);
    });
  }

  _setPeer(msg) {
    this.peers.set(msg.id_player, {
      seenAt: Date.now(), priority: msg.priority ?? 0,
      fp: msg.fp ?? null, ready: !!msg.ready,
    });
    if (msg.fp && !this._fpSeenAt.has(msg.fp)) this._fpSeenAt.set(msg.fp, Date.now());
    // Liveness du leader légitime (hystérésis de promotion) : tout message d'un nœud qui me
    // surpasse à l'élection prouve qu'un leader candidat est vivant → je ne dois pas me promouvoir.
    if (this._outranksMe(msg)) this._lastLeaderMsgAt = Date.now();
  }

  // Le nœud émetteur me SURPASSE-t-il pour l'élection (= leader légitime potentiel) ?
  // Priorité supérieure, ou priorité égale + id_player plus petit (même tie-break que l'élection).
  _outranksMe(msg) {
    const p = msg.priority ?? 0;
    return p > this.masterPriority || (p === this.masterPriority && msg.id_player < this.idPlayer);
  }

  _handleMessage(msg, rinfo) {
    switch (msg.type) {
      case 'sync_announce':
        this._setPeer(msg);
        this._electLeader();
        this._checkBarrier();
        break;

      case 'barrier_release':
        // Un membre (leader ou timeout) a ouvert la barrière pour cette empreinte.
        if (msg.fp && msg.fp === this.myFp && !this._released.has(msg.fp)) {
          this._released.add(msg.fp);
          console.log(`[LAN Sync] Barrier OPEN fp=${String(msg.fp).slice(0, 8)} (relayé par ${msg.id_player})`);
          if (this._onBarrierRelease) this._onBarrierRelease(msg.fp);
        }
        break;

      case 'sync_play':
        this._setPeer(msg);
        // Anti split-brain : ne suivre (offset + switch_at) QUE le leader LÉGITIME — meilleure
        // priorité / plus petit id parmi self + peers. Si un usurpateur s'est auto-élu faute de
        // voir le vrai master (partition partielle) et diffuse aussi des sync_play, on l'ignore :
        // sinon le slave est ballotté entre les deux et se cale sur le mauvais (vu : RPi/MINIX
        // calés sur l'AOpen prio0 au lieu du NUC prio1, qu'ils reçoivent pourtant).
        if (!this.isLeader && msg.id_player === this._bestLeaderId()) {
          // IMPORTANT : start_offset_ms est la position DANS LA VIDEO (video.currentTime),
          // independante de l'horloge machine. On NE l'ajuste PAS avec un delta d'horloge
          // cross-machine (NUC vs RPi non synchronises NTP = skew de plusieurs centaines de ms
          // qui rendait la correction inoperante). La latence reseau LAN reelle est < 1ms.
          const leaderOffset = msg.start_offset_ms;

          const myState    = this._getState ? this._getState() : null;
          const samePl     = myState && myState.id_playlist === msg.id_playlist;
          const sameItem   = samePl && myState.currentIndex === msg.start_index;
          const myOffset   = (sameItem && myState.currentOffsetMs != null)
            ? myState.currentOffsetMs : null;
          const drift      = myOffset !== null
            ? Math.abs(leaderOffset - myOffset) : Infinity;

          if (!samePl || !sameItem || drift > DRIFT_THRESHOLD_MS || msg.force) {
            this.onSyncReceived({
              id_playlist:     msg.id_playlist,
              start_index:     msg.start_index,
              start_offset_ms: leaderOffset,
              source:          'lan',
            });
          }
          // #2b : aligne la bascule d'item du slave sur celle du maître (switch_at
          // absolu, horloge NTP commune). Envoyé à chaque message, indépendant du drift.
          if (this._onSwitchHint && msg.switch_at && samePl) {
            this._onSwitchHint({
              start_index: msg.start_index,
              switch_at:   msg.switch_at,
              next_index:  msg.next_index,
            });
          }
        }
        this._checkBarrier();
        break;

      case 'sync_bye':
        this.peers.delete(msg.id_player);
        this._electLeader();
        break;

      default:
        break;
    }
  }

  /**
   * Le leader est le candidat avec la plus haute priorite (master designe),
   * puis le plus petit id_player en cas d'egalite.
   * Retourne true si CE player doit etre leader.
   */
  // Id du leader LÉGITIME = meilleure priorité (puis plus petit id) parmi self + peers.
  // Sert à l'élection ET au filtrage des sync_play reçus (anti split-brain).
  _bestLeaderId() {
    let bestPriority = this.masterPriority;
    let bestId       = this.idPlayer;
    for (const [id, info] of this.peers.entries()) {
      const p = info.priority ?? 0;
      if (p > bestPriority || (p === bestPriority && id < bestId)) {
        bestPriority = p;
        bestId       = id;
      }
    }
    return bestId;
  }
  _shouldBeLeader() {
    if (this._bestLeaderId() !== this.idPlayer) return false;
    // Je ne connais AUCUN pair : soit je suis réellement seul (groupe d'un membre — légitime :
    // on active la synchro LAN sur un écran avant d'installer les suivants), soit je viens de
    // démarrer et je ne les ai pas encore entendus. Tant que la fenêtre de découverte n'est pas
    // écoulée, je ne tranche pas. Sans ce délai, un player qui REDÉMARRE dans un groupe existant
    // se croirait seul, s'auto-promeuvrait et ouvrirait sa barrière tout seul : il partirait
    // AVANT le groupe, exactement ce que la barrière existe pour empêcher.
    if (this.peers.size === 0 && (Date.now() - this._startedAt) < DISCOVERY_WINDOW_MS) {
      return false;
    }
    // Je serais leader d'après les peers VIVANTS. Mais si un leader légitime m'a parlé
    // récemment (< PROMOTION_GRACE_MS), c'est un trou transitoire (frontière d'item / jank de
    // reconnexion serveur) : je reste SLAVE pour ne pas flip-flopper. Au-delà du délai (master
    // réellement disparu), je m'auto-promeus.
    if (this._lastLeaderMsgAt && (Date.now() - this._lastLeaderMsgAt) < PROMOTION_GRACE_MS) {
      return false;
    }
    return true;
  }

  _electLeader() {
    const wasLeader = this.isLeader;
    this.isLeader = this._shouldBeLeader();

    if (this.isLeader && !wasLeader) {
      console.log(
        `[LAN Sync] Elected LEADER (priority=${this.masterPriority}, peers: ` +
        `${[...this.peers.keys()].join(', ')})`
      );
      this._startBroadcast();
    } else if (!this.isLeader && wasLeader) {
      console.log('[LAN Sync] Became SLAVE');
      this._stopBroadcast();
    }
  }

  _startBroadcast() {
    if (this.broadcastTimer) return;
    this._sendSync();
    this.broadcastTimer = setInterval(() => this._sendSync(), SYNC_INTERVAL_MS);
  }

  _stopBroadcast() {
    if (this.broadcastTimer) {
      clearInterval(this.broadcastTimer);
      this.broadcastTimer = null;
    }
  }

  _sendSync() {
    if (!this.isLeader || !this._getState) return;
    const state = this._getState();
    if (!state || !state.id_playlist) return;

    this._broadcast({
      type:            'sync_play',
      group:           this.groupName,
      id_player:       this.idPlayer,
      priority:        this.masterPriority,
      id_playlist:     state.id_playlist,
      start_index:     state.currentIndex,
      start_offset_ms: state.currentOffsetMs ?? 0,
      switch_at:       state.switch_at ?? null,   // #2b : instant absolu de la prochaine bascule
      next_index:      state.next_index ?? null,
      fp:              this.myFp,
      ready:           this.myReady,
      sent_at:         Date.now(),
    });
  }

  // Barrière (Q1) : ouvre l'empreinte courante quand le groupe est prêt (leader) ou au
  // timeout (filet anti-gel, tout membre). Un peer SANS fp (ancien player / Android non
  // porté) est NON-bloquant (rétro-compat + flottes mixtes). Idempotent par fp.
  _checkBarrier() {
    const fp = this.myFp;
    if (!fp || this._released.has(fp)) return;
    const seenAt = this._fpSeenAt.get(fp) || Date.now();
    const timedOut = (Date.now() - seenAt) > BARRIER_TIMEOUT_MS;
    let groupReady = false;
    if (this.isLeader) {
      // tous les peers QUI PARLENT le protocole (fp défini) doivent être sur la même
      // empreinte ET prêts ; + moi prêt. Les peers fp=null sont ignorés (non-bloquants).
      groupReady = this.myReady && [...this.peers.values()].every(
        (p) => p.fp == null || (p.fp === fp && p.ready)
      );
    }
    if ((this.isLeader && groupReady) || timedOut) {
      this._released.add(fp);
      const reason = (this.isLeader && groupReady) ? 'group-ready' : 'timeout';
      console.log(`[LAN Sync] Barrier RELEASE fp=${String(fp).slice(0, 8)} (${reason}, leader=${this.isLeader})`);
      this._broadcast({ type: 'barrier_release', id_player: this.idPlayer, group: this.groupName, fp });
      if (this._onBarrierRelease) this._onBarrierRelease(fp);
    }
  }

  forceSyncNow() {
    if (this.isLeader) this._sendSync();
  }

  _cleanupPeers() {
    const cutoff = Date.now() - PEER_TIMEOUT_MS;
    let removed = false;
    for (const [id, info] of this.peers.entries()) {
      if (info.seenAt < cutoff) {
        console.log(`[LAN Sync] Peer ${id} timed out, removing`);
        this.peers.delete(id);
        removed = true;
      }
    }
    // Tout retrait de peer peut changer le leader : si le maitre actuel a disparu
    // (crash/perte reseau sans sync_bye), il faut reelire parmi les survivants.
    if (removed) this._electLeader();
    // Tick régulier de la barrière : déclenche le timeout (filet anti-gel) et ré-évalue
    // group-ready si un peer prêt n'a pas redéclenché de message depuis.
    this._checkBarrier();
  }

  stop() {
    this._stopBroadcast();
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer);
      this.cleanupTimer = null;
    }
    if (this.announceTimer) {
      clearInterval(this.announceTimer);
      this.announceTimer = null;
    }
    if (this.socket) {
      this._broadcast({ type: 'sync_bye', id_player: this.idPlayer, group: this.groupName });
      try { this.socket.close(); } catch {}
      this.socket = null;
    }
    this.isLeader = false;
    this.peers.clear();
    this._released.clear();
    this._fpSeenAt.clear();
    this.myFp = null;
    this.myReady = false;
    console.log('[LAN Sync] Stopped');
  }
}

module.exports = { LanSyncController };
