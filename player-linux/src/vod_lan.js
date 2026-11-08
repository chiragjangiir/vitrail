'use strict';

/**
 * vod_lan.js — Déclenchement VOD multi-cible AUTONOME en réseau local (Feature B, Phase 3).
 *
 * Permet au panneau de contrôle local (§19.3) d'un player de lancer une vidéo sur N'IMPORTE
 * QUEL player du groupe VOD, SANS serveur (survit à une coupure internet — exigence §XIX).
 *
 * Transport : UDP broadcast 255.255.255.255:7779 (port DÉDIÉ, séparé du LAN sync 7778 qui n'est
 * actif que dans un groupe de synchro — le trigger VOD doit marcher hors groupe sync).
 *
 * Sécurité : chaque commande est signée HMAC-SHA256 avec le secret partagé par site (livré dans
 * le sync `vod_lan.secret`, donc caché offline). Anti-rejeu = fraîcheur ts (≤30s) + set de nonces.
 * Le récepteur ne joue que les commandes qui le CIBLENT (id_player == soi).
 */

const dgram = require('dgram');
const crypto = require('crypto');

const BROADCAST_ADDR = '255.255.255.255';
// Modes admis sur le fil. Les variantes `_muted` portent le choix « sans son » du
// panneau local sans toucher au format signe (cf. broadcast/_onMessage).
const _MODES = new Set(['once', 'loop', 'stop', 'once_muted', 'loop_muted']);
const VOD_LAN_PORT   = 7779;
const FRESH_MS       = 30000;   // une commande plus vieille que 30s est rejetée (anti-rejeu)
const NONCE_TTL_MS   = 60000;   // on se souvient des nonces vus 60s

function _canonical(m) {
  // Chaîne canonique signée (ordre figé, séparateur improbable dans les valeurs).
  return `vod_play|${m.id_player}|${m.id_media}|${m.mode}|${m.ts}|${m.nonce}`;
}

class VodLanController {
  /**
   * @param {number}   idPlayer  id_player de CE player (filtre des commandes reçues)
   * @param {string}   secret    secret partagé par site (hex) — null tant qu'inconnu
   * @param {function} onCommand callback({ id_media, mode }) quand une commande nous cible
   */
  constructor(idPlayer, secret, onCommand) {
    this.idPlayer  = idPlayer;
    this.secret    = secret || null;
    this.onCommand = onCommand;
    this.socket    = null;
    this._seen     = new Map();   // nonce -> seenAt (anti-rejeu)
    this._sweep    = null;
  }

  /** Re-clé sans redémarrer le socket (le secret peut changer à un re-sync). */
  updateSecret(secret) { this.secret = secret || null; }

  start() {
    if (this.socket) return;
    const sock = dgram.createSocket({ type: 'udp4', reuseAddr: true });
    sock.on('error', (e) => { try { console.warn('[vod_lan] socket error', e.message); } catch (_) {} });
    sock.on('message', (buf) => this._onMessage(buf));
    sock.bind(VOD_LAN_PORT, () => {
      try { sock.setBroadcast(true); } catch (_) {}
    });
    this.socket = sock;
    this._sweep = setInterval(() => this._sweepNonces(), NONCE_TTL_MS);
    if (this._sweep.unref) this._sweep.unref();
  }

  stop() {
    if (this._sweep) { clearInterval(this._sweep); this._sweep = null; }
    if (this.socket) { try { this.socket.close(); } catch (_) {} this.socket = null; }
    this._seen.clear();
  }

  /**
   * Diffuse une commande de lecture VOD vers un player cible (signée).
   * @param {{ id_player:number, id_media:number, mode:string }} cmd
   */
  broadcast(cmd) {
    if (!this.socket || !this.secret) return;
    const m = {
      cmd: 'vod_play',
      id_player: cmd.id_player,
      id_media:  cmd.id_media,
      // Liste blanche ELARGIE aux variantes muettes (2026-07-19) : le son du takeover voyage
      // encode dans le mode pour ne pas modifier la chaine signee. Sans `_muted` ici, le choix
      // « sans son » du panneau local etait silencieusement ecrase a l'emission.
      mode:      _MODES.has(cmd.mode) ? cmd.mode : 'once',
      ts:        Date.now(),
      nonce:     crypto.randomBytes(8).toString('hex'),
    };
    m.sig = crypto.createHmac('sha256', this.secret).update(_canonical(m)).digest('hex');
    const data = Buffer.from(JSON.stringify(m));
    try { this.socket.send(data, 0, data.length, VOD_LAN_PORT, BROADCAST_ADDR); } catch (_) {}
  }

  _onMessage(buf) {
    if (!this.secret) return;
    let m;
    try { m = JSON.parse(buf.toString('utf8')); } catch (_) { return; }
    if (!m || m.cmd !== 'vod_play') return;
    if (m.id_player !== this.idPlayer) return;             // ne joue que ce qui ME cible
    if (typeof m.ts !== 'number' || Math.abs(Date.now() - m.ts) > FRESH_MS) return;  // fraîcheur
    if (!m.nonce || this._seen.has(m.nonce)) return;       // anti-rejeu
    const expected = crypto.createHmac('sha256', this.secret).update(_canonical(m)).digest('hex');
    let ok = false;
    try {
      ok = typeof m.sig === 'string' && m.sig.length === expected.length
        && crypto.timingSafeEqual(Buffer.from(m.sig), Buffer.from(expected));
    } catch (_) { ok = false; }
    if (!ok) return;
    this._seen.set(m.nonce, Date.now());
    try { this.onCommand({ id_media: m.id_media, mode: m.mode }); } catch (_) {}
  }

  _sweepNonces() {
    const cutoff = Date.now() - NONCE_TTL_MS;
    for (const [n, t] of this._seen) if (t < cutoff) this._seen.delete(n);
  }
}

module.exports = { VodLanController, VOD_LAN_PORT };
