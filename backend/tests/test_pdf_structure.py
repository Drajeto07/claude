"""PDF -> editable (tracker P2E-001, P2E-002, P2E-008): each PDF fixture
(tests/fixtures/pdf/, scripts/make_pdf_fixtures.py) imports as the document its layout
makes -- headings, paragraphs, lists, captions, columns read one after the other, the
running header and page numbers moved into the document's -- with where each block was
(ElementLayout) and how sure the rebuild is, every word kept and checked; the layout is
the server's, kept through every save; and an import the layout read can't fully stand
behind falls back to the text, saying why. The heuristics' edges are pinned on pages built
here, character by character."""

import asyncio
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.fidelity.content import document_words, words
from app.main import app
from app.models.document import Element, ElementLayout, ElementType, MarkType
from app.parsers import pdf_structure
from app.parsers.pdf import read_pdf
from app.parsers.pdf_geometry import PdfAnnotation, PdfChar, PdfPage
from app.parsers.pdf_structure import GUESS, LIKELY, SURE, UNREADABLE, build_pdf_document, page_lines
from app.services import ingestion_service
from app.services.ingestion_service import NOT_REBUILT_FAILED, NOT_REBUILT_SHORT, build_document_from_upload
from tests.fakes import FakeAIProvider

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"
client = TestClient(app, base_url="https://testserver")
_PDF = "application/pdf"


def _ai() -> FakeAIProvider:
    return FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)


def _import(name: str):
    return asyncio.run(build_document_from_upload((FIXTURES / name).read_bytes(), name, None, _ai()))


def _shape(document) -> list[tuple]:
    """Each block as (type, heading level, text) -- a list as its items' (level, text), a
    picture as its name."""
    shape = []
    for element in document.elements:
        if element.type == ElementType.IMAGE:
            shape.append(("image", element.image.name))
        elif element.type == ElementType.LIST:
            shape.append(("list", element.ordered, [(item.level, "".join(run.text for run in item.inline)) for item in element.listItems]))
        else:
            shape.append((element.type.value, element.level, element.content))
    return shape


def _features(document) -> dict:
    return {item.feature: item for item in document.importReport.items}


# --- the fixtures, as documents ----------------------------------------------------------------


def test_text_pdf_headings_paragraphs_links_and_colours():
    document = _import("text.pdf")
    assert _shape(document) == [
        ("heading", 1, "Quarterly report"),
        ("paragraph", None, "The first paragraph has plain words in Helvetica. It runs over two lines of text."),
        ("paragraph", None, "A second paragraph is set in Times Roman."),
        ("paragraph", None, "A warning in red, in Courier."),
        ("paragraph", None, "Visit the example site."),
        ("paragraph", None, "Do not run this script."),
        ("paragraph", None, "Go to the details."),
        ("heading", 2, "Details"),
        ("paragraph", None, "The second page holds the details. Its words are plain as well."),
    ]
    elements = document.elements
    # The web link is a link; the javascript: one and the one into the file are only text.
    assert [mark.href for mark in elements[4].inline[0].marks if mark.type == MarkType.LINK] == ["https://example.com/report"]
    assert all(not run.marks for run in elements[5].inline + elements[6].inline)
    # The title's blue and the warning's red, kept; a heading set bold isn't marked bold again.
    assert [(mark.type, mark.color) for mark in elements[0].inline[0].marks] == [(MarkType.TEXT_STYLE, "#1a3399")]
    assert [mark.color for mark in elements[3].inline[0].marks] == ["#cc0000"]
    # Where each block was: its page, its box on it, how many lines, how its words were read.
    first = elements[1].layout
    assert (first.page, first.x, first.lines, first.rotation, first.column, first.source) == (1, 72.0, 2, 0, None, "pdf-text")
    assert 90 < first.y < 110 and 200 < first.width < 300 and 20 < first.height < 30
    assert [element.layout.page for element in elements] == [1] * 7 + [2] * 2
    assert all(element.confidence == SURE for element in elements)
    assert (document.settings.pageSize, document.settings.orientation, document.settings.marginLeftCm) == ("A4", "portrait", 2.5)


def test_two_columns_are_read_one_after_the_other():
    document = _import("columns.pdf")
    heading, left, right = document.elements
    assert (heading.type, heading.content) == (ElementType.HEADING, "Two columns")
    assert left.content.startswith("Left column line 1 of the text. Left column line 2") and left.content.endswith("line 20 of the text.")
    assert right.content.startswith("Right column line 1 here.") and right.content.endswith("Right column line 20 here.")
    assert (left.layout.column, left.layout.lines, right.layout.column, right.layout.lines) == (0, 20, 1, 20)
    assert right.layout.x > 300 > left.layout.x + left.layout.width


