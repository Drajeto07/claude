"""Golden documents (корекции.docx §44, §45): real Word files in
tests/fixtures/documents/ (built by scripts/make_golden_documents.py), each
imported into the canonical model, formatted, exported to Word, imported again
and compared -- so nothing is lost silently on the way. Then the critical
round trip through the API: upload, the editor's save, formatting, export and
re-import of a document with everything in it."""

import io
import os
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient

from app.export.docx_export import build_docx
from app.formatting.engine import apply_formatting
from app.formatting.templates import BUILTIN_TEMPLATES
from app.main import app
from app.models.document import Document, ElementType, MarkType, plain_text_from_inline
from app.parsers.docx import parse_docx

FIXTURES = Path(__file__).parent / "fixtures" / "documents"
GOLDEN = sorted(path.name for path in FIXTURES.glob("*.docx"))
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Said on import only: after an export the notes are in the body already.
_IMPORT_ONLY_NOTES = {"Footnotes and endnotes were moved to the end of the document."}


def _import(name: str) -> Document:
    return parse_docx((FIXTURES / name).read_bytes(), name)


def _text(value: str | None) -> str:
    return " ".join((value or "").split())


def _signature(document: Document) -> list[tuple]:
    """Everything the document says, element by element: kind, text, heading
    level, list items with their levels and checkboxes, table cells with their
    spans and shading, pictures, and each run's formatting and link."""
    rows = []
    for element in document.elements:
        entry: tuple = (element.type.value, _text(element.content))
        if element.type == ElementType.HEADING:
            entry += (element.level,)
        if element.type == ElementType.LIST:
            entry += (element.ordered, tuple((_text(plain_text_from_inline(item.inline)), item.level, item.checked) for item in element.listItems))
        if element.type == ElementType.TABLE:
            entry += (
                tuple(
                    tuple((_text(plain_text_from_inline(cell.inline)), cell.colspan, cell.rowspan, cell.background) for cell in row.cells)
                    for row in element.table.rows
                ),
            )
        if element.type == ElementType.IMAGE:
            entry += (bool(element.image and (element.image.src or element.image.assetId)),)
        runs = tuple(
            (run.text, tuple(sorted(mark.type.value for mark in run.marks)), tuple(mark.href for mark in run.marks if mark.type == MarkType.LINK))
            for run in element.inline or []
            if run.marks
        )
        rows.append(entry + ((runs,) if runs else ()))
    return rows


def _page(document: Document) -> tuple:
    s = document.settings
    return (s.pageSize, s.orientation, s.marginLeftCm, s.marginRightCm, s.marginTopCm, s.marginBottomCm, s.header, s.footer)


def _elements(document: Document, kind: ElementType):
    return [element for element in document.elements if element.type == kind]


# -- what each golden document imports as ------------------------------------------------


def test_the_golden_set_is_all_there():
    assert GOLDEN == [
        "01-simple.docx",
        "02-rich-text.docx",
        "03-tables.docx",
        "04-images.docx",
        "05-links.docx",
        "06-lists.docx",
        "07-headings.docx",
        "08-caption.docx",
        "09-sections.docx",
        "10-header-footer.docx",
        "11-page-breaks.docx",
        "12-complex.docx",
    ]


def test_01_simple():
    document = _import("01-simple.docx")

    assert [(element.type, _text(element.content)) for element in document.elements] == [
        (ElementType.HEADING, "Annual Report"),
        (ElementType.PARAGRAPH, "This report summarises the year."),
        (ElementType.PARAGRAPH, "Revenue grew in every quarter."),
        (ElementType.PARAGRAPH, "Отчетът обобщава годината и резултатите от нея."),
    ]
    assert document.metadata.title == "Annual Report"


def test_02_rich_text():
    paragraph = _import("02-rich-text.docx").elements[0]

    formatted = [(run.text, {mark.type: mark for mark in run.marks}) for run in paragraph.inline if run.marks]
    assert [(text, set(marks)) for text, marks in formatted[:6]] == [
        ("bold", {MarkType.BOLD}),
        ("italic", {MarkType.ITALIC}),
        ("underlined", {MarkType.UNDERLINE}),
        ("struck", {MarkType.STRIKE}),
        ("2", {MarkType.SUPERSCRIPT}),
        ("2", {MarkType.SUBSCRIPT}),
    ]
    styles = {text: marks[MarkType.TEXT_STYLE] for text, marks in formatted[6:]}
    assert styles["red"].color == "#C00000"
    assert styles["highlighted"].backgroundColor == "#FFFF00"
    assert styles["Georgia"].fontFamily == "Georgia"
    assert styles["large"].fontSizePt == 18.0
    assert _text(paragraph.content) == "Plain, bold, italic, underlined, struck, E=mc2, H2O, red, highlighted, Georgia and large."


