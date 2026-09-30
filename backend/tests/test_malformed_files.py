"""Malformed Word files (tracker SEC-010): the corpus in tests/malformed_docx.py, made from
two of the fixtures, through the parser, the upload route and the jobs. Each file comes
back as the document it holds or as invalid_file with a message for people -- never a
500, never a document made of half of it, never a word of the file in the log."""

import logging
from collections import Counter
from functools import cache
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.db.models import Document as DocumentRow
from app.db.models import DocumentAsset
from app.fidelity.content import document_words
from app.main import app
from app.models.document import Document
from app.parsers import docx as docx_module
from app.parsers.docx import UNREADABLE, DocxParseError, import_docx
from app.security.files import DAMAGED
from app.services.ingestion_service import build_document_from_docx
from tests.fakes import FakeAIProvider
from tests.malformed_docx import READABLE, SAME_TEXT, W, variants, with_entity, with_part

client = TestClient(app, base_url="https://testserver")
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_FIXTURES = Path(__file__).parent / "fixtures"
_SOURCES = {"a03": _FIXTURES / "word" / "a03-lists.docx", "12-complex": _FIXTURES / "documents" / "12-complex.docx"}
_NOT_A_DOCX = "'broken.docx' is not a valid .docx file"
# What each refusal says -- a message written for people, never what an exception says.
# Every XML part cut short is DAMAGED.
_REFUSALS = {
    "truncated in the middle": DAMAGED,
    "truncated central directory": DAMAGED,
    "a zip of garbage": DAMAGED,
    "document.xml empty": DAMAGED,
    "document.xml not WordprocessingML": UNREADABLE,
    "document.xml without a body": UNREADABLE,
    "document.xml missing": _NOT_A_DOCX,
    "no relationships": _NOT_A_DOCX,
    "no content types": "This isn't a Word (.docx) file.",
    "a macro document's content type": UNREADABLE,
    "a relationship to a missing part": _NOT_A_DOCX,
    "a DTD with entities that expand": DAMAGED,
    "a DTD it doesn't use": DAMAGED,
    "blocks nested 3000 deep": DAMAGED,
}
# Over the API, one of each way of being refused (the rest take the same path), and every
# file that is read -- storing it runs more over the file (DOCX-028's kept original).
_ONE_OF_EACH = {
    "truncated in the middle",
    "no content types",
    "word/document.xml cut short",
    "a DTD with entities that expand",
    "document.xml missing",
    "document.xml without a body",
    "a macro document's content type",
}


@cache
def _valid(source: str) -> bytes:
    return _SOURCES[source].read_bytes()


@cache
def _corpus(source: str) -> dict[str, bytes]:
    return variants(_valid(source))


_CASES = [(source, name) for source in _SOURCES for name in _corpus(source)]
_API_CASES = [(source, name) for source, name in _CASES if name in READABLE or name in _ONE_OF_EACH]


def _refusal(name: str) -> str:
    return DAMAGED if name.endswith(" cut short") else _REFUSALS[name]