def test_the_structure_fixture():
    document = _import("structure.pdf")
    assert _shape(document) == [
        ("heading", 1, "Annual review"),
        ("heading", 2, "Overview"),
        ("paragraph", None, "The year brought steady work across every team, and this review sums it up in a few short sections."),
        ("paragraph", None, "A second paragraph starts with an indent instead of a gap, as books set them, and carries on at the margin."),
        ("heading", 3, "Key points"),
        (
            "list",
            False,
            [
                (0, "Sales grew in every region."),
                (0, "Costs stayed close to plan, with two exceptions noted below."),
                (1, "Travel ran over."),
                (1, "Training ran under."),
                (0, "Hiring finished early."),
            ],
        ),
        ("paragraph", None, "The steps taken were these:"),
        ("list", True, [(0, "Reviewed every budget line."), (0, "Agreed the targets."), (0, "Set the next dates.")]),
        ("heading", 2, "Results"),
        ("paragraph", None, "Output rose in each quarter, as the figure shows."),
        ("image", "Page 2, picture 1"),
        ("caption", None, "Figure 1. Output by quarter."),
        (
            "paragraph",
            None,
            "The last quarter closed with more orders than any before it, and the team carried them into the new year "
            "without a pause in the work, which the next review will follow.",
        ),
        ("heading", 2, "Next steps"),
        ("paragraph", None, "The plan resumes at step three:"),
        ("list", True, [(0, "Hire two more people."), (0, "Open the second office.")]),
    ]
    elements = document.elements
    # A bold line at body size is a heading -- a guess; the bullets the font gives no text
    # for are taken for bullets -- a guess too.
    assert (elements[4].confidence, elements[5].confidence) == (GUESS, GUESS)
    assert elements[7].numbering is None and (elements[15].numbering.start, elements[15].numbering.format) == (3, "decimal")
    # The paragraph running on to the last page: where it starts and ends, less sure.
    running = elements[12]
    assert (running.layout.page, running.layout.lastPage, running.layout.lines, running.confidence) == (2, 3, 3, LIKELY)
    assert elements[11].confidence == LIKELY  # "Figure 1" names a caption
    # The running header and the page numbers are the document's now, and the report says so.
    settings = document.settings
    assert (settings.header, settings.footer, settings.showPageNumbers) == ("Annual review - Synthetic Ltd", None, True)
    assert "Annual review - Synthetic Ltd" not in [element.content for element in elements]
    features = _features(document)
    assert features["pdf.running_header"].count == 3 and features["pdf.page_numbers"].count == 3
    assert features["pdf.list_markers"].count == 10
    assert "pdf.unreadable_characters" not in features  # the unreadable glyphs were the bullets
    assert features["pdf.picture_position"].count == 1 and "pdf.images" not in features
    assert document.importReport.content.verified


def test_turned_pages_are_read_in_their_text_s_direction():
    document = _import("rotated.pdf")
    assert [(element.content, element.layout.rotation) for element in document.elements] == [
        ("This page is turned 0 degrees.", 0),
        ("This page is turned 90 degrees.", 90),
        ("This page is turned 270 degrees.", 270),
        ("A landscape page.", 0),
        ("A page with crop, bleed, trim and art boxes.", 0),
    ]
    turned = document.elements[1].layout
    assert turned.width < turned.height  # the box of text running down the page is tall


def test_a_text_layer_over_a_scan_says_so():
    document = _import("hybrid.pdf")
    sources = [(element.layout.page, element.layout.source) for element in document.elements]
    # The scan under page 1's text layer isn't added (its words came in); page 3, a scan with no text, comes in as a picture.
    assert sources == [(1, "pdf-text-layer")] * 4 + [(2, "pdf-text"), (3, "pdf-picture")]
    features = _features(document)
    assert {"pdf.hybrid_pages", "pdf.scanned_pages", "pdf.scan_backgrounds"} <= set(features) and features["pdf.scan_backgrounds"].count == 1


def test_a_ruled_table_is_a_table():
    document = _import("table.pdf")
    assert _shape(document) == [
        ("heading", 1, "Prices"),
        ("table", None, "Item | Size | Count | Price\nPen | S | 10 | 1.20\nBook | M | 2 | 9.50\nDesk | L | 1 | 120.00"),
    ]
    assert "pdf.unruled_tables" not in _features(document)  # the cells' details: tests/test_pdf_tables.py


def test_a_short_line_under_a_picture_is_its_caption_and_other_scripts_stay_as_they_are():
    pictures = _import("pictures.pdf")
    assert (pictures.elements[-1].type, pictures.elements[-1].content, pictures.elements[-1].confidence) == (
        ElementType.CAPTION,
        "A caption under the pictures.",
        GUESS,
    )
    multilingual = _import("multilingual.pdf")
    assert [element.content for element in multilingual.elements] == [
        "Добър ден, свят!",
        "Това е български текст на кирилица.",
        "Καλημέρα κόσμε!",
        "Αυτό είναι ελληνικό κείμενο.",
    ]


