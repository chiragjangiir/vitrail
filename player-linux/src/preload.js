'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('signflow', {
  onSync:          (cb) => ipcRenderer.on('player:sync',           (_e, p) => cb(p)),
  onConnected:     (cb) => ipcRenderer.on('player:connected',      (_e)    => cb()),
  onDisconnected:  (cb) => ipcRenderer.on('player:disconnected',   (_e)    => cb()),
  onMaintenance:   (cb) => ipcRenderer.on('player:maintenance',    (_e, p) => cb(p)),
  onSetupRequired: (cb) => ipcRenderer.on('player:setup-required', (_e)    => cb()),
  onLanAdjust:     (cb) => ipcRenderer.on('player:lan-adjust',     (_e, p) => cb(p)),
  onLanSwitch:     (cb) => ipcRenderer.on('player:lan-switch',     (_e, p) => cb(p)),
  reportPlaybackPos: (pos) => ipcRenderer.send('player:playback-pos', pos),
  requestResync:   ()  => ipcRenderer.send('player:request-resync'),
  reportEvent:     (ev) => ipcRenderer.send('player:report-event', ev),
  reportPlay:      (e)  => ipcRenderer.send('player:report-play', e),  // Proof of Play (§XXIV)
  saveWizard:      (cfg) => ipcRenderer.invoke('wizard:save', cfg),
  // Store Control Panel LAN (§19.3)
  onControlApply:  (cb) => ipcRenderer.on('control:apply', (_e, a) => cb(a)),
  sendControlStatus: (s) => ipcRenderer.send('control:status', s),
  onAudioRestart:  (cb) => ipcRenderer.on('audio:restart', () => cb()),
  // Overlay de maintenance (toggle depuis le CMS)
  onOverlay:       (cb) => ipcRenderer.on('player:overlay', (_e, p) => cb(p)),
  // VOD à la demande (Feature B) : lecture ad-hoc takeover par-dessus la programmation
  onPlayNow:       (cb) => ipcRenderer.on('player:play_now', (_e, p) => cb(p)),
  // Store local (offline-first) : un média vient d'arriver en cache → bascule local
  onStoreUpdate:   (cb) => ipcRenderer.on('player:store-update', (_e, p) => cb(p)),
  // Barrière de sync LAN (Q1) : le groupe est prêt → démarrer le contenu en attente
  onLanRelease:    (cb) => ipcRenderer.on('player:lan-release', () => cb()),
  // Rendu vidéo HW VAAPI via mpv (Intel/Linux, display_config.video_renderer=mpv). Le
  // renderer route la vidéo vers mpv au lieu du <video> Chromium (software sur Intel/Linux).
  mpv: {
    load:     (opts) => ipcRenderer.invoke('mpv:load', opts),   // {url, seekMs, muted, subtitles} → bool
    seek:     (ms)   => ipcRenderer.send('mpv:seek', ms),       // resync LAN (best-effort)
    setSpeed: (r)    => ipcRenderer.send('mpv:set-speed', r),   // nudge LAN
    getProp:  (name) => ipcRenderer.invoke('mpv:get-prop', name),
    raise:    ()     => ipcRenderer.send('mpv:raise'),
    lower:    ()     => ipcRenderer.send('mpv:lower'),
    stop:     ()     => ipcRenderer.send('mpv:stop'),
    setMute:  (b)    => ipcRenderer.send('mpv:set-mute', b),
    osd:      (text, durMs) => ipcRenderer.send('mpv:osd', { text, durMs }),
    onEnded:    (cb) => ipcRenderer.on('player:mpv-ended', () => cb()),
    onTimepos:  (cb) => ipcRenderer.on('player:mpv-timepos', (_e, d) => cb(d)),
    onVideoInfo:(cb) => ipcRenderer.on('player:mpv-videoinfo', (_e, d) => cb(d)),
  },
});
