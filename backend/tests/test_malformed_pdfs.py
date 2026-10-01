"""Malformed PDFs (tracker SEC-011) and text no document can hold (SEC-023): the corpus in
tests/malformed_pdf.py through the reader, the upload route, the import job and the
instructions route. Each PDF comes back as all its text, as the text that could be read
with the damage said, or as invalid_file with its exact message -- never a 500, and
nothing pypdf says about the file ever reaches the log."""

import asyncio
import io
import logging
from collections import Counter

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.db.models import Document as DocumentRow
from app.main import app
from app.models.document import Element, ElementType, InlineRun
from app.parsers import pdf as pdf_module
from app.parsers.pdf import DAMAGED, INVALID, NO_TEXT, PARTLY_DAMAGED, PASSWORD, TOO_MUCH, PdfParseError, extract_pdf_text, read_pdf
from app.services.ingestion_service import build_document_from_text, build_document_from_upload
from tests.fakes import FakeAIProvider
from tests.malformed_pdf import DAMAGED as READ_DAMAGED
from tests.malformed_pdf import READ, pdf, variants, with_control_code, words

pytestmark = pytest.mark.security  # the security regression suite (TEST-030)

client = TestClient(app, base_url="https://testserver")
_PDF = "application/pdf"
_CORPUS = variants()
_REFUSALS = {"invalid": INVALID, "too much": TOO_MUCH, "no text": NO_TEXT, "password": PASSWORD, "damaged, no text": DAMAGED}