@pytest.mark.parametrize("name", sorted(path.name for path in FIXTURES.glob("*.pdf") if path.name != "scanned.pdf"))
def test_every_word_is_kept_and_checked(name):
    document = _import(name)
    assert document.importReport.content.method == "pdf-layout" and document.importReport.content.verified
    assert all(element.layout is not None and element.confidence is not None for element in document.elements)
    # Every word is in the document's blocks, or in its header and footer -- once there, for every page it was on.
    bands = set(words(" ".join(filter(None, [document.settings.header, document.settings.footer]))))
    missing = Counter(words(read_pdf((FIXTURES / name).read_bytes()).text)) - Counter(document_words(document.elements))
    assert all(word.isdigit() or word in {"Page", "of"} | bands for word in missing), missing  # list numbers and page numbers
    assert (document.metadata.sourceType, document.metadata.originalFilename) == ("uploaded_pdf", name)


# --- when the text is used instead --------------------------------------------------------------


def test_when_the_lines_can_t_be_made_the_text_is_imported_and_it_is_said(monkeypatch):
    def broken(*_, **__):
        raise RuntimeError("a bug in the reconstruction")

    monkeypatch.setattr(ingestion_service, "page_lines", broken)
    document = _import("text.pdf")
    assert document.importReport.content.method == "pdf-extracted-text" and document.elements
    assert _features(document)["pdf.structure_not_rebuilt"].reason == ingestion_service.NOT_REBUILT_PARTLY
    assert all(element.layout is None for element in document.elements)

    monkeypatch.setattr(ingestion_service, "page_lines", page_lines)
    monkeypatch.setattr(ingestion_service, "build_pdf_document", broken)
    assert _features(_import("text.pdf"))["pdf.structure_not_rebuilt"].reason == NOT_REBUILT_FAILED


def test_when_the_layout_read_finds_less_text_than_the_text_read_the_text_is_used(monkeypatch):
    def fewer(pages, title, pictures=None, **options):
        for page in pages:
            page.lines = page.lines[:1]  # as if the rest of each page's text had no place on it
        return build_pdf_document(pages, title, pictures, **options)

    monkeypatch.setattr(ingestion_service, "build_pdf_document", fewer)
    document = _import("text.pdf")
    assert _features(document)["pdf.structure_not_rebuilt"].reason == NOT_REBUILT_SHORT
    assert "Its words are plain as well." in " ".join(element.content for element in document.elements)


def test_a_few_words_only_the_text_read_finds_are_said_to_be_missing(monkeypatch):
    def one_fewer(pages, title, pictures=None, **options):
        line = pages[1].lines[-1]
        line.runs = line.runs[:1]
        line.runs[0].text = "Its words are plain as"  # "well." gone
        return build_pdf_document(pages, title, pictures, **options)

    monkeypatch.setattr(ingestion_service, "build_pdf_document", one_fewer)
    item = _features(_import("text.pdf"))["pdf.text_reads_differ"]
    assert (item.count, item.contentChanged) == (1, True) and "“well”" in item.reason


