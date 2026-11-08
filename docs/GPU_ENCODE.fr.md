# Encodage matériel GPU (NVENC / Intel VAAPI-QSV)

🇬🇧 [English version](GPU_ENCODE.md)

Le worker `celery-media` détecte automatiquement les encodeurs matériels disponibles
(`app/core/encoders.py`) et s'en sert pour ffmpeg : **NVENC** (Nvidia) > **QSV/VAAPI**
(Intel) > **libx264/libx265** (repli logiciel). Détection par test-encode réel → si le GPU
n'est pas accessible au conteneur, repli logiciel transparent (zéro régression).

Préférence/qualité : `-cq 21` (NVENC) / `-global_quality 21` (QSV) / `-qp 22` (VAAPI) ≈
`-crf 20` logiciel. HDR → toujours libx265 10-bit (logiciel). Échec d'un encode HW → repli
auto libx264 (le worker retente une fois en logiciel).

## Prérequis — accès GPU au conteneur (par hôte, non commité)

Le `docker-compose.yml` de base reste **portable** (aucun GPU imposé). L'accès GPU se
configure dans **`docker-compose.override.yml`** (gitignoré, propre à chaque machine).

### 1. NVIDIA (NVENC) — RTX 5050 prod, RTX 4060 local

Installer le toolkit conteneur **sur l'hôte** (une fois) :

```bash
# Dépôt nvidia-container-toolkit (cf. doc officielle NVIDIA pour la clé/repo à jour)
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
# Vérif : doit lister le GPU
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

Bloc à ajouter dans `docker-compose.override.yml` :

```yaml
services:
  celery-media:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu, video]   # 'video' = NVENC/NVDEC
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,video,utility
```

### 2. Intel iGPU (VAAPI/QSV) — Core Ultra prod

Pas de toolkit : on passe le nœud DRM. Le pilote iHD est dans l'image (Dockerfile).

```yaml
services:
  celery-media:
    devices:
      - "/dev/dri:/dev/dri"
    group_add:
      - "render"        # accès au groupe render (sinon /dev/dri/renderD* non utilisable)
```

> Les deux blocs peuvent coexister (NVENC prioritaire ; VAAPI en secours). Sur une machine
> sans GPU, ne rien ajouter → repli logiciel automatique.

## Déploiement

```bash
cd /opt/signflow
git pull
docker compose build celery-media        # rebuild (libs Intel + code)
docker compose up -d celery-media        # recrée avec l'override GPU
```

## Vérification

```bash
# Encodeurs détectés (test-encode réel) :
docker compose exec -T celery-media python -c \
  "from app.core.encoders import detect_hw_encoders, best_encoder; \
   print('HW:', detect_hw_encoders()); print('h264:', best_encoder('h264'))"

# Upload une vidéo → log : 'Video transcode: encoder=h264_nvenc ...'
docker compose logs celery-media | grep -E "encoder=|HW encode"
# GPU utilisé pendant l'encode :
nvidia-smi   # process ffmpeg visible

# Forcer un encodeur / désactiver le HW (debug), via env du service celery-media :
#   SF_VIDEO_ENCODER=h264_vaapi   (force)
#   SF_DISABLE_HWENC=1            (repli logiciel)
#   HWENC_CONCURRENCY=4          (sessions parallèles GPU ; défaut min(4, cœurs/2))
```

## Concurrence

Avec un encodeur matériel actif, l'encode part sur le GPU (plus CPU-bound) :
`media_concurrency()` se cale alors sur les **sessions GPU** (`min(4, cœurs/2)`, surcharge
`HWENC_CONCURRENCY`) et **libère des cœurs CPU**. Sans GPU : borné CPU+RAM comme avant
(cf. `app/core/resources.py`,).
