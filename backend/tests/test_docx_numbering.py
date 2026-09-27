"""Word list numbering on import (tracker DOCX-016, FID-002): a list keeps its
top level's number format, where it starts, where it restarts and how it goes
on counting after an interruption -- and what the model can't hold yet is
reported instead of silently renumbered."""

import io

from docx import Document as DocxDocument
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from app.export.docx_export import build_docx
from app.parsers.docx import parse_docx


def _numbering(document, abstract_id: int, levels: list[tuple[str, str, int]]) -> None:
    """Adds a multi-level definition: (numFmt, lvlText, start) per level."""
    xml = "".join(
        f'<w:lvl w:ilvl="{ilvl}"><w:start w:val="{start}"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/></w:lvl>'
        for ilvl, (fmt, text, start) in enumerate(levels)
    )
    numbering = document.part.numbering_part.element
    abstract = parse_xml(f'<w:abstractNum {nsdecls("w")} w:abstractNumId="{abstract_id}">{xml}</w:abstractNum>')
    first_num = numbering.find(f"{{{numbering.nsmap['w']}}}num")
    if first_num is not None:
        first_num.addprevious(abstract)
    else:
        numbering.append(abstract)


def _num(document, num_id: int, abstract_id: int, restart_at: int | None = None) -> None:
    override = f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="{restart_at}"/></w:lvlOverride>' if restart_at is not None else ""
    document.part.numbering_part.element.append(
        parse_xml(f'<w:num {nsdecls("w")} w:numId="{num_id}"><w:abstractNumId w:val="{abstract_id}"/>{override}</w:num>')
    )


def _item(document, text: str, num_id: int, level: int = 0) -> None:
    paragraph = document.add_paragraph(text, style="List Paragraph")
    paragraph._p.get_or_add_pPr().append(
        parse_xml(f'<w:numPr {nsdecls("w")}><w:ilvl w:val="{level}"/><w:numId w:val="{num_id}"/></w:numPr>')
    )


def _import(build):
    document = DocxDocument()
    build(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return parse_docx(buffer.getvalue(), "numbering.docx")


def _lists(document):
    return [element for element in document.elements if element.type == "list"]


def _features(document):
    return {item.feature for item in document.importReport.items}


def test_the_top_levels_format_and_start_are_kept():
    def build(document):
        _numbering(document, 90, [("upperRoman", "%1.", 1)])
        _numbering(document, 91, [("lowerLetter", "%1.", 5)])
        _num(document, 90, 90)
        _num(document, 91, 91)
        _item(document, "first roman", 90)
        document.add_paragraph("between")
        _item(document, "e is the fifth letter", 91)

    roman, letters = _lists(_import(build))
    assert (roman.numbering.start, roman.numbering.format) == (1, "upperRoman")
    assert (letters.numbering.start, letters.numbering.format) == (5, "lowerLetter")


def test_numbering_goes_on_after_an_interruption_and_restarts_where_word_restarts_it():
    def build(document):
        _numbering(document, 92, [("decimal", "%1.", 1)])
        _num(document, 92, 92)
        _num(document, 93, 92, restart_at=1)
        for text in ("a1", "a2", "a3"):
            _item(document, text, 92)
        document.add_paragraph("An interrupting paragraph.")
        _item(document, "a4", 92)  # the same list: Word shows 4
        document.add_paragraph("Another paragraph.")
        _item(document, "b1", 93)  # a new instance restarting at 1

    first, continued, restarted = _lists(_import(build))
    assert first.numbering is None  # 1, 2, 3 needs no numbering of its own
    assert continued.numbering.start == 4
    assert restarted.numbering is None


def test_an_empty_numbered_item_still_takes_its_number():
    def build(document):
        _numbering(document, 94, [("decimal", "%1.", 1)])
        _num(document, 94, 94)
        _item(document, "one", 94)
        _item(document, "", 94)  # Word shows "2." with nothing after it
        _item(document, "three", 94)

    document = _import(build)
    assert _lists(document)[1].numbering.start == 3
    assert "docx.list_numbering.empty_item" in _features(document)


def test_what_the_model_cannot_hold_is_reported():
    def build(document):
        _numbering(document, 95, [("decimal", "Чл. %1.", 1), ("decimal", "%1.%2.", 1)])
        _numbering(document, 96, [("decimalZero", "%1.", 1)])
        _num(document, 95, 95)
        _num(document, 96, 96)
        _item(document, "Article", 95)
        _item(document, "Clause", 95, level=1)
        document.add_paragraph("between")
        _item(document, "zero-padded", 96)

    document = _import(build)
    assert {"docx.list_numbering.label", "docx.list_numbering.multilevel", "docx.list_numbering.format"} <= _features(document)
    items = {item.feature: item for item in document.importReport.items}
    assert items["docx.list_numbering.label"].contentChanged  # "Чл. 1." becomes "1."


def test_a_list_keeps_its_format_start_and_continuation_through_a_round_trip():
    def build(document):
        _numbering(document, 97, [("lowerRoman", "%1.", 3)])
        _num(document, 97, 97)
        _item(document, "iii", 97)
        _item(document, "iv", 97)
        document.add_paragraph("interruption")
        _item(document, "v", 97)

    imported = _import(build)
    again = parse_docx(build_docx(imported), "again.docx")

    assert [(el.numbering.start, el.numbering.format) for el in _lists(again)] == [(3, "lowerRoman"), (5, "lowerRoman")]
