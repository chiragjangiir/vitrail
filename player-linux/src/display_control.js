'use strict';

/**
 * display_control.js — Controle des ecrans via RS232 (serial), IP (TCP) ou HDMI-CEC.
 *
 * Aucune dependance native requise :
 *   - RS232 : fs.openSync() + stty (Linux/RPi) ou mode (Windows)
 *   - IP    : net.Socket (Node.js built-in)
 *   - CEC   : cec-ctl (paquet v4l-utils ; RPi = /dev/cec0 natif)
 *
 * Protocoles implementes :
 *   - samsung_mdc  : Samsung MDC (RS232 baud 9600 / IP port 1515)
 *   - lg_rs232c    : LG RS232C (baud 9600)
 *   - generic      : octets bruts depuis params.hex (fallback universel)
 *
 * Structure display_config (JSONB en base) :
 *   { type: 'rs232', serial_port: '/dev/ttyUSB0', baud_rate: 9600,
 *     model: 'samsung_mdc', address: 1,
 *     lan_sync_enabled: false, lan_sync_group: null }
 *
 *   { type: 'ip', host: '192.168.1.50', tcp_port: 1515,
 *     model: 'samsung_mdc', address: 1,
 *     lan_sync_enabled: false }
 */

const fs   = require('fs');
const net  = require('net');
const os   = require('os');
const { execSync } = require('child_process');

// ── Protocole Samsung MDC ──────────────────────────────────────────────────────
// Reference : Samsung MDC Protocol v14.0
// Trame : 0xAA [CMD] [ID] [LEN] [DATA...] [CHECKSUM]
// Checksum = somme de CMD+ID+LEN+DATA, modulo 256

function samsungChecksum(frame) {
  // Somme de tous les octets apres 0xAA
  return frame.slice(1).reduce((acc, b) => (acc + b) & 0xFF, 0);
}

function samsungFrame(cmd, id, data) {
  const frame = [0xAA, cmd, id, data.length, ...data];
  frame.push(samsungChecksum(frame));
  return Buffer.from(frame);
}

// Sources d'entree Samsung MDC
const SAMSUNG_INPUT = {
  pc:    0x14,
  av:    0x18,
  hdmi1: 0x21,
  hdmi2: 0x23,
  hdmi3: 0x31,
  dp:    0x25,
  dvi:   0x18,
};

// ── Protocole LG RS232C ────────────────────────────────────────────────────────
// Reference : LG Display Control Manual
// Trame : [CMD1] [CMD2] [SET_ID] [DATA] [CR]

function lgFrame(cmd1, cmd2, setId, data) {
  const line = `${cmd1}${cmd2} ${String.fromCharCode(setId)} ${data}\r`;
  return Buffer.from(line, 'ascii');
}

// ── Registre de protocoles ─────────────────────────────────────────────────────

const PROTOCOLS = {
  samsung_mdc: {
    power_on:       (id)     => samsungFrame(0x11, id, [0x01]),
    power_off:      (id)     => samsungFrame(0x11, id, [0x00]),
    get_status:     (id)     => samsungFrame(0x00, id, [0x11]),  // query power
    set_brightness: (id, p)  => samsungFrame(0x25, id, [Math.max(0, Math.min(100, p.level ?? 50))]),
    set_contrast:   (id, p)  => samsungFrame(0x24, id, [Math.max(0, Math.min(100, p.level ?? 50))]),
    set_volume:     (id, p)  => samsungFrame(0x12, id, [Math.max(0, Math.min(100, p.level ?? 50))]),
    mute_on:        (id)     => samsungFrame(0x13, id, [0x01]),
    mute_off:       (id)     => samsungFrame(0x13, id, [0x00]),
    set_input:      (id, p)  => {
      const code = SAMSUNG_INPUT[p.source ?? 'hdmi1'] ?? 0x21;
      return samsungFrame(0x14, id, [code]);
    },
  },

  lg_rs232c: {
    power_on:       (id)     => lgFrame('k', 'a', id, '01'),
    power_off:      (id)     => lgFrame('k', 'a', id, '00'),
    get_status:     (id)     => lgFrame('k', 'a', id, 'ff'),
    set_brightness: (id, p)  => {
      const hex = Math.max(0, Math.min(100, p.level ?? 50)).toString(16).padStart(2, '0');
      return lgFrame('k', 'h', id, hex);
    },
    set_input:      (id, p)  => {
      const codes = { av: '20', hdmi1: '90', hdmi2: '91', dp: 'c0' };
      return lgFrame('x', 'b', id, codes[p.source ?? 'hdmi1'] ?? '90');
    },
  },

  // Generique : le champ params.hex contient les octets bruts en hexadecimal
  generic: {
    power_on:       (id, p)  => Buffer.from(p.hex ?? '', 'hex'),
    power_off:      (id, p)  => Buffer.from(p.hex ?? '', 'hex'),
    get_status:     (id, p)  => Buffer.from(p.hex ?? '', 'hex'),
    set_brightness: (id, p)  => Buffer.from(p.hex ?? '', 'hex'),
    set_input:      (id, p)  => Buffer.from(p.hex ?? '', 'hex'),
  },
};

