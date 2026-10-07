"""Frames (tracker P2E-020): where a block is meant to sit when it isn't in the flow of the text,
asked the same way of any block -- a Word file's floating picture or text box from its anchor, a
layout-focused PDF import's block from its box on the page -- and none for a block in the flow,
or a PDF imported as an editable document (its boxes say only where the text came from)."""

import asyncio
from pathlib import Path

import pytest

from app.ai.base import AIStructuredOutputError
from app.formatting.frames import PT_PER_CM, frame_of, frames
from app.models.document import Document, Element, ElementType, ImageContent, ImagePlacement, TextBoxContent
from app.services.ingestion_service import build_document_from_docx, build_document_from_upload
from tests.fakes import FakeAIProvider

FIXTURES = Path(__file__).parent / "fixtures"


def test_a_floating_picture_from_word_is_framed_as_its_anchor_says():
    picture = Element(
        type=ElementType.IMAGE,
        content="",
        order=0,
        image=ImageContent(
            src="",
            widthCm=4,
            heightCm=3,
            placement=ImagePlacement(wrap="square", horizontalFrom="margin", horizontalCm=2.54, verticalFrom="paragraph", verticalAlign="top", distanceLeftCm=0.32, side="right"),
        ),
    )
    frame = frame_of(Document(elements=[picture]), picture)
    assert frame.source == "docx-anchor" and frame.wrap == "square" and frame.page is None
    assert (frame.horizontal.relativeTo, frame.horizontal.offsetPt) == ("margin", 72.0)
    assert (frame.vertical.relativeTo, frame.vertical.offsetPt, frame.vertical.align) == ("paragraph", None, "top")
    assert (frame.widthPt, frame.heightPt) == (round(4 * PT_PER_CM, 2), round(3 * PT_PER_CM, 2))
    assert frame.distancePt == (0, 0, 0, round(0.32 * PT_PER_CM, 2))


def test_word_files_floating_pictures_and_text_boxes_have_frames_and_the_rest_none():
    for name in ("a13-pictures.docx", "a09-objects.docx"):
        document = build_document_from_docx((FIXTURES / "word" / name).read_bytes(), name, None)
        framed = frames(document)
        for element in document.elements:
            floating = (element.image and element.image.placement) or (element.textBox and element.textBox.placement)
            assert (element.id in framed) == bool(floating), (name, element.type, element.content[:30])
        assert framed  # each has some


def _pdf(mode: str) -> Document:
    data = (FIXTURES / "pdf" / "structure.pdf").read_bytes()
    provider = FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)
    return asyncio.run(build_document_from_upload(data, "structure.pdf", None, provider, pdf_mode=mode))


@pytest.mark.parametrize("mode", ["layout", "editable"])
def test_a_layout_focused_pdf_import_frames_each_block_on_its_page_and_an_editable_one_none(mode):
    document = _pdf(mode)
    framed = frames(document)
    placed = [element for element in document.elements if element.layout is not None]
    assert placed
    if mode == "editable":
        assert framed == {}
        return
    assert set(framed) == {element.id for element in placed}
    heading = next(element for element in placed if element.content == "Annual review")
    frame = framed[heading.id]
    assert (frame.source, frame.page, frame.wrap) == ("pdf-layout", heading.layout.page, "none")
    assert (frame.horizontal.offsetPt, frame.vertical.offsetPt) == (round(heading.layout.x, 2), round(heading.layout.y, 2))
    assert frame.horizontal.relativeTo == frame.vertical.relativeTo == "page"


def test_a_text_box_in_line_and_a_paragraph_are_in_the_flow():
    box = Element(type=ElementType.TEXT_BOX, content="", order=0, textBox=TextBoxContent(widthCm=5))
    paragraph = Element(type=ElementType.PARAGRAPH, content="Text.", order=1)
    document = Document(elements=[box, paragraph])
    assert frame_of(document, box) is None and frame_of(document, paragraph) is None
