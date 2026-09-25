"""Document Health (корекции.docx §38): deterministic checks, each naming the
elements concerned, and a score from them alone."""

import pytest
from fastapi.testclient import TestClient

from app.formatting.engine import recompute_styles, set_element_override
from app.formatting.health import check_health
from app.main import app
from app.models.document import (
    Document,
    Element,
    ElementType,
    FormattingProperty,
    ImageContent,
    InlineRun,
    ListItem,
    Mark,
    MarkType,
    TableCell,
    TableContent,
    TableRow,
)

_LONG = "This paragraph has enough words in it to count as real body text for the checks below."


def _el(kind: ElementType, text: str = _LONG, **fields) -> Element:
    return Element(type=kind, content=text, inline=[InlineRun(text=text, marks=fields.pop("marks", []))] if text else None, order=0, **fields)


def _doc(*elements: Element) -> Document:
    for index, element in enumerate(elements):
        element.order = index
    document = Document(elements=list(elements))
    recompute_styles(document)
    return document


def _check(document: Document, check_id: str):
    return next(check for check in check_health(document).checks if check.id == check_id)


def test_a_tidy_document_is_healthy():
    document = _doc(
        _el(ElementType.HEADING, "Introduction", level=1),
        _el(ElementType.PARAGRAPH),
        _el(ElementType.HEADING, "Details", level=2),
        _el(ElementType.PARAGRAPH),
    )

    report = check_health(document)

    assert (report.score, report.rating) == (100, "good")
    assert {check.status for check in report.checks} <= {"pass", "skip"}


def test_extra_fonts_in_body_text_are_named_with_where_they_are():
    odd = _el(ElementType.PARAGRAPH, marks=[Mark(type=MarkType.TEXT_STYLE, fontFamily="Comic Sans MS")])
    document = _doc(_el(ElementType.PARAGRAPH), odd)

    check = _check(document, "fonts")

    assert check.status == "warn"
    assert check.issues[0].message.startswith("Comic Sans MS") and check.issues[0].elementIds == [odd.id]


def test_heading_levels_in_several_sizes_or_upside_down_are_found():
    first, second, third = _el(ElementType.HEADING, "One", level=2), _el(ElementType.HEADING, "Two", level=2), _el(ElementType.HEADING, "Top", level=1)
    document = _doc(third, first, second, _el(ElementType.PARAGRAPH))
    set_element_override(document, element_id=second.id, property=FormattingProperty.FONT_SIZE, value="30", unit="pt")

    check = _check(document, "heading_sizes")

    assert check.status == "fail"
    assert second.id in check.issues[0].elementIds


def test_empty_paragraphs_used_as_spacing_are_found():
    blanks = [_el(ElementType.PARAGRAPH, "") for _ in range(3)]
    document = _doc(_el(ElementType.PARAGRAPH), *blanks, _el(ElementType.PARAGRAPH))

    check = _check(document, "spacing")

    assert check.status == "warn"
    assert check.issues[0].elementIds == [blank.id for blank in blanks]


def test_hand_numbered_headings_with_a_gap_fail():
    gap = _el(ElementType.HEADING, "4. Results", level=1)
    document = _doc(_el(ElementType.HEADING, "1. Intro", level=1), _el(ElementType.HEADING, "2. Method", level=1), gap, _el(ElementType.PARAGRAPH))

    check = _check(document, "numbering")

    assert check.status == "fail"
    assert check.issues[0].elementIds == [gap.id] and "4 comes after 2" in check.issues[0].message


def test_numbered_lists_with_typed_numbers_are_doubled():
    doubled = _el(ElementType.LIST, "1. First", ordered=True, listItems=[ListItem(inline=[InlineRun(text="1. First", marks=[])], level=0, checked=None)])

    assert _check(_doc(doubled), "numbering").issues[0].elementIds == [doubled.id]


def test_skipped_heading_levels_and_long_text_without_headings():
    jump = _el(ElementType.HEADING, "Deep", level=3)
    assert _check(_doc(_el(ElementType.HEADING, "Top", level=1), jump), "hierarchy").issues[0].elementIds == [jump.id]

    wall = _doc(*[_el(ElementType.PARAGRAPH, " ".join(["word"] * 120)) for _ in range(6)])
    assert _check(wall, "hierarchy").status == "fail"


@pytest.mark.parametrize(
    "href, usable",
    [("https://example.com/a", True), ("mailto:someone@example.com", True), ("javascript:alert(1)", False), ("https://", False), ("", False), ("www.example.com", False)],
)
def test_links_need_a_usable_address(href, usable):
    link = _el(ElementType.PARAGRAPH, marks=[Mark(type=MarkType.LINK, href=href)])

    assert _check(_doc(link), "links").status == ("pass" if usable else "fail")


def test_figures_without_captions_once_others_have_one():
    image = lambda: Element(type=ElementType.IMAGE, content="", image=ImageContent(src="https://example.com/a.png"), order=0)  # noqa: E731
    captioned, bare = image(), image()
    document = _doc(captioned, _el(ElementType.CAPTION, "Figure 1: A chart"), _el(ElementType.PARAGRAPH), bare)

    check = _check(document, "captions")

    assert check.status == "warn" and check.issues[0].elementIds == [bare.id]


def test_page_breaks_at_the_edges_or_in_a_row():
    first, second, third = (Element(type=ElementType.PAGE_BREAK, content="", order=0) for _ in range(3))
    document = _doc(first, _el(ElementType.PARAGRAPH), second, third, _el(ElementType.PARAGRAPH))

    check = _check(document, "page_breaks")

    assert {tuple(issue.elementIds) for issue in check.issues} == {(first.id,), (third.id,)}


def test_tables_with_and_without_a_header_row():
    def table(header: bool) -> Element:
        rows = [TableRow(cells=[TableCell(inline=[InlineRun(text="Cell", marks=[])], header=header)])]
        return Element(type=ElementType.TABLE, content="Cell", table=TableContent(rows=rows, hasHeaderRow=header), order=0)

    plain = table(False)
    check = _check(_doc(table(True), plain), "tables")

    assert check.status == "warn" and check.issues[0].elementIds == [plain.id]


def test_the_score_weighs_each_check_and_skips_what_does_not_apply():
    odd = _el(ElementType.PARAGRAPH, marks=[Mark(type=MarkType.TEXT_STYLE, fontFamily="Comic Sans MS")])
    document = _doc(_el(ElementType.PARAGRAPH), odd)

    report = check_health(document)
    counted = [check for check in report.checks if check.status != "skip"]
    expected = round(100 * sum(check.weight * {"pass": 1, "warn": 0.5, "fail": 0}[check.status] for check in counted) / sum(check.weight for check in counted))

    assert report.score == expected < 100


def test_the_health_endpoint(api_db):
    client = TestClient(app, base_url="https://testserver")
    client.post("/api/auth/register", json={"email": "health@example.com", "password": "long enough password"})
    document = client.post("/api/documents", json={"text": "# Title\n\nSome body text for the check."}).json()

    report = client.get(f"/api/documents/{document['id']}/health").json()

    assert 0 <= report["score"] <= 100 and report["rating"] in {"good", "fair", "poor"}
    assert {check["id"] for check in report["checks"]} >= {"fonts", "hierarchy", "links"}
    assert client.get("/api/documents/unknown/health").status_code == 404
