"""S2-140 (H1, Validation Pack R06 and R08): two diagnosis-only Document Health checks -- paragraphs that look like
headings but aren't (fake_headings) and headers/footers that disagree from section to section (headers_footers).
Deterministic, no AI, nothing in the document changed, no fix offered; conservative: what can be meant is left alone."""

from app.formatting.engine import recompute_styles
from app.formatting.health import check_health, fake_headings, headers_footers_that_disagree
from app.formatting.health_fixes import fix_counts
from app.models.document import Document, Element, ElementType, InlineRun, Mark, MarkType, SectionSettings

_BODY = "The committee met on Monday and reviewed the budget for the coming year in some detail."


def _runs(*parts: tuple[str, list[Mark]]) -> list[InlineRun]:
    return [InlineRun(text=text, marks=marks) for text, marks in parts]


def _bold(size: float | None = 16) -> list[Mark]:
    marks = [Mark(type=MarkType.BOLD)]
    if size is not None:
        marks.append(Mark(type=MarkType.TEXT_STYLE, fontSizePt=size))
    return marks


def _p(text: str = _BODY, marks: list[Mark] | None = None, kind: ElementType = ElementType.PARAGRAPH, **fields) -> Element:
    return Element(type=kind, content=text, inline=_runs((text, marks or [])) if text else None, order=0, **fields)


def _doc(*elements: Element, **document_fields) -> Document:
    for index, element in enumerate(elements):
        element.order = index
    document = Document(elements=list(elements), **document_fields)
    recompute_styles(document)
    return document


def _check(document: Document, check_id: str):
    return next(check for check in check_health(document).checks if check.id == check_id)


# -- R06: paragraphs made to look like headings ----------------------------------------------------------------------


def test_a_bold_larger_line_before_body_text_is_named_with_its_place_and_a_heading_to_use():
    fake = _p("Project background", _bold(16))
    document = _doc(fake, _p(), _p("Delivery plan", _bold(16)), _p())

    check = _check(document, "fake_headings")

    assert check.status == "warn" and check.weight == 2
    assert [issue.elementIds for issue in check.issues] == [[fake.id], [document.elements[2].id]]
    assert check.issues[0].message == "“Project background” looks like a heading (bold, 16 pt against 11 pt body text) but is a plain paragraph: make it Heading 1"
    assert check.fixes == 0  # diagnosis only: nothing is offered to apply


def test_real_headings_and_a_clean_document_pass():
    document = _doc(_p("Introduction", kind=ElementType.HEADING, level=1), _p(), _p("Details", kind=ElementType.HEADING, level=2), _p())

    assert _check(document, "fake_headings").status == "pass"
    assert fake_headings(document) == []


def test_the_proposed_level_is_the_document_s_own_heading_closest_in_size():
    document = _doc(_p("Introduction", kind=ElementType.HEADING, level=1), _p(), _p("Scope", kind=ElementType.HEADING, level=2), _p())
    size_2 = float(document.resolvedStyles["Heading 2"]["font-size"].removesuffix("pt"))
    fake = _p("Methods", _bold(size_2))
    document = _doc(*document.elements, fake, _p())

    [(element, _, _, level)] = fake_headings(document)

    assert element.id == fake.id and level == 2


def test_emphasis_notices_labels_and_sentences_are_left_alone():
    document = _doc(
        _p("Please note", _bold(None)),  # bold at body size: emphasis, not a heading
        _p(),
        _p("Important:", _bold(16)),  # a label introducing what follows
        _p(),
        _p("Draft, not for distribution.", _bold(16)),  # a sentence
        _p(),
        _p("Twelve or more words are a sentence set in bold large type rather than any kind of heading", _bold(16)),
        _p(),
        _p("2026", _bold(16)),  # no letter
        _p(),
    )

    assert fake_headings(document) == []


def test_partly_bold_lines_and_a_last_line_with_nothing_after_it_are_left_alone():
    mixed = Element(type=ElementType.PARAGRAPH, content="Budget overview", inline=_runs(("Budget ", _bold(16)), ("overview", [Mark(type=MarkType.TEXT_STYLE, fontSizePt=16)])), order=0)

    assert fake_headings(_doc(mixed, _p())) == []
    assert fake_headings(_doc(_p(), _p("Thank you", _bold(16)))) == []


def test_lists_captions_quotes_and_table_text_are_never_candidates():
    for kind in (ElementType.LIST, ElementType.CAPTION, ElementType.QUOTE, ElementType.HEADING):
        document = _doc(_p("Project background", _bold(16), kind=kind, **({"level": 1} if kind == ElementType.HEADING else {})), _p())
        assert fake_headings(document) == [], kind


def test_without_the_body_text_s_size_nothing_is_guessed():
    document = _doc(_p("Project background", _bold(16)), _p())
    document.resolvedStyles.pop("Paragraph")

    assert fake_headings(document) == []
    assert _check(document, "fake_headings").status == "pass"


def test_checking_changes_nothing_and_gives_the_same_answer_every_time():
    document = _doc(_p("Project background", _bold(16)), _p())
    before = document.model_dump()

    first, second = check_health(document), check_health(document)

    assert document.model_dump() == before
    assert first == second
    assert fix_counts(document, ["fake_headings", "headers_footers"]) == {}


