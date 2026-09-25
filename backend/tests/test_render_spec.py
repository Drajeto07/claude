"""The Document Render Specification (корекции.docx §23): one set of page sizes and
base block styles, resolved by the engine for the editor and both exports."""

from app.formatting import render_spec
from app.formatting.engine import apply_formatting, recompute_styles, resolve_styles, set_element_override
from app.formatting.priorities import Priority
from app.formatting.templates import BUILTIN_TEMPLATES
from app.models.document import Document, DocumentMetadata, Element, ElementType, FormattingProperty, FormattingRule, InlineRun


def _document() -> Document:
    elements = [
        Element(type=ElementType.HEADING, content="Title", inline=[InlineRun(text="Title")], level=1, order=0),
        Element(type=ElementType.PARAGRAPH, content="Body.", inline=[InlineRun(text="Body.")], order=1),
    ]
    return Document(metadata=DocumentMetadata(title="Spec"), elements=elements)


def test_every_kind_of_block_resolves_to_a_complete_look_with_no_rules_at_all():
    styles = resolve_styles([])

    assert styles["Paragraph"] == {
        "font-family": "Arial",
        "font-size": "11pt",
        "text-align": "left",
        "line-height": "1.15",
        "--line-spacing": "1",
        "margin-bottom": "8pt",
    }
    heading = styles["Heading 1"]
    assert (heading["font-size"], heading["font-weight"], heading["margin-top"], heading["font-family"]) == ("20pt", "bold", "18pt", "Arial")
    assert styles["CodeBlock"]["font-family"] == "Courier New"
    assert (styles["Quote"]["font-style"], styles["Quote"]["margin-left"], styles["Quote"]["font-size"]) == ("italic", "1cm", "11pt")
    assert styles["Caption"]["font-size"] == "9pt"


def test_other_kinds_of_text_take_the_body_font_unless_they_set_their_own():
    """Like Word styles based on Normal: a template that sets only the body font
    gets it in its lists and quotes, and in headings that set no font of their own."""
    document = _document()
    rules = [FormattingRule(target="Paragraph", property=FormattingProperty.FONT_FAMILY, value="Georgia", priority=Priority.CUSTOM_TEMPLATE)]
    apply_formatting(document, template_id=None, template_rules=rules, instruction_rules=[])

    assert document.resolvedStyles["Heading 1"]["font-family"] == "Georgia"
    assert document.resolvedStyles["List"]["font-family"] == "Georgia"
    assert document.resolvedStyles["CodeBlock"]["font-family"] == "Courier New"  # code keeps its own

    academic = BUILTIN_TEMPLATES["academic-default"]
    apply_formatting(document, template_id=academic.id, template_rules=academic.rules, instruction_rules=[])
    assert document.resolvedStyles["Heading 1"]["font-family"] == "Times New Roman"


def test_a_heading_changed_by_hand_keeps_what_it_takes_from_the_body():
    document = _document()
    recompute_styles(document)

    set_element_override(document, element_id=document.elements[0].id, property=FormattingProperty.COLOR, value="#C00000", unit=None)

    own = document.resolvedStyles[document.elements[0].id]
    assert (own["color"], own["font-family"], own["font-size"]) == ("#C00000", "Arial", "20pt")


def test_a_document_saved_with_the_old_few_defaults_still_gets_the_whole_look():
    old_defaults = [
        FormattingRule(target="Paragraph", property=FormattingProperty.FONT_FAMILY, value="Arial", priority=7, source="default"),
        FormattingRule(target="Paragraph", property=FormattingProperty.FONT_SIZE, value="11", unit="pt", priority=7, source="default"),
    ]
    document = _document()
    document.formattingRules = old_defaults

    recompute_styles(document)

    assert document.resolvedStyles["Heading 1"]["font-size"] == "20pt"


def test_page_sizes_are_words_own_and_turn_for_landscape():
    assert render_spec.page_size_mm("Letter", "portrait") == (215.9, 279.4)
    assert render_spec.page_size_mm("A4", "landscape") == (297.0, 210.0)
    assert render_spec.page_size_mm("Tabloid", "portrait") == (210.0, 297.0)  # unknown: A4


def test_a_line_spacing_is_drawn_at_words_single_height_and_kept_as_word_counts_it():
    assert render_spec.line_height_css("1.5", None) == {"line-height": "1.725", "--line-spacing": "1.5"}
    assert render_spec.line_height_css("14", "pt") == {"line-height": "14pt", "--line-spacing": "14pt"}
