"""The PDF inspection (tracker PDF-012): what the geometry read found in each fixture
(tests/fixtures/pdf/), page by page, kept with the imported document and sent with it
-- through the upload, the import job and a later read -- while the editable import
refuses what it refused, and keeps every word the text read finds."""

import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.fidelity.content import document_words, words
from app.fidelity.pdf_inspection import FAILED, inspect_pdf, page_kind_items
from app.main import app
from app.parsers import pdf_geometry
from app.parsers.pdf import NO_TEXT, TOO_MUCH, read_pdf
from app.services.ingestion_service import build_document_from_upload
from scripts.make_pdf_fixtures import SCAN_LINES
from tests.fakes import FakeAIProvider

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"
client = TestClient(app, base_url="https://testserver")
_PDF = "application/pdf"


def _ai() -> FakeAIProvider:
    return FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = _ai
    assert client.post("/api/v1/auth/register", json={"email": "inspect@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def _data(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# name: (the file's kind, its pages' kinds, outline entries, form fields)
_FILES = {
    "text.pdf": ("text", ["text", "text"], 3, 0),
    "columns.pdf": ("text", ["text"], 0, 0),
    "table.pdf": ("text", ["text"], 0, 0),
    "pictures.pdf": ("text", ["text"], 0, 0),
    "scanned.pdf": ("scanned", ["scanned"], 0, 0),
    "hybrid.pdf": ("hybrid", ["hybrid", "text", "scanned"], 0, 0),
    "rotated.pdf": ("text", ["text"] * 5, 0, 0),
    "multilingual.pdf": ("text", ["text"], 0, 0),
    "form.pdf": ("text", ["text"], 0, 3),
}


@pytest.mark.parametrize("name", list(_FILES))
def test_each_fixture_is_inspected_page_by_page(name):
    inspection = inspect_pdf(_data(name))
    kind, kinds, outline, fields = _FILES[name]
    assert (inspection.kind, [page.kind for page in inspection.pages]) == (kind, kinds)
    assert (inspection.complete, inspection.stopped, inspection.notRead, inspection.structureProblem) == (True, None, [], None)
    assert (inspection.pageCount, inspection.outlineCount, inspection.formFieldCount) == (len(kinds), outline, fields)
    assert [page.number for page in inspection.pages] == list(range(1, len(kinds) + 1))
    assert inspection.metadata == ["Author", "CreationDate", "Creator", "Keywords", "ModDate", "Producer", "Subject", "Title", "Trapped"]
    for page in inspection.pages:
        assert page.reason and 0 < page.confidence <= 1
        assert page.boxes["media"][2] > 0 and set(page.boxes) >= {"media", "crop"}


def test_a_pages_summary_holds_its_fonts_colours_drawing_and_links():
    first, second = inspect_pdf(_data("text.pdf")).pages
    assert [(font.name, font.sizes, font.characters) for font in first.fonts] == [
        ("Helvetica", [11.0], 121), ("Times-Roman", [12.0], 34), ("Courier", [10.0], 24), ("Helvetica-Bold", [20.0], 15)
    ]
    assert first.textColours == ["#000000", "#cc0000", "#1a3399"]
    assert first.links.model_dump() == {"web": 1, "internal": 1, "unsafe": 1, "other": 0}
    assert first.annotations == {"Link": 3, "Text": 1}
    assert (first.characters, first.evidence.visibleCharacters, second.links.web) == (230, 194, 0)

    table = inspect_pdf(_data("table.pdf")).pages[0]
    assert (table.lines, table.rectangles, table.curves, table.imageCount) == (10, 1, 0, 0)
    pictures = inspect_pdf(_data("pictures.pdf")).pages[0]
    assert [(image.box, image.pixelWidth, image.pixelHeight) for image in pictures.images] == [
        ([72.0, 161.89, 272.0, 281.89], 200, 120), ([320.0, 161.89, 440.0, 281.89], 120, 120)
    ]
    turned = inspect_pdf(_data("rotated.pdf")).pages
    assert [(page.rotation, page.width, page.height) for page in turned] == [
        (0, 595.28, 841.89), (90, 595.28, 841.89), (270, 595.28, 841.89), (0, 841.89, 595.28), (0, 595.28, 841.89)
    ]
    assert set(turned[4].boxes) == {"media", "crop", "bleed", "trim", "art"}
    form = inspect_pdf(_data("form.pdf"))
    assert [(field.name, field.kind) for field in form.formFields] == [("applicant", "text"), ("subscribe", "button"), ("size", "choice")]
    assert form.pages[0].annotations == {"Widget": 3}
    outline = inspect_pdf(_data("text.pdf")).outline
    assert [(entry.title, entry.level, entry.page) for entry in outline] == [("Introduction", 0, 1), ("Details", 0, 2), ("Figures", 1, 2)]
    hybrid = inspect_pdf(_data("hybrid.pdf")).pages[0]
    layer = sum(len(line.replace(" ", "")) for line in SCAN_LINES)  # spaces aside
    assert (hybrid.evidence.invisibleCharacters, hybrid.evidence.imageCoverage, hybrid.textColours) == (layer, 1.0, [])


def test_the_inspection_says_nothing_personal():
    """Metadata by name, form fields without values, web links counted: none of what the file holds."""
    text = inspect_pdf(_data("text.pdf")).model_dump_json()
    for value in ("SmartDoc PDF fixtures", "Text fixture", "Synthetic test document", "example.com", "javascript", "reviewer"):
        assert value not in text
    assert '"M"' not in inspect_pdf(_data("form.pdf")).model_dump_json()  # the choice's value


def test_the_import_reports_scanned_and_hybrid_pages():
    items = {item.feature: item for item in page_kind_items(inspect_pdf(_data("hybrid.pdf")))}
    scanned, hybrid = items["pdf.scanned_pages"], items["pdf.hybrid_pages"]
    assert (scanned.count, scanned.policy, scanned.contentChanged, scanned.confidence) == (1, "unsupported", True, 0.9)
    assert scanned.reason.startswith("Page 3 is a scan with no text")
    assert (hybrid.count, hybrid.policy, hybrid.contentChanged, hybrid.confidence) == (1, "lossy", False, 0.95)
    assert hybrid.reason.startswith("Page 1 has text over a page-sized picture")
    assert page_kind_items(inspect_pdf(_data("text.pdf"))) == []


def test_a_pdf_upload_carries_its_inspection_and_says_what_its_pages_are(signed_in):
    response = client.post("/api/v1/documents/upload", files={"file": ("hybrid.pdf", _data("hybrid.pdf"), _PDF)})
    assert response.status_code == 201, response.text[:500]
    document = response.json()
    inspection = document["pdfInspection"]
    assert (inspection["kind"], [page["kind"] for page in inspection["pages"]], inspection["complete"]) == ("hybrid", ["hybrid", "text", "scanned"], True)
    assert inspection["pages"][0]["evidence"]["invisibleCharacters"] > 0
    items = {item["feature"]: item for item in document["importReport"]["items"]}
    assert {"pdf.layout", "pdf.images", "pdf.scanned_pages", "pdf.hybrid_pages"} <= set(items)
    assert items["pdf.scanned_pages"]["contentChanged"] and document["importReport"]["contentLossCount"] >= 1
    # Kept with the document: a later read sends the same.
    again = client.get(f"/api/v1/documents/{document['id']}").json()
    assert again["pdfInspection"] == inspection


def test_an_import_job_carries_the_inspection(signed_in):
    job = client.post("/api/v1/jobs/import-file", files={"file": ("text.pdf", _data("text.pdf"), _PDF)}).json()
    assert job["status"] == "succeeded", job
    document = client.get(f"/api/v1/documents/{job['result']['documentId']}").json()
    assert (document["pdfInspection"]["kind"], document["pdfInspection"]["outlineCount"]) == ("text", 3)


def test_a_word_or_pasted_document_has_none(signed_in):
    pasted = client.post("/api/v1/documents", json={"text": "# Notes\n\nSome text."}).json()
    assert pasted["pdfInspection"] is None


def test_a_scanned_pdf_is_still_refused(signed_in):
    response = client.post("/api/v1/documents/upload", files={"file": ("scanned.pdf", _data("scanned.pdf"), _PDF)})
    assert (response.status_code, response.json()["code"], response.json()["message"]) == (400, "invalid_file", NO_TEXT)


@pytest.mark.parametrize("name", [name for name in _FILES if name != "scanned.pdf"])
def test_the_editable_import_keeps_every_word_the_text_read_finds(name):
    """The document rebuilt from the layout (P2E-002) holds every word the text read alone
    finds: in its blocks, or in the header and footer the running ones became -- only the
    list markers and page numbers it makes itself are left out. The report says what it did."""
    data = _data(name)
    uploaded = asyncio.run(build_document_from_upload(data, name, "Title", _ai()))
    report = uploaded.importReport
    assert report.content.method == "pdf-layout" and report.content.verified
    kept = Counter(document_words(uploaded.elements)) + Counter(words(" ".join(filter(None, [uploaded.settings.header, uploaded.settings.footer]))))
    missing = Counter(words(read_pdf(data).text)) - kept
    assert all(word.isdigit() or word in {"Page", "of"} for word in missing), missing
    features = {item.feature for item in report.items}
    assert not features & {"pdf.text_reads_differ", "pdf.structure_not_rebuilt"}
    assert features <= {
        "pdf.layout", "pdf.images", "pdf.scanned_pages", "pdf.hybrid_pages", "pdf.running_header", "pdf.running_footer",
        "pdf.page_numbers", "pdf.list_markers", "pdf.annotations", "pdf.form_fields", "pdf.outline", "pdf.links",
    }


def test_an_inspection_that_fails_never_costs_the_import(monkeypatch):
    def broken(*_, **__):
        raise RuntimeError("a bug in the inspection")

    monkeypatch.setattr("app.fidelity.pdf_inspection.read_pdf_geometry", broken)
    document = asyncio.run(build_document_from_upload(_data("text.pdf"), "text.pdf", "Title", _ai()))
    assert (document.pdfInspection.complete, document.pdfInspection.stopped, document.pdfInspection.pages) == (False, FAILED, [])
    assert document.elements and document.importReport.content.verified

    monkeypatch.undo()
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_OBJECTS", 5)  # refused by the geometry read, not by the import
    document = asyncio.run(build_document_from_upload(_data("text.pdf"), "text.pdf", "Title", _ai()))
    assert (document.pdfInspection.complete, document.pdfInspection.stopped, document.pdfInspection.kind) == (False, TOO_MUCH, None)
    assert document.elements


def test_a_stopped_inspection_keeps_the_pages_it_read(monkeypatch):
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_DECODED", 800)
    inspection = inspect_pdf(_data("text.pdf"))
    assert (inspection.complete, [page.number for page in inspection.pages], inspection.pageCount) == (False, [1], 2)
    assert inspection.stopped == pdf_geometry.STOPPED_DATA.format(page=2)
    assert json.loads(inspection.model_dump_json())["stopped"].startswith("Page 2 holds more data")
