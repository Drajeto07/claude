"""Security hardening (корекции.docx §33, §76): what uploaded files really are,
the request-size cap, rate limits, response headers, CORS, and settings that
refuse to start unsafe."""

import base64
import io
import zipfile

import pytest
from docx import Document as DocxDocument
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.api.errors import install_error_handlers
from app.config import Settings, get_settings
from app.db.models import DocumentAsset
from app.main import app
from app.parsers import pdf as pdf_module
from app.parsers.pdf import PdfParseError, extract_pdf_text
from app.security import files as files_module
from app.security import rate_limit
from app.security.files import UnsafeFileError, check_docx, check_upload, image_matches, parse_xml_part
from app.security.http import RequestSizeLimit
from app.security.rate_limit import MemoryCounter, Rate, RedisCounter
from tests.helpers import error_body

client = TestClient(app, base_url="https://testserver")
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/auth/register", json={"email": "secure@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()


def _docx() -> bytes:
    doc = DocxDocument()
    doc.add_paragraph("A paragraph.")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _zip(entries: dict[str, bytes], *, compression=zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as package:
        for name, data in entries.items():
            package.writestr(name, data)
    return buffer.getvalue()


_CONTENT_TYPES = b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'


# -- what a file really is -------------------------------------------------------


def test_a_real_word_file_passes_and_its_real_type_is_named():
    assert check_upload("docx", _docx(), _DOCX) == _DOCX
    assert check_upload("docx", _docx(), "application/octet-stream") == _DOCX  # the browser didn't know
    assert check_upload("pdf", b"%PDF-1.7\n...", None) == "application/pdf"
    assert check_upload("txt", "Кирилица и текст".encode(), "text/plain") == "text/plain"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100, "old-format (.doc) or password-protected"),
        (b"<html><script>alert(1)</script></html>", "isn't a Word (.docx) file"),
        (_zip({"word/document.xml": b"<w/>"}), "isn't a Word (.docx) file"),  # no [Content_Types].xml
        (_zip({"[Content_Types].xml": _CONTENT_TYPES, "../../evil.xml": b"<x/>"}), "parts a Word document never has"),
        (_zip({"[Content_Types].xml": _CONTENT_TYPES, "/etc/evil.xml": b"<x/>"}), "parts a Word document never has"),
        (b"PK\x03\x04 but then nothing a zip file has", "damaged"),
    ],
)
def test_a_file_that_isnt_a_word_document_is_refused(data, message):
    with pytest.raises(UnsafeFileError) as refused:
        check_docx(data)
    assert message in str(refused.value)


def test_a_zip_bomb_is_refused_before_it_is_opened(monkeypatch):
    # 30 MB of one repeated byte packs into a few tens of KB: a ratio no Word file has.
    bomb = _zip({"[Content_Types].xml": _CONTENT_TYPES, "word/media/image1.png": b"\0" * (30 * 1024 * 1024)})
    assert len(bomb) < 100_000
    with pytest.raises(UnsafeFileError, match="unpacks to far more"):
        check_docx(bomb)

    monkeypatch.setattr(files_module, "MAX_ZIP_ENTRIES", 3)
    many = _zip({"[Content_Types].xml": _CONTENT_TYPES, **{f"word/part{index}.xml": b"<x/>" for index in range(5)}})
    with pytest.raises(UnsafeFileError, match="too many parts"):
        check_docx(many)

    monkeypatch.setattr(files_module, "MAX_XML_PART_BYTES", 1000)
    big_xml = _zip({"[Content_Types].xml": _CONTENT_TYPES, "word/document.xml": b"<w>" + b"<p>text</p>" * 500 + b"</w>"})
    with pytest.raises(UnsafeFileError, match="unpacks to far more"):
        check_docx(big_xml)


