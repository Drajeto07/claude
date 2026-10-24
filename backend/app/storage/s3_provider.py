import asyncio
import logging
from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.storage.base import AssetNotFoundError, StorageProvider

logger = logging.getLogger(__name__)


def _missing(exc: ClientError) -> bool:
    """Whether a GetObject error means the object isn't there. AWS says NoSuchKey; an S3-compatible store may answer a
    missing key with HTTP 404 and an error body botocore can't read a code from (B-036: on the Preview, Supabase's
    answer came out with an empty code). A missing bucket is not a missing object: that stays an error, as do access
    denied (403), a bad request (400) and anything transient (5xx)."""
    error = exc.response.get("Error", {})
    code = error.get("Code")
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if code in ("NoSuchKey", "404"):
        return True
    return status == 404 and code != "NoSuchBucket"


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
            config=Config(
                # Custom endpoints (Supabase, MinIO, R2) require path-style URLs.
                s3={"addressing_style": "path" if endpoint_url else "auto"},
                # A checksum only where S3 requires one: boto3 adds CRC32 to every upload by
                # default, which S3-compatible stores don't all take (Supabase Storage lists no
                # checksum headers for PutObject).
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    async def check(self) -> None:
        # HeadBucket: the endpoint, the region, the keys and the bucket in one call, writing nothing.
        await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object, Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(self._client.get_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _missing(exc):
                raise AssetNotFoundError(key) from exc
            # What the store answered, never the key or the file: enough to tell a misread answer from a real failure.
            logger.warning(
                "S3 GetObject failed: HTTP %s, code %r",
                exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode"),
                exc.response.get("Error", {}).get("Code"),
            )
            raise
        return await asyncio.to_thread(response["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def list(self, prefix: str) -> list[tuple[str, datetime]]:
        def pages() -> list[tuple[str, datetime]]:
            found = []
            for page in self._client.get_paginator("list_objects_v2").paginate(Bucket=self._bucket, Prefix=prefix):
                found += [(item["Key"], item["LastModified"]) for item in page.get("Contents", [])]
            return found

        return await asyncio.to_thread(pages)