def test_03_tables():
    [table] = _elements(_import("03-tables.docx"), ElementType.TABLE)

    cells = [[(_text(plain_text_from_inline(cell.inline)), cell.colspan, cell.rowspan) for cell in row.cells] for row in table.table.rows]
    assert cells == [
        [("Item", 1, 1), ("Quarter", 1, 1), ("Price", 1, 1)],
        [("Paper", 1, 1), ("Q1", 1, 1), ("12.50", 1, 2)],
        [("Ink, all quarters", 2, 1)],
    ]
    assert [cell.background for cell in table.table.rows[0].cells] == ["#D9EAF7"] * 3
    assert table.table.alignments[0] == "center"


def test_04_images():
    document = _import("04-images.docx")

    images = _elements(document, ElementType.IMAGE)
    assert len(images) == 2 and all(image.image.src.startswith("data:image/png;base64,") for image in images)
    first = document.resolvedStyles[images[0].styleRef]
    assert (first["margin-left"], first["margin-right"]) == ("auto", "auto")
    assert first["width"].endswith("%")


def test_05_links():
    document = _import("05-links.docx")

    links = {run.text: mark.href for element in document.elements for run in element.inline or [] for mark in run.marks if mark.type == MarkType.LINK}
    assert links == {
        "the documentation": "https://example.com/docs",
        "write to us": "mailto:team@example.org",
        "www.example.net": "https://www.example.net",
    }
    kinds = [piece["kind"] for element in document.elements for piece in (element.preservedAttributes or {}).get("ooxml", [])]
    assert kinds == ["bookmark", "link"]


def test_06_lists():
    bullets, numbers, checklist = _elements(_import("06-lists.docx"), ElementType.LIST)

    assert [(plain_text_from_inline(item.inline), item.level) for item in bullets.listItems] == [
        ("Fruit", 0),
        ("Apples", 1),
        ("Green apples", 2),
        ("Bread", 0),
    ]
    assert numbers.ordered and [item.level for item in numbers.listItems] == [0, 0, 1, 0]
    assert [(plain_text_from_inline(item.inline), item.checked) for item in checklist.listItems] == [("Write the report", False), ("Book the room", True)]


def test_07_headings():
    headings = _elements(_import("07-headings.docx"), ElementType.HEADING)

    assert [(heading.level, heading.content) for heading in headings] == [(level, f"Heading level {level}") for level in range(1, 7)]


def test_08_caption():
    document = _import("08-caption.docx")

    assert [element.type for element in document.elements] == [
        ElementType.IMAGE,
        ElementType.CAPTION,
        ElementType.CAPTION,
        ElementType.TABLE,
        ElementType.PARAGRAPH,
    ]
    assert [element.content for element in _elements(document, ElementType.CAPTION)] == ["Figure 1: The blue box.", "Table 1. Quarterly prices"]


def test_09_sections():
    settings = _import("09-sections.docx").settings

    assert (settings.pageSize, settings.orientation) == ("Letter", "landscape")
    assert (settings.marginLeftCm, settings.marginRightCm, settings.marginTopCm, settings.marginBottomCm) == (2.0, 2.0, 2.5, 2.5)


def test_10_header_footer():
    settings = _import("10-header-footer.docx").settings

    assert (settings.header, settings.footer) == ("Quarterly report", "Page {PAGE} of {NUMPAGES}")


def test_11_page_breaks():
    assert [element.type for element in _import("11-page-breaks.docx").elements] == [
        ElementType.PARAGRAPH,
        ElementType.PAGE_BREAK,
        ElementType.PARAGRAPH,
        ElementType.PAGE_BREAK,
        ElementType.PARAGRAPH,
        ElementType.HORIZONTAL_RULE,
        ElementType.PARAGRAPH,
    ]


def test_12_complex():
    document = _import("12-complex.docx")

    assert [element.type.value for element in document.elements] == [
        "heading", "paragraph", "heading", "list", "quote", "code_block", "caption", "table", "image", "caption",
        "page_break", "heading", "paragraph", "footnote",
    ]  # fmt: skip
    intro = document.elements[1]
    assert _text(intro.content) == "A report with bold and italic words, a link and a note1."
    assert [mark.href for run in intro.inline for mark in run.marks if mark.type == MarkType.LINK] == ["https://example.com/report"]
    assert document.elements[-1].content.endswith("Sources are listed at the end.")
    assert document.settings.footer == "Page {PAGE} of {NUMPAGES}"


# -- import -> format -> export -> re-import -> compare -----------------------------------


