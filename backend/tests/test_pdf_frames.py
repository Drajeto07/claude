"""A PDF export honours frames (tracker P2E-021, docs/architecture/layout-preserving.md): a PDF
imported layout-focused comes out with each page its own size and each block in its box on its
page -- turned as its text was -- and a block added since under the one before it; a Word picture
behind or in front of the text is drawn where its anchor says, the text left where it is. Checked
against the drawn pages (pdfminer's boxes of the text and pictures)."""

import asyncio
import io
from pathlib import Path

import pytest
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTFigure, LTImage, LTTextBox, LTTextLine

from app.ai.base import AIStructuredOutputError
from app.export.pdf_export import build_pdf
from app.export.pdf_layout import is_layout_document
from app.formatting.engine import recompute_styles
from app.formatting.frames import frame_of
from app.models.document import Document, Element, ElementType, ImageContent, ImagePlacement, InlineRun
from app.services.ingestion_service import build_document_from_upload
from tests.fakes import FakeAIProvider

PDFS = Path(__file__).parent / "fixtures" / "pdf"


def _imported(name: str, mode: str = "layout") -> Document:
    provider = FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 4)
    return asyncio.run(build_document_from_upload((PDFS / name).read_bytes(), name, None, provider, pdf_mode=mode))


def _pages(pdf: bytes) -> list:
    return list(extract_pages(io.BytesIO(pdf)))


def _lines(page) -> list[LTTextLine]:
    return [line for box in page if isinstance(box, LTTextBox) for line in box if isinstance(line, LTTextLine)]


def _first_line(page, text: str) -> LTTextLine:
    return next(line for line in _lines(page) if line.get_text().strip().startswith(text[:20]))


def test_each_block_of_a_layout_focused_import_is_drawn_in_its_box_on_its_page():
    document = _imported("structure.pdf")
    assert is_layout_document(document)

    pages = _pages(build_pdf(document))

    assert [(round(page.width), round(page.height)) for page in pages] == [(595, 842)] * 3
    checked = 0
    for element in document.elements:
        frame = frame_of(document, element)
        if frame is None or element.type not in (ElementType.HEADING, ElementType.PARAGRAPH, ElementType.CAPTION):
            continue
        page = pages[frame.page - 1]
        line = _first_line(page, element.content)
        assert abs(line.x0 - frame.horizontal.offsetPt) < 3, element.content  # at its box's left edge ...
        assert abs((page.height - line.y1) - frame.vertical.offsetPt) < 8, element.content  # ... and its top
        checked += 1
    assert checked >= 8
    picture = next(element for element in document.elements if element.type == ElementType.IMAGE)
    frame = frame_of(document, picture)
    [drawn] = [item for item in pages[frame.page - 1] if isinstance(item, (LTFigure, LTImage))]
    assert abs(drawn.x0 - frame.horizontal.offsetPt) < 3 and abs((pages[0].height - drawn.y1) - frame.vertical.offsetPt) < 3


def test_columns_stay_side_by_side_and_turned_pages_and_text_stay_turned():
    [page] = _pages(build_pdf(_imported("columns.pdf")))
    assert abs(_first_line(page, "Right column line 1").x0 - 316) < 3  # beside the left one, not under it
    assert abs(_first_line(page, "Left column line 1").x0 - 72) < 3

    document = _imported("rotated.pdf")
    pages = _pages(build_pdf(document))
    assert [(round(page.width), round(page.height)) for page in pages][3] == (842, 595)  # the landscape page
    down = [element for element in document.elements if element.layout and element.layout.rotation == 90][0].layout
    letters = _lines(pages[1])
    assert len(letters) > 10 and all(abs(line.x0 - down.x) < 8 for line in letters)  # one letter a line: running down the page
    assert max(pages[1].height - line.y1 for line in letters) > min(pages[1].height - line.y1 for line in letters) + 100


