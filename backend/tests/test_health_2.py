"""Document Health 2.0 (tracker HLTH-001/002): the new checks -- alt text, hidden text, another
language, what the import couldn't keep, sections, lists, empty paragraphs, layout, repeated
formatting -- and the deterministic fixes: proposals that show what they change, apply only
when accepted, and only to the block as it was checked."""

import pytest
from fastapi.testclient import TestClient

from app.fidelity.report import FidelityItem, FidelityPolicy, FidelityReport, FidelityStage
from app.formatting.engine import recompute_styles
from app.formatting.health import check_health
from app.formatting.health_fixes import element_fingerprint, fixes
from app.formatting.proposals import StaleProposalError, accept, prune_stale
from app.main import app
from app.models.document import (
    Document,
    DocumentMetadata,
    Element,
    ElementType,
    ImageContent,
    InlineRun,
    ListItem,
    ListNumbering,
    Mark,
    MarkType,
    SectionSettings,
    TableCell,
    TableContent,
    TableRow,
)

_LONG = "This paragraph has enough words in it to count as real body text for the checks below."
_ENGLISH = "The report is in the drawer and it is not for the public to read, this is the last copy."
_BULGARIAN = "Това е текст на български език и той не е за всеки, но е важен за нас и за тях."


def _el(kind: ElementType, text: str = _LONG, **fields) -> Element:
    return Element(type=kind, content=text, inline=[InlineRun(text=text, marks=fields.pop("marks", []))] if text else None, order=0, **fields)


def _doc(*elements: Element, **fields) -> Document:
    for index, element in enumerate(elements):
        element.order = index
    document = Document(elements=list(elements), **fields)
    recompute_styles(document)
    return document


def _check(document: Document, check_id: str):
    return next(check for check in check_health(document).checks if check.id == check_id)


def _image(alt: str | None = None, width: float | None = None) -> Element:
    return Element(type=ElementType.IMAGE, content="", image=ImageContent(src="https://example.com/a.png", alt=alt, widthCm=width, heightCm=width), order=0)


def _list(*texts: str, ordered: bool = True, levels: list[int] | None = None, numbering: ListNumbering | None = None) -> Element:
    items = [ListItem(inline=[InlineRun(text=text)], level=(levels or [0] * len(texts))[i]) for i, text in enumerate(texts)]
    return Element(type=ElementType.LIST, content="\n".join(texts), listItems=items, ordered=ordered, numbering=numbering, order=0)


def _only(document: Document, check_id: str):
    found = fixes(document, [check_id])
    assert found and {proposal.checkId for proposal in found} == {check_id}
    return found


# --- HLTH-001: the checks ---------------------------------------------------------------------------


def test_pictures_need_alt_text_and_a_file_name_is_none():
    described, named, bare = _image("A bar chart of sales by month"), _image("IMG_0042.JPG"), _image()
    check = _check(_doc(_el(ElementType.PARAGRAPH), described, named, bare), "alt_text")
    assert check.status == "fail" and check.issues[0].elementIds == [named.id, bare.id]
    assert check.fixes == 0  # only a person can say what a picture shows
    assert _check(_doc(_el(ElementType.PARAGRAPH), described), "alt_text").status == "pass"


def test_hidden_text_is_named_and_left_alone():
    hidden = _el(ElementType.PARAGRAPH, marks=[Mark(type=MarkType.HIDDEN)])
    check = _check(_doc(_el(ElementType.PARAGRAPH), hidden), "hidden_text")
    assert (check.status, check.issues[0].elementIds, check.fixes) == ("warn", [hidden.id], 0)


def test_text_in_another_language_is_found_and_marked_as_it():
    english = _el(ElementType.PARAGRAPH, _ENGLISH)
    document = _doc(*[_el(ElementType.PARAGRAPH, _BULGARIAN) for _ in range(3)], english, metadata=DocumentMetadata(language="bg"))
    check = _check(document, "language")
    assert check.status == "warn" and check.issues[0].elementIds == [english.id] and "English" in check.issues[0].message

    [fix] = _only(document, "language")
    document.proposals.append(fix)
    accept(document, fix.id)
    marked = next(element for element in document.elements if element.id == english.id)
    assert all(any(mark.lang == "en" for mark in run.marks) for run in marked.inline)
    assert marked.content == _ENGLISH and _check(document, "language").status == "pass"


def test_what_the_import_could_not_keep_is_listed():
    report = FidelityReport(
        stage=FidelityStage.IMPORT,
        sourceType="docx",
        items=[
            FidelityItem(feature="docx.chart", policy=FidelityPolicy.UNSUPPORTED, reason="A chart was left out", contentChanged=True),
            FidelityItem(feature="docx.bookmark", policy=FidelityPolicy.DETECTED_NOT_EDITABLE, reason="Bookmarks kept for export"),
        ],
    )
    check = _check(_doc(_el(ElementType.PARAGRAPH), importReport=report), "unsupported")
    assert check.status == "fail" and [issue.message for issue in check.issues] == ["A chart was left out"]
    assert _check(_doc(_el(ElementType.PARAGRAPH)), "unsupported").status == "skip"


