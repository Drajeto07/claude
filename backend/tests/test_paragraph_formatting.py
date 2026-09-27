"""Word's paragraph formatting beyond spacing and indents (tracker DOCX-014): the
right indent, a background colour (shading), keep with next, keep lines
together, widow and orphan control, contextual spacing and the writing
direction are read from the paragraph and its style, kept as formatting rules,
drawn with CSS's own properties, written back into Word in the schema's order,
and followed by the PDF."""

import io
import zipfile

import pytest
from docx import Document as DocxDocument
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from reportlab.lib.enums import TA_RIGHT

from app.export.docx_export import _P_PR_ORDER, build_docx
from app.export.package_check import package_problems
from app.export.pdf_export import _paragraph_style, build_pdf
from app.formatting.engine import recompute_styles
from app.formatting.values import InvalidRuleValue, clean_rule_value
from app.models.document import FormattingProperty
from app.parsers.docx import parse_docx

_W = nsdecls("w")
_PROPERTIES = (
    '<w:keepNext/><w:keepLines/><w:widowControl w:val="0"/>'
    '<w:shd w:val="clear" w:color="auto" w:fill="FFF2CC"/><w:bidi/>'
    '<w:ind w:right="567"/><w:contextualSpacing/>'
)


def _word_file() -> bytes:
    word = DocxDocument()
    word.styles["Normal"].paragraph_format.widow_control = True  # the paragraph below turns it off
    word.styles["Heading 1"].paragraph_format.keep_with_next = True
    word.add_heading("A heading kept with what follows", level=1)
    formatted = word.add_paragraph("Shaded, indented on the right, right to left, kept together.")
    formatted._p.get_or_add_pPr().extend(parse_xml(f"<w:pPr {_W}>{_PROPERTIES}</w:pPr>"))
    word.add_paragraph("An ordinary paragraph.")
    buffer = io.BytesIO()
    word.save(buffer)
    return buffer.getvalue()


def _document():
    document = parse_docx(_word_file(), "paragraphs.docx")
    recompute_styles(document)
    return document


def test_paragraph_formatting_is_read_from_the_paragraph_and_its_style():
    document = _document()
    heading, formatted, ordinary = document.elements

    assert document.resolvedStyles[heading.styleRef]["break-after"] == "avoid"  # from Heading 1
    css = document.resolvedStyles[formatted.styleRef]
    assert css["margin-right"] == "1cm"
    assert css["background-color"] == "#FFF2CC"
    assert css["break-after"] == "avoid" and css["break-inside"] == "avoid"
    assert (css["widows"], css["orphans"]) == ("1", "1")
    assert css["--contextual-spacing"] == "true" and css["direction"] == "rtl"
    assert "background-color" not in document.resolvedStyles[ordinary.styleRef]


def test_a_word_export_writes_them_back_in_the_schemas_order():
    document = _document()

    exported = build_docx(document)

    assert package_problems(exported) == []
    with zipfile.ZipFile(io.BytesIO(exported)) as package:
        body = parse_xml(package.read("word/document.xml"))
    properties = [p.find(qn("w:pPr")) for p in body.iter(qn("w:p")) if "kept together" in "".join(t.text or "" for t in p.iter(qn("w:t")))][0]
    tags = [child.tag.split("}")[1] for child in properties]
    assert {"keepNext", "keepLines", "widowControl", "shd", "bidi", "ind", "contextualSpacing"} <= set(tags)
    assert tags == sorted(tags, key=_P_PR_ORDER.index)
    again = parse_docx(exported, "again.docx")
    recompute_styles(again)
    before = {key: value for key, value in document.resolvedStyles[document.elements[1].styleRef].items() if key != "font-family"}
    after = {key: value for key, value in again.resolvedStyles[again.elements[1].styleRef].items() if key != "font-family"}
    assert {key: after.get(key) for key in ("margin-right", "background-color", "break-after", "break-inside", "widows", "direction", "--contextual-spacing")} == {
        key: before.get(key) for key in ("margin-right", "background-color", "break-after", "break-inside", "widows", "direction", "--contextual-spacing")
    }


def test_a_pdf_follows_them():
    style = _paragraph_style(
        "p",
        {"margin-right": "1cm", "background-color": "#FFF2CC", "break-after": "avoid", "widows": "1", "direction": "rtl"},
    )

    assert round(style.rightIndent) == 28 and style.keepWithNext == 1
    assert (style.allowWidows, style.allowOrphans) == (1, 1)
    assert style.backColor is not None and style.alignment == TA_RIGHT
    assert build_pdf(_document()).startswith(b"%PDF")


@pytest.mark.parametrize(
    ("prop", "value", "unit"),
    [
        (FormattingProperty.KEEP_WITH_NEXT, "maybe", None),
        (FormattingProperty.DIRECTION, "upwards", None),
        (FormattingProperty.SHADING, "url(x)", None),
        (FormattingProperty.INDENT_RIGHT, "30", "cm"),
    ],
)
def test_a_value_that_cant_be_drawn_is_refused(prop, value, unit):
    with pytest.raises(InvalidRuleValue):
        clean_rule_value(prop, value, unit)


def test_values_are_written_one_way():
    assert clean_rule_value(FormattingProperty.KEEP_LINES_TOGETHER, "Yes", None) == ("true", None)
    assert clean_rule_value(FormattingProperty.DIRECTION, "RTL", None) == ("rtl", None)
    assert clean_rule_value(FormattingProperty.INDENT_RIGHT, "1.50", "cm") == ("1.5", "cm")


def test_contextual_spacing_closes_up_paragraphs_of_the_same_kind_in_a_pdf():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    from app.export.pdf_export import _close_up

    first = Paragraph("One", ParagraphStyle("one", spaceBefore=6, spaceAfter=12))
    second = Paragraph("Two", ParagraphStyle("two", spaceBefore=6, spaceAfter=12))

    _close_up([first], [second])

    assert (first.style.spaceBefore, first.style.spaceAfter) == (6, 0)
    assert (second.style.spaceBefore, second.style.spaceAfter) == (0, 12)