function buildFrame(model, cmd, address, params) {
  const proto = PROTOCOLS[model] ?? PROTOCOLS.generic;
  const fn = proto[cmd];
  if (!fn) throw new Error(`Unknown command '${cmd}' for model '${model}'`);
  const frame = fn(address ?? 1, params ?? {});
  if (!frame || frame.length === 0) throw new Error(`Empty frame for '${cmd}' (check params.hex)`);
  return frame;
}

// ── Controleur RS232 via fs (sans native module) ───────────────────────────────

class Rs232Controller {
  constructor(serialPort, baudRate = 9600) {
    this.serialPort = serialPort;
    this.baudRate   = baudRate;
    this.fd         = null;
  }

  _configure() {
    const platform = os.platform();
    try {
      if (platform === 'win32') {
        // Windows : mode COM3: BAUD=9600 PARITY=N DATA=8 STOP=1
        const portId = this.serialPort.replace(/^\\\\\.\\/,'');  // strip \\.\
        execSync(
          `mode ${portId}: BAUD=${this.baudRate} PARITY=N DATA=8 STOP=1 to=off`,
          { stdio: 'ignore', timeout: 3000 }
        );
      } else {
        // Linux / RPi : stty
        execSync(
          `stty -F ${this.serialPort} ${this.baudRate} raw -echo cs8 -cstopb -parenb`,
          { stdio: 'ignore', timeout: 3000 }
        );
      }
    } catch (e) {
      throw new Error(`RS232 configure failed (${this.serialPort}): ${e.message}`);
    }
  }

  open() {
    if (this.fd !== null) return;
    this._configure();
    this.fd = fs.openSync(this.serialPort, 'r+');
    console.log(`[Display] RS232 opened: ${this.serialPort} @ ${this.baudRate} baud`);
  }

  close() {
    if (this.fd !== null) {
      try { fs.closeSync(this.fd); } catch {}
      this.fd = null;
    }
  }

  async command(model, cmd, address, params) {
    const frame = buildFrame(model, cmd, address, params);
    if (this.fd === null) this.open();
    fs.writeSync(this.fd, frame);
    console.log(`[Display] RS232 sent ${frame.length}B: ${frame.toString('hex')}`);
  }
}

// ── Controleur IP (TCP) ────────────────────────────────────────────────────────

class IpController {
  constructor(host, tcpPort, connectTimeoutMs = 5000) {
    this.host    = host;
    this.tcpPort = tcpPort;
    this.timeout = connectTimeoutMs;
  }

  async command(model, cmd, address, params) {
    const frame = buildFrame(model, cmd, address, params);
    return new Promise((resolve, reject) => {
      const socket = new net.Socket();
      const timer  = setTimeout(() => {
        socket.destroy();
        reject(new Error(`TCP timeout connecting to ${this.host}:${this.tcpPort}`));
      }, this.timeout);

      socket.connect(this.tcpPort, this.host, () => {
        socket.write(frame, () => {
          clearTimeout(timer);
          socket.destroy();
          console.log(`[Display] IP sent ${frame.length}B to ${this.host}:${this.tcpPort}`);
          resolve();
        });
      });

      socket.on('error', (err) => {
        clearTimeout(timer);
        socket.destroy();
        reject(new Error(`TCP error: ${err.message}`));
      });
    });
  }

