from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.storage.base import StorageProvider
from app.storage.local_provider import LocalStorageProvider
from app.storage.s3_provider import S3StorageProvider


@lru_cache
def get_storage_provider() -> StorageProvider:
    settings = get_settings()
    if settings.storage_backend == "local":
        return LocalStorageProvider(Path(settings.local_storage_dir))
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise ValueError("STORAGE_BACKEND=s3 requires S3_BUCKET")
        return S3StorageProvider(
            settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
        )
    raise ValueError(f"Unknown STORAGE_BACKEND: {settings.storage_backend}")
