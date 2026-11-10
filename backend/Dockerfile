# Image backend SignFlow — multi-stage, une cible par profil de service.
#
# ⚠️ ORDRE DES STAGES : la dernière cible du fichier est celle que Docker construit
# quand aucun `target:` n'est précisé. `media` (la plus complète) est donc VOLONTAIREMENT
# en dernier, pour que les services du docker-compose qui ne précisent pas de cible
# gardent exactement le comportement actuel.
#
#   cible `backend` → backend, celery-beat        (aucun outil média)
#   cible `worker`  → celery-worker               (ffmpeg : generation_worker, file `default`)
#   cible `media`   → celery-media                (ffmpeg + LibreOffice/poppler : documents)
#
# Les cibles s'empilent (media ⊃ worker ⊃ backend) : le registre et le client ne
# stockent/transfèrent les couches communes qu'UNE fois.

# ── Stage 1 : dépendances Python ──────────────────────────────────────────────
# gcc et libpq-dev ne servent QU'ICI (compilation d'éventuelles roues sources).
# Ils sont jetés avec ce stage et n'atteignent aucune image finale.
# ⚠️ `.` et non `.[dev]` : pytest/ruff/mypy/moto n'ont rien à faire en production
# (taille + surface d'attaque). Les tests tournent en CI, pas dans l'image livrée.
FROM python:3.12-slim AS pydeps
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip
COPY pyproject.toml constraints.txt ./
RUN pip install --no-cache-dir -c constraints.txt -e .

# ── Stage 2 : socle runtime commun (sans aucun outil média) ───────────────────
FROM python:3.12-slim AS rt
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=pydeps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
# Derive WEB_CONCURRENCY des coeurs de la machine quand la commande est uvicorn (et
# seulement dans ce cas : celery-beat partage cette image et ne doit pas heriter d'un
# parallelisme web). Pose ici, dans le socle, pour valoir sur tous les etages.
# ⚠️ ENTRYPOINT et pas CMD : le CMD reste la ligne uvicorn, que la garde
# assert_no_reload de publish-images.sh inspecte pour refuser une image `--reload`.
COPY docker-entrypoint.sh /usr/local/bin/signflow-entrypoint
RUN chmod +x /usr/local/bin/signflow-entrypoint
ENTRYPOINT ["/usr/local/bin/signflow-entrypoint"]

# ── Stage 3 : socle + ffmpeg et encodage matériel Intel ───────────────────────
# NVENC (Nvidia) ne nécessite AUCUN paquet ici : ses libs sont injectées au runtime
# par nvidia-container-toolkit. Le pilote iHD (intel-media-va-driver) est en dépôt
# non-free → activé pour la version Debian de l'image (VERSION_CODENAME). Best-effort :
# si l'install Intel échoue, le build continue (NVENC + repli libx264 restent
# fonctionnels). Cf. docs/GPU_ENCODE.md.
FROM rt AS rt-av
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && (. /etc/os-release \
        && echo "deb http://deb.debian.org/debian ${VERSION_CODENAME} non-free non-free-firmware" \
           > /etc/apt/sources.list.d/nonfree.list \
        && apt-get update \
        && apt-get install -y --no-install-recommends \
             libva2 libva-drm2 vainfo intel-media-va-driver-non-free \
        || echo "WARN: pilotes Intel VAAPI non installes (NVENC/libx264 restent OK)") \
    && rm -rf /var/lib/apt/lists/*

# ── Stage 4 : socle A/V + conversion de documents ─────────────────────────────
# poppler-utils (pdftoppm : PDF → images par page) + libreoffice-impress (PPT/PPTX → PDF)
# + polices metric-compatible Microsoft (Carlito=Calibri, Caladea=Cambria,
# Liberation=Arial/Times) pour limiter les substitutions de mise en page dans les
# PowerPoint clients.
FROM rt-av AS rt-office
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
         poppler-utils libreoffice-impress \
         fonts-liberation fonts-dejavu-core fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*

# ── Cibles finales ────────────────────────────────────────────────────────────
# Le code est copié EN DERNIER dans chaque cible : une modification de code
# n'invalide aucune couche système.

# backend + celery-beat
FROM rt AS backend
WORKDIR /app
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# celery-worker (file `default` — generation_worker appelle ffmpeg)
FROM rt-av AS worker
WORKDIR /app
COPY . .
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info", "--queues=default,notifications,analytics"]

# celery-media (file `media` — transcodes + conversion de documents)
FROM rt-office AS media
WORKDIR /app
COPY . .
EXPOSE 8000
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info", "--queues=media"]

# celery-screenshot (file `cms_screenshot` — captures URL Display + rendus promo)
# Part de `rt` et NON de `rt-av` : Chromium suffit, ce worker ne touche pas à ffmpeg
# (promo_worker.animate_promo_video, la seule étape ffmpeg, est routée sur la file `media`).
# Anciennement un fichier séparé `Dockerfile.screenshot` : le fusionner ici fait PARTAGER
# le socle et la pile de dépendances Python avec les autres cibles — un client ne les
# télécharge donc plus qu'une seule fois au lieu de deux.
FROM rt AS screenshot
WORKDIR /app
# libatomic1 : le Node.js embarqué par Playwright (>= 1.65) en a besoin AVANT même que
# `--with-deps` installe quoi que ce soit, et python:3.12-slim ne l'a pas (issue #1).
# Version figée par constraints.txt, comme le reste de la pile.
COPY constraints.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -c constraints.txt playwright \
    && playwright install --with-deps chromium
COPY . .
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=info", "--queues=cms_screenshot", "--concurrency=2"]

# ── Cible de DÉVELOPPEMENT ────────────────────────────────────────────────────
# ⚠️ DERNIER STAGE = cible par défaut quand aucun `target:` n'est précisé (voir
# l'avertissement en tête de fichier). C'est VOLONTAIRE : les services du
# docker-compose n'en précisent aucun, ils continuent donc de recevoir une image
# identique à celle d'avant ce refactor — outils média complets ET dépendances de
# dev. C'est ce qui garde `make test` (docker compose exec backend pytest)
# fonctionnel. Les images DISTRIBUÉES, elles, sont construites avec un
# `--target backend|worker|media` explicite et n'embarquent aucune de ces deps.
FROM rt-office AS dev
WORKDIR /app
COPY pyproject.toml constraints.txt ./
RUN pip install --no-cache-dir -c constraints.txt -e ".[dev]"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
