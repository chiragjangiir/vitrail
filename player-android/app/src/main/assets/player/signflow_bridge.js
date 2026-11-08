'use strict';

/**
 * signflow_bridge.js — Android WebView equivalent of Electron's preload.js
 *
 * Provides window.signflow API identical to the Electron preload,
 * so player.js can run unchanged.
 *
 * Events flow:
 *   Kotlin → evaluateJavascript("window.signflow._dispatch('sync', {...})") → player.js callback
 *   player.js → window.Android.log(msg) → Kotlin @JavascriptInterface
 */
(function () {
  var _handlers = {};

  window.signflow = {
    // Called by player.js to register event handlers
    onSync:          function (cb) { _handlers['sync'] = cb; },
    onConnected:     function (cb) { _handlers['connected'] = cb; },
    onDisconnected:  function (cb) { _handlers['disconnected'] = cb; },
    onMaintenance:   function (cb) { _handlers['maintenance'] = cb; },
    onSetupRequired: function (cb) { _handlers['setupRequired'] = cb; },
    // Overlay de maintenance (toggle depuis le CMS) — dispatch('overlay', {device})
    onOverlay:       function (cb) { _handlers['overlay'] = cb; },
    // VOD à la demande (Feature B) — dispatch('play_now', {id_media,media_type,mode,src,duration_ms})
    onPlayNow:       function (cb) { _handlers['play_now'] = cb; },

    // Offline-first / Local Content Store (P0) — équivalent des IPC Electron.
    // store-update : un média vient d'arriver en cache (Kotlin) → bascule file:// en place.
    // lan-release  : la barrière de sync LAN (Q1) s'ouvre → démarrer le contenu en attente.
    onStoreUpdate:   function (cb) { _handlers['store-update'] = cb; },
    onLanRelease:    function (cb) { _handlers['lan-release'] = cb; },

    // Store Control Panel LAN (§19.3) — équivalent des IPC Electron control:apply /
    // control:status. Le serveur natif (LocalControlServer Kotlin) applique les actions
    // de l'opérateur via dispatch('control:apply', action) et lit l'état audio que le
    // renderer pousse ici (~2s) via window.Android.nativeCall('control_status', json).
    onControlApply:    function (cb) { _handlers['control:apply'] = cb; },
    sendControlStatus: function (s) {
      if (window.Android && window.Android.nativeCall) {
        try { window.Android.nativeCall('control_status', JSON.stringify(s)); } catch (e) { /* ignore */ }
      }
    },

    // LAN sync (§III.3) — équivalent des IPC Electron player:lan-adjust / player:lan-switch /
    // player:playback-pos. Le contrôleur natif (LanSyncController Kotlin) dispatch 'lan-adjust'
    // (seek/playbackRate) et 'lan-switch' (alignement de bascule) ; le renderer remonte sa
    // position de lecture via window.Android.nativeCall('playback_pos', json).
    onLanAdjust:       function (cb) { _handlers['lan-adjust'] = cb; },
    onLanSwitch:       function (cb) { _handlers['lan-switch'] = cb; },
    reportPlaybackPos: function (pos) {
      if (window.Android && window.Android.nativeCall) {
        try { window.Android.nativeCall('playback_pos', JSON.stringify(pos)); } catch (e) { /* ignore */ }
      }
    },

    // Alerte sortante (ex. url_display inaccessible §XXV.2) → natif → serveur (ou file si offline).
    reportEvent: function (ev) {
      if (window.Android && window.Android.nativeCall) {
        try { window.Android.nativeCall('report_event', JSON.stringify(ev)); } catch (e) { /* ignore */ }
      }
    },
    // Proof of Play (§XXIV) : lecture → natif (file persistée + flush /pop/batch côté MainActivity).
    reportPlay: function (e) {
      if (window.Android && window.Android.nativeCall) {
        try { window.Android.nativeCall('report_play', JSON.stringify(e)); } catch (err) { /* ignore */ }
      }
    },

    // Rendu vidéo HW natif (ExoPlayer) — équivalent du contrôleur mpv côté Linux. Le renderer
    // délègue la vidéo à la surface native quand display_config.video_renderer='exo' (HEVC +
    // 4K@60 hors WebView). Les commandes partent en nativeCall ; la position / les events
    // (ready/ended/error/videoinfo) reviennent via _dispatch (handlers ci-dessous).
    exo: {
      load:    function (o) { _exoCall('exo_load', o || {}); },
      stop:    function ()  { _exoCall('exo_stop', {}); },
      seek:    function (ms) { _exoCall('exo_seek', { ms: ms }); },
      setRate: function (r) { _exoCall('exo_rate', { rate: r }); },
      setMute: function (b) { _exoCall('exo_mute', { muted: !!b }); },
      show:    function ()  { _exoCall('exo_show', {}); },
      hide:    function ()  { _exoCall('exo_hide', {}); },
      // Video Wall (compensation bezel) : applique un Matrix sur la TextureView native (équivalent
      // de video-zoom/align mpv). tf = display_config.wall_transform (calculé serveur), null = reset.
      setWall: function (tf) { _exoCall('exo_wall', { transform: tf || null }); },
    },
    // Écran idle NATIF (vue Android, PAS du HTML WebView) : affiché quand le player n'a rien à
    // diffuser. Natif car, sur certaines box (Amlogic, Chromium 83), la WebView cesse de composer
    // quand aucune frame ne bouge → un repli HTML restait invisible. Une vue native se compose
    // toujours (comme la TextureView vidéo).
    idle: {
      show: function (msg) { _exoCall('idle_show', { msg: msg || '' }); },
      hide: function ()    { _exoCall('idle_hide', {}); },
    },
    available: !!(window.Android && window.Android.nativeCall),   // pont natif présent
    onExoReady:     function (cb) { _handlers['exo-ready'] = cb; },
    onExoEnded:     function (cb) { _handlers['exo-ended'] = cb; },
    onExoError:     function (cb) { _handlers['exo-error'] = cb; },
    onExoTimepos:   function (cb) { _handlers['exo-timepos'] = cb; },
    onExoVideoinfo: function (cb) { _handlers['exo-videoinfo'] = cb; },

    // Called by Kotlin via evaluateJavascript to dispatch an event
    _dispatch: function (type, data) {
      var cb = _handlers[type];
      if (cb) cb(data);
    },
  };

  function _exoCall(action, params) {
    if (window.Android && window.Android.nativeCall) {
      try { window.Android.nativeCall(action, JSON.stringify(params)); } catch (e) { /* ignore */ }
    }
  }

  // Redirect console.log to Kotlin @JavascriptInterface (Android.log)
  var _origLog = console.log.bind(console);
  console.log = function () {
    var msg = Array.prototype.slice.call(arguments).join(' ');
    _origLog(msg);
    if (window.Android && window.Android.log) {
      try { window.Android.log(msg); } catch (e) { /* ignore */ }
    }
  };
})();
