"""A formatting rule's value reaches CSS, Word and PDF styles as text, so only
values every renderer can use are ever accepted or resolved
(app/formatting/values.py): the style endpoints refuse the rest, an
instruction's rules and operations drop them, and a stored one is skipped."""

import pytest
from fastapi.testclient import TestClient

from app.ai.instruction_extraction import _response_to_edits
from app.ai.schemas import AIDocumentOperation, AIFormattingRule, AIInstructionExtractionResponse
from app.formatting.engine import DEFAULT_RULES, InvalidOperationError, recompute_styles, validate_operations
from app.formatting.priorities import Priority
from app.formatting.templates import _load_builtin_templates
from app.formatting.values import clean_rule_value
from app.main import app
from app.models.document import Document, Element, ElementType, FormattingProperty, FormattingRule, InlineRun

client = TestClient(app, base_url="https://testserver")
P = FormattingProperty
_CSS_BREAKOUT = "center;background-image:url(https://example.invalid/pixel)"


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    response = client.post("/api/v1/auth/register", json={"email": "values@example.com", "password": "long enough password"})
    assert response.status_code == 201
    yield
    client.cookies.clear()


def test_every_default_and_template_rule_is_accepted_as_it_is():
    rules = list(DEFAULT_RULES)
    for template in _load_builtin_templates().values():
        rules += template.rules
    assert [(r.property, r.value, r.unit) for r in rules if clean_rule_value(r.property, r.value, r.unit) != (r.value, r.unit)] == []


@pytest.mark.parametrize(
    ("prop", "value", "unit", "expected"),
    [
        (P.ALIGNMENT, " Center ", None, ("center", None)),
        (P.BOLD, "YES", None, ("true", None)),
        (P.FONT_FAMILY, "Times New Roman", None, ("Times New Roman", None)),
        (P.FONT_SIZE, "12.50", "PT", ("12.5", "pt")),
        (P.FONT_SIZE, "16", "px", ("16", "px")),
        (P.LINE_SPACING, "1.15", None, ("1.15", None)),
        (P.INDENT_LEFT, "-1", "cm", ("-1", "cm")),
        (P.IMAGE_WIDTH, "50", "%", ("50", "%")),
        (P.COLOR, "#1F4E79", None, ("#1F4E79", None)),
        (P.PAGE_SIZE, "letter", None, ("Letter", None)),
        (P.MARGIN_TOP, "25", "mm", ("25", "mm")),
        (P.HEADER, "  Report; draft  ", None, ("  Report; draft  ", None)),  # text, never CSS
    ],
)
def test_values_every_renderer_can_use_are_kept(prop, value, unit, expected):
    assert clean_rule_value(prop, value, unit) == expected


@pytest.mark.parametrize(
    ("prop", "value", "unit"),
    [
        (P.ALIGNMENT, _CSS_BREAKOUT, None),
        (P.ALIGNMENT, "middle", None),
        (P.COLOR, "red;position:fixed", None),
        (P.COLOR, "rgb(1,2,3)", None),
        (P.FONT_FAMILY, "Arial, sans-serif", None),
        (P.FONT_FAMILY, "x'}", None),
        (P.FONT_SIZE, "12pt", None),  # the unit belongs in `unit`
        (P.FONT_SIZE, "0", None),
        (P.FONT_SIZE, "nan", None),
        (P.FONT_SIZE, "12", "em"),
        (P.LINE_SPACING, "1;x", None),
        (P.SPACE_BEFORE, "-3", "pt"),
        (P.IMAGE_WIDTH, "120", "%"),
        (P.IMAGE_WIDTH, "300", "px"),
        (P.MARGIN_LEFT, "11", "cm"),
        (P.BOLD, "maybe", None),
        (P.HEADER, "x" * 501, None),
        (P.ALIGNMENT, "   ", None),
    ],
)
def test_anything_else_is_refused(prop, value, unit):
    with pytest.raises(ValueError):
        clean_rule_value(prop, value, unit)


def test_the_style_endpoints_refuse_what_could_break_out_of_a_style(signed_in):
    document_id = client.post("/api/v1/documents", json={"text": "One paragraph of text."}).json()["id"]
    element_id = client.get(f"/api/v1/documents/{document_id}").json()["elements"][0]["id"]

    refused = client.patch(f"/api/v1/documents/{document_id}/elements/{element_id}/style", json={"property": "alignment", "value": _CSS_BREAKOUT})
    assert refused.status_code == 422
    page = client.patch(f"/api/v1/documents/{document_id}/settings", json={"property": "marginTop", "value": "2;x", "unit": "cm"})
    assert page.status_code == 422

    kept = client.patch(f"/api/v1/documents/{document_id}/elements/{element_id}/style", json={"property": "alignment", "value": "Center"})
    assert kept.status_code == 200
    assert kept.json()["resolvedStyles"][element_id]["text-align"] == "center"


def _paragraph_document(*rules: FormattingRule) -> Document:
    document = Document(elements=[Element(type=ElementType.PARAGRAPH, content="x", inline=[InlineRun(text="x")], order=0)])
    document.formattingRules = [
        rule.model_copy(update={"target": document.elements[0].id}) if rule.target == "element" else rule for rule in rules
    ]
    recompute_styles(document)
    return document


def test_a_stored_rule_no_renderer_can_use_is_skipped_for_the_next_one():
    document = _paragraph_document(
        FormattingRule(target="element", property=P.ALIGNMENT, value=_CSS_BREAKOUT, priority=Priority.LIVE_OVERRIDE),
        FormattingRule(target="Paragraph", property=P.ALIGNMENT, value="right", priority=Priority.INSTRUCTION),
        FormattingRule(target="Document", property=P.MARGIN_TOP, value="3;x", unit="cm", priority=Priority.LIVE_OVERRIDE),
    )

    css = document.resolvedStyles[document.elements[0].styleRef]
    assert css["text-align"] == "right"  # the instruction's, not the unusable override
    assert all("url(" not in value for styles in document.resolvedStyles.values() for value in styles.values())
    assert document.settings.marginTopCm == 2.0  # the default, not "3;x"


def test_instructions_cannot_carry_such_values():
    edits = _response_to_edits(
        AIInstructionExtractionResponse(
            rules=[
                AIFormattingRule(target="Paragraph", property="alignment", value=_CSS_BREAKOUT),
                AIFormattingRule(target="Paragraph", property="fontSize", value="11", unit="pt"),
            ],
            operations=[
                AIDocumentOperation(op="set_style", element_id="e1", property="color", value="red;x:y"),
                AIDocumentOperation(op="set_style", element_id="e1", property="color", value="Red"),
            ],
        )
    )

    assert [(rule.property, rule.value, rule.unit) for rule in edits.rules] == [(P.FONT_SIZE, "11", "pt")]
    assert [(op.property, op.value) for op in edits.operations] == [("color", "Red")]

    document = _paragraph_document()
    with pytest.raises(InvalidOperationError):
        validate_operations(
            document, [AIDocumentOperation(op="set_style", element_id=document.elements[0].id, property="alignment", value=_CSS_BREAKOUT)]
        )
