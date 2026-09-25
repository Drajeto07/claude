"""Comparing two versions (formatting/compare.py): structure by element id, styles
per kind of text and per element formatted on its own, page settings."""

from app.formatting.compare import compare_documents
from app.formatting.engine import recompute_styles, set_element_override
from app.models.document import Document, Element, ElementType, FormattingProperty, FormattingRule


def _el(kind: ElementType, text: str, level: int | None = None) -> Element:
    return Element(type=kind, content=text, order=0, level=level)


def _doc(elements: list[Element], rules: list[FormattingRule] | None = None) -> Document:
    for index, element in enumerate(elements):
        element.order = index
    document = Document(elements=elements, formattingRules=rules or [])
    recompute_styles(document)
    return document


def _copy(document: Document) -> Document:
    return Document.model_validate(document.model_dump())


def test_structure_changes_are_found_by_element_id():
    a, b, c, d = _el(ElementType.PARAGRAPH, "A"), _el(ElementType.PARAGRAPH, "B"), _el(ElementType.PARAGRAPH, "C"), _el(ElementType.PARAGRAPH, "D")
    before = _doc([a, b, c, d])
    after = _copy(before)
    moved = after.elements.pop(0)  # A moves to the end
    after.elements.append(moved)
    after.elements[0].content = "B, rewritten"  # B edited
    after.elements[1].type, after.elements[1].level = ElementType.HEADING, 2  # C becomes a heading
    del after.elements[2]  # D removed
    added = _el(ElementType.PARAGRAPH, "E")
    after.elements.insert(0, added)

    changes = {(change.change, change.elementId) for change in compare_documents(before, after, from_version=1, to_version=2).structure}

    assert changes == {("added", added.id), ("edited", b.id), ("retyped", c.id), ("moved", a.id), ("removed", d.id)}


def test_style_changes_per_kind_of_text_and_per_element():
    heading, body = _el(ElementType.HEADING, "Title", level=1), _el(ElementType.PARAGRAPH, "Text")
    before = _doc([heading, body])
    after = _copy(before)
    after.formattingRules.append(FormattingRule(target="Paragraph", property=FormattingProperty.FONT_FAMILY, value="Georgia", priority=5))
    set_element_override(after, element_id=heading.id, property=FormattingProperty.COLOR, value="red", unit=None)
    recompute_styles(after)

    styles = compare_documents(before, after, from_version=1, to_version=2).styles

    body_font = next(change for change in styles if change.target == "Paragraph" and change.property == "font-family")
    assert (body_font.label, body_font.after) == ("Body text", "Georgia")
    own = next(change for change in styles if change.target == heading.id and change.property == "color")
    assert own.label == "Heading 1 “Title”" and own.after == "red"


def test_styles_are_compared_as_the_settings_people_change():
    picture = Element(type=ElementType.IMAGE, content="", order=0)
    before = _doc([_el(ElementType.PARAGRAPH, "Text"), picture])
    after = _copy(before)
    after.formattingRules += [
        FormattingRule(target="Paragraph", property=FormattingProperty.LINE_SPACING, value="2", priority=5),
        FormattingRule(target="Image", property=FormattingProperty.IMAGE_ALIGNMENT, value="center", priority=5),
    ]
    recompute_styles(after)

    changes = {(change.target, change.property): (change.before, change.after) for change in compare_documents(before, after, from_version=1, to_version=2).styles}

    assert changes[("Paragraph", "--line-spacing")][1] == "2"
    assert ("Paragraph", "line-height") not in changes  # follows from the line spacing
    assert changes[("Image", "alignment")] == ("left", "center")
    assert not {prop for target, prop in changes if target == "Image"} & {"display", "margin-left", "margin-right"}


def test_settings_changes():
    before = _doc([_el(ElementType.PARAGRAPH, "Text")])
    after = _copy(before)
    after.settings.orientation = "landscape"
    after.settings.header = "Draft"

    settings = {(change.property, change.before, change.after) for change in compare_documents(before, after, from_version=1, to_version=2).settings}

    assert settings == {("orientation", "portrait", "landscape"), ("header", None, "Draft")}


def test_nothing_changed_is_an_empty_comparison():
    document = _doc([_el(ElementType.PARAGRAPH, "Same")])

    comparison = compare_documents(document, _copy(document), from_version=2, to_version=2)

    assert (comparison.structure, comparison.styles, comparison.settings) == ([], [], [])
