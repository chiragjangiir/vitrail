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
  // Rotation du contenu (CSS) — pilotée par main (OS rotation impossible sur certaines box)
  onRotate:        (cb) => ipcRenderer.on('player:rotate', (_e, p) => cb(p)),
});