@pytest.mark.parametrize("name", GOLDEN)
def test_a_formatted_export_loses_nothing(name):
    original = _import(name)
    formatted = original.model_copy(deep=True)
    template = BUILTIN_TEMPLATES["academic-default"]
    apply_formatting(formatted, template_id=template.id, template_rules=template.rules, instruction_rules=[])

    again = parse_docx(build_docx(formatted), name)

    assert _signature(again) == _signature(original)
    assert _page(again) == _page(formatted)  # the template's page setup, which is what was exported
    assert again.resolvedStyles["Paragraph"]["font-family"] == "Times New Roman"
    # No new warnings, and every one that still applies is said again.
    assert set(again.unsupportedFeatures) <= set(original.unsupportedFeatures)
    assert set(original.unsupportedFeatures) - _IMPORT_ONLY_NOTES <= set(again.unsupportedFeatures)


@pytest.mark.parametrize("name", GOLDEN)
def test_an_unformatted_export_keeps_the_documents_own_look(name):
    original = _import(name)

    again = parse_docx(build_docx(original), name)

    assert _signature(again) == _signature(original)
    assert _page(again) == _page(original)


# -- the critical round trip, through the API (§45) --------------------------------------


@pytest.fixture
def client(api_db):
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/register", json={"email": "golden@example.com", "password": "long enough password"}).status_code == 201
    return client


def _critical_round_trip(client: TestClient, name: str, data: bytes) -> None:
    uploaded = client.post("/api/v1/documents/upload", files={"file": (name, data, _DOCX)})
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()
    before = _signature(Document.model_validate(document))

    # The editor's save: the elements as the editor sends them back, with one edit typed in.
    elements = document["elements"]
    index = next(index for index, element in enumerate(elements) if element["type"] == "paragraph" and element["content"].strip())
    edited = elements[index]
    edited["content"] = edited["content"] + " Edited in the editor."
    edited["inline"] = (edited.get("inline") or []) + [{"text": " Edited in the editor.", "marks": []}]
    saved = client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements}, headers={"If-Match": str(document["revision"])})
    assert saved.status_code == 200, saved.text

    formatted = client.post(f"/api/v1/documents/{document['id']}/format", data={"templateId": "academic-default"})
    assert formatted.status_code == 200, formatted.text
    exported = client.get(f"/api/v1/documents/{document['id']}/export/docx")
    assert exported.status_code == 200 and exported.headers["content-type"] == _DOCX

    again = parse_docx(exported.content, name)
    expected = list(before)
    expected[index] = (before[index][0], before[index][1] + " Edited in the editor.", *before[index][2:])  # the typed text has no marks
    assert _signature(again) == expected
    assert again.resolvedStyles["Paragraph"]["font-family"] == "Times New Roman"
    # Pictures went into asset storage on upload and came back out into the Word file.
    assert len(_elements(again, ElementType.IMAGE)) == sum(1 for row in before if row[0] == "image")


def test_a_real_document_survives_upload_editing_formatting_and_export(client):
    _critical_round_trip(client, "12-complex.docx", (FIXTURES / "12-complex.docx").read_bytes())


@pytest.mark.skipif(not os.environ.get("SMARTDOC_REAL_DOCX"), reason="set SMARTDOC_REAL_DOCX to the path of a real Word file to check it too")
def test_a_users_own_document_survives_the_round_trip(client):
    """Run with SMARTDOC_REAL_DOCX=<path> to put any real document (one that
    can't be committed) through the same round trip."""
    path = Path(os.environ["SMARTDOC_REAL_DOCX"])
    _critical_round_trip(client, path.name, path.read_bytes())


def test_the_frontend_golden_json_is_current():
    """frontend/tests/fixtures/golden/ holds what the importer makes of each golden
    document, for the editor's own round-trip tests. Regenerate with
    `python -m scripts.export_golden_json` after changing the importer."""
    target = Path(__file__).resolve().parents[2] / "frontend" / "tests" / "fixtures" / "golden"
    for name in GOLDEN:
        committed = Document.model_validate_json((target / name.replace(".docx", ".json")).read_text(encoding="utf-8"))
        assert _signature(committed) == _signature(_import(name)), name
        assert _page(committed) == _page(_import(name)), name


def test_the_fixtures_are_what_the_builder_makes():
    """The committed files and scripts/make_golden_documents.py agree, so a
    fixture is never edited by hand without the builder knowing."""
    from scripts.make_golden_documents import build

    for name in GOLDEN:
        built = parse_docx(build(name), name)
        assert _signature(built) == _signature(_import(name)), name
        assert DocxDocument(io.BytesIO(build(name))).core_properties.author == "SmartDoc golden fixtures"
