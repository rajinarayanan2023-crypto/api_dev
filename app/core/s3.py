import logging
import re
import uuid

import boto3
from botocore.client import Config

from app.core.config import get_settings
from app.core.exceptions import AppError

logger = logging.getLogger("app.s3")
settings = get_settings()

_UPLOAD_URL_EXPIRE_SECONDS = 5 * 60
_DOWNLOAD_URL_EXPIRE_SECONDS = 60 * 60

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9_.-]+")

_client = None


def _get_client():
    global _client
    if _client is None:
        if not (settings.r2_account_id and settings.r2_access_key_id and settings.r2_secret_access_key and settings.r2_bucket_name):
            raise AppError(
                "File storage is not configured — set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY, and R2_BUCKET_NAME to use uploads."
            )
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            # R2 is S3-API-compatible (same boto3 S3 client, same SigV4
            # presigned URLs) — "auto" is R2's own region value, not a real
            # AWS region, and is what R2's endpoint expects here.
            region_name="auto",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            config=Config(signature_version="s3v4"),
        )
    return _client


def build_key(category: str, filename: str) -> str:
    """A raw client-supplied filename is never trusted as a storage key
    directly — collapsed to safe characters and prefixed with a random id,
    so two uploads named "bill.jpg" in the same category can never collide
    or silently overwrite one another.
    """
    safe_name = _SAFE_FILENAME.sub("_", filename).strip("_.") or "file"
    return f"{category}/{uuid.uuid4()}_{safe_name}"


def get_upload_presigned_url(key: str, content_type: str) -> str:
    client = _get_client()
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": key, "ContentType": content_type},
        ExpiresIn=_UPLOAD_URL_EXPIRE_SECONDS,
    )


def get_download_presigned_url(key: str) -> str:
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": key},
        ExpiresIn=_DOWNLOAD_URL_EXPIRE_SECONDS,
    )


def delete_object(key: str) -> None:
    """Best-effort by design: called for a bill the user genuinely removed,
    or when cleaning up every bill on a fuel entry / credit customer that's
    itself being deleted. A transient R2 failure here is logged rather than
    raised — the database change it accompanies is either already committed
    or about to be, and failing the whole request over a storage-cleanup
    hiccup would be worse than leaving one orphaned object in the bucket.
    """
    try:
        client = _get_client()
        logger.info("R2 delete_object key=%s", key)
        client.delete_object(Bucket=settings.r2_bucket_name, Key=key)
    except Exception:
        logger.exception("Failed to delete R2 object key=%s", key)
