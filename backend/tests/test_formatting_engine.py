import pytest

from app.formatting.engine import (
    DEFAULT_RULES,
    PRIORITY_BUILTIN_TEMPLATE,
    PRIORITY_INSTRUCTION,
    UnknownElementError,
    apply_formatting,
    clear_element_override,
    detect_conflicts,
    extract_settings,
    resolve_styles,
    set_element_override,
)
from app.models.document import (
    Document,
    DocumentMetadata,
    Element,
    ElementType,
    FormattingProperty,
    FormattingRule,
    target_for_element,
)


def _element(element_type: ElementType, level: int | None = None) -> Element:
    return Element(type=element_type, content="x", order=0, level=level)


def test_target_for_element_covers_every_type():
    assert target_for_element(_element(ElementType.HEADING, level=2)) == "Heading 2"
    assert target_for_element(_element(ElementType.HEADING)) == "Heading 1"  # missing level defaults to 1
    assert target_for_element(_element(ElementType.PARAGRAPH)) == "Paragraph"
    assert target_for_element(_element(ElementType.LIST)) == "List"
    assert target_for_element(_element(ElementType.TABLE)) == "Table"
    assert target_for_element(_element(ElementType.IMAGE)) == "Image"
    assert target_for_element(_element(ElementType.QUOTE)) == "Quote"
    assert target_for_element(_element(ElementType.CAPTION)) == "Caption"
    assert target_for_element(_element(ElementType.FOOTNOTE)) == "Footnote"
    assert target_for_element(_element(ElementType.CODE_BLOCK)) == "CodeBlock"
    assert target_for_element(_element(ElementType.OTHER)) == "Paragraph"


def test_resolve_styles_default_only():
    styles = resolve_styles(DEFAULT_RULES)

    assert styles["Paragraph"]["font-family"] == "Arial"
    assert styles["Paragraph"]["font-size"] == "11pt"
    assert styles["Paragraph"]["text-align"] == "left"
    # Document is a page-level target, never a resolvedStyles entry.
    assert "Document" not in styles


def test_lower_priority_number_wins_on_conflict():
    template_rule = FormattingRule(
        target="Heading 1", property=FormattingProperty.COLOR, value="black", priority=PRIORITY_BUILTIN_TEMPLATE, source="template"
    )
    instruction_rule = FormattingRule(
        target="Heading 1", property=FormattingProperty.COLOR, value="red", priority=PRIORITY_INSTRUCTION, source="instruction"
    )

    styles = resolve_styles([template_rule, instruction_rule])

    assert styles["Heading 1"]["color"] == "red"


def test_boolean_and_unit_properties_map_to_expected_css():
    rules = [
        FormattingRule(target="Heading 1", property=FormattingProperty.BOLD, value="true", priority=5, source="template"),
        FormattingRule(target="Heading 1", property=FormattingProperty.ITALIC, value="false", priority=5, source="template"),
        FormattingRule(target="Paragraph", property=FormattingProperty.FIRST_LINE_INDENT, value="1.25", unit="cm", priority=5, source="template"),
        FormattingRule(target="Image", property=FormattingProperty.IMAGE_ALIGNMENT, value="center", priority=5, source="template"),
    ]

    styles = resolve_styles(rules)

    assert styles["Heading 1"]["font-weight"] == "bold"
    assert styles["Heading 1"]["font-style"] == "normal"
    assert styles["Paragraph"]["text-indent"] == "1.25cm"
    assert styles["Image"]["margin-left"] == "auto"
    assert styles["Image"]["margin-right"] == "auto"


def test_extract_settings_reads_page_level_properties_not_resolve_styles():
    rules = [
        FormattingRule(target="Document", property=FormattingProperty.PAGE_SIZE, value="Letter", priority=5, source="template"),
        FormattingRule(target="Document", property=FormattingProperty.MARGIN_LEFT, value="3", unit="cm", priority=5, source="template"),
        FormattingRule(target="Document", property=FormattingProperty.SHOW_PAGE_NUMBERS, value="true", priority=5, source="template"),
    ]

    settings = extract_settings(rules)
    assert settings.pageSize == "Letter"
    assert settings.marginLeftCm == 3.0
    assert settings.showPageNumbers is True

    # Page-level properties must never leak into the per-element style map.
    assert resolve_styles(rules) == {}


