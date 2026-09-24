import asyncio

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.storage.base import AssetNotFoundError, StorageProvider


class S3StorageProvider(StorageProvider):
    """Any S3-compatible service: AWS S3, Cloudflare R2, MinIO, or Supabase
    Storage's S3 endpoint. boto3 is synchronous, so every call runs in a worker
    thread rather than blocking the event loop."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
            # Custom endpoints (Supabase, MinIO, R2) require path-style URLs.
            config=Config(s3={"addressing_style": "path" if endpoint_url else "auto"}),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object, Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(self._client.get_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise AssetNotFoundError(key) from exc
            raise
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