def _break(**margins) -> Element:
    return Element(type=ElementType.SECTION_BREAK, content="", order=0, sectionBreak=SectionSettings(**margins))


def test_sections_with_margins_almost_alike_are_a_slip_and_get_the_usual_ones():
    slip, meant = _break(marginLeftCm=2.3), _break(marginLeftCm=5.0)
    document = _doc(_el(ElementType.PARAGRAPH), slip, _el(ElementType.PARAGRAPH), _break(), _el(ElementType.PARAGRAPH), meant, _el(ElementType.PARAGRAPH))
    check = _check(document, "sections")
    assert check.status == "warn" and check.issues[0].elementIds == [slip.id]  # 5 cm is a choice, 2.3 a slip

    [fix] = _only(document, "sections")
    document.proposals.append(fix)
    accept(document, fix.id)
    fixed = next(element for element in document.elements if element.id == slip.id)
    assert (fixed.sectionBreak.marginLeftCm, fixed.sectionBreak.marginTopCm) == (2.0, 2.0)


def test_broken_lists_are_found_and_mended_in_one_fix():
    broken = _list("one", "", "deep", levels=[0, 0, 2])
    first, again = _list("a", "b"), _list("c", "d")
    document = _doc(broken, _el(ElementType.PARAGRAPH), first, again)
    check = _check(document, "lists")
    assert {tuple(issue.elementIds) for issue in check.issues} == {(broken.id,), (again.id,)}

    found = {proposal.elementId: proposal for proposal in _only(document, "lists")}
    assert set(found) == {broken.id, again.id}
    mended = found[broken.id].replacement
    assert [item.level for item in mended.listItems] == [0, 1] and mended.content == "one\ndeep"
    assert found[again.id].replacement.numbering.start == 3  # continues from a., b.


def test_empty_paragraphs_have_their_own_check_and_are_deleted_on_acceptance():
    blank = _el(ElementType.PARAGRAPH, "")
    bookmark = _el(ElementType.PARAGRAPH, "", preservedAttributes={"ooxml": [{"kind": "bookmark"}]})  # kept for export: not empty
    document = _doc(_el(ElementType.PARAGRAPH), blank, bookmark, _el(ElementType.PARAGRAPH))
    [fix] = _only(document, "empty_paragraphs")
    assert fix.type == "delete_element" and fix.category.value == "structure" and fix.elementId == blank.id
    document.proposals.append(fix)
    accept(document, fix.id)
    assert blank.id not in {element.id for element in document.elements}
    assert document.revisions[-1].description.startswith("Health fix accepted")


def test_pictures_and_tables_wider_than_the_text_are_shrunk_to_it():
    wide = _image("A diagram", width=25.0)
    table = Element(
        type=ElementType.TABLE, content="x", order=0,
        table=TableContent(rows=[TableRow(cells=[TableCell(inline=[InlineRun(text="x")]), TableCell(inline=[InlineRun(text="y")])])], widthCm=34.0, columnWidthsCm=[17.0, 17.0]),
    )
    fits = _image("A logo", width=5.0)
    document = _doc(_el(ElementType.PARAGRAPH), wide, table, fits)
    check = _check(document, "layout")
    assert check.issues[0].elementIds == [wide.id, table.id]

    found = {proposal.elementId: proposal.replacement for proposal in _only(document, "layout")}
    assert (found[wide.id].image.widthCm, found[wide.id].image.heightCm) == (17.0, 17.0)  # A4, 2 cm margins
    assert (found[table.id].table.widthCm, found[table.id].table.columnWidthsCm) == (17.0, [8.5, 8.5])


def test_formatting_repeating_the_style_is_cleared_and_the_rest_kept():
    document = _doc(_el(ElementType.PARAGRAPH))
    font = document.resolvedStyles["Paragraph"]["font-family"].split(",")[0].strip().strip("'\"")
    repeats = [
        _el(ElementType.PARAGRAPH, marks=[Mark(type=MarkType.TEXT_STYLE, fontFamily=font, color="#ff0000")]) for _ in range(3)
    ]
    document = _doc(_el(ElementType.PARAGRAPH), *repeats)
    check = _check(document, "duplicated_formatting")
    assert check.status == "warn" and check.fixes == 3
    fix = _only(document, "duplicated_formatting")[0]
    marks = fix.replacement.inline[0].marks
    assert [(mark.fontFamily, mark.color) for mark in marks] == [(None, "#ff0000")]  # the red stays, the font goes


