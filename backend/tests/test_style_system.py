from collections import Counter
from typing import get_args

import pytest
from pydantic import ValidationError

from app.export import docx_export, pdf_export
from app.formatting.engine import apply_formatting, extract_settings
from app.formatting.priorities import Priority
from app.formatting.style_system import PageSize, StyleSystem, compile_rules, style_system_from_rules
from app.formatting.templates import BUILTIN_TEMPLATES
from app.formatting.units import to_cm, to_pt
from app.models.document import Document, Element, ElementType, FormattingProperty as P, FormattingRule


def _content(rules: list[FormattingRule]) -> Counter:
    """Rules compared by what they do: ids are random and order doesn't matter."""
    return Counter((r.target, r.property, r.value, r.unit, r.priority, r.source) for r in rules)


def _builtin(target, prop, value, unit=None):
    return FormattingRule(target=target, property=prop, value=value, unit=unit, priority=Priority.BUILTIN_TEMPLATE, source="template")


# The rule lists the three original built-ins were hand-written as before they
# became StyleSystem data, frozen here: moving them must not change a thing.
_BEFORE_STYLE_SYSTEMS = {
    "academic-default": [
        _builtin("Paragraph", P.FONT_FAMILY, "Times New Roman"),
        _builtin("Paragraph", P.FONT_SIZE, "12", "pt"),
        _builtin("Paragraph", P.ALIGNMENT, "justify"),
        _builtin("Paragraph", P.LINE_SPACING, "1.5"),
        _builtin("Paragraph", P.FIRST_LINE_INDENT, "1.25", "cm"),
        _builtin("Heading 1", P.FONT_FAMILY, "Times New Roman"),
        _builtin("Heading 1", P.FONT_SIZE, "14", "pt"),
        _builtin("Heading 1", P.BOLD, "true"),
        _builtin("Heading 2", P.FONT_FAMILY, "Times New Roman"),
        _builtin("Heading 2", P.FONT_SIZE, "13", "pt"),
        _builtin("Heading 2", P.BOLD, "true"),
        _builtin("Heading 3", P.FONT_FAMILY, "Times New Roman"),
        _builtin("Heading 3", P.FONT_SIZE, "12", "pt"),
        _builtin("Heading 3", P.BOLD, "true"),
        _builtin("Heading 3", P.ITALIC, "true"),
        _builtin("Document", P.PAGE_SIZE, "A4"),
        _builtin("Document", P.ORIENTATION, "portrait"),
        _builtin("Document", P.MARGIN_TOP, "2", "cm"),
        _builtin("Document", P.MARGIN_BOTTOM, "2", "cm"),
        _builtin("Document", P.MARGIN_LEFT, "3", "cm"),
        _builtin("Document", P.MARGIN_RIGHT, "2", "cm"),
    ],
    "professional-cv": [
        _builtin("Paragraph", P.FONT_FAMILY, "Calibri"),
        _builtin("Paragraph", P.FONT_SIZE, "11", "pt"),
        _builtin("Paragraph", P.ALIGNMENT, "left"),
        _builtin("Paragraph", P.LINE_SPACING, "1.15"),
        _builtin("Heading 1", P.FONT_FAMILY, "Calibri"),
        _builtin("Heading 1", P.FONT_SIZE, "16", "pt"),
        _builtin("Heading 1", P.BOLD, "true"),
        _builtin("Heading 2", P.FONT_FAMILY, "Calibri"),
        _builtin("Heading 2", P.FONT_SIZE, "12", "pt"),
        _builtin("Heading 2", P.BOLD, "true"),
        _builtin("Document", P.PAGE_SIZE, "A4"),
        _builtin("Document", P.ORIENTATION, "portrait"),
        _builtin("Document", P.MARGIN_TOP, "2", "cm"),
        _builtin("Document", P.MARGIN_BOTTOM, "2", "cm"),
        _builtin("Document", P.MARGIN_LEFT, "2", "cm"),
        _builtin("Document", P.MARGIN_RIGHT, "2", "cm"),
    ],
    "official-standard": [
        _builtin("Paragraph", P.FONT_FAMILY, "Times New Roman"),
        _builtin("Paragraph", P.FONT_SIZE, "12", "pt"),
        _builtin("Paragraph", P.ALIGNMENT, "justify"),
        _builtin("Paragraph", P.LINE_SPACING, "1"),
        _builtin("Heading 1", P.FONT_FAMILY, "Times New Roman"),
        _builtin("Heading 1", P.FONT_SIZE, "13", "pt"),
        _builtin("Heading 1", P.BOLD, "true"),
        _builtin("Document", P.PAGE_SIZE, "A4"),
        _builtin("Document", P.ORIENTATION, "portrait"),
        _builtin("Document", P.MARGIN_TOP, "2.5", "cm"),
        _builtin("Document", P.MARGIN_BOTTOM, "2.5", "cm"),
        _builtin("Document", P.MARGIN_LEFT, "2.5", "cm"),
        _builtin("Document", P.MARGIN_RIGHT, "2.5", "cm"),
    ],
}


