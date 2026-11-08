"""Service MinIO/S3 pour la Media Library (§XVI.2)."""

import hashlib
import re
import uuid
from functools import partial
from typing import IO

import anyio
import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

from app.core.config import settings

_MULTIPART_THRESHOLD = 8 * 1024 * 1024   # 8 MB
_TRANSFER_CONFIG = TransferConfig(multipart_threshold=_MULTIPART_THRESHOLD, multipart_chunksize=_MULTIPART_THRESHOLD)


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if settings.MINIO_USE_SSL else 'http'}://{settings.MINIO_ENDPOINT}",
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _s3_public():
    """Client S3 utilisant l'endpoint public (browser-accessible) pour les URLs pré-signées."""
    public = settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT
    # Scheme public découplé de l'interne : permet des URLs https (MinIO derrière proxy TLS)
    # tout en gardant le client interne en http vers le conteneur minio:9000.
    public_ssl = settings.MINIO_PUBLIC_USE_SSL or settings.MINIO_USE_SSL
    return boto3.client(
        "s3",
        endpoint_url=f"{'https' if public_ssl else 'http'}://{public}",
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def make_storage_key(id_org: int, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"{id_org}/{uuid.uuid4().hex}.{ext}"


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stream_upload_sync(file_obj: IO[bytes], storage_key: str, content_type: str) -> tuple[str, int]:
    """Upload en streaming vers MinIO avec calcul SHA-256 à la volée (pas de chargement en RAM).

    boto3.upload_fileobj utilise le multipart S3 automatiquement au-delà de 8 MB.
    """
    hasher = hashlib.sha256()
    total = [0]

    class _HashingReader:
        def read(self, n: int = -1) -> bytes:
            chunk = file_obj.read(n)
            if chunk:
                hasher.update(chunk)
                total[0] += len(chunk)
            return chunk

    extra_args: dict = {"ContentType": content_type}
    if settings.MINIO_SSE_ENABLED:
        extra_args["ServerSideEncryption"] = "AES256"

    _s3().upload_fileobj(
        _HashingReader(),
        settings.MINIO_BUCKET_MEDIA,
        storage_key,
        ExtraArgs=extra_args,
        Config=_TRANSFER_CONFIG,
    )
    return hasher.hexdigest(), total[0]


async def stream_upload(file_obj: IO[bytes], storage_key: str, content_type: str) -> tuple[str, int]:
    """Wrapper async du streaming upload. Retourne (sha256_hex, file_size_bytes)."""
    fn = partial(_stream_upload_sync, file_obj, storage_key, content_type)
    return await anyio.to_thread.run_sync(fn)


async def upload_file(content: bytes, storage_key: str, content_type: str) -> None:
    """Upload bytes vers MinIO — réservé aux petits fichiers (stock import, etc.)."""
    client = _s3()
    kwargs: dict = {
        "Bucket": settings.MINIO_BUCKET_MEDIA,
        "Key": storage_key,
        "Body": content,
        "ContentType": content_type,
    }
    if settings.MINIO_SSE_ENABLED:
        kwargs["ServerSideEncryption"] = "AES256"
    fn = partial(client.put_object, **kwargs)
    await anyio.to_thread.run_sync(fn)


def get_signed_url(storage_key: str, ttl: int = 3600, download_name: str | None = None) -> str:
    """Génère une URL pré-signée MinIO (TTL 1h par défaut) avec l'endpoint public.

    Si ``download_name`` est fourni, l'URL force le téléchargement (Content-Disposition
    ``attachment``) avec ce nom de fichier — sinon le navigateur affiche le média inline.
    """
    client = _s3_public()
    params: dict[str, str] = {"Bucket": settings.MINIO_BUCKET_MEDIA, "Key": storage_key}
    if download_name:
        # Nom assaini (pas de guillemet/saut de ligne qui casserait l'en-tête HTTP).
        safe = re.sub(r'[\r\n"]', "", download_name).strip() or "download"
        params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
    return client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=ttl,
    )


async def download_file(storage_key: str) -> bytes:
    """Télécharge un objet depuis MinIO et retourne les bytes."""
    client = _s3()
    fn = partial(client.get_object, Bucket=settings.MINIO_BUCKET_MEDIA, Key=storage_key)
    response = await anyio.to_thread.run_sync(fn)
    return response["Body"].read()


async def object_exists(storage_key: str) -> bool:
    """True si l'objet existe (head_object, sans télécharger le corps). 404/absent → False."""
    client = _s3()
    fn = partial(client.head_object, Bucket=settings.MINIO_BUCKET_MEDIA, Key=storage_key)
    try:
        await anyio.to_thread.run_sync(fn)
        return True
    except Exception:  # noqa: BLE001 — objet absent / stockage indispo
        return False


async def delete_file(storage_key: str) -> None:
    """Supprime un objet de MinIO."""
    client = _s3()
    fn = partial(
        client.delete_object,
        Bucket=settings.MINIO_BUCKET_MEDIA,
        Key=storage_key,
    )
    await anyio.to_thread.run_sync(fn)