def test_skipped_heading_levels_are_fixed_as_a_chain():
    top, deep, deeper = _el(ElementType.HEADING, "Top", level=1), _el(ElementType.HEADING, "Deep", level=3), _el(ElementType.HEADING, "Deeper", level=4)
    document = _doc(top, deep, _el(ElementType.PARAGRAPH), deeper)
    found = {proposal.elementId: proposal.replacement.level for proposal in _only(document, "hierarchy")}
    assert found == {deep.id: 2, deeper.id: 3}


def test_typed_numbers_and_broken_links_are_fixed_keeping_the_text():
    doubled = _list("1. First", "2) Second")
    doubled.listItems.append(ListItem(inline=[InlineRun(text="3. "), InlineRun(text="Third", marks=[Mark(type=MarkType.BOLD)])]))
    doubled.content += "\n3. Third"
    link = _el(ElementType.PARAGRAPH, marks=[Mark(type=MarkType.LINK, href="https://"), Mark(type=MarkType.BOLD)])
    document = _doc(doubled, link)
    [numbers] = _only(document, "numbering")
    assert [[run.text for run in item.inline] for item in numbers.replacement.listItems] == [["First"], ["Second"], ["Third"]]
    assert numbers.after == "First\nSecond\nThird" and numbers.replacement.listItems[2].inline[0].marks[0].type == MarkType.BOLD
    [unlink] = _only(document, "links")
    assert [mark.type for mark in unlink.replacement.inline[0].marks] == [MarkType.BOLD] and unlink.replacement.content == _LONG


def test_stray_fonts_go_back_to_the_style_font():
    odd = _el(ElementType.PARAGRAPH, marks=[Mark(type=MarkType.TEXT_STYLE, fontFamily="Comic Sans MS", fontSizePt=30)])
    document = _doc(_el(ElementType.PARAGRAPH), _el(ElementType.PARAGRAPH), odd)
    [fix] = _only(document, "fonts")
    assert [(mark.fontFamily, mark.fontSizePt) for mark in fix.replacement.inline[0].marks] == [(None, 30)]


# --- HLTH-002: fixes are proposals --------------------------------------------------------------------


def test_a_fix_applies_only_to_the_block_as_it_was_checked():
    blank = _el(ElementType.PARAGRAPH, "")
    document = _doc(_el(ElementType.PARAGRAPH), blank, _el(ElementType.PARAGRAPH))
    [fix] = fixes(document, ["empty_paragraphs"])
    document.proposals.append(fix)
    assert fix.elementHash == element_fingerprint(blank)

    # The user types into the "empty" paragraph before accepting: deleting it now would lose that.
    blank.content, blank.inline = "Now it says something", [InlineRun(text="Now it says something")]
    with pytest.raises(StaleProposalError):
        accept(document, fix.id)
    assert blank.id in {element.id for element in document.elements}
    prune_stale(document)  # what a save does
    assert document.proposals == []


def test_fixes_are_not_proposed_twice_nor_for_passing_checks():
    document = _doc(_el(ElementType.PARAGRAPH), _el(ElementType.PARAGRAPH, ""), _el(ElementType.PARAGRAPH))
    first = fixes(document)
    document.proposals.extend(first)
    assert fixes(document) == [] and _check(document, "empty_paragraphs").fixes == 0
    assert fixes(_doc(_el(ElementType.PARAGRAPH))) == []


@pytest.fixture
def client(api_db):
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/register", json={"email": "health2@example.com", "password": "long enough password"}).status_code == 201
    return client


def test_the_fixes_endpoint_proposes_and_accepting_applies_with_undo(client):
    document = client.post("/api/v1/documents", json={"text": "# Title\n\nBody text.\n\n### Deep heading\n\nMore body text."}).json()
    health = client.get(f"/api/v1/documents/{document['id']}/health").json()
    hierarchy = next(check for check in health["checks"] if check["id"] == "hierarchy")
    assert hierarchy["fixes"] == 1

    proposed = client.post(f"/api/v1/documents/{document['id']}/health/fixes", json={"checkIds": ["hierarchy"]})
    assert proposed.status_code == 200, proposed.text[:300]
    body = proposed.json()
    [proposal] = [waiting for waiting in body["document"]["proposals"] if waiting["source"] == "health"]
    assert body["proposalCount"] == 1 and proposal["reason"].startswith("Heading 3 → Heading 2")
    heading = next(element for element in body["document"]["elements"] if element["content"] == "Deep heading")
    assert heading["level"] == 3  # nothing changed yet
    assert client.post(f"/api/v1/documents/{document['id']}/health/fixes", json={"checkIds": ["hierarchy"]}).json()["proposalCount"] == 0

    accepted = client.post(f"/api/v1/documents/{document['id']}/proposals/{proposal['id']}/accept").json()
    assert next(element for element in accepted["elements"] if element["id"] == heading["id"])["level"] == 2
    assert accepted["proposals"] == []
    undone = client.post(f"/api/v1/documents/{document['id']}/undo").json()
    assert next(element for element in undone["elements"] if element["id"] == heading["id"])["level"] == 3
