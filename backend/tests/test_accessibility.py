"""The accessibility checker (brief §97, tracker FEAT-010): heading hierarchy, alt text, link
labels, table headers, reading order, language and contrast, each naming its blocks."""

import pytest
from fastapi.testclient import TestClient

from app.formatting.accessibility import check_accessibility, contrast_ratio
from app.formatting.engine import recompute_styles
from app.main import app
from app.models.document import (
    Document,
    DocumentMetadata,
    Element,
    ElementType,
    ImageContent,
    ImagePlacement,
    InlineRun,
    Mark,
    MarkType,
    TableCell,
    TableContent,
    TableFloat,
    TableRow,
)

_LONG = "This paragraph has enough words in it to count as real body text for the checks below."


def _el(kind: ElementType, text: str = _LONG, runs: list[InlineRun] | None = None, **fields) -> Element:
    inline = runs if runs is not None else ([InlineRun(text=text, marks=fields.pop("marks", []))] if text else None)
    return Element(type=kind, content=text if runs is None else "".join(run.text for run in runs), inline=inline, order=0, **fields)


def _doc(*elements: Element, language: str | None = "en") -> Document:
    for index, element in enumerate(elements):
        element.order = index
    document = Document(elements=list(elements), metadata=DocumentMetadata(language=language))
    recompute_styles(document)
    return document


def _check(document: Document, check_id: str):
    return next(check for check in check_accessibility(document).checks if check.id == check_id)


def test_an_accessible_document_passes_or_skips_every_check():
    report = check_accessibility(_doc(_el(ElementType.HEADING, "Introduction", level=1), _el(ElementType.PARAGRAPH)))
    assert report.problems == 0 and {check.status for check in report.checks} <= {"pass", "skip"}


def test_headings_start_at_one_go_down_a_step_at_a_time_and_say_something():
    start, skip, empty = _el(ElementType.HEADING, "Part", level=2), _el(ElementType.HEADING, "Deep", level=4), _el(ElementType.HEADING, "", level=2)
    check = _check(_doc(start, _el(ElementType.PARAGRAPH), skip, empty), "a11y_headings")
    assert check.status == "warn"
    assert [issue.elementIds for issue in check.issues] == [[start.id], [skip.id], [empty.id]]
    assert _check(_doc(*[_el(ElementType.PARAGRAPH, " ".join(["word"] * 80)) for _ in range(5)]), "a11y_headings").status == "fail"


def test_links_say_where_they_go():
    def link(text: str, href: str = "https://example.com/report") -> Element:
        return _el(ElementType.PARAGRAPH, runs=[InlineRun(text="See the report "), InlineRun(text=text, marks=[Mark(type=MarkType.LINK, href=href)])])

    vague, address, good = link("click here"), link("https://example.com/reports/2026/annual/final-version.pdf"), link("the annual report")
    split = _el(ElementType.PARAGRAPH, runs=[
        InlineRun(text="the ", marks=[Mark(type=MarkType.LINK, href="https://example.com")]),
        InlineRun(text="report", marks=[Mark(type=MarkType.LINK, href="https://example.com"), Mark(type=MarkType.BOLD)]),
    ])  # one link over two runs: its text is "the report"
    check = _check(_doc(vague, address, good, split), "a11y_links")
    assert [issue.elementIds for issue in check.issues] == [[vague.id], [address.id]]
    assert _check(_doc(good, split), "a11y_links").status == "pass"
    assert _check(_doc(link("тук")), "a11y_links").status == "warn"
    href = "https://example.com/reports/2026/annual/final.pdf"
    split_address = _el(ElementType.PARAGRAPH, runs=[
        InlineRun(text="https://example.com/reports/", marks=[Mark(type=MarkType.LINK, href=href)]),
        InlineRun(text="2026/annual/final.pdf", marks=[Mark(type=MarkType.LINK, href=href), Mark(type=MarkType.ITALIC)]),
    ])  # neither run is long on its own; the link's text is
    assert _check(_doc(split_address), "a11y_links").issues[0].elementIds == [split_address.id]


def _table(header: bool, rows: int = 2) -> Element:
    cells = [TableRow(cells=[TableCell(inline=[InlineRun(text="Cell")], header=header and index == 0)]) for index in range(rows)]
    return Element(type=ElementType.TABLE, content="Cell", table=TableContent(rows=cells, hasHeaderRow=header), order=0)


