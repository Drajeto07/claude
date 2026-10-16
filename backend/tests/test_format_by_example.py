"""Format by Example, hardened (tracker FMT-001..003): a reference's look includes its tables
(border, header shading, bold header), its lists' levels and its heading numbering, and applying
the look sets them on the document; the AI's heading mapping is used only when its levels fit
the headings' sizes; and the look can be tried on the document -- before and after, what
changes -- before anything is saved."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.ai.factory import get_ai_provider
from app.ai.semantic_labeling import AIParagraphLabel, AIParagraphLabels, label_headings
from app.formatting.reference_style import ParagraphLook, _structure
from app.formatting.structure import applies, apply_structure
from app.formatting.style_system import ListStructure, StructureStyle, StyleSystem, TableStructure
from app.main import app
from app.models.document import (
    Document,
    Element,
    ElementType,
    HeadingNumbering,
    InlineRun,
    ListItem,
    ListLevel,
    ListNumbering,
    TableCell,
    TableContent,
    TableBorders,
    TableRow,
)
from app.services.reference_service import extract_from_docx
from scripts.export_expected_losses import FOLDERS
from tests.fakes import FakeAIProvider

client = TestClient(app, base_url="https://testserver")


def _fixture(name: str) -> bytes:
    return next(path for folder in FOLDERS for path in folder.glob(name)).read_bytes()


# --- FMT-001: the reference's structure -----------------------------------------------------------


def test_a_references_tables_and_lists_are_part_of_its_look():
    reference = asyncio.run(extract_from_docx(_fixture("r01-university-paper.docx"), "r01-university-paper.docx", None))
    structure = reference.style_system.structure
    assert structure.tables == TableStructure(border="solid 0.5pt #45B0E1", headerShading="#156082", headerBold=True)
    assert [level.format for level in structure.lists.numberedLevels][:1] == ["decimal"]
    lists = asyncio.run(extract_from_docx(_fixture("06-lists.docx"), "06-lists.docx", None)).style_system.structure.lists
    assert [(level.format, level.text) for level in lists.bulletLevels][:2] == [("bullet", "•"), ("bullet", "•")]
    assert [level.text for level in lists.numberedLevels][:2] == ["%1.", "%2."]


def test_a_border_only_some_of_its_tables_have_is_not_its_look():
    def table(border):
        rows = [TableRow(cells=[TableCell(inline=[InlineRun(text="x")])])]
        return Element(type=ElementType.TABLE, content="", order=0, table=TableContent(rows=rows, borders=TableBorders(insideH=border) if border else None))

    ruled = Document(elements=[table("solid 1pt #000000"), table("solid 1pt #000000"), table(None)])
    assert _structure(ruled).tables.border == "solid 1pt #000000"  # two of its three tables
    mostly_plain = Document(elements=[table("solid 1pt #000000"), table(None), table(None)])
    assert _structure(mostly_plain).tables.border is None  # one of three isn't the reference's look


def _document() -> Document:
    header = TableRow(cells=[TableCell(inline=[InlineRun(text="Item")], header=True), TableCell(inline=[InlineRun(text="Price")], header=True)])
    row = TableRow(cells=[TableCell(inline=[InlineRun(text="Pen")]), TableCell(inline=[InlineRun(text="1")])])
    return Document(
        elements=[
            Element(type=ElementType.TABLE, content="", order=0, table=TableContent(rows=[header, row], hasHeaderRow=True)),
            Element(type=ElementType.LIST, content="a", order=1, ordered=True, numbering=ListNumbering(start=4), listItems=[ListItem(inline=[InlineRun(text="a")])]),
            Element(type=ElementType.LIST, content="b", order=2, listItems=[ListItem(inline=[InlineRun(text="b")])]),
        ]
    )


def test_applying_a_structure_sets_tables_lists_and_heading_numbering():
    structure = StructureStyle(
        tables=TableStructure(border="double 1pt #333333", headerShading="#dddddd", headerBold=False),
        lists=ListStructure(
            bulletLevels=[ListLevel(format="bullet", text="–")],
            numberedLevels=[ListLevel(format="lowerLetter", text="%1)"), ListLevel(format="decimal", text="%2.")],
        ),
        headingNumbering=HeadingNumbering(levels=[ListLevel(format="decimal", text="%1.")], sourceNumId="7"),
    )
    document = _document()
    assert applies(structure) and not applies(StructureStyle())
    assert apply_structure(document, structure) == 3
    table, numbered, bulleted = document.elements
    borders = table.table.borders
    assert {borders.top, borders.bottom, borders.left, borders.right, borders.insideH, borders.insideV} == {"double 1pt #333333"}
    assert [cell.background for cell in table.table.rows[0].cells] == ["#dddddd", "#dddddd"] and table.table.headerBold is False
    assert [cell.background for cell in table.table.rows[1].cells] == [None, None]  # only the header row
    assert (numbered.numbering.start, numbered.numbering.format, [level.text for level in numbered.numbering.levels]) == (4, "lowerLetter", ["%1)", "%2."])
    assert (bulleted.numbering.format, bulleted.numbering.levels[0].text) == ("decimal", "–")
    assert document.headingNumbering.sourceNumId is None and document.headingNumbering.levels[0].text == "%1."


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([])
    assert client.post("/api/v1/auth/register", json={"email": "fbe@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


MARKDOWN = "# Prices\n\n| Item | Price |\n| --- | --- |\n| Pen | 1.20 |\n\n1. First\n2. Second\n\n- one\n- two\n"


def test_a_template_with_a_structure_sets_it_when_applied_and_one_without_leaves_them(signed_in):
    style = {"structure": {"tables": {"border": "solid 1pt #ff0000", "headerShading": "#eeeeee"}, "lists": {"numberedLevels": [{"format": "upperRoman", "text": "%1."}]}}}
    template = client.post("/api/v1/templates", json={"name": "Ruled", "styleSystem": style})
    assert template.status_code == 201, template.text[:300]
    document = client.post("/api/v1/documents", json={"text": MARKDOWN}).json()
    formatted = client.post(f"/api/v1/documents/{document['id']}/format", data={"templateId": template.json()["id"]}).json()["document"]
    table = next(element for element in formatted["elements"] if element["type"] == "table")
    numbered = next(element for element in formatted["elements"] if element["type"] == "list" and element["ordered"])
    bulleted = next(element for element in formatted["elements"] if element["type"] == "list" and not element["ordered"])
    assert table["table"]["borders"]["insideH"] == "solid 1pt #ff0000" and table["table"]["rows"][0]["cells"][0]["background"] == "#eeeeee"
    assert numbered["numbering"]["format"] == "upperRoman" and bulleted["numbering"] is None  # it sets numbered lists only

    other = client.post("/api/v1/documents", json={"text": MARKDOWN}).json()
    plain = client.post(f"/api/v1/documents/{other['id']}/format", data={"templateId": "academic-default"}).json()["document"]
    assert next(element for element in plain["elements"] if element["type"] == "table")["table"]["borders"] is None


# --- FMT-002: the AI's heading mapping, checked ---------------------------------------------------


def _paragraphs(*texts: str) -> Document:
    return Document(elements=[Element(type=ElementType.PARAGRAPH, content=text, inline=[InlineRun(text=text)], order=i) for i, text in enumerate(texts)])


def _looks(document: Document, sizes: list[float]) -> dict[str, ParagraphLook]:
    return {element.id: ParagraphLook(size, False, False, None) for element, size in zip(document.elements, sizes, strict=True)}


def test_the_ais_heading_levels_must_fit_the_headings_sizes():
    document = _paragraphs("Introduction", "Some body text that runs on.", "Background", "More body text here.", "Details", "Body.", "Body again.")
    looks = _looks(document, [18, 11, 14, 11, 14, 11, 11])
    body = ParagraphLook(11, False, False, None)
    ids = [element.id for element in document.elements]
    fits = AIParagraphLabels(labels=[AIParagraphLabel(id=ids[0], role="heading", level=1), AIParagraphLabel(id=ids[2], role="heading", level=2), AIParagraphLabel(id=ids[4], role="heading", level=2)])
    upside_down = AIParagraphLabels(labels=[AIParagraphLabel(id=ids[0], role="heading", level=2), AIParagraphLabel(id=ids[2], role="heading", level=1), AIParagraphLabel(id=ids[4], role="heading", level=1)])
    candidates = [document.elements[i] for i in (0, 2, 4)]
    assert asyncio.run(label_headings(FakeAIProvider([fits]), document, candidates, looks, body)) == {ids[0]: 1, ids[2]: 2, ids[4]: 2}
    # The 18pt line under 14pt ones: the AI's levels don't fit what the reference shows -- not used.
    assert asyncio.run(label_headings(FakeAIProvider([upside_down]), document, candidates, looks, body)) is None


# --- FMT-003: before and after, before it's kept --------------------------------------------------


def test_a_look_is_tried_on_the_document_and_nothing_is_saved(signed_in):
    document = client.post("/api/v1/documents", json={"text": MARKDOWN}).json()
    style = StyleSystem.model_validate(
        {
            "page": {"size": "Letter"},
            "paragraph": {"fontFamily": "Georgia", "fontSizePt": 13},
            "structure": {"tables": {"border": "solid 1pt #000000"}, "lists": {"bulletLevels": [{"format": "bullet", "text": "■"}]}},
        }
    )
    preview = client.post(f"/api/v1/documents/{document['id']}/style-preview", json={"styleSystem": style.model_dump(mode="json")})
    assert preview.status_code == 200, preview.text[:300]
    found = preview.json()
    assert "Georgia" in found["after"]["Paragraph"]["font-family"] and "Georgia" not in found["before"]["Paragraph"]["font-family"]
    assert (found["settingsBefore"]["pageSize"], found["settingsAfter"]["pageSize"]) == ("A4", "Letter")
    assert {"Table: font Arial → Georgia", "Table: size 11pt → 13pt", "List: size 11pt → 13pt"} <= set(found["changes"])
    assert "Page: page size A4 → Letter" in found["changes"] and (found["tables"], found["lists"]) == (1, 1)
    again = client.get(f"/api/v1/documents/{document['id']}").json()
    assert (again["revision"], again["resolvedStyles"], again["settings"]["pageSize"]) == (document["revision"], document["resolvedStyles"], "A4")
