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


@pytest.mark.parametrize("key", ["../escape", "ws/../../escape", "", "ws//double", "ws/./dot", r"ws\..\..\escape", "C:escape", "/rooted"])
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


async def test_local_root_is_created_before_it_is_resolved(tmp_path):
    # A provider made before anything was written must agree with one made after: Windows
    # resolves a missing folder differently (8.3 names), which once refused valid keys.
    root = tmp_path / "not-yet" / "assets"
    early = LocalStorageProvider(root)
    assert root.is_dir()
    late = LocalStorageProvider(root)

    await early.put("thumbnails/doc.png", b"png", "image/png")
    assert await late.get("thumbnails/doc.png") == b"png"


async def test_local_keys_with_folders_land_inside_the_root(tmp_path):
    provider = LocalStorageProvider(tmp_path / "root")
    await provider.put("thumbnails/doc-1.png", b"png", "image/png")
    assert (tmp_path / "root" / "thumbnails" / "doc-1.png").read_bytes() == b"png"


async def test_local_many_writes_in_one_new_folder_at_once(tmp_path):
    # Thumbnails drawn side by side on a fresh server: every key is accepted.
    import asyncio

    provider = LocalStorageProvider(tmp_path / "root")
    await asyncio.gather(*(provider.put(f"thumbnails/doc-{n}.png", b"png", "image/png") for n in range(12)))
    assert len(list((tmp_path / "root" / "thumbnails").glob("*.png"))) == 12


# -- Listing keys under a prefix (B-035A: sweeping abandoned uploads) --------------------------------------------


async def test_local_lists_the_keys_under_a_prefix_with_when_they_were_written(tmp_path):
    provider = LocalStorageProvider(tmp_path / "root")
    for key in ("uploads/w1/a/session.json", "uploads/w1/a/part-00000", "uploads/w2/b/session.json", "jobs/x/input"):
        await provider.put(key, b"x", "application/octet-stream")
    listed = await provider.list("uploads/w1/")
    assert sorted(key for key, _ in listed) == ["uploads/w1/a/part-00000", "uploads/w1/a/session.json"]
    assert all(written.tzinfo is not None for _, written in listed)
    assert sorted(key for key, _ in await provider.list("uploads/")) == ["uploads/w1/a/part-00000", "uploads/w1/a/session.json", "uploads/w2/b/session.json"]


async def test_s3_lists_the_keys_under_a_prefix_across_pages(s3_bucket):
    provider = _s3(s3_bucket)
    keys = [f"uploads/w1/a/part-{index:05d}" for index in range(1005)]  # more than one page of 1000
    for key in keys:
        await provider.put(key, b"x", "application/octet-stream")
    await provider.put("jobs/x/input", b"x", "application/octet-stream")
    listed = await provider.list("uploads/")
    assert sorted(key for key, _ in listed) == keys
    assert all(written.tzinfo is not None for _, written in listed)