def _with_added(document: Document, count: int) -> Document:
    after = next(index for index, element in enumerate(document.elements) if element.content.startswith("The steps taken"))
    added = [
        Element(type=ElementType.PARAGRAPH, content=f"Added paragraph {number}.", inline=[InlineRun(text=f"Added paragraph {number}.")], order=0)
        for number in range(count)
    ]
    document.elements[after + 1 : after + 1] = added
    for order, element in enumerate(document.elements):
        element.order = order
    recompute_styles(document)
    return document


def test_a_block_added_since_goes_under_the_one_before_it_and_onto_a_page_of_its_own_when_full():
    document = _with_added(_imported("structure.pdf"), 1)
    pages = _pages(build_pdf(document))
    above = _first_line(pages[0], "The steps taken")
    added = _first_line(pages[0], "Added paragraph 0.")
    assert added.y1 < above.y0 and abs(added.x0 - above.x0) < 3  # under it, at its left edge

    two = _pages(build_pdf(_with_added(_imported("structure.pdf"), 2)))
    first, second = _first_line(two[0], "Added paragraph 0."), _first_line(two[0], "Added paragraph 1.")
    assert second.y1 < first.y0 and abs(second.x0 - first.x0) < 3  # the next one under the first, not over it

    many = _pages(build_pdf(_with_added(_imported("structure.pdf"), 60)))
    assert len(many) == 4  # what doesn't fit on page 1 goes onto a page after it, the PDF's own pages after that
    assert _first_line(many[1], "Added paragraph").get_text().startswith("Added paragraph")
    assert _first_line(many[2], "Results")  # the PDF's second page, still where it was


def test_an_editable_import_flows_as_before():
    document = _imported("structure.pdf", mode="editable")
    assert not is_layout_document(document)
    assert len(_pages(build_pdf(document))) >= 1


def _png() -> str:
    import base64

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (100, 50), "teal").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


TEXT = "The text of the page, which a picture behind or in front of it leaves where it is. " * 4


def _anchored_document(placement: ImagePlacement | None) -> Document:
    elements = [Element(type=ElementType.PARAGRAPH, content=TEXT, inline=[InlineRun(text=TEXT)], order=0)]
    if placement is not None:
        elements.append(Element(type=ElementType.IMAGE, content="", order=1, image=ImageContent(src=_png(), widthCm=4, heightCm=2, placement=placement)))
    elements.append(Element(type=ElementType.PARAGRAPH, content="After it.", inline=[InlineRun(text="After it.")], order=2))
    document = Document(elements=elements)
    recompute_styles(document)
    return document


@pytest.mark.parametrize(
    ("placement", "left_cm", "top_cm"),
    [
        (ImagePlacement(wrap="behind", horizontalFrom="page", horizontalCm=5, verticalFrom="page", verticalCm=10), 5, 10),
        (ImagePlacement(wrap="inFront", horizontalFrom="margin", horizontalAlign="right", verticalFrom="margin", verticalAlign="top"), None, None),
    ],
)
def test_a_picture_behind_or_in_front_of_the_text_is_drawn_where_its_anchor_says(placement, left_cm, top_cm):
    [page] = _pages(build_pdf(_anchored_document(placement)))
    [alone] = _pages(build_pdf(_anchored_document(None)))

    [drawn] = [item for item in page if isinstance(item, (LTFigure, LTImage))]
    cm = 72 / 2.54
    if left_cm is not None:
        assert abs(drawn.x0 - left_cm * cm) < 2 and abs((page.height - drawn.y1) - top_cm * cm) < 2
    else:  # at the right margin's edge, at the top margin's
        from app.export.pdf_export import _SectionPage

        margins = _SectionPage.of(None, Document().settings)
        assert abs(drawn.x1 - (page.width - margins.right)) < 1
        assert abs(drawn.y1 - (page.height - margins.top)) < 1
    # The text is where it is without the picture: nothing moved over or down for it.
    for text in ("The text of the page", "After it."):
        with_picture, without = _first_line(page, text), _first_line(alone, text)
        assert (round(with_picture.x0), round(with_picture.y1)) == (round(without.x0), round(without.y1))
