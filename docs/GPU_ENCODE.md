# GPU hardware encoding (NVENC / Intel VAAPI-QSV)

🇫🇷 [Version française](GPU_ENCODE.fr.md)

The `celery-media` worker automatically detects the available hardware encoders
(`app/core/encoders.py`) and uses them for ffmpeg: **NVENC** (Nvidia) > **QSV/VAAPI**
(Intel) > **libx264/libx265** (software fallback). Detection uses a real test encode → if the GPU
is not accessible to the container, there is a transparent software fallback (zero regression).

Preference/quality: `-cq 21` (NVENC) / `-global_quality 21` (QSV) / `-qp 22` (VAAPI) ≈
software `-crf 20`. HDR → always libx265 10-bit (software). If a HW encode fails → automatic
fallback to libx264 (the worker retries once in software).

## Prerequisite — GPU access for the container (per host, not committed)

The base `docker-compose.yml` stays **portable** (no GPU imposed). GPU access is configured in
**`docker-compose.override.yml`** (gitignored, specific to each machine).

### 1. NVIDIA (NVENC) — tested on an RTX 5050 and an RTX 4060

Install the container toolkit **on the host** (once):

```bash
# Dépôt nvidia-container-toolkit (cf. doc officielle NVIDIA pour la clé/repo à jour)
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
# Vérif : doit lister le GPU
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

(Set up the nvidia-container-toolkit repository first — see the official NVIDIA documentation for
the current key/repo. The last command must list the GPU.)

Block to add to `docker-compose.override.yml`:

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

### 2. Intel iGPU (VAAPI/QSV) — tested on an Intel Core Ultra

No toolkit: the DRM node is passed through. The iHD driver is in the image (Dockerfile).

```yaml
services:
  celery-media:
    devices:
      - "/dev/dri:/dev/dri"
    group_add:
      - "render"        # accès au groupe render (sinon /dev/dri/renderD* non utilisable)
```

(The `render` group is required; otherwise `/dev/dri/renderD*` cannot be used.)

> Both blocks can coexist (NVENC takes priority; VAAPI as a fallback). On a machine without a
> GPU, add nothing → automatic software fallback.

## Deployment

```bash
cd /opt/signflow
git pull
docker compose build celery-media        # rebuild (libs Intel + code)
docker compose up -d celery-media        # recrée avec l'override GPU
```

(Rebuild the image for the Intel libraries and code, then recreate the container so it picks up
the GPU override.)

## Verification

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

In short: the first command lists the detected encoders (real test encode). After uploading a
video, the log shows `Video transcode: encoder=h264_nvenc ...`, and `nvidia-smi` shows the ffmpeg
process during the encode. For debugging, set these in the `celery-media` service environment:
`SF_VIDEO_ENCODER` forces an encoder, `SF_DISABLE_HWENC=1` forces the software fallback,
`HWENC_CONCURRENCY` sets the number of parallel GPU sessions (default `min(4, cores/2)`).

## Concurrency

With a hardware encoder active, encoding runs on the GPU (no longer CPU-bound):
`media_concurrency()` then aligns with the **GPU sessions** (`min(4, cores/2)`, override with
`HWENC_CONCURRENCY`) and **frees CPU cores**. Without a GPU: bounded by CPU+RAM as before
(see `app/core/resources.py`).