def test_apply_formatting_stamps_style_ref_and_records_revision():
    document = Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[
            Element(type=ElementType.HEADING, content="Title", level=1, order=0),
            Element(type=ElementType.PARAGRAPH, content="Body", order=1),
        ],
    )

    apply_formatting(document, template_id="academic-default", template_rules=[], instruction_rules=[])

    assert document.templateId == "academic-default"
    assert document.elements[0].styleRef == "Heading 1"
    assert document.elements[1].styleRef == "Paragraph"
    assert len(document.revisions) == 1
    assert "academic-default" in document.revisions[0].description


def test_apply_formatting_is_idempotent_not_additive():
    document = Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[Element(type=ElementType.PARAGRAPH, content="Body", order=0)],
    )
    some_template_rules = [
        FormattingRule(target="Paragraph", property=FormattingProperty.FONT_FAMILY, value="Georgia", priority=PRIORITY_BUILTIN_TEMPLATE, source="template")
    ]

    apply_formatting(document, template_id="academic-default", template_rules=some_template_rules, instruction_rules=[])
    first_rule_count = len(document.formattingRules)
    apply_formatting(document, template_id=None, template_rules=[], instruction_rules=[])

    # Re-applying with no template must fully replace, not accumulate.
    assert document.templateId is None
    assert len(document.formattingRules) == len(DEFAULT_RULES)
    assert len(document.formattingRules) < first_rule_count


def test_element_override_wins_for_targeted_element_only():
    document = Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[
            Element(type=ElementType.PARAGRAPH, content="First", order=0),
            Element(type=ElementType.PARAGRAPH, content="Second", order=1),
        ],
    )
    apply_formatting(document, template_id=None, template_rules=[], instruction_rules=[])
    target_id = document.elements[0].id

    set_element_override(document, element_id=target_id, property=FormattingProperty.FONT_FAMILY, value="Georgia", unit=None)

    assert document.resolvedStyles[target_id]["font-family"] == "Georgia"
    assert document.elements[0].styleRef == target_id
    # The sibling paragraph is untouched -- still the coarse target, still Arial.
    assert document.elements[1].styleRef == "Paragraph"
    assert document.resolvedStyles["Paragraph"]["font-family"] == "Arial"


def test_clear_element_override_restores_coarse_value():
    document = Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[Element(type=ElementType.PARAGRAPH, content="Body", order=0)],
    )
    apply_formatting(document, template_id=None, template_rules=[], instruction_rules=[])
    target_id = document.elements[0].id
    set_element_override(document, element_id=target_id, property=FormattingProperty.FONT_FAMILY, value="Georgia", unit=None)

    clear_element_override(document, element_id=target_id, property=FormattingProperty.FONT_FAMILY)

    assert document.elements[0].styleRef == "Paragraph"
    assert target_id not in document.resolvedStyles


def test_set_element_override_raises_for_unknown_element():
    document = Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[Element(type=ElementType.PARAGRAPH, content="Body", order=0)],
    )
    apply_formatting(document, template_id=None, template_rules=[], instruction_rules=[])

    with pytest.raises(UnknownElementError):
        set_element_override(
            document, element_id="does-not-exist", property=FormattingProperty.FONT_FAMILY, value="Georgia", unit=None
        )


def test_apply_formatting_preserves_overrides_across_reformat():
    document = Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[Element(type=ElementType.PARAGRAPH, content="Body", order=0)],
    )
    apply_formatting(document, template_id="academic-default", template_rules=[], instruction_rules=[])
    target_id = document.elements[0].id
    set_element_override(document, element_id=target_id, property=FormattingProperty.FONT_FAMILY, value="Georgia", unit=None)

    # Re-apply a *different* template -- NFR-008: the manual override must survive.
    new_template_rules = [
        FormattingRule(
            target="Paragraph", property=FormattingProperty.FONT_FAMILY, value="Calibri", priority=PRIORITY_BUILTIN_TEMPLATE, source="template"
        )
    ]
    apply_formatting(document, template_id="professional-cv", template_rules=new_template_rules, instruction_rules=[])

    assert document.resolvedStyles[target_id]["font-family"] == "Georgia"
    assert document.elements[0].styleRef == target_id


