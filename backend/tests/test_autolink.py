"""Plain-text addresses in a Word file stay text unless asked for (tracker DOCX-026,
audit AUD-03/AUD-13): Word turns a typed address into a link only while typing, and a
file's plain "see www.example.com" is what its author left. With the import option on,
they become links, and the import report says so."""

import io

from docx import Document as DocxDocument
from fastapi.testclient import TestClient

from app.fidelity.imports import docx_import_report
from app.main import app
from app.models.document import MarkType
from app.parsers.docx import parse_docx

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _word_file() -> bytes:
    word = DocxDocument()
    word.add_paragraph("Write to someone@example.com or see https://example.com/page.")
    buffer = io.BytesIO()
    word.save(buffer)
    return buffer.getvalue()


def _links(document) -> list[str]:
    return [mark.href for element in document.elements for run in element.inline or [] for mark in run.marks if mark.type == MarkType.LINK]


def test_plain_text_addresses_stay_text_by_default():
    data = _word_file()
    document = parse_docx(data, "addresses.docx")
    report = docx_import_report(document, data)

    assert _links(document) == []
    assert "docx.autolink" not in {item.feature for item in report.items}


def test_asked_for_they_become_links_and_the_report_says_so():
    data = _word_file()
    document = parse_docx(data, "addresses.docx", autolink=True)
    report = docx_import_report(document, data, autolink=True)

    assert _links(document) == ["mailto:someone@example.com", "https://example.com/page"]
    [item] = [item for item in report.items if item.feature == "docx.autolink"]
    assert item.count == 2


def test_the_upload_takes_the_option(api_db):
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/register", json={"email": "links@example.com", "password": "long enough password"}).status_code == 201

    plain = client.post("/api/v1/documents/upload", files={"file": ("a.docx", _word_file(), _DOCX)}).json()
    linked = client.post("/api/v1/documents/upload", files={"file": ("b.docx", _word_file(), _DOCX)}, data={"autolink": "true"}).json()

    hrefs = lambda document: [mark["href"] for element in document["elements"] for run in element.get("inline") or [] for mark in run["marks"] if mark["type"] == "link"]  # noqa: E731
    assert hrefs(plain) == []
    assert hrefs(linked) == ["mailto:someone@example.com", "https://example.com/page"]