# -- R08: headers and footers that disagree between sections ----------------------------------------------------------


def _section(**texts) -> Element:
    return Element(type=ElementType.SECTION_BREAK, content="", order=0, sectionBreak=SectionSettings(**texts))


def _sections(*breaks: Element, last: dict | None = None, **settings) -> Document:
    """Body text, then each section break (the section above it ends there), then the last section's text."""
    elements: list[Element] = []
    for section_break in breaks:
        elements += [_p(), section_break]
    elements.append(_p())
    document = _doc(*elements, lastSection=SectionSettings(**(last or {})) if last else None)
    # The last section's main header and footer are the document's settings (as an import leaves them; set after the
    # styles are worked out, which derive the settings from the formatting rules).
    document.settings = document.settings.model_copy(update=settings)
    return document


def test_one_section_is_skipped():
    assert _check(_doc(_p()), "headers_footers").status == "skip"


def test_linked_headers_and_footers_agree():
    document = _sections(_section(header="Northwind Ltd - Annual report 2026", footer="Confidential"))

    check = _check(document, "headers_footers")

    assert check.status == "pass" and headers_footers_that_disagree(document) == []


def test_a_footer_that_stops_after_earlier_sections_had_one_is_named():
    document = _sections(_section(header="Northwind Ltd - Annual report 2026", footer="Confidential"), last={"footer": ""})

    check = _check(document, "headers_footers")

    assert check.status == "warn" and check.weight == 1
    assert [(issue.message, issue.elementIds) for issue in check.issues] == [("Section 2: its footer is empty while section 1's reads “Confidential”", [])]


def test_a_different_year_and_a_name_written_two_ways_are_named_in_the_later_section():
    year = _sections(_section(header="Northwind Ltd - Annual report 2026"), header="Northwind Ltd - Annual report 2025")
    name = _sections(_section(header="Northwind Ltd - Annual report 2026"), header="Northwind Limited - Annual report 2026")

    assert headers_footers_that_disagree(year) == [(2, ["its header has 2025 where section 1's has 2026"])]
    assert headers_footers_that_disagree(name) == [(2, ["its header has “limited” where section 1's has “ltd”"])]


def test_the_validation_pack_case_names_both_header_and_footer_in_one_issue():
    document = _sections(
        _section(header="Northwind Ltd - Annual report 2026", footer="Confidential"), header="Northwind Limited - Annual report 2025", last={"footer": ""}
    )

    [issue] = _check(document, "headers_footers").issues

    assert issue.message == "Section 2: its header has 2025 where section 1's has 2026; its footer is empty while section 1's reads “Confidential”"


def test_a_cover_page_without_a_header_and_chapter_headers_are_meant():
    cover = _sections(_section(header="", footer=""), header="Annual report 2026", footer="Page")
    chapters = _sections(_section(header="Annual report - Chapter 1 Introduction"), _section(header="Annual report - Chapter 2 Methods"), header="Annual report - Chapter 3 Results")
    different = _sections(_section(header="Terms and conditions"), header="Price list for the coming season")

    for document in (cover, chapters, different):
        assert headers_footers_that_disagree(document) == []
        assert _check(document, "headers_footers").status == "pass"


def test_first_page_and_even_page_headers_are_not_compared():
    first_page = _sections(_section(header="Northwind Ltd 2026", firstHeader="Northwind Limited 2025", differentFirstPage=True), header="Northwind Ltd 2026")
    even_pages = _sections(_section(header="Northwind Ltd 2026", evenHeader="Northwind Limited 2025"), header="Northwind Ltd 2026")
    even_pages.evenAndOddHeaders = True

    assert headers_footers_that_disagree(first_page) == []
    assert headers_footers_that_disagree(even_pages) == []


def test_with_many_sections_only_the_one_that_disagrees_is_named():
    document = _sections(_section(header="Acme Ltd report 2026"), _section(header=None), _section(header="Acme Ltd report 2025"), header=None)

    # Section 3 sets 2025; section 2 and 4 are linked (repeat the one before) and aren't named for it again.
    assert headers_footers_that_disagree(document) == [(3, ["its header has 2025 where section 1's has 2026"])]


def test_sections_without_any_header_or_footer_pass_and_nothing_is_guessed():
    document = _sections(_section(), _section())

    assert _check(document, "headers_footers").status == "pass"


def test_the_module_s_own_size_reading_is_left_as_it_was_and_a_malformed_size_is_no_error():
    """S2-140's size helper is its own (`_size_points`): the module's `_points`, which the older checks use, still reads
    px and gives 0.0 for nothing -- a same-named helper once replaced it for the whole module (found in review)."""
    from app.formatting import health

    assert health._points("12px") == 9.0 and health._points("16pt") == 16.0 and health._points("") == 0.0
    assert health._size_points("16pt") == 16.0 and health._size_points("12px") is None and health._size_points("1.2.3pt") is None
    document = _doc(_p("Project background", _bold(16)), _p())
    document.resolvedStyles["Paragraph"]["font-size"] = "1.2.3pt"

    assert fake_headings(document) == []  # unknown body size: nothing guessed, and no error (the older checks' own
    # parsing of such a size is theirs, unchanged here; resolved sizes come from the style engine, never malformed)