@pytest.mark.parametrize("template_id", sorted(_BEFORE_STYLE_SYSTEMS))
def test_original_builtins_compile_to_exactly_the_rules_they_had(template_id):
    assert _content(BUILTIN_TEMPLATES[template_id].rules) == _content(_BEFORE_STYLE_SYSTEMS[template_id])


@pytest.mark.parametrize("template_id", sorted(BUILTIN_TEMPLATES))
def test_every_builtin_formats_and_exports_a_document(template_id):
    document = Document(
        elements=[
            Element(type=ElementType.HEADING, content="Title", order=0, level=1),
            Element(type=ElementType.PARAGRAPH, content="Body text.", order=1),
            Element(type=ElementType.CAPTION, content="Figure 1", order=2),
        ]
    )
    template = BUILTIN_TEMPLATES[template_id]
    apply_formatting(document, template_id=template.id, template_rules=template.rules, instruction_rules=[])

    assert document.resolvedStyles["Paragraph"]
    assert document.resolvedStyles["Heading 1"]
    assert docx_export.build_docx(document)[:2] == b"PK"
    assert pdf_export.build_pdf(document)[:4] == b"%PDF"


def test_an_empty_style_system_sets_nothing():
    assert compile_rules(StyleSystem(), priority=Priority.CUSTOM_TEMPLATE, source="custom_template") == []


def test_document_font_reaches_every_text_block_except_code():
    style = StyleSystem.model_validate(
        {"document": {"fontFamily": "Georgia", "color": "#333333"}, "headings": {"h2": {"fontFamily": "Arial"}}}
    )
    rules = compile_rules(style, priority=Priority.CUSTOM_TEMPLATE, source="custom_template")
    fonts = {r.target: r.value for r in rules if r.property == P.FONT_FAMILY}
    colors = {r.target: r.value for r in rules if r.property == P.COLOR}

    assert fonts["Paragraph"] == fonts["Heading 1"] == fonts["Caption"] == fonts["Table"] == "Georgia"
    assert fonts["Heading 2"] == "Arial"  # a block's own value wins over the document-wide one
    assert "CodeBlock" not in fonts  # code keeps its monospace font...
    assert colors["CodeBlock"] == "#333333"  # ...but does take the text colour
    assert "Image" not in fonts and "Document" not in fonts


def test_compiled_rules_carry_the_requested_tier_and_units():
    style = StyleSystem.model_validate(
        {"paragraph": {"fontSizePt": 10.5, "spaceAfterPt": 6, "firstLineIndentCm": 1}, "images": {"widthPercent": 80}}
    )
    rules = {(r.target, r.property): r for r in compile_rules(style, priority=Priority.CUSTOM_TEMPLATE, source="custom_template")}

    assert (rules[("Paragraph", P.FONT_SIZE)].value, rules[("Paragraph", P.FONT_SIZE)].unit) == ("10.5", "pt")
    assert (rules[("Paragraph", P.PARAGRAPH_SPACING)].value, rules[("Paragraph", P.PARAGRAPH_SPACING)].unit) == ("6", "pt")
    assert (rules[("Paragraph", P.FIRST_LINE_INDENT)].value, rules[("Paragraph", P.FIRST_LINE_INDENT)].unit) == ("1", "cm")
    assert (rules[("Image", P.IMAGE_WIDTH)].value, rules[("Image", P.IMAGE_WIDTH)].unit) == ("80", "%")
    assert {r.priority for r in rules.values()} == {Priority.CUSTOM_TEMPLATE}


@pytest.mark.parametrize("template_id", sorted(BUILTIN_TEMPLATES))
def test_rules_to_style_system_and_back_changes_nothing(template_id):
    rules = BUILTIN_TEMPLATES[template_id].rules
    style, notes = style_system_from_rules(rules)

    assert notes == []
    assert _content(compile_rules(style, priority=Priority.BUILTIN_TEMPLATE, source="template")) == _content(rules)


