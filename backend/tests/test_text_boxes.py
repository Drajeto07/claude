"""Text boxes as boxes (tracker DOCX-019A): a Word text box is a block of its own holding its
paragraphs -- with its size, outline, fill, insets and where it floats -- shown as a box here and
in a PDF, and written back as a Word text box; before, its text became the document's own
paragraphs and the box survived only while its paragraph was unchanged."""

import io
import re
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfReader

from app.export.docx_export import build_docx
from app.export.package_check import package_problems
from app.export.pdf_export import build_pdf
from app.formatting.engine import recompute_styles
from app.main import app
from app.models.document import Document, Element, ElementType, ImagePlacement, InlineRun, TextBoxContent
from app.parsers.docx import parse_docx
from app.services.ingestion_service import build_document_from_docx

A09 = Path(__file__).parent / "fixtures" / "word" / "a09-objects.docx"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _boxes(document: Document) -> list[Element]:
    return [element for element in document.elements if element.type == ElementType.TEXT_BOX]


def test_a_word_text_box_is_a_box_holding_its_own_paragraphs():
    document = build_document_from_docx(A09.read_bytes(), "a09-objects.docx", None)
    first, second = _boxes(document)
    assert [child.content for child in first.children] == ["Text inside a text box"] and first.inline is None
    look = first.textBox
    assert (look.widthCm, look.heightCm, look.border, look.name) == (6.35, 2.12, "solid 0.5pt #000000", "Text Box 1")
    assert (look.insets.leftCm, look.insets.topCm) == (0.25, 0.13) and look.placement.wrap == "inFront"
    assert second.children[0].content == "Shape text"
    # Its text isn't the document's own paragraphs any more -- and every word is still checked.
    assert not any(element.type == ElementType.PARAGRAPH and element.content == "Text inside a text box" for element in document.elements)
    assert document.importReport.contentStatus == "verified"
    assert "docx.text_box" in {item.feature for item in document.importReport.items}


def _box_document(placement: ImagePlacement | None = None) -> Document:
    inner = [
        Element(type=ElementType.PARAGRAPH, content="A note in a box.", inline=[InlineRun(text="A note in a box.")], order=0),
        Element(type=ElementType.PARAGRAPH, content="Its second line.", inline=[InlineRun(text="Its second line.")], order=1),
    ]
    box = Element(
        type=ElementType.TEXT_BOX, content="A note in a box.\nIts second line.", children=inner, order=1,
        textBox=TextBoxContent(widthCm=5, heightCm=2, border="solid 1pt #C00000", fill="#FFF2CC", name="Note", placement=placement),
    )
    text = Element(type=ElementType.PARAGRAPH, content="The text around it.", inline=[InlineRun(text="The text around it.")], order=0)
    document = Document(elements=[text, box])
    recompute_styles(document)
    return document


@pytest.mark.parametrize("placement", [None, ImagePlacement(wrap="square", side="right", horizontalAlign="right")])
def test_a_text_box_written_anew_is_a_word_text_box_again(placement):
    exported = build_docx(_box_document(placement))
    assert package_problems(exported) == []
    xml = DocxDocument(io.BytesIO(exported)).element.xml
    assert ("wp:anchor" in xml) == (placement is not None) and "w:txbxContent" in xml
    [box] = _boxes(parse_docx(exported, "again.docx"))
    assert [child.content for child in box.children] == ["A note in a box.", "Its second line."]
    look = box.textBox
    assert (look.widthCm, look.heightCm, look.border, look.fill, look.name) == (5.0, 2.0, "solid 1pt #C00000", "#FFF2CC", "Note")
    assert (look.placement.side if look.placement else None) == (placement.side if placement else None)


def test_a_pdf_draws_the_box_with_its_text():
    page = PdfReader(io.BytesIO(build_pdf(_box_document()))).pages[0]
    text = page.extract_text()
    assert "A note in a box." in text and "Its second line." in text and "The text around it." in text
    drawn = page.get_contents().get_data()
    # Its #C00000 outline as a stroke colour (reportlab writes .752941): the box itself, not just its text.
    assert re.search(rb"(?<![\d.])0?\.752941 0 0 RG", drawn)


def test_a_pdf_lays_the_text_after_a_floating_box_beside_it():
    # Found with DOCX-017B: reportlab sizes only pictures beside text, so a floating box with text
    # after it stopped the whole PDF export.
    document = _box_document(ImagePlacement(wrap="square", side="left", horizontalAlign="left"))
    after = "Text after the box, beside it. " * 12
    document.elements.append(Element(type=ElementType.PARAGRAPH, content=after, inline=[InlineRun(text=after)], order=2))
    recompute_styles(document)

    text = PdfReader(io.BytesIO(build_pdf(document))).pages[0].extract_text()

    assert "A note in a box." in text and "Text after the box" in text


def test_only_a_text_box_has_a_box_look_and_its_values_are_checked():
    with pytest.raises(ValidationError):
        Element(type=ElementType.PARAGRAPH, content="x", order=0, textBox=TextBoxContent())
    with pytest.raises(ValidationError):
        TextBoxContent(fill="url(evil)")
    with pytest.raises(ValidationError):
        TextBoxContent(border="solid; background: red")
    assert Element(type=ElementType.TEXT_BOX, content="", order=0).textBox == TextBoxContent()


def test_a_text_box_saved_from_the_editor_keeps_its_blocks_and_look(api_db):
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/register", json={"email": "boxes@example.com", "password": "long enough password"}).status_code == 201
    uploaded = client.post("/api/v1/documents/upload", files={"file": ("a09-objects.docx", A09.read_bytes(), _DOCX)}).json()
    saved = client.put(f"/api/v1/documents/{uploaded['id']}/content", json={"elements": uploaded["elements"]}, headers={"If-Match": str(uploaded["revision"])})
    assert saved.status_code == 200, saved.text[:300]
    boxes = [element for element in saved.json()["elements"] if element["type"] == "text_box"]
    assert len(boxes) == 2 and boxes[0]["textBox"]["widthCm"] == 6.35 and boxes[0]["children"][0]["content"] == "Text inside a text box"
