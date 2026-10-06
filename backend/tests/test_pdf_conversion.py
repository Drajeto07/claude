"""The PDF -> editable conversion's confidence and report (tracker P2E-005, brief §41, §88):
how sure the conversion is of each aspect and in all, kept with the document; and every
thing the PDF holds that the document doesn't -- notes, a form's fields, the outline, the
links it can't keep -- said in the import report, never dropped silently."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.fidelity.pdf_conversion import LOW, conversion_items
from app.main import app
from app.models.pdf_inspection import PdfInspection, PdfLinkCounts, PdfPageEvidence, PdfPageInspection
from app.services import ingestion_service
from app.services.ingestion_service import build_document_from_upload
from tests.fakes import FakeAIProvider

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"
client = TestClient(app, base_url="https://testserver")


def _ai() -> FakeAIProvider:
    return FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)


def _import(name: str):
    return asyncio.run(build_document_from_upload((FIXTURES / name).read_bytes(), name, None, _ai()))


def _aspects(document) -> dict:
    return {aspect.aspect: aspect for aspect in document.pdfConversion.aspects}


def _features(document) -> dict:
    return {item.feature: item for item in document.importReport.items}


def test_the_structure_fixture_s_conversion():
    document = _import("structure.pdf")
    conversion = document.pdfConversion
    aspects = _aspects(document)
    assert conversion.rebuilt and (conversion.blocks, conversion.lowConfidenceBlocks) == (16, 2)
    assert {name: (aspect.confidence, aspect.count) for name, aspect in aspects.items()} == {
        "text": (0.95, 16),
        "paragraphs": (0.88, 6),
        "headings": (0.83, 5),
        "lists": (0.78, 3),
        "captions": (0.75, 1),
        "pictures": (0.75, 1),
        "readingOrder": (0.75, 0),
    }
    assert "1 of them a guess" in aspects["headings"].note and "paragraph run on" in aspects["readingOrder"].note
    # The figure is in its place: nothing holds the conversion down but its blocks and its reading order.
    assert conversion.confidence == 0.75 and _features(document)["pdf.layout"].confidence == 0.75
    assert sum(1 for element in document.elements if element.confidence < LOW) == conversion.lowConfidenceBlocks


def test_a_plain_text_pdf_is_sure_of_itself():
    conversion = _import("text.pdf").pdfConversion
    assert (conversion.confidence, conversion.lowConfidenceBlocks) == (0.9, 0)
    assert set(_aspects(_import("text.pdf"))) == {"text", "paragraphs", "headings", "readingOrder"}


def test_what_isn_t_rebuilt_yet_holds_the_confidence_down():
    table = _import("table.pdf")  # ruled: rebuilt, nothing held down (columns of space alone: tests/test_pdf_tables.py)
    assert (_aspects(table)["tables"].confidence, _aspects(table)["tables"].count, table.pdfConversion.confidence) == (0.9, 1, 0.9)
    assert _aspects(table)["tables"].note == "1 ruled table rebuilt, cell by cell."
    columns = _import("columns.pdf")
    assert (_aspects(columns)["columns"].count, _aspects(columns)["readingOrder"].confidence, columns.pdfConversion.confidence) == (1, 0.75, 0.75)
    turned = _import("rotated.pdf")
    assert _aspects(turned)["readingOrder"].confidence == 0.55 and "turned text" in _aspects(turned)["readingOrder"].note
    hybrid = _import("hybrid.pdf")
    text = _aspects(hybrid)["text"]
    assert text.confidence == 0.5 and "text layer over a scan" in text.note and "1 scanned page had no text" in text.note
    assert hybrid.pdfConversion.confidence == 0.5


def test_what_the_pdf_holds_that_the_document_doesn_t_is_said():
    text = _features(_import("text.pdf"))
    assert text["pdf.annotations"].reason == "What was marked on the PDF's pages -- 1 note -- wasn't imported."
    assert (text["pdf.annotations"].count, text["pdf.annotations"].contentChanged) == (1, True)
    assert text["pdf.outline"].count == 3 and "3 entries" in text["pdf.outline"].reason
    # The javascript: link and the one into the file; the web link is kept as a link.
    assert text["pdf.links"].count == 2 and "came in as their text" in text["pdf.links"].reason
    form = _features(_import("form.pdf"))
    assert (form["pdf.form_fields"].count, form["pdf.form_fields"].policy, form["pdf.form_fields"].contentChanged) == (3, "unsupported", True)
    assert not {"pdf.annotations", "pdf.outline", "pdf.links"} & set(_features(_import("columns.pdf")))


def test_annotation_kinds_are_named_in_words():
    page = PdfPageInspection(
        number=1, kind="text", confidence=1.0, reason="", width=595, height=842, rotation=0, boxes={}, characters=0, lines=0,
        rectangles=0, curves=0, imageCount=0,
        evidence=PdfPageEvidence(textCoverage=0.1, imageCoverage=0.0, visibleCharacters=10, invisibleCharacters=0),
        links=PdfLinkCounts(web=2), annotations={"Highlight": 2, "Text": 1, "Popup": 1, "Link": 2, "Square": 2},
    )
    inspection = PdfInspection(pageCount=1, complete=True, pages=[page])
    (item,) = conversion_items(inspection, rebuilt=True)
    assert item.reason == "What was marked on the PDF's pages -- 2 highlights, 2 boxes, 1 note -- weren't imported." and item.count == 5
    # Imported as text alone, web links are lost too.
    assert [item.count for item in conversion_items(inspection, rebuilt=False) if item.feature == "pdf.links"] == [2]


def test_the_text_alone_says_its_structure_wasn_t_rebuilt(monkeypatch):
    def broken(*_, **__):
        raise RuntimeError("a bug in the reconstruction")

    monkeypatch.setattr(ingestion_service, "page_lines", broken)
    document = _import("text.pdf")
    conversion = document.pdfConversion
    assert not conversion.rebuilt and conversion.confidence == 0.5
    assert _aspects(document)["readingOrder"].note.startswith("The text read's order")
    assert _features(document)["pdf.links"].count == 3  # the web link too: the text alone keeps no link


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = _ai
    assert client.post("/api/v1/auth/register", json={"email": "conversion@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def test_the_conversion_is_kept_with_the_document_as_imported(signed_in):
    document = client.post("/api/v1/documents/upload", files={"file": ("text.pdf", (FIXTURES / "text.pdf").read_bytes(), "application/pdf")}).json()
    conversion = document["pdfConversion"]
    assert conversion["rebuilt"] and conversion["confidence"] == 0.9
    elements = document["elements"]
    elements[1]["content"] = "Edited."
    elements[1]["inline"] = [{"text": "Edited.", "marks": []}]
    assert client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements}).status_code == 200
    assert client.get(f"/api/v1/documents/{document['id']}").json()["pdfConversion"] == conversion
    pasted = client.post("/api/v1/documents", json={"text": "# Notes\n\nSome text."}).json()
    assert pasted["pdfConversion"] is None
