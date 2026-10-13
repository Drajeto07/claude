"""File storage for the first release (RELEASE, REL-005): what reaches Supabase Storage's S3
endpoint, and how /api/ready tells whether files are kept anywhere that lasts."""

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

import app.main as main_module
from app.config import get_settings
from app.main import app
from app.storage.s3_provider import S3StorageProvider

client = TestClient(app)


def _supabase_like() -> S3StorageProvider:
    return S3StorageProvider(
        "smartdoc-files",
        endpoint_url="https://ref.storage.supabase.co/storage/v1/s3",
        region="eu-central-1",
        access_key_id="k",
        secret_access_key="s",
    )


class _Sent(Exception):
    """Stops a request once its headers are seen: nothing leaves the machine."""


def test_an_upload_carries_no_checksum_headers_supabase_doesnt_list():
    provider = _supabase_like()
    seen: dict[str, str] = {}

    def capture(request, **_):
        seen.update({name.lower(): value.decode() if isinstance(value, bytes) else value for name, value in request.headers.items()})
        raise _Sent

    provider._client.meta.events.register("before-send.s3.PutObject", capture)
    with pytest.raises(_Sent):
        provider._client.put_object(Bucket="smartdoc-files", Key="ws/a", Body=b"picture bytes", ContentType="image/png")

    assert seen["content-type"] == "image/png"
    assert not [name for name in seen if name.startswith("x-amz-checksum") or name == "x-amz-sdk-checksum-algorithm"]
    assert "content-md5" not in seen
    assert provider._client.meta.config.request_checksum_calculation == "when_required"
    assert provider._client.meta.config.response_checksum_validation == "when_required"


async def test_the_check_reaches_the_bucket_and_writes_nothing(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="assets")
        provider = S3StorageProvider("assets", region="us-east-1", access_key_id="testing", secret_access_key="testing")

        await provider.check()
        assert s3.list_objects_v2(Bucket="assets").get("KeyCount") == 0

        with pytest.raises(Exception):
            await S3StorageProvider("no-such-bucket", region="us-east-1", access_key_id="testing", secret_access_key="testing").check()


class _Store:
    def __init__(self, fails: bool) -> None:
        self.fails = fails

    async def check(self) -> None:
        if self.fails:
            raise ConnectionError("the store is away")


def test_ready_says_the_file_store_answers(api_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_backend", "s3")
    monkeypatch.setattr(main_module, "get_storage_provider", lambda: _Store(fails=False))

    response = client.get("/api/ready")

    assert (response.status_code, response.json()) == (200, {"status": "ready", "checks": {"database": "ok", "storage": "ok"}})


def test_not_ready_while_the_file_store_is_away(api_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_backend", "s3")
    monkeypatch.setattr(main_module, "get_storage_provider", lambda: _Store(fails=True))

    response = client.get("/api/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "storage": "unavailable"}


def test_not_ready_on_vercel_with_files_on_the_instances_own_disk(api_db, monkeypatch):
    # As production ran at first (2026-10-13): STORAGE_BACKEND unset, so pictures and exports
    # were written inside the container and lost when it stopped.
    monkeypatch.setattr(get_settings(), "storage_backend", "local")
    monkeypatch.setenv("VERCEL", "1")

    response = client.get("/api/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "ok", "storage": "ephemeral"}}


def test_local_files_off_vercel_are_nothing_to_check(api_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_backend", "local")
    monkeypatch.delenv("VERCEL", raising=False)

    assert client.get("/api/ready").json() == {"status": "ready", "checks": {"database": "ok"}}