def test_the_declared_type_has_to_fit_the_extension():
    with pytest.raises(UnsafeFileError, match="text/html"):
        check_upload("docx", _docx(), "text/html; charset=utf-8")
    with pytest.raises(UnsafeFileError, match="isn't a PDF"):
        check_upload("pdf", b"GIF89a not a pdf", "application/pdf")


def test_text_files_have_to_be_text():
    with pytest.raises(UnsafeFileError, match="text file"):
        check_upload("txt", b"MZ\x90\x00\x03\x00\x00\x00 an executable", "text/plain")
    assert check_upload("txt", "﻿UTF-16 text".encode("utf-16"), "text/plain") == "text/plain"


def test_an_image_has_to_be_what_its_type_says():
    assert image_matches("image/png", _PNG)
    assert not image_matches("image/jpeg", _PNG)
    assert not image_matches("image/png", b"<svg onload=alert(1)>")
    assert image_matches("image/webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    assert not image_matches("image/svg+xml", b"<svg/>")


def test_raw_xml_parts_resolve_no_entities():
    xxe = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'
    assert "root:" not in "".join(parse_xml_part(xxe).itertext())
    laughs = (
        b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><l>&c;</l>'
    )
    assert len("".join(parse_xml_part(laughs).itertext())) < 10  # left unexpanded, not 1,000 characters


def test_a_pdf_past_the_page_limit_is_refused(monkeypatch):
    buffer = io.BytesIO()
    pages = canvas.Canvas(buffer)
    for number in range(3):
        pages.drawString(72, 720, f"Page {number + 1} text")
        pages.showPage()
    pages.save()
    monkeypatch.setattr(pdf_module, "MAX_PDF_PAGES", 2)

    with pytest.raises(PdfParseError, match="more than 2 pages"):
        extract_pdf_text(buffer.getvalue())
    with pytest.raises(PdfParseError, match="isn't a valid PDF"):
        extract_pdf_text(b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF")


def test_a_renamed_file_is_refused_over_the_api_and_nothing_is_queued(signed_in, api_db):
    for path in ("/api/jobs/import-file", "/api/documents/upload", "/api/jobs/extract-reference", "/api/templates/extract"):
        response = client.post(path, files={"file": ("photo.docx", _PNG, _DOCX)})
        assert (response.status_code, response.json()["code"]) == (400, "invalid_file"), path
    instructions = client.post("/api/documents", json={"text": "# Doc\n\nText."}).json()
    response = client.post(
        f"/api/documents/{instructions['id']}/format", files={"instructionsFile": ("rules.pdf", b"not a pdf at all", "application/pdf")}
    )
    assert (response.status_code, response.json()["code"]) == (400, "invalid_file")


def test_an_inline_image_whose_bytes_arent_its_type_is_never_stored(signed_in, api_db):
    document = client.post("/api/documents", json={"text": "# Notes\n\nSome text."}).json()
    disguised = {"type": "image", "content": "", "order": 99, "image": {"src": "data:image/png;base64," + base64.b64encode(b"<script>alert(1)</script>").decode()}}

    saved = client.put(f"/api/documents/{document['id']}/content", json={"elements": document["elements"] + [disguised]}).json()

    assert not [element for element in saved["elements"] if element["type"] == "image"]
    assert any("was removed" in note for note in saved["unsupportedFeatures"])
    with OrmSession(api_db) as session:
        assert session.scalar(select(func.count(DocumentAsset.id))) == 0


# -- the request-size cap ----------------------------------------------------------


def _size_limited_app(max_bytes: int) -> TestClient:
    small = FastAPI()
    install_error_handlers(small)
    small.add_middleware(RequestSizeLimit, max_bytes=max_bytes)

    @small.post("/echo")
    async def echo(request: Request) -> dict:
        return {"size": len(await request.body())}

    return TestClient(small)


def test_a_body_over_the_cap_is_refused_whether_or_not_it_says_its_size():
    small = _size_limited_app(100)

    assert small.post("/echo", content=b"x" * 100).json() == {"size": 100}
    declared = small.post("/echo", content=b"x" * 101)
    assert (declared.status_code, declared.json()["code"]) == (413, "too_large")

    def stream():  # no Content-Length: counted as it arrives
        for _ in range(10):
            yield b"x" * 20

    streamed = small.post("/echo", content=stream())
    assert (streamed.status_code, streamed.json()["code"]) == (413, "too_large")


def test_the_app_refuses_an_oversized_request_with_its_request_id(api_db):
    cap = get_settings().max_request_size_mb * 1024 * 1024
    response = client.post("/api/auth/login", content=b"{}", headers={"Content-Length": str(cap + 1), "Content-Type": "application/json"})

    assert (response.status_code, response.json()["code"]) == (413, "too_large")
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


# -- rate limits --------------------------------------------------------------------


def _limits(monkeypatch, **rates: str) -> None:
    for scope, rate in rates.items():
        monkeypatch.setattr(get_settings(), f"rate_limit_{scope}", rate)


def test_rates_read_as_count_per_window():
    assert Rate.parse("20/minute") == Rate(20, 60)
    assert Rate.parse("5/hours") == Rate(5, 3600)
    assert Rate.parse("") is None and Rate.parse("0/minute") is None
    with pytest.raises(ValueError):
        Rate.parse("lots/minute")


def test_signing_in_is_limited_per_account_and_per_address(monkeypatch, api_db):
    _limits(monkeypatch, login_account="2/minute", login="4/minute")
    client.post("/api/auth/register", json={"email": "target@example.com", "password": "long enough password"})
    attempt = {"email": "target@example.com", "password": "wrong password guess"}

    assert [client.post("/api/auth/login", json=attempt).status_code for _ in range(2)] == [401, 401]
    refused = client.post("/api/auth/login", json=attempt)
    assert (refused.status_code, refused.json()["code"]) == (429, "rate_limited")
    assert int(refused.headers["Retry-After"]) >= 1 and refused.json()["details"]["retryAfter"] == int(refused.headers["Retry-After"])
    # Another account from the same address, until the address's own limit.
    other = {"email": "someone@example.com", "password": "wrong password guess"}
    assert client.post("/api/auth/login", json=other).status_code == 401
    assert client.post("/api/auth/login", json=other).status_code == 429


def test_registering_is_limited_per_address(monkeypatch, api_db):
    _limits(monkeypatch, register="2/hour")
    statuses = [
        client.post("/api/auth/register", json={"email": f"new{index}@example.com", "password": "long enough password"}).status_code
        for index in range(3)
    ]
    assert statuses == [201, 201, 429]


def test_ai_uploads_and_exports_have_their_own_allowances(monkeypatch, signed_in):
    _limits(monkeypatch, ai="1/minute", export="1/minute", upload="1/minute")
    first = client.post("/api/documents", json={"text": "# One\n\nText."})
    assert first.status_code == 201
    assert client.post("/api/jobs/import-text", json={"text": "# Two\n\nText."}).status_code == 429
    document_id = first.json()["id"]
    # Formatting with a template alone uses no AI, so it isn't counted.
    assert client.post("/api/jobs/format", data={"documentId": document_id, "templateId": "academic-default"}).status_code == 202
    assert client.post("/api/jobs/format", data={"documentId": document_id, "instructionsText": "bold headings"}).status_code == 429
    assert client.get(f"/api/documents/{document_id}/export/docx").status_code == 200
    assert client.post("/api/jobs/export", json={"documentId": document_id, "format": "pdf"}).status_code == 429
    assert client.post("/api/documents/upload", files={"file": ("a.txt", b"Text.", "text/plain")}).status_code == 201
    assert client.post("/api/jobs/import-file", files={"file": ("b.txt", b"Text.", "text/plain")}).status_code == 429


def test_every_client_has_an_overall_allowance(monkeypatch, signed_in):
    _limits(monkeypatch, **{"global": "3/minute"})
    statuses = [client.get("/api/auth/me").status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]
    assert client.get("/api/health").status_code == 200  # never limited


async def test_a_window_ends_and_counting_starts_again(monkeypatch):
    counter, rate, now = MemoryCounter(), Rate(2, 60), [1_000_040.0]  # 20 s into a minute's window
    monkeypatch.setattr(rate_limit.time, "time", lambda: now[0])

    assert [await counter.hit("k", rate) for _ in range(3)] == [None, None, 40]
    now[0] += 40
    assert await counter.hit("k", rate) is None


async def test_redis_counts_are_shared_and_a_redis_outage_lets_requests_through():
    class Pipeline:
        def __init__(self, store, fail):
            self.store, self.fail, self.ops = store, fail, []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def incr(self, key):
            self.ops.append(key)

        def expire(self, key, seconds):
            pass

        async def execute(self):
            if self.fail:
                raise ConnectionError("Redis is down")
            key = self.ops[0]
            self.store[key] = self.store.get(key, 0) + 1
            return [self.store[key], True]

    class FakeRedis:
        def __init__(self):
            self.store, self.fail = {}, False

        def pipeline(self, transaction=True):
            return Pipeline(self.store, self.fail)

    counter = RedisCounter.__new__(RedisCounter)
    counter._redis = FakeRedis()
    rate = Rate(1, 3600)

    assert await counter.hit("user:1", rate) is None
    assert await counter.hit("user:1", rate) is not None
    counter._redis.fail = True
    assert await counter.hit("user:1", rate) is None


# -- headers, CORS and settings ------------------------------------------------------


def test_api_responses_carry_the_security_headers(monkeypatch, api_db):
    response = client.get("/api/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in response.headers
    monkeypatch.setattr(get_settings(), "hsts_seconds", 31536000)
    assert client.get("/api/health").headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_cors_lets_the_frontend_send_only_what_it_sends(api_db):
    origin = get_settings().cors_origins.split(",")[0]
    allowed = client.options(
        "/api/documents", headers={"Origin": origin, "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "if-match,content-type"}
    )
    assert allowed.status_code == 200 and allowed.headers["Access-Control-Allow-Origin"] == origin
    refused = client.options(
        "/api/documents", headers={"Origin": origin, "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "x-anything-else"}
    )
    assert refused.status_code == 400
    foreign = client.options("/api/documents", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "Access-Control-Allow-Origin" not in foreign.headers


def test_settings_refuse_to_start_unsafe():
    with pytest.raises(ValidationError, match="isn't allowed"):
        Settings(cors_origins="*", _env_file=None)
    with pytest.raises(ValidationError, match="rate limit"):
        Settings(rate_limit_login="many per minute", _env_file=None)
    with pytest.raises(ValidationError, match="MAX_REQUEST_SIZE_MB"):
        Settings(max_request_size_mb=5, max_upload_size_mb=10, _env_file=None)


def test_secrets_never_show_when_the_settings_are_printed():
    settings = Settings(
        anthropic_api_key="anthropic-test-secret", stripe_secret_key="stripe-test-secret", s3_secret_access_key="s3-secret-value", _env_file=None
    )

    printed = repr(settings) + str(settings) + str(settings.model_dump())
    assert not any(secret in printed for secret in ("anthropic-test-secret", "stripe-test-secret", "s3-secret-value"))
    assert settings.anthropic_api_key.get_secret_value() == "anthropic-test-secret"


def test_error_bodies_look_the_same_for_every_refusal(api_db):
    first = client.post("/api/auth/login", content=b"x" * 10, headers={"Content-Length": str(10**12), "Content-Type": "application/json"})
    second = client.post("/api/auth/login", content=b"x" * 10, headers={"Content-Length": str(10**12), "Content-Type": "application/json"})
    assert error_body(first) == error_body(second)
    assert set(first.json()) == {"code", "message", "details", "request_id"}
