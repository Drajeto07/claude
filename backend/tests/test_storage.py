import boto3
import pytest
from moto import mock_aws

from app.config import Settings
from app.storage import factory as factory_module
from app.storage.base import AssetNotFoundError
from app.storage.factory import get_storage_provider
from app.storage.local_provider import LocalStorageProvider
from app.storage.s3_provider import S3StorageProvider

# Not valid UTF-8: proves no provider decodes or re-encodes the bytes.
_BINARY = b"\x89PNG\r\n\x1a\n" + bytes(range(256))


async def test_local_round_trips_binary_data(tmp_path):
    provider = LocalStorageProvider(tmp_path)
    await provider.put("ws/asset", _BINARY, "image/png")
    assert await provider.get("ws/asset") == _BINARY


async def test_local_put_overwrites_and_leaves_no_temp_file(tmp_path):
    provider = LocalStorageProvider(tmp_path)
    await provider.put("ws/asset", b"old", "text/plain")
    await provider.put("ws/asset", b"new", "text/plain")
    assert await provider.get("ws/asset") == b"new"
    assert [p.name for p in (tmp_path / "ws").iterdir()] == ["asset"]


async def test_local_get_missing_raises_asset_not_found(tmp_path):
    with pytest.raises(AssetNotFoundError):
        await LocalStorageProvider(tmp_path).get("ws/missing")


async def test_local_delete_is_idempotent(tmp_path):
    provider = LocalStorageProvider(tmp_path)
    await provider.put("ws/asset", b"x", "text/plain")
    await provider.delete("ws/asset")
    await provider.delete("ws/asset")
    with pytest.raises(AssetNotFoundError):
        await provider.get("ws/asset")


@pytest.mark.parametrize("key", ["../escape", "ws/../../escape", ""])
async def test_local_rejects_keys_outside_the_root(tmp_path, key):
    with pytest.raises(ValueError):
        await LocalStorageProvider(tmp_path / "root").put(key, b"x", "text/plain")


async def test_local_rejects_absolute_key(tmp_path):
    with pytest.raises(ValueError):
        await LocalStorageProvider(tmp_path / "root").put(str(tmp_path / "elsewhere"), b"x", "text/plain")


@pytest.fixture
def s3_bucket(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="assets")
        yield "assets"


def _s3(bucket: str) -> S3StorageProvider:
    return S3StorageProvider(bucket, region="us-east-1", access_key_id="testing", secret_access_key="testing")


async def test_s3_round_trips_binary_data_and_content_type(s3_bucket):
    await _s3(s3_bucket).put("ws/asset", _BINARY, "image/png")

    assert await _s3(s3_bucket).get("ws/asset") == _BINARY
    head = boto3.client("s3", region_name="us-east-1").head_object(Bucket=s3_bucket, Key="ws/asset")
    assert head["ContentType"] == "image/png"


async def test_s3_get_missing_raises_asset_not_found(s3_bucket):
    with pytest.raises(AssetNotFoundError):
        await _s3(s3_bucket).get("ws/missing")


async def test_s3_delete_is_idempotent(s3_bucket):
    provider = _s3(s3_bucket)
    await provider.put("ws/asset", b"x", "text/plain")
    await provider.delete("ws/asset")
    await provider.delete("ws/asset")
    with pytest.raises(AssetNotFoundError):
        await provider.get("ws/asset")


def test_s3_custom_endpoint_uses_path_style_addressing():
    # Supabase Storage's S3 endpoint (like MinIO/R2) rejects virtual-hosted-style URLs.
    provider = S3StorageProvider(
        "assets",
        endpoint_url="https://ref.storage.supabase.co/storage/v1/s3",
        region="eu-central-1",
        access_key_id="k",
        secret_access_key="s",
    )
    assert provider._client.meta.config.s3["addressing_style"] == "path"


@pytest.fixture
def storage_settings(monkeypatch):
    def use(**overrides):
        monkeypatch.setattr(factory_module, "get_settings", lambda: Settings(**overrides))
        get_storage_provider.cache_clear()

    yield use
    get_storage_provider.cache_clear()


def test_factory_defaults_to_local(storage_settings, tmp_path):
    storage_settings(local_storage_dir=str(tmp_path))
    assert isinstance(get_storage_provider(), LocalStorageProvider)


def test_factory_builds_s3_when_configured(storage_settings):
    storage_settings(
        storage_backend="s3", s3_bucket="assets", s3_region="eu-central-1", s3_access_key_id="k", s3_secret_access_key="s"
    )
    assert isinstance(get_storage_provider(), S3StorageProvider)


def test_factory_s3_without_bucket_fails_fast(storage_settings):
    storage_settings(storage_backend="s3", s3_bucket="")
    with pytest.raises(ValueError, match="S3_BUCKET"):
        get_storage_provider()


def test_factory_rejects_unknown_backend(storage_settings):
    storage_settings(storage_backend="ftp")
    with pytest.raises(ValueError, match="STORAGE_BACKEND"):
        get_storage_provider()
