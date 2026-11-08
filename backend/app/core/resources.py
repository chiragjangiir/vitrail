"""Dimensionnement automatique des workers selon les ressources RÉELLES de l'hôte.

Tout est dérivé du CPU et de la RAM réellement disponibles (limites cgroup/conteneur
respectées) → la même image s'adapte d'un mini-PC 4 cœurs/8 Go à un serveur 32 cœurs/64 Go
sans aucun réglage manuel. Objectif : un upload massif de vidéos (transcodes ffmpeg, gros
consommateurs CPU+RAM) ne doit JAMAIS saturer la machine au point de rendre l'API / la DB /
le sync des players non-réactifs.

Les valeurs sont surchageables par variables d'environnement (MEDIA_CONCURRENCY,
LIGHT_CONCURRENCY, FFMPEG_THREADS) pour un réglage fin si besoin, mais le défaut est auto.
"""

import os


def cpu_count() -> int:
    """Nombre de cœurs réellement utilisables (respecte cpuset/cgroup du conteneur)."""
    try:
        n = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        n = os.cpu_count() or 1
    return max(1, n)


def _total_ram_gb() -> float:
    """RAM totale en GiB (lue de /proc/meminfo ; repli prudent si indisponible)."""
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 * 1024)  # kB → GiB
    except (OSError, ValueError):
        pass
    return 4.0


def _env_int(name: str) -> int | None:
    v = os.environ.get(name)
    if v and v.strip().isdigit() and int(v) > 0:
        return int(v)
    return None


def media_concurrency() -> int:
    """Nombre de transcodes ffmpeg SIMULTANÉS.

    Borné par le CPU ET la RAM : un transcode 4K consomme plusieurs Go et veut beaucoup
    de cœurs. On en autorise ~1 par tranche de 4 cœurs et ~1 par tranche de 4 Go, en
    laissant toujours de quoi faire tourner l'API, la DB, MinIO et le sync players.
    Minimum 1 (la machine traite au moins une vidéo à la fois, jamais zéro).
    """
    if (override := _env_int("MEDIA_CONCURRENCY")) is not None:
        return override
    # Encode MATÉRIEL (NVENC/QSV/VAAPI) : l'encodage part sur le GPU → plus CPU-bound. On se
    # cale alors sur les sessions GPU (NVENC grand public ≈ 3-8) et on LIBÈRE des cœurs CPU
    # (decode/filtres seulement). Sinon (logiciel) : borné par CPU ET RAM.
    try:
        from app.core import encoders  # import local (évite tout cycle au chargement)
        if encoders.hw_encode_available():
            return _env_int("HWENC_CONCURRENCY") or min(4, max(2, cpu_count() // 2))
    except Exception:  # noqa: BLE001 — la détection ne doit jamais bloquer le dimensionnement
        pass
    by_cpu = cpu_count() // 4
    by_ram = int(_total_ram_gb() // 4)
    return max(1, min(by_cpu, by_ram))


def ffmpeg_threads() -> int:
    """Plafond de threads PAR transcode = part équitable des cœurs sur la concurrence
    média, en réservant ≥1 cœur pour le reste du système. Garantit que
    `media_concurrency × ffmpeg_threads` ne sature pas tous les cœurs.
    """
    if (override := _env_int("FFMPEG_THREADS")) is not None:
        return override
    return max(1, (cpu_count() - 1) // media_concurrency())


def light_concurrency() -> int:
    """Concurrence du worker « léger » (events, notifications, analytics) : tâches courtes
    et peu coûteuses → un petit pool suffit, indépendamment de la taille de la machine.
    """
    if (override := _env_int("LIGHT_CONCURRENCY")) is not None:
        return override
    return max(2, min(cpu_count(), 6))