def test_detect_conflicts_finds_real_conflict():
    document = Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[Element(type=ElementType.PARAGRAPH, content="Body", order=0)],
    )
    apply_formatting(document, template_id=None, template_rules=[], instruction_rules=[])
    target_id = document.elements[0].id
    set_element_override(document, element_id=target_id, property=FormattingProperty.COLOR, value="red", unit=None)

    competing_template_rules = [
        FormattingRule(
            target="Paragraph", property=FormattingProperty.COLOR, value="blue", priority=PRIORITY_BUILTIN_TEMPLATE, source="template"
        )
    ]

    conflicts = detect_conflicts(document, competing_template_rules, [])

    assert len(conflicts) == 1
    assert conflicts[0].elementId == target_id
    assert conflicts[0].property == FormattingProperty.COLOR
    assert conflicts[0].currentValue == "red"
    assert conflicts[0].requiredValue == "blue"


def test_detect_conflicts_ignores_agreeing_values():
    document = Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[Element(type=ElementType.PARAGRAPH, content="Body", order=0)],
    )
    apply_formatting(document, template_id=None, template_rules=[], instruction_rules=[])
    target_id = document.elements[0].id
    set_element_override(document, element_id=target_id, property=FormattingProperty.COLOR, value="red", unit=None)

    same_template_rules = [
        FormattingRule(
            target="Paragraph", property=FormattingProperty.COLOR, value="red", priority=PRIORITY_BUILTIN_TEMPLATE, source="template"
        )
    ]

    assert detect_conflicts(document, same_template_rules, []) == []


def test_detect_conflicts_ignores_unrelated_properties():
    document = Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[Element(type=ElementType.PARAGRAPH, content="Body", order=0)],
    )
    apply_formatting(document, template_id=None, template_rules=[], instruction_rules=[])
    target_id = document.elements[0].id
    set_element_override(document, element_id=target_id, property=FormattingProperty.COLOR, value="red", unit=None)

    unrelated_template_rules = [
        FormattingRule(
            target="Paragraph", property=FormattingProperty.FONT_FAMILY, value="Calibri", priority=PRIORITY_BUILTIN_TEMPLATE, source="template"
        )
    ]

    assert detect_conflicts(document, unrelated_template_rules, []) == []


def test_apply_formatting_drop_overrides_lets_incoming_rule_win_for_named_pairs_only():
    document = Document(
        metadata=DocumentMetadata(title="Test"),
        elements=[
            Element(type=ElementType.PARAGRAPH, content="First", order=0),
            Element(type=ElementType.PARAGRAPH, content="Second", order=1),
        ],
    )
    apply_formatting(document, template_id=None, template_rules=[], instruction_rules=[])
    first_id, second_id = document.elements[0].id, document.elements[1].id
    set_element_override(document, element_id=first_id, property=FormattingProperty.COLOR, value="red", unit=None)
    set_element_override(document, element_id=second_id, property=FormattingProperty.COLOR, value="green", unit=None)

    new_template_rules = [
        FormattingRule(
            target="Paragraph", property=FormattingProperty.COLOR, value="blue", priority=PRIORITY_BUILTIN_TEMPLATE, source="template"
        )
    ]

    apply_formatting(
        document,
        template_id="some-template",
        template_rules=new_template_rules,
        instruction_rules=[],
        drop_overrides=[(first_id, FormattingProperty.COLOR)],
    )

    # first_id's override was named -- dropped, falls back to the coarse "Paragraph" target's blue.
    assert document.elements[0].styleRef == "Paragraph"
    assert document.resolvedStyles["Paragraph"]["color"] == "blue"
    # second_id's override was NOT named -- must survive untouched.
    assert document.elements[1].styleRef == second_id
    assert document.resolvedStyles[second_id]["color"] == "green"