def _ai() -> FakeAIProvider:
    return FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = _ai
    assert client.post("/api/v1/auth/register", json={"email": "pdfs@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def _documents(api_db) -> int:
    with OrmSession(api_db) as session:
        return session.scalar(select(func.count(DocumentRow.id)))


def _features(document: dict) -> dict[str, dict]:
    return {item["feature"]: item for item in document["importReport"]["items"]}


@pytest.mark.parametrize("name", list(_CORPUS))
def test_a_malformed_pdf_is_read_whole_read_with_its_loss_said_or_refused(name):
    data, expected = _CORPUS[name]
    if expected in _REFUSALS:
        with pytest.raises(PdfParseError) as refused:
            read_pdf(data)
        assert str(refused.value) == _REFUSALS[expected]
        return
    read = read_pdf(data)
    if expected == READ:
        assert (read.damaged, read.text.split()) == (False, words())
    else:  # what could be read, and said not to be all
        assert read.damaged and len(read.text.split()) < len(words())
        assert not Counter(read.text.split()) - Counter(words())


@pytest.mark.parametrize("name", list(_CORPUS))
def test_over_the_api_a_malformed_pdf_is_a_document_or_invalid_file(signed_in, name):
    data, expected = _CORPUS[name]
    response = client.post("/api/v1/documents/upload", files={"file": ("broken.pdf", data, _PDF)})

    if expected in _REFUSALS:
        body = response.json()
        assert (response.status_code, body["code"], body["message"]) == (400, "invalid_file", _REFUSALS[expected])
        assert body["request_id"] and _documents(signed_in) == 0
        return
    assert response.status_code == 201, response.text[:500]
    document = response.json()
    damage = _features(document).get("pdf.damaged")
    if expected == READ:
        assert damage is None and document["importReport"]["contentLossCount"] == 0
    else:
        assert expected == READ_DAMAGED
        assert damage["contentChanged"] and damage["policy"] == "lossy"
        assert document["importReport"]["contentLossCount"] >= 1  # "No content changes" is never claimed


def test_a_damaged_pdf_imports_as_a_job_with_its_loss_said_and_a_broken_one_fails_it(signed_in):
    damaged = client.post("/api/v1/jobs/import-file", files={"file": ("damaged.pdf", _CORPUS["a stream that doesn't decode"][0], _PDF)}).json()
    assert damaged["status"] == "succeeded"
    document = client.get(f"/api/v1/documents/{damaged['result']['documentId']}").json()
    assert "pdf.damaged" in _features(document)

    broken = client.post("/api/v1/jobs/import-file", files={"file": ("broken.pdf", _CORPUS["kids that loop"][0], _PDF)}).json()
    assert (broken["status"], broken["error"]) == ("failed", INVALID)
    assert _documents(signed_in) == 1


def test_an_instructions_pdf_must_be_whole_or_it_is_refused(signed_in):
    document = client.post("/api/v1/documents", json={"text": "# Notes\n\nSome text."}).json()
    for name, message in (("a stream that doesn't decode", PARTLY_DAMAGED), ("kids that loop", INVALID)):
        response = client.post(
            f"/api/v1/documents/{document['id']}/format", files={"instructionsFile": ("rules.pdf", _CORPUS[name][0], _PDF)}
        )
        assert (response.status_code, response.json()["code"], response.json()["message"]) == (400, "invalid_file", message), name
    with pytest.raises(PdfParseError, match="part of its text"):
        extract_pdf_text(_CORPUS["a stream that doesn't decode"][0])
    assert extract_pdf_text(pdf()).split() == words()


class _Root(logging.Handler):
    """What reaches the root logger -- where the app's own handler writes the log from."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_nothing_pypdf_says_about_a_file_reaches_the_log(caplog):
    root = _Root()
    logging.getLogger().addHandler(root)
    try:
        with caplog.at_level(logging.DEBUG):
            read_pdf(_CORPUS["offsets shifted"][0])  # read whole, after repairs pypdf warns about
            with pytest.raises(PdfParseError):
                read_pdf(_CORPUS["kids that loop"][0])
    finally:
        logging.getLogger().removeHandler(root)
    # (pytest itself hangs its capture on loggers that don't propagate, so caplog sees pypdf's.)
    assert [record.name for record in root.records if record.name.startswith("pypdf")] == []
    ours = [record.getMessage() for record in root.records if record.name == "app.parsers.pdf"]
    assert any("repairs, 0 of them losing text (pypdf._reader)" in message for message in ours), ours
    assert any(message.startswith("Unreadable PDF: ") and " at " in message for message in ours), ours
    assert not [message for message in ours if "begins" in message or "Page 1" in message]


def test_concurrent_reads_keep_their_own_damage():
    async def both():
        damaged, whole = _CORPUS["a stream that doesn't decode"][0], _CORPUS["offsets shifted"][0]
        return await asyncio.gather(*(asyncio.to_thread(read_pdf, data) for data in (damaged, whole) * 4))

    results = asyncio.run(both())
    assert [result.damaged for result in results] == [True, False] * 4


def test_a_pdf_whose_pictures_cant_be_counted_says_so(monkeypatch):
    def broken(*_, **__):
        raise AttributeError("resources that aren't a dictionary")

    monkeypatch.setattr("app.fidelity.text_sources.PdfReader", broken)
    document = asyncio.run(build_document_from_upload(pdf(), "pictures.pdf", "Pictures", _ai()))
    item = {item.feature: item for item in document.importReport.items}["pdf.images"]
    assert "couldn't be counted" in item.reason and item.contentChanged
    assert document.importReport.contentLossCount >= 1


def test_control_codes_never_reach_a_document_and_are_said_to_be_left_out(signed_in):
    # From a PDF: the backspace goes, the words stay, the content check agrees, and it is said.
    response = client.post("/api/v1/documents/upload", files={"file": ("control.pdf", with_control_code(), _PDF)})
    assert response.status_code == 201, response.text[:500]
    document = response.json()
    assert "\x08" not in response.text.replace("\\b", "")  # nowhere, not even escaped in the JSON
    assert "\\u0008" not in response.text
    item = _features(document)["text.control_characters"]
    assert (item["count"], item["policy"], item["contentChanged"]) == (1, "unsupported", False)
    assert document["importReport"]["contentStatus"] == "verified"

    # Pasted: a form feed parts two words, a null goes.
    pasted = client.post("/api/v1/documents", json={"text": "# Title\n\nfirst\fsecond\x00 third"}).json()
    assert [element["content"] for element in pasted["elements"]] == ["Title", "first second third"]

    # From the editor: saved without them -- and the document still exports to Word.
    elements = document["elements"]
    elements[0]["content"] = "Bell\x07 here"
    elements[0]["inline"] = [{"text": "Bell\x07 here", "marks": []}]
    saved = client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements})
    assert saved.status_code == 200, saved.text[:300]
    assert saved.json()["elements"][0]["content"] == "Bell here"
    exported = client.get(f"/api/v1/documents/{document['id']}/export/docx")
    assert exported.status_code == 200
    assert "Bell here" in "\n".join(paragraph.text for paragraph in DocxDocument(io.BytesIO(exported.content)).paragraphs)


def test_the_model_holds_only_what_xml_can():
    element = Element(type=ElementType.PARAGRAPH, content="a\x08b\x0bc\ud800d\uffff", order=0, inline=[InlineRun(text="x\x1fy\tz\n")])
    assert (element.content, element.inline[0].text) == ("ab cd", "x y\tz\n")  # tab and newline are XML's own
    document = asyncio.run(build_document_from_text("Plain words\x0cand more", "Title", _ai()))
    assert {item.feature: item.count for item in document.importReport.items}["text.control_characters"] == 1