def _ids(cases: list[tuple[str, str]]) -> list[str]:
    return [f"{source}: {name}" for source, name in cases]


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)
    assert client.post("/api/v1/auth/register", json={"email": "malformed@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def _nothing_stored(api_db) -> None:
    with OrmSession(api_db) as session:
        assert session.scalar(select(func.count(DocumentRow.id))) == 0
        assert session.scalar(select(func.count(DocumentAsset.id))) == 0


@pytest.mark.parametrize(("source", "name"), _CASES, ids=_ids(_CASES))
def test_a_malformed_word_file_is_read_whole_or_refused(source, name):
    data = _corpus(source)[name]
    if name not in READABLE:
        with pytest.raises(DocxParseError) as refused:
            build_document_from_docx(data, "broken.docx", None)
        assert str(refused.value) == _refusal(name)
        return

    document = build_document_from_docx(data, "broken.docx", None)
    read = document_words(document.elements)
    if name in SAME_TEXT:  # every word of the file, as it is read when nothing is wrong with it
        whole = document_words(build_document_from_docx(_valid(source), "valid.docx", None).elements)
        assert not Counter(whole) - Counter(read)
    elif name == "a picture that isn't one":  # its text read; the picture said to be left out
        assert read == ["Before", "the", "picture"]
        assert [item.feature for item in document.importReport.items if item.feature.startswith("docx.image")] == ["docx.image.unreadable"]
    else:
        assert read == {"blocks nested 60 deep": ["Deep"], "numbers that aren't numbers": ["Odd", "numbers"]}[name]


@pytest.mark.parametrize(("source", "name"), _API_CASES, ids=_ids(_API_CASES))
def test_over_the_api_a_malformed_file_is_a_document_or_invalid_file(signed_in, source, name):
    data = _corpus(source)[name]
    response = client.post("/api/v1/documents/upload", files={"file": ("broken.docx", data, _DOCX)})

    if name in READABLE:
        assert response.status_code == 201, response.text[:500]
        stored = Document.model_validate(response.json())
        assert document_words(stored.elements) == document_words(build_document_from_docx(data, "broken.docx", None).elements)
        return
    body = response.json()
    assert (response.status_code, body["code"]) == (400, "invalid_file"), response.text[:500]
    assert body["message"] == _refusal(name) and body["request_id"]
    _nothing_stored(signed_in)


def test_a_malformed_file_fails_its_jobs_with_the_reason_and_leaves_nothing(signed_in):
    for name, message in (("word/document.xml cut short", DAMAGED), ("document.xml without a body", UNREADABLE)):
        upload = {"file": ("broken.docx", _corpus("a03")[name], _DOCX)}
        for path in ("/api/v1/jobs/import-file", "/api/v1/jobs/extract-reference"):
            job = client.post(path, files=upload).json()
            assert (job["status"], job["error"]) == ("failed", message), (path, name)
        response = client.post("/api/v1/templates/extract", files=upload)
        assert (response.status_code, response.json()["code"], response.json()["message"]) == (400, "invalid_file", message), name
    _nothing_stored(signed_in)


def test_a_file_whose_import_cant_be_checked_is_refused_not_half_reported(monkeypatch):
    # The import report is what says what a file loses: without it, nothing would.
    def breaks(*_, **__):
        raise AttributeError("a part of the file the report couldn't check")

    monkeypatch.setattr("app.services.ingestion_service.docx_import_report", breaks)
    with pytest.raises(DocxParseError) as refused:
        build_document_from_docx(_valid("a03"), "report.docx", None)
    assert str(refused.value) == UNREADABLE


def test_an_external_entity_is_never_read(signed_in, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("SEC010-MARKER, never to be read", encoding="utf-8")
    data = with_entity(_valid("a03"), secret.as_uri())

    with pytest.raises(DocxParseError) as refused:
        import_docx(data, "entity.docx")
    assert str(refused.value) == DAMAGED
    response = client.post("/api/v1/documents/upload", files={"file": ("entity.docx", data, _DOCX)})
    assert (response.status_code, response.json()["message"]) == (400, DAMAGED)
    assert "SEC010-MARKER" not in response.text
    _nothing_stored(signed_in)


def test_the_log_says_where_a_file_broke_never_what_it_holds(caplog, monkeypatch):
    private = "Private words about the client"
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>{private} &Undeclared;</w:t></w:r></w:p></w:body></w:document>'
    with caplog.at_level(logging.WARNING, logger="app.parsers.docx"), pytest.raises(DocxParseError):
        import_docx(with_part(_valid("a03"), "word/document.xml", xml.encode("utf-8")), "private.docx")
    assert "its part 'word/document.xml' isn't well-formed XML" in caplog.text
    assert "Private" not in caplog.text and "Undeclared" not in caplog.text  # lxml's message names the entity

    caplog.clear()

    def leaks(self):
        raise ValueError(f"{private} were in this paragraph")

    monkeypatch.setattr(docx_module._Importer, "read_body", leaks)
    with caplog.at_level(logging.WARNING, logger="app.parsers.docx"), pytest.raises(DocxParseError) as refused:
        import_docx(_valid("a03"), "private.docx")
    assert str(refused.value) == UNREADABLE
    assert "couldn't be read: ValueError at test_malformed_files.py:" in caplog.text
    assert "Private" not in caplog.text
