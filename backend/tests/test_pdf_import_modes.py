"""How editable a PDF import is (tracker P2E-007, brief §88 and §93): an editable document
(the default) flows its text, joining a paragraph across pages; layout-focused keeps the
pages -- a page break where each began, no paragraph across one -- and the text's own fonts
and sizes. The choice travels through the upload and the import job, and is kept with the
conversion; the import is "Imported from PDF" either way."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.main import app
from app.models.document import Element, ElementLayout, ElementType, MarkType
from app.parsers.pdf_structure import _family, _page_breaks
from app.services.ingestion_service import build_document_from_upload
from tests.fakes import FakeAIProvider

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"
client = TestClient(app, base_url="https://testserver")


def _ai() -> FakeAIProvider:
    return FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)


def _import(name: str, mode: str = "editable"):
    return asyncio.run(build_document_from_upload((FIXTURES / name).read_bytes(), name, None, _ai(), pdf_mode=mode))


def _looks(element) -> set[tuple]:
    runs = list(element.inline or []) + [run for item in element.listItems or [] for run in item.inline]
    return {(mark.fontFamily, mark.fontSizePt) for run in runs for mark in run.marks if mark.type == MarkType.TEXT_STYLE}


def test_layout_focused_keeps_the_pages_and_the_look():
    editable, layout = _import("structure.pdf"), _import("structure.pdf", "layout")
    assert (editable.pdfConversion.mode, layout.pdfConversion.mode) == ("editable", "layout")
    assert ElementType.PAGE_BREAK not in [element.type for element in editable.elements]
    kinds = [element.type for element in layout.elements]
    breaks = [index for index, kind in enumerate(kinds) if kind == ElementType.PAGE_BREAK]
    assert len(breaks) == 2
    # Each break stands between the last block of one page and the first of the next.
    for index in breaks:
        assert layout.elements[index - 1].layout.page + 1 == layout.elements[index + 1].layout.page
    # The paragraph the editable document runs on across pages 2 and 3 is two here, one on each.
    texts = [element.content for element in layout.elements]
    assert "The last quarter closed with more orders than any before it, and the team carried them into the new year without a pause in the" in texts
    assert "work, which the next review will follow." in texts
    assert any(text.endswith("which the next review will follow.") and text.startswith("The last quarter") for text in (e.content for e in editable.elements))
    # Fonts and sizes as the PDF sets them; none in the editable document.
    by_text = {element.content: element for element in layout.elements}
    assert _looks(by_text["Annual review"]) == {("Helvetica", 22.0)}
    assert _looks(by_text["Figure 1. Output by quarter."]) == {("Helvetica", 9.0)}
    assert _looks(next(element for element in layout.elements if element.type == ElementType.LIST)) == {("Helvetica", 11.0)}
    assert all(not _looks(element) for element in editable.elements)
    assert layout.importReport.content.verified
    reason = next(item.reason for item in layout.importReport.items if item.feature == "pdf.layout")
    assert "Layout-focused: each PDF page starts a page" in reason


def test_a_page_with_nothing_on_it_is_still_a_page():
    def on(page: int) -> Element:
        return Element(type=ElementType.PARAGRAPH, content=f"On page {page}.", order=0, layout=ElementLayout(page=page, x=0, y=0, width=1, height=1))

    kinds = [element.type for element in _page_breaks([on(1), on(1), on(3), on(4)])]
    breaks = ElementType.PAGE_BREAK
    assert kinds == [ElementType.PARAGRAPH, ElementType.PARAGRAPH, breaks, breaks, ElementType.PARAGRAPH, breaks, ElementType.PARAGRAPH]


def test_font_families_by_the_names_documents_use():
    assert [_family(name) for name in ("TimesNewRomanPS-BoldMT", "Times-Roman", "Helvetica-Bold", "Courier", "ArialMT", "Calibri,Bold", "Brand-Regular")] == [
        "Times New Roman",
        "Times New Roman",
        "Helvetica",
        "Courier New",
        "Arial",
        "Calibri",
        "Brand",
    ]


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = _ai
    assert client.post("/api/v1/auth/register", json={"email": "modes@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def _file():
    return {"file": ("structure.pdf", (FIXTURES / "structure.pdf").read_bytes(), "application/pdf")}


def test_the_choice_travels_through_the_upload_and_the_import_job(signed_in):
    uploaded = client.post("/api/v1/documents/upload", files=_file(), data={"pdf_mode": "layout"})
    assert uploaded.status_code == 201 and uploaded.json()["pdfConversion"]["mode"] == "layout"
    job = client.post("/api/v1/jobs/import-file", files=_file(), data={"pdf_mode": "layout"}).json()
    assert job["status"] == "succeeded", job
    document = client.get(f"/api/v1/documents/{job['result']['documentId']}").json()
    assert document["pdfConversion"]["mode"] == "layout" and "page_break" in [element["type"] for element in document["elements"]]
    assert client.post("/api/v1/documents/upload", files=_file()).json()["pdfConversion"]["mode"] == "editable"
    assert client.post("/api/v1/documents/upload", files=_file(), data={"pdf_mode": "pixel-perfect"}).status_code == 422
