"""B-036: a missing object on an S3-compatible store is "not found", whatever error body the store sends.

On the Preview (Supabase Storage's S3 endpoint) every project thumbnail answered 404: drawing one starts by reading its
revision marker, which for a thumbnail never drawn doesn't exist, and Supabase's answer reached the app as a ClientError
with an EMPTY code ("An error occurred () when calling the GetObject operation: ", runtime log 2026-10-23) -- not
NoSuchKey, so S3StorageProvider didn't say AssetNotFoundError and the thumbnail was never drawn. botocore gives exactly
that empty code for an XML error body whose root isn't <Error>. Here every answer goes through botocore's own parser
(a raw HTTP response handed to the client), and a 404 is "not found" however its body reads -- while a missing bucket,
access denied, a bad request and transient failures stay errors. The HTTP status Supabase used is not known from the
log; if it isn't 404 this doesn't change the Preview, and the warning logged now says what it was.
"""

import asyncio
import logging

import boto3
import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from moto import mock_aws

from app.main import app
from app.storage.base import AssetNotFoundError
from app.storage.factory import get_storage_provider
from app.storage.s3_provider import S3StorageProvider

NOT_FOUND_BODIES = {
    "aws": b'<?xml version="1.0" encoding="UTF-8"?><Error><Code>NoSuchKey</Code><Message>The specified key does not exist.</Message></Error>',
    "empty-body": b"",
    "json-body": b'{"statusCode":"404","error":"not_found","message":"Object not found"}',
    "xml-without-code": b'<?xml version="1.0"?><Error><Message>Object not found</Message></Error>',
    "xml-other-root": b'<?xml version="1.0"?><NotFound><message>Object not found</message></NotFound>',  # -> empty code
}


class _Raw:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def stream(self, **_):
        yield self._body


def _answering(provider: S3StorageProvider, status: int, body: bytes) -> None:
    """Every GetObject of this client gets this raw HTTP answer, parsed by botocore as any real one is."""

    def send(request, **_):
        return AWSResponse(request.url, status, {"Content-Type": "application/xml"}, _Raw(body))

    provider._client.meta.events.register("before-send.s3.GetObject", send)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="assets")
        yield S3StorageProvider("assets", region="us-east-1", access_key_id="testing", secret_access_key="testing")


@pytest.mark.parametrize("body", NOT_FOUND_BODIES.values(), ids=NOT_FOUND_BODIES.keys())
def test_a_404_is_not_found_whatever_its_body_says(provider, body):
    _answering(provider, 404, body)
    with pytest.raises(AssetNotFoundError):
        asyncio.run(provider.get("thumbnails/x.rev"))


def test_the_empty_code_seen_on_the_preview_is_what_botocore_makes_of_such_a_body(provider):
    _answering(provider, 404, NOT_FOUND_BODIES["xml-other-root"])
    with pytest.raises(AssetNotFoundError) as caught:
        asyncio.run(provider.get("thumbnails/x.rev"))
    cause = caught.value.__cause__
    assert isinstance(cause, ClientError) and cause.response["Error"]["Code"] == ""
    assert str(cause) == "An error occurred () when calling the GetObject operation: "  # the Preview's log line, word for word


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (404, b'<?xml version="1.0"?><Error><Code>NoSuchBucket</Code><Message>The specified bucket does not exist</Message></Error>', "NoSuchBucket"),
        (403, b'<?xml version="1.0"?><Error><Code>AccessDenied</Code><Message>Access Denied</Message></Error>', "AccessDenied"),
        (403, b'<?xml version="1.0"?><Error><Code>SignatureDoesNotMatch</Code><Message>x</Message></Error>', "SignatureDoesNotMatch"),
        (403, b'<?xml version="1.0"?><Error><Code>InvalidAccessKeyId</Code><Message>x</Message></Error>', "InvalidAccessKeyId"),
        (403, b'<?xml version="1.0"?><NotFound><message>x</message></NotFound>', ""),
        (400, b'<?xml version="1.0"?><NotFound><message>x</message></NotFound>', ""),
        (400, b"", "400"),
        (500, b'<?xml version="1.0"?><Error><Code>InternalError</Code><Message>We encountered an internal error.</Message></Error>', "InternalError"),
        (503, b'<?xml version="1.0"?><Error><Code>SlowDown</Code><Message>Reduce your request rate.</Message></Error>', "SlowDown"),
    ],
    ids=["no-bucket", "access-denied", "bad-signature", "bad-key", "403-empty-code", "400-empty-code", "400-no-body", "500", "503-slow-down"],
)
def test_anything_but_a_missing_object_stays_an_error_and_is_logged_without_the_key(provider, caplog, status, body, code):
    _answering(provider, status, body)
    with caplog.at_level(logging.WARNING, logger="app.storage.s3_provider"):
        with pytest.raises(ClientError) as caught:
            asyncio.run(provider.get("workspace-1/secret-asset-id"))
    assert caught.value.response["Error"]["Code"] == code
    assert f"HTTP {status}, code {code!r}" in caplog.text
    assert "secret-asset-id" not in caplog.text and "testing" not in caplog.text


def test_a_network_failure_is_never_taken_for_a_missing_object(provider):
    from botocore.exceptions import EndpointConnectionError

    def unreachable(request, **_):
        raise EndpointConnectionError(endpoint_url=request.url)

    provider._client.meta.events.register("before-send.s3.GetObject", unreachable)
    with pytest.raises(EndpointConnectionError):
        asyncio.run(provider.get("workspace-1/a"))


def test_an_object_that_is_there_still_comes_back(provider):
    asyncio.run(provider.put("workspace-1/a", b"bytes", "image/png"))
    assert asyncio.run(provider.get("workspace-1/a")) == b"bytes"


# -- The thumbnail itself, on a store that answers a missing key as the Preview's did ----------------------------


def test_a_thumbnail_is_drawn_on_a_store_answering_a_missing_key_with_an_unreadable_404(api_db, provider):
    real_get_object = provider._client.get_object

    def supabase_like(**kwargs):
        try:
            return real_get_object(**kwargs)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "NoSuchKey":
                raise
            raise ClientError({"Error": {"Code": "", "Message": ""}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject") from None

    provider._client.get_object = supabase_like
    app.dependency_overrides[get_storage_provider] = lambda: provider
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/register", json={"email": "thumbs@example.com", "password": "long enough password"}).status_code == 201
    document = client.post("/api/v1/documents", json={"text": "# Report\n\nA paragraph long enough to be one."}).json()

    first = client.get(f"/api/v1/documents/{document['id']}/thumbnail")
    assert first.status_code == 200 and first.content.startswith(b"\x89PNG")
    again = client.get(f"/api/v1/documents/{document['id']}/thumbnail")  # kept: served from the store, not drawn again
    assert again.content == first.content