def test_from_rules_keeps_the_rule_the_engine_would_apply():
    rules = [
        FormattingRule(target="Paragraph", property=P.FONT_FAMILY, value="Arial", priority=Priority.DEFAULT),
        FormattingRule(target="Paragraph", property=P.FONT_FAMILY, value="Georgia", priority=Priority.INSTRUCTION),
        FormattingRule(target="Paragraph", property=P.FONT_FAMILY, value="Calibri", priority=Priority.INSTRUCTION),
    ]
    style, _ = style_system_from_rules(rules)
    assert style.paragraph.fontFamily == "Georgia"  # lowest number wins, the first one on a tie


def test_from_rules_leaves_out_single_element_overrides():
    rules = [
        FormattingRule(target="Paragraph", property=P.COLOR, value="red", priority=Priority.CUSTOM_TEMPLATE),
        FormattingRule(target="3f1c9a52-element-id", property=P.COLOR, value="blue", priority=Priority.LIVE_OVERRIDE),
    ]
    style, notes = style_system_from_rules(rules)
    assert style.paragraph.color == "red"
    assert notes == []


def test_from_rules_converts_units_to_the_style_systems_own():
    rules = [
        FormattingRule(target="Paragraph", property=P.FONT_SIZE, value="16", unit="px"),
        FormattingRule(target="Paragraph", property=P.FIRST_LINE_INDENT, value="10", unit="mm"),
        FormattingRule(target="Document", property=P.MARGIN_LEFT, value="1", unit="in"),
    ]
    style, notes = style_system_from_rules(rules)
    assert notes == []
    assert style.paragraph.fontSizePt == 12
    assert style.paragraph.firstLineIndentCm == 1
    assert style.page.marginLeftCm == 2.54


def test_from_rules_reports_everything_it_cannot_represent():
    rules = [
        FormattingRule(target="Paragraph", property=P.FONT_SIZE, value="1.2", unit="em"),
        FormattingRule(target="Paragraph", property=P.COLOR, value="chartreuse"),
        FormattingRule(target="Paragraph", property=P.PAGE_SIZE, value="A4"),
        FormattingRule(target="PageBreak", property=P.FONT_FAMILY, value="Arial"),
        FormattingRule(target="Heading 2", property=P.BOLD, value="maybe"),
        FormattingRule(target="Heading 2", property=P.ITALIC, value="true"),
    ]
    style, notes = style_system_from_rules(rules)

    assert style.headings.h2.italic is True  # the valid rule still comes through
    assert len(notes) == 5
    joined = "\n".join(notes)
    for fragment in ("'em'", "chartreuse", "Paragraph: 'pageSize'", "PageBreak", "'maybe'"):
        assert fragment in joined


@pytest.mark.parametrize(
    "payload",
    [
        {"paragraph": {"fontFamily": "Arial; color: red"}},
        {"paragraph": {"color": "url(https://example.com/x)"}},
        {"paragraph": {"fontSizePt": 0}},
        {"paragraph": {"alignment": "centre"}},
        {"paragraph": {"fontSize": 12}},  # a typo'd field name
        {"page": {"size": "B5"}},
        {"page": {"marginTopCm": 50}},
        {"images": {"widthPercent": 150}},
        {"colour": {}},
    ],
)
def test_invalid_style_systems_are_rejected(payload):
    with pytest.raises(ValidationError):
        StyleSystem.model_validate(payload)


def test_blank_strings_mean_not_set():
    style = StyleSystem.model_validate(
        {"paragraph": {"fontFamily": "  ", "color": ""}, "header": {"text": ""}, "footer": {"text": " "}}
    )
    assert style == StyleSystem()


def test_page_sizes_are_exactly_the_ones_the_exporters_know():
    assert set(get_args(PageSize)) == set(docx_export._PAGE_DIMENSIONS_MM) == set(pdf_export._PAGE_DIMENSIONS_MM)


def test_unit_conversions():
    assert to_cm("25.4", "mm") == pytest.approx(2.54)
    assert to_cm("72", "pt") == pytest.approx(2.54)
    assert to_cm("3", None) == 3
    assert to_pt("16", "px") == 12
    with pytest.raises(ValueError):
        to_cm("2", "em")
    with pytest.raises(ValueError):
        to_pt("big", "pt")


def test_margins_given_in_other_units_are_converted_not_misread_as_cm():
    settings = extract_settings(
        [
            FormattingRule(target="Document", property=P.MARGIN_TOP, value="25", unit="mm", priority=Priority.INSTRUCTION),
            FormattingRule(target="Document", property=P.MARGIN_LEFT, value="wide", unit="cm", priority=Priority.INSTRUCTION),
        ]
    )
    assert settings.marginTopCm == pytest.approx(2.5)
    assert settings.marginLeftCm == 2.0  # unreadable value: the default stays