  close() { /* pas d'etat persistant */ }
}

// ── Controleur HDMI-CEC (cec-ctl, kernel CEC — paquet v4l-utils) ───────────────
// Pilote le TELEVISEUR branche en HDMI comme une telecommande : veille (Standby),
// reveil (Image View On) + bascule sur notre entree (Active Source). Cibles :
// RPi (/dev/cec0 natif vc4) et tout Linux avec adaptateur CEC (Pulse-Eight...).
// Les PC x86 (NUC) n'ont generalement PAS de materiel CEC, Windows non plus ->
// la commande echoue proprement (erreur remontee au CMS via display:status).
// model/address sont ignores : en CEC la TV est toujours l'adresse logique 0.

class CecController {
  constructor(device = '/dev/cec0') {
    this.device  = device;
    this.claimed = false;
  }

  _run(args) {
    // cec-ctl est court (<1s) ; timeout de securite 5s. stderr capture dans l'erreur.
    return execSync(`cec-ctl -d ${this.device} ${args}`, { encoding: 'utf8', timeout: 5000 });
  }

  _claim() {
    if (this.claimed) return;
    // Se declarer « Playback device » sur le bus (requis avant d'emettre).
    // Idempotent : re-claim silencieux apres redemarrage du player.
    this._run('--playback --osd-name SignFlow');
    this.claimed = true;
    console.log(`[Display] CEC claimed as playback device on ${this.device}`);
  }

  _physAddr() {
    const m = this._run('').match(/Physical Address\s*:\s*([0-9a-f.]+)/i);
    return m ? m[1] : null;
  }

  async command(model, cmd, address, params) {
    this._claim();
    switch (cmd) {
      case 'power_on': {
        this._run('--to 0 --image-view-on');       // reveille la TV
        try {
          const pa = this._physAddr();             // + bascule sur NOTRE entree (best-effort)
          if (pa) this._run(`--to 0 --active-source phys-addr=${pa}`);
        } catch { /* la TV peut deja etre sur la bonne entree */ }
        break;
      }
      case 'power_off':
        this._run('--to 0 --standby');
        break;
      case 'get_status':
        console.log('[Display] CEC power status:\n' + this._run('--to 0 --give-device-power-status'));
        break;
      case 'set_input': {
        // CEC ne choisit pas une entree arbitraire : on se declare Active Source
        // -> la TV bascule sur l'entree de CE player (params.source ignore).
        const pa = this._physAddr();
        if (!pa) throw new Error('CEC physical address unknown');
        this._run(`--to 0 --active-source phys-addr=${pa}`);
        break;
      }
      default:
        throw new Error(`Command '${cmd}' not supported via CEC`);
    }
    console.log(`[Display] CEC ${cmd} sent on ${this.device}`);
  }

  close() { this.claimed = false; }
}

// ── Factory ────────────────────────────────────────────────────────────────────

/**
 * Cree un DisplayController a partir d'un display_config.
 * Retourne null si display_config est absent ou de type inconnu.
 */
function createDisplayController(displayConfig) {
  if (!displayConfig || !displayConfig.type) return null;

  if (displayConfig.type === 'rs232') {
    const port    = displayConfig.serial_port ?? '/dev/ttyUSB0';
    const baud    = displayConfig.baud_rate   ?? 9600;
    return new Rs232Controller(port, baud);
  }

  if (displayConfig.type === 'ip') {
    const host    = displayConfig.host;
    const tcpPort = displayConfig.tcp_port ?? 1515;
    if (!host) {
      console.warn('[Display] display_config.type=ip but host is missing');
      return null;
    }
    return new IpController(host, tcpPort);
  }

  if (displayConfig.type === 'cec') {
    return new CecController(displayConfig.cec_device ?? '/dev/cec0');
  }

  console.warn(`[Display] Unknown display_config.type: ${displayConfig.type}`);
  return null;
}

module.exports = { createDisplayController, buildFrame, PROTOCOLS };
