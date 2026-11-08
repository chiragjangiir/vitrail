"""Règles de compatibilité LAN Sync (source de vérité unique).

**Règle d'HOMOGÉNÉITÉ (décision Ed, 2026-06-11)** — remplace l'ancienne « mpv ⟺ LAN
Sync mutuellement exclusifs ». Validé terrain : un groupe LAN **hétérogène** (renderers /
OS / hardware mélangés) flip-flop ; un groupe **homogène** (players identiques hardware +
config) tient la synchro, **même en mpv 4K** (cf. test riri/fifi 2 × J4025). Le vrai
coupable n'est pas mpv en soi, c'est l'hétérogénéité (chemins de décodage et horloges
différents ; la position mpv qui se refige ballotte des followers de latences distinctes).

Conséquence :
  - Un groupe LAN homogène est toujours OK (y compris tout-mpv ou tout-exo).
  - Un groupe hétérogène contenant un renderer HW natif (mpv / ExoPlayer) est BLOQUÉ
    (la synchro y casse durement).
  - Un groupe hétérogène sans renderer HW natif (Chromium / WebView mélangés) est WARN
    (synchro moins précise mais tolérable — généralise l'ancien avertissement Android).

Le moteur reste une simple table de règles, extensible. Niveaux :
  - "ok"    : compatible, aucune réserve.
  - "warn"  : compatible mais déconseillé (groupe hétérogène sans HW natif).
  - "block" : incompatible (groupe hétérogène avec mpv/exo → flip-flop garanti).

L'évaluation est consciente du GROUPE : `peers` = les AUTRES membres du même groupe LAN.
Sans pairs (player solo / hors groupe), un player est toujours homogène avec lui-même → ok.
"""
from __future__ import annotations

from typing import Optional

LAN_SYNC_LEVELS = ("ok", "warn", "block")

# Renderers à décodage HW natif HORS Chromium : exigent un groupe homogène pour la synchro
# (mpv = VAAPI Intel/Linux ; exo = ExoPlayer Android, box 4K60 HEVC).
_HW_NATIVE_RENDERERS = ("mpv", "exo")


def _normalize_renderer(display_config: Optional[dict]) -> str:
    """video_renderer normalisé : '', 'auto' → 'chromium' ; sinon la valeur (mpv/exo)."""
    renderer = str((display_config or {}).get("video_renderer") or "auto").lower()
    return "chromium" if renderer in ("", "auto") else renderer


def homogeneity_signature(
    display_config: Optional[dict],
    player_os: Optional[str] = None,
    capabilities: Optional[dict] = None,
) -> tuple:
    """Signature d'homogénéité d'un player pour la synchro LAN.

    Deux players sont « identiques » (au sens sync) s'ils partagent : la même classe d'OS,
    le même renderer vidéo, et le même modèle matériel (proxy du hardware). On normalise l'OS en
    enlevant le suffixe d'archi (`linux-x64` → `linux`) pour que des machines de même famille
    matchent. Le token matériel peut être None (capacités pas remontées) — deux None matchent.

    **BrightSign** (toutes séries 4/5/6) : les players ne remontent pas `gpu_model` mais leur
    **référence exacte** via `bs_model` (XT1144, HD1024, XD1035, XT2145, HD1025…) et sa famille SoC
    via `bs_family` (malibu, pagani, impala…). Le décodeur et la **latence d'affichage** diffèrent
    d'une réf à l'autre (drift 1-2s CONFIRMÉ sur HW XT1144↔HD1024, séries différentes ; la sync
    `currentTime` reste bonne mais l'affichage décale). On prend donc `bs_model` (réf exacte) comme
    identité matérielle, repli sur `bs_family` : deux BrightSign de MÊME modèle = homogène (ok),
    modèles/séries mélangés = hétérogène (warn). Générique — aucune réf codée en dur.
    """
    os_ = (player_os or "").lower().split("-", 1)[0]
    renderer = _normalize_renderer(display_config)
    caps = capabilities or {}
    hw_model = caps.get("gpu_model")
    if hw_model is None and (os_ == "brightsign" or caps.get("bs_model") or caps.get("bs_family")):
        hw_model = caps.get("bs_model") or caps.get("bs_family")
    return (os_, renderer, hw_model)


def lan_sync_eligibility(
    display_config: Optional[dict],
    player_os: Optional[str] = None,
    capabilities: Optional[dict] = None,
    peers: Optional[list[dict]] = None,
) -> dict:
    """{level, reason} pour l'aptitude d'un player à être dans son groupe LAN Sync.

    `peers` : liste de dicts {display_config, player_os, capabilities} des AUTRES membres du
    même groupe LAN (peut être None/vide → player solo, toujours homogène). `reason` est un
    code stable (i18n côté front), None si level == "ok".
    """
    self_sig = homogeneity_signature(display_config, player_os, capabilities)
    peer_sigs = [
        homogeneity_signature(
            p.get("display_config"), p.get("player_os"), p.get("capabilities")
        )
        for p in (peers or [])
    ]

    homogeneous = all(sig == self_sig for sig in peer_sigs)  # vrai si aucun pair
    if homogeneous:
        return {"level": "ok", "reason": None}

    # Groupe hétérogène. On distingue l'hétérogénéité MATÉRIELLE (OS + GPU = horloges et chemins
    # de décodage distincts = le VRAI coupable du flip-flop) d'un simple écart de RENDERER. Sur un
    # matériel IDENTIQUE, un renderer différent est typiquement une **bascule de groupe en cours**
    # (on passe les membres en mpv/exo un par un) : la bloquer interdirait de basculer le 1er membre
    # (son pair n'est pas encore en mpv) = DEADLOCK. On l'autorise donc en warn — le matériel
    # identique garantit que le groupe redeviendra homogène une fois tous les membres alignés.
    self_hw = (self_sig[0], self_sig[2])   # (classe d'OS, gpu_model)
    hw_homogeneous = all((sig[0], sig[2]) == self_hw for sig in peer_sigs)
    if hw_homogeneous:
        return {"level": "warn", "reason": "renderer_mismatch"}

    # Hétérogénéité MATÉRIELLE : bloquant si le groupe contient un renderer HW natif (self ou un
    # pair) — c'est là que la synchro casse durement. Sinon simple avertissement.
    group_has_hw_native = self_sig[1] in _HW_NATIVE_RENDERERS or any(
        sig[1] in _HW_NATIVE_RENDERERS for sig in peer_sigs
    )
    if group_has_hw_native:
        return {"level": "block", "reason": "lan_sync_heterogeneous_hw"}
    return {"level": "warn", "reason": "heterogeneous_group"}


def lan_sync_blocked(
    display_config: Optional[dict],
    player_os: Optional[str] = None,
    capabilities: Optional[dict] = None,
    peers: Optional[list[dict]] = None,
) -> bool:
    """True si le player ne peut PAS être dans son groupe LAN Sync (niveau block)."""
    return (
        lan_sync_eligibility(display_config, player_os, capabilities, peers)["level"]
        == "block"
    )


def clear_lan_sync(display_config: Optional[dict]) -> dict:
    """Retire un player de tout groupe LAN Sync (désactive + efface groupe/master).

    Renvoie une COPIE du config nettoyé. `lan_sync_enabled` est mis explicitement à False
    (et non supprimé) pour que le player détecte le changement et quitte le groupe.
    """
    cfg = dict(display_config or {})
    cfg["lan_sync_enabled"] = False
    cfg["lan_sync_master"] = False
    cfg["lan_sync_group"] = None
    return cfg
