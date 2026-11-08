"""Crée le bucket MinIO signflow-media s'il n'existe pas déjà."""
import os

import boto3
from botocore.config import Config

endpoint = os.environ.get("MINIO_ENDPOINT", "minio:9000")
access_key = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
secret_key = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
bucket = os.environ.get("MINIO_BUCKET_MEDIA", "signflow-media")
use_ssl = os.environ.get("MINIO_USE_SSL", "false").lower() == "true"

s3 = boto3.client(
    "s3",
    endpoint_url=f"{'https' if use_ssl else 'http'}://{endpoint}",
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)

try:
    s3.create_bucket(Bucket=bucket)
    print(f"Bucket '{bucket}' créé avec succès")
except Exception as exc:
    msg = str(exc)
    if "BucketAlreadyOwnedByYou" in msg or "BucketAlreadyExists" in msg:
        print(f"Bucket '{bucket}' existe déjà — OK")
    else:
        raise
