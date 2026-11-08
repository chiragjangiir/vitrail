// vaapi_profiles.js — Harnais d'expérimentation VA-API (Intel/Linux, Chromium 124 / Electron 30).
//
// But : débloquer le décodage vidéo matériel VA-API dans Electron sur Gemini Lake
// (UHD600) où mpv décode le 4K H.264 en HW (VAAPI iHD) mais Chromium reste en
// software. Les noms de features et le gating GL changent entre versions de
// Chromium → on ne peut pas deviner LE bon combo, on le trouve empiriquement.
//
// Utilisation terrain (sans réinstaller) :
//   SF_VAAPI_PROFILE=gl-angle SF_VLOG=2 <electron> /opt/signflow/player-linux
//   → applique le combo nommé + écrit un chromium.log verbeux filtré VA-API.
// Puis on lit l'engine "Video" de `intel_gpu_top` (vérité terrain) et le log.
//
// Quand un profil gagne (Video % > 0 + log "VaapiVideoDecoder ... Initialize"),
// on fige son combo dans install.sh (chromium_flags) + capabilities.json.

// Base commune à toutes les tentatives VA-API sur desktop Linux Intel :
//  - ignore-gpu-blocklist : Gemini Lake est souvent blocklisté côté Chromium.
//  - UseChromeOSDirectVideoDecoder DOIT être désactivé hors ChromeOS pour que
//    VaapiVideoDecoder prenne la main.
//  - VaapiIgnoreDriverChecks : iHD/Gemini Lake passe parfois sous le radar des
//    checks de version de driver.
const BASE = [
  '--ignore-gpu-blocklist',
  '--disable-features=UseChromeOSDirectVideoDecoder',
  // VaapiVideoDecoder alloue son frame pool via des GpuMemoryBuffers natifs
  // (NativePixmap/GBM-DRM), désactivés par défaut hors ChromeOS → sans ça,
  // "failed Initialize()ing the frame pool" et repli software (constat NUC).
  '--enable-native-gpu-memory-buffers',
];

// enable-features cumulés (on les concatène en un seul switch à la fin).
const FEAT_CORE   = ['VaapiVideoDecoder', 'VaapiVideoDecodeLinuxGL', 'VaapiIgnoreDriverChecks'];
// Features apparues en Chromium 121+ : gating du décodage accéléré quand le GPU
// process tourne sur backend GL (et non Vulkan). Très probable pièce manquante.
const FEAT_MODERN = ['AcceleratedVideoDecodeLinuxGL', 'AcceleratedVideoDecodeLinuxZeroCopyGL'];

function withFeatures(extra, ...glFlags) {
  const feats = [...FEAT_CORE, ...extra];
  return [...BASE, ...glFlags, `--enable-features=${feats.join(',')}`];
}

// Profils ordonnés par probabilité de succès (gl-angle-modern en tête).
// Chacun = liste complète de flags (hors logging, ajouté séparément par SF_VLOG).
const PROFILES = {
  // P0 — combo actuellement figé dans install.sh (baseline, échoue aujourd'hui).
  current: [
    '--ignore-gpu-blocklist',
    '--enable-features=VaapiVideoDecoder,VaapiVideoDecodeLinuxGL',
    '--disable-features=UseChromeOSDirectVideoDecoder',
    '--disable-gpu-driver-bug-workarounds',
  ],

  // P1 — ANGLE-sur-GL + features modernes 121+ (candidat n°1).
  'gl-angle': withFeatures(FEAT_MODERN, '--use-gl=angle', '--use-angle=gl'),

  // P2 — EGL natif (l'ancien backend que la VA-API aimait avant le passage ANGLE).
  'gl-egl': withFeatures(FEAT_MODERN, '--use-gl=egl'),

  // P3 — Desktop GL (glX). Parfois le seul où VaapiVideoDecodeLinuxGL s'arme.
  'gl-desktop': withFeatures(FEAT_MODERN, '--use-gl=desktop'),

  // P4 — comme gl-angle mais sans les features modernes (isole leur effet).
  'gl-angle-core': withFeatures([], '--use-gl=angle', '--use-angle=gl'),

  // P5 — ANGLE Vulkan (Gemini Lake supporte Vulkan ; chemin zero-copy alternatif).
  'gl-vulkan': withFeatures(FEAT_MODERN, '--use-gl=angle', '--use-angle=vulkan'),

  // WAYLAND — la vraie piste : sous Ozone/Wayland (via cage), le chemin
  // NativePixmap/dma-buf existe (≠ Ozone/X11) → le frame pool VA-API peut
  // s'allouer. À lancer avec cage (cf. vaapi-diag-wayland.sh), PAS sous X11.
  // On laisse Ozone/Wayland choisir le backend GL ANGLE par défaut.
  wayland: withFeatures(FEAT_MODERN, '--ozone-platform=wayland'),
};

// Flags de logging verbeux ciblés VA-API/décodage vidéo. v = niveau (1|2|3).
// Le log Chromium (C++) part sur stderr → capté par la redirection openbox, ou
// dans chromium.log si log-file est fourni.
// Le décodage VA-API vit dans le GPU process, qui logge sur stderr (pas dans
// --log-file, réservé au process navigateur). On laisse donc tout sur stderr
// (capté par la redirection du script de diag) → pas de --log-file.
function verboseFlags(level) {
  return [
    '--enable-logging=stderr',
    `--v=${level}`,
    // vmodule : VA-API + l'INTERIEUR du frame pool / allocation buffers (la vraie
    // cause de "failed Initialize()ing the frame pool" vit la, pas dans vaapi*).
    '--vmodule=' + [
      '*vaapi*=2', 'vaapi_video_decoder=3', '*vaapi_wrapper*=2',
      '*video_decode*=2', '*gpu_video*=2',
      '*frame_pool*=3', '*video_frame_pool*=3',
      '*gpu_memory_buffer*=3', '*native_pixmap*=3', '*gbm*=3',
      '*va_surface*=2', '*vaapi_picture*=2',
    ].join(','),
  ];
}

module.exports = { PROFILES, verboseFlags };
