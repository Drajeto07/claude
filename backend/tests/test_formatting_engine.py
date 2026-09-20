from app.formatting.engine import (
    DEFAULT_RULES,
    PRIORITY_BUILTIN_TEMPLATE,
    PRIORITY_INSTRUCTION,
    apply_formatting,
    extract_settings,
    resolve_styles,
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
