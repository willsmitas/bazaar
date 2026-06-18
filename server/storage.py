"""
storage.py — Image upload abstraction for Bazaar.

Switch backends by changing STORAGE_BACKEND in your .env (or hosting dashboard):
  local  →  saves to uploads/ on disk, served at /uploads/<filename>
  s3     →  uploads to an S3-compatible bucket
"""
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from config import settings

_UPLOAD_DIR   = Path("uploads")
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

_UPLOAD_DIR.mkdir(exist_ok=True)


async def save_image(file: UploadFile) -> str:
    """Upload an image and return its public URL."""
    _validate(file)
    if settings.storage_backend == "local":
        return await _save_local(file)
    if settings.storage_backend == "s3":
        return await _save_s3(file)
    raise ValueError(f"Unknown storage backend: {settings.storage_backend!r}")


def _validate(file: UploadFile) -> None:
    # Client-facing validation → 400, not a 500 from an uncaught ValueError.
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type or 'unknown'}. "
                   f"Allowed: {', '.join(sorted(_ALLOWED_TYPES))}",
        )


async def _save_local(file: UploadFile) -> str:
    ext      = Path(file.filename or "upload").suffix or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    dest     = _UPLOAD_DIR / filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return f"{settings.local_base_url}/uploads/{filename}"


async def _save_s3(file: UploadFile) -> str:
    if not settings.s3_bucket_name:
        raise RuntimeError("S3_BUCKET_NAME is not set")
    # import boto3
    # s3 = boto3.client(
    #     "s3",
    #     region_name=settings.s3_region,
    #     aws_access_key_id=settings.aws_access_key_id,
    #     aws_secret_access_key=settings.aws_secret_access_key,
    # )
    # ext      = Path(file.filename or "upload").suffix or ".jpg"
    # filename = f"{uuid.uuid4().hex}{ext}"
    # s3.upload_fileobj(file.file, settings.s3_bucket_name, filename,
    #                   ExtraArgs={"ContentType": file.content_type})
    # return f"https://{settings.s3_bucket_name}.s3.{settings.s3_region}.amazonaws.com/{filename}"
    raise NotImplementedError("Uncomment the boto3 block above to enable S3")