# --- the layout is the server's -----------------------------------------------------------------


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = _ai
    assert client.post("/api/v1/auth/register", json={"email": "layout@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def test_the_layout_is_kept_through_saves_and_never_taken_from_the_editor(signed_in):
    uploaded = client.post("/api/v1/documents/upload", files={"file": ("text.pdf", (FIXTURES / "text.pdf").read_bytes(), _PDF)})
    assert uploaded.status_code == 201
    document = uploaded.json()
    history = client.get(f"/api/v1/documents/{document['id']}/versions").json()
    assert "Imported from PDF file “text.pdf”" in str(history)
    stored = document["elements"][1]["layout"]
    assert stored["page"] == 1 and stored["source"] == "pdf-text"
    second = dict(document["elements"][2]["layout"])

    elements = document["elements"]
    elements[1]["content"] = "Edited."
    elements[1]["inline"] = [{"text": "Edited.", "marks": []}]
    elements[1]["layout"] = None  # what an editor that drops it sends
    elements[2]["layout"] = dict(stored, page=2, x=1.0)  # and one that would move a block's origin
    new = dict(elements[3], id="00000000-0000-4000-8000-000000000001", layout=stored)  # a new block claiming a place
    saved = client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": [*elements[:4], new, *elements[4:]]})
    assert saved.status_code == 200, saved.text[:300]
    after = saved.json()["elements"]
    assert after[1]["content"] == "Edited." and after[1]["layout"] == stored
    assert after[2]["layout"] == second and second["page"] == 1
    assert after[4]["layout"] is None


def test_word_markdown_and_text_documents_carry_no_layout(signed_in):
    pasted = client.post("/api/v1/documents", json={"text": "# Notes\n\nSome text."}).json()
    assert all(element["layout"] is None for element in pasted["elements"])


def test_a_layout_is_only_what_a_page_can_be():
    with pytest.raises(ValidationError):
        ElementLayout(page=0, x=0, y=0, width=1, height=1)
    with pytest.raises(ValidationError):
        ElementLayout(page=1, x=0, y=0, width=1, height=1, rotation=45)
    with pytest.raises(ValidationError):
        ElementLayout(page=1, x=0, y=0, width=-1, height=1)
    assert Element(type=ElementType.PARAGRAPH, content="x", order=0).layout is None


# --- the heuristics, on pages built here --------------------------------------------------------

_W, _H = 595.0, 842.0


def _page(rows: list[tuple[str, float, float]], *, number: int = 1, size: float = 10.0, font: str = "Helvetica", links=()) -> PdfPage:
    """A page whose rows of text start at (x, top), each character half its size wide."""
    page = PdfPage(number=number, width=_W, height=_H, rotation=0, boxes={})
    for text, x, top in rows:
        for character in text:
            page.chars.append(PdfChar(character, font, size, "#000000", (x, top, x + size / 2, top + size), False, True))
            x += size / 2
    page.annotations = list(links)
    return page


def _built(*pages: PdfPage):
    return build_pdf_document([page_lines(page) for page in pages], None)


def test_numbers_that_don_t_count_on_stay_in_the_text():
    structure = _built(_page([("1. First point here.", 72, 100), ("5. Fifth one next.", 72, 114), ("2. And back.", 72, 128)]))
    assert [(element.type, element.content) for element in structure.document.elements] == [
        (ElementType.PARAGRAPH, "1. First point here."),
        (ElementType.PARAGRAPH, "5. Fifth one next."),
        (ElementType.PARAGRAPH, "2. And back."),
    ]
    assert "pdf.list_markers" not in {item.feature for item in structure.items}


def test_a_sentence_starting_with_an_initial_is_no_list():
    structure = _built(_page([("A. Smith wrote the first part of this report.", 72, 100)]))
    (element,) = structure.document.elements
    assert (element.type, element.content) == (ElementType.PARAGRAPH, "A. Smith wrote the first part of this report.")


def test_lettered_items_and_a_list_from_a_later_number():
    structure = _built(_page([("a) one", 72, 100), ("b) two", 72, 114), ("c) three", 72, 128)]))
    (element,) = structure.document.elements
    assert element.ordered and (element.numbering.start, element.numbering.format) == (1, "lowerLetter")
    assert [item.inline[0].text for item in element.listItems] == ["one", "two", "three"]


def test_a_paragraph_runs_on_to_the_next_page_only_mid_sentence():
    running = _built(
        _page([("This sentence does not end", 72, 100)], number=1), _page([("here but on the next page.", 72, 100)], number=2)
    ).document.elements
    assert [element.content for element in running] == ["This sentence does not end here but on the next page."]
    assert (running[0].layout.page, running[0].layout.lastPage, running[0].confidence) == (1, 2, LIKELY)
    ended = _built(_page([("This sentence ends.", 72, 100)], number=1), _page([("another starts.", 72, 100)], number=2)).document.elements
    assert [element.content for element in ended] == ["This sentence ends.", "another starts."]


def test_a_word_broken_at_the_end_of_a_line_is_joined():
    structure = _built(_page([("The import keeps every docu-", 72, 100), ("ment it reads.", 72, 114)]))
    assert structure.document.elements[0].content == "The import keeps every docu-ment it reads."


def test_glyphs_without_text_are_said_and_control_codes_left_out():
    page = _page([("Price X here", 72, 100)])
    page.chars[6] = PdfChar("(cid:150)", "Helvetica", 10.0, "#000000", page.chars[6].box, False, True)
    page.chars.insert(2, PdfChar("(cid:8)", "Helvetica", 10.0, "#000000", (82, 100, 82, 110), False, True))
    structure = _built(page)
    assert structure.document.elements[0].content == f"Price {UNREADABLE} here"
    features = {item.feature: item for item in structure.items}
    assert features["pdf.unreadable_characters"].count == 1 and features["text.control_characters"].count == 1


def test_a_web_link_s_box_makes_its_words_a_link():
    link = PdfAnnotation(kind="Link", box=(72, 98, 117, 112), link="web", target="https://example.com/")  # over "Read this"
    structure = _built(_page([("Read this guide.", 72, 100)], links=[link]))
    runs = structure.document.elements[0].inline
    assert [(run.text, [mark.href for mark in run.marks]) for run in runs] == [("Read this", ["https://example.com/"]), (" guide.", [])]