def test_data_tables_have_a_header_row():
    bare = _table(False)
    check = _check(_doc(_el(ElementType.PARAGRAPH), _table(True), bare, _table(False, rows=1)), "a11y_tables")
    assert check.status == "warn" and check.issues[0].elementIds == [bare.id]  # a one-row table isn't a data table
    headed_cells = _table(True)
    headed_cells.table.hasHeaderRow = False  # its first row's cells are header cells all the same
    assert _check(_doc(_el(ElementType.PARAGRAPH), headed_cells), "a11y_tables").status == "pass"


def test_what_floats_on_the_page_is_flagged_for_its_reading_order():
    floating = Element(type=ElementType.IMAGE, content="", image=ImageContent(src="https://example.com/a.png", alt="A chart", placement=ImagePlacement()), order=0)
    inline = Element(type=ElementType.IMAGE, content="", image=ImageContent(src="https://example.com/b.png", alt="A logo"), order=0)
    floating_table = _table(True)
    floating_table.table.floating = TableFloat()
    check = _check(_doc(_el(ElementType.PARAGRAPH), floating, inline, _table(True), floating_table), "a11y_order")
    assert check.status == "warn" and check.issues[0].elementIds == [floating.id, floating_table.id]


def test_the_language_is_set_and_other_languages_are_marked():
    unset = _check(_doc(_el(ElementType.PARAGRAPH), language=None), "a11y_language")
    assert unset.status == "warn" and "isn't set (it reads as English)" in unset.issues[0].message
    bulgarian = _el(ElementType.PARAGRAPH, "Това е текст на български език и той не е за всеки, но е важен за нас и за тях.")
    other = _check(_doc(_el(ElementType.PARAGRAPH), _el(ElementType.PARAGRAPH), bulgarian), "a11y_language")
    assert other.issues[0].elementIds == [bulgarian.id]


@pytest.mark.parametrize(
    "foreground, background, ratio",
    [((0, 0, 0), (255, 255, 255), 21.0), ((255, 255, 255), (255, 255, 255), 1.0), ((118, 118, 118), (255, 255, 255), 4.54)],
)
def test_contrast_is_wcags(foreground, background, ratio):
    assert round(contrast_ratio(foreground, background), 2) == ratio


def test_faint_text_is_found_where_it_is_and_large_text_needs_less():
    faint = _el(ElementType.PARAGRAPH, marks=[Mark(type=MarkType.TEXT_STYLE, color="#aaaaaa")])  # 2.3:1 on white
    large = _el(ElementType.PARAGRAPH, marks=[Mark(type=MarkType.TEXT_STYLE, color="#888888", fontSizePt=20)])  # 3.5:1, large: enough
    highlighted = _el(ElementType.PARAGRAPH, marks=[Mark(type=MarkType.TEXT_STYLE, color="yellow", backgroundColor="#000000")])
    cell = Element(
        type=ElementType.TABLE, content="Dark", order=0,
        table=TableContent(rows=[TableRow(cells=[TableCell(inline=[InlineRun(text="Dark")], background="#000080")])]),
    )
    check = _check(_doc(_el(ElementType.PARAGRAPH), faint, large, highlighted, cell), "a11y_contrast")
    assert check.status == "fail" and check.issues[0].elementIds == [faint.id, cell.id]
    assert "(lowest 1.3:1)" in check.summary  # the default black text on the navy cell


def test_the_accessibility_endpoint(api_db):
    client = TestClient(app, base_url="https://testserver")
    client.post("/api/v1/auth/register", json={"email": "a11y@example.com", "password": "long enough password"})
    document = client.post("/api/v1/documents", json={"text": "## Not a top heading\n\n[click here](https://example.com)"}).json()

    report = client.get(f"/api/v1/documents/{document['id']}/accessibility").json()

    checks = {check["id"]: check for check in report["checks"]}
    assert set(checks) == {"a11y_headings", "a11y_alt_text", "a11y_links", "a11y_tables", "a11y_order", "a11y_language", "a11y_contrast"}
    assert checks["a11y_headings"]["status"] == checks["a11y_links"]["status"] == "warn" and report["problems"] >= 2
    assert client.get("/api/v1/documents/unknown/accessibility").status_code == 404
