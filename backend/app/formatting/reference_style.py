"""Format by Example (корекции.docx §17): the StyleSystem a reference document
really uses, read from the document the DOCX importer built out of it.

Deterministic. For each kind of text, every property takes the value that most
of the reference's text of that kind has (weighted by length), so formatting
applied by hand counts as much as Word's styles do. The one judgement call --
which short paragraphs are really headings, in a reference that doesn't use
heading styles -- is made from their look (larger, or bold where the body text
isn't), or by the AI when one is available (ai/semantic_labeling.py). Either way
that only decides *which* paragraphs are headings, never how anything looks."""

import re
from collections import defaultdict
from dataclasses import dataclass, field

from app.formatting.engine import SOURCE_DOCUMENT_SOURCE
from app.formatting.priorities import Priority
from app.formatting.style_system import StyleSystem, style_system_from_rules
from app.models.document import (
    COARSE_TARGETS,
    Document,
    Element,
    ElementType,
    FormattingProperty,
    FormattingRule,
    MarkType,
    target_for_element,
)

_TEXT_TARGETS = (
    "Paragraph",
    *(f"Heading {level}" for level in range(1, 7)),
    "List",
    "Table",
    "Caption",
    "Quote",
    "Footnote",
    "CodeBlock",
)
_TEXT_PROPERTIES = (
    FormattingProperty.FONT_FAMILY,
    FormattingProperty.FONT_SIZE,
    FormattingProperty.BOLD,
    FormattingProperty.ITALIC,
    FormattingProperty.UNDERLINE,
    FormattingProperty.COLOR,
    FormattingProperty.ALIGNMENT,
    FormattingProperty.LINE_SPACING,
    FormattingProperty.SPACE_BEFORE,
    FormattingProperty.PARAGRAPH_SPACING,
    FormattingProperty.INDENT_LEFT,
    FormattingProperty.FIRST_LINE_INDENT,
)
_MARK_FOR = {
    FormattingProperty.BOLD: MarkType.BOLD,
    FormattingProperty.ITALIC: MarkType.ITALIC,
    FormattingProperty.UNDERLINE: MarkType.UNDERLINE,
}
_PAGE_FIELD = re.compile(r"\{(?:PAGE|NUMPAGES)\}")
# A heading is short and isn't a sentence.
_HEADING_MAX_CHARS = 120
_HEADING_MAX_WORDS = 15
_SENTENCE_END = (".", ",", ";")


@dataclass
class ReferenceStyle:
    style_system: StyleSystem
    notes: list[str]
    # "styles" (Word heading styles), "look", "ai", or "none" (no headings at all)
    headings_from: str
    heading_counts: dict[int, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


class _SourceRules:
    """The reference's own formatting: its style rules and, per element, what
    that element sets differently."""

    def __init__(self, document: Document) -> None:
        self.by_type: dict[tuple[str, FormattingProperty], FormattingRule] = {}
        self.by_element: dict[tuple[str, FormattingProperty], FormattingRule] = {}
        for rule in document.formattingRules:
            if rule.source != SOURCE_DOCUMENT_SOURCE:
                continue
            table = self.by_type if rule.target in COARSE_TARGETS else self.by_element
            table.setdefault((rule.target, rule.property), rule)

    def effective(self, element: Element, prop: FormattingProperty) -> FormattingRule | None:
        own = self.by_element.get((element.id, prop))
        if own is not None:
            return own
        # Bold, italic and underline stay on the text as marks even when the
        # whole paragraph has them; for its look, that is the paragraph's.
        mark = _MARK_FOR.get(prop)
        runs = [run for run in element.inline or [] if run.text.strip()]
        if mark is not None and runs and all(any(m.type == mark for m in run.marks) for run in runs):
            return FormattingRule(
                target=element.id, property=prop, value="true", priority=Priority.SOURCE_DOCUMENT, source=SOURCE_DOCUMENT_SOURCE
            )
        return self.by_type.get((target_for_element(element), prop))


def _weight(element: Element) -> int:
    return max(1, len(element.content.strip()))


@dataclass(frozen=True)
class ParagraphLook:
    """What makes a line stand out from the body text."""

    size_pt: float | None
    bold: bool
    italic: bool
    alignment: str | None

    @property
    def signature(self) -> tuple[float | None, bool, bool]:
        return self.size_pt, self.bold, self.italic


def _look(rules: _SourceRules, element: Element) -> ParagraphLook:
    size_rule = rules.effective(element, FormattingProperty.FONT_SIZE)
    try:
        size = float(size_rule.value) if size_rule is not None and (size_rule.unit or "pt") == "pt" else None
    except ValueError:
        size = None

    def flag(prop: FormattingProperty) -> bool:
        rule = rules.effective(element, prop)
        return rule is not None and rule.value.strip().lower() == "true"

    alignment = rules.effective(element, FormattingProperty.ALIGNMENT)
    return ParagraphLook(size, flag(FormattingProperty.BOLD), flag(FormattingProperty.ITALIC), alignment.value if alignment else None)


def paragraph_looks(document: Document) -> dict[str, ParagraphLook]:
    rules = _SourceRules(document)
    return {element.id: _look(rules, element) for element in document.elements if element.type == ElementType.PARAGRAPH}


def body_look(document: Document, looks: dict[str, ParagraphLook]) -> ParagraphLook:
    """The look most of the paragraph text has (by length)."""
    votes: dict[ParagraphLook, int] = defaultdict(int)
    for element in document.elements:
        if element.type == ElementType.PARAGRAPH and element.content.strip():
            votes[looks[element.id]] += _weight(element)
    return max(votes.items(), key=lambda item: item[1])[0] if votes else ParagraphLook(None, False, False, None)


def heading_candidates(document: Document) -> list[Element]:
    """Paragraphs short enough to be headings. Empty when the reference uses
    heading styles: then those are trusted and nothing is guessed."""
    if any(element.type == ElementType.HEADING for element in document.elements):
        return []
    return [
        element
        for element in document.elements
        if element.type == ElementType.PARAGRAPH
        and 0 < len(element.content.strip()) <= _HEADING_MAX_CHARS
        and len(element.content.split()) <= _HEADING_MAX_WORDS
        and not element.content.strip().endswith(_SENTENCE_END)
    ]


def infer_heading_levels(document: Document) -> dict[str, int]:
    """For a reference without heading styles: the short paragraphs that stand
    out from the body text -- at least 1 pt larger, or bold where the body
    isn't -- levelled by prominence, largest first (up to six levels). Nothing
    when more than half of the paragraphs would count: then it's no heading
    pattern at all."""
    candidates = heading_candidates(document)
    paragraphs = [element for element in document.elements if element.type == ElementType.PARAGRAPH and element.content.strip()]
    if not candidates or not paragraphs:
        return {}
    looks = paragraph_looks(document)
    body = body_look(document, looks)

    def stands_out(look: ParagraphLook) -> bool:
        larger = look.size_pt is not None and body.size_pt is not None and look.size_pt >= body.size_pt + 1
        return larger or (look.bold and not body.bold)

    headings = [element for element in candidates if stands_out(looks[element.id])]
    if not headings or len(headings) * 2 > len(paragraphs):
        return {}
    signatures = sorted(
        {looks[element.id].signature for element in headings},
        key=lambda signature: (-(signature[0] or 0), not signature[1], signature[2]),
    )
    level_of = {signature: min(index + 1, 6) for index, signature in enumerate(signatures)}
    return {element.id: level_of[looks[element.id].signature] for element in headings}


def _majority(members: list[Element], prop: FormattingProperty, rules: _SourceRules, *, target: str) -> FormattingRule | None:
    """The value most of this text has (by length); None when most of it sets
    nothing. Ties go to the value that comes first in the document."""
    votes: dict[tuple[str, str | None] | None, int] = {}
    samples: dict[tuple[str, str | None], FormattingRule] = {}
    for element in members:
        rule = rules.effective(element, prop)
        key = (rule.value, rule.unit) if rule is not None else None
        votes[key] = votes.get(key, 0) + _weight(element)
        if rule is not None:
            samples.setdefault(key, rule)
    winner = max(votes, key=votes.__getitem__)
    if winner is None:
        return None
    return samples[winner].model_copy(update={"target": target, "priority": Priority.SOURCE_DOCUMENT})


def _nearest_used(level: int, used: list[int]) -> int:
    """The used heading level an unused one should look like: the closest,
    the deeper one on a tie (it reads as subordinate)."""
    return min(used, key=lambda candidate: (abs(candidate - level), -candidate))


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 60 else text[:57] + "..."


def extract_reference_style(
    document: Document,
    *,
    heading_levels: dict[str, int] | None = None,
    headings_from: str | None = None,
    notes: list[str] | None = None,
) -> ReferenceStyle:
    """The reference document's look as a StyleSystem. `heading_levels`
    (element id -> level) marks the paragraphs to treat as headings, found by
    infer_heading_levels() or the AI; `notes` are the importer's notes on page
    setup and styles, passed through."""
    heading_levels = heading_levels or {}
    rules = _SourceRules(document)
    all_notes = list(notes or [])

    def as_target(element: Element) -> str:
        level = heading_levels.get(element.id)
        return f"Heading {level}" if level else target_for_element(element)

    groups: dict[str, list[Element]] = defaultdict(list)
    for element in document.elements:
        groups[as_target(element)].append(element)

    type_rules: list[FormattingRule] = []
    for target in _TEXT_TARGETS:
        members = groups.get(target, [])
        if members:
            for prop in _TEXT_PROPERTIES:
                winner = _majority(members, prop, rules, target=target)
                if winner is not None:
                    type_rules.append(winner)
        else:  # not used in the reference: its style definition, if it has one
            type_rules.extend(rule for (rule_target, _), rule in rules.by_type.items() if rule_target == target)

    used_levels = sorted({int(target.split()[1]) for target in groups if target.startswith("Heading ")})
    if heading_levels and used_levels:
        # Headings found by their look: the reference's Word heading styles (if
        # any) are unused defaults, so unused levels copy the nearest used one.
        for level in range(1, 7):
            if level in used_levels:
                continue
            source = f"Heading {_nearest_used(level, used_levels)}"
            copies = [rule.model_copy(update={"target": f"Heading {level}"}) for rule in type_rules if rule.target == source]
            type_rules = [rule for rule in type_rules if rule.target != f"Heading {level}"] + copies

    images = groups.get("Image", [])
    if images:
        alignment = _majority(images, FormattingProperty.IMAGE_ALIGNMENT, rules, target="Image")
        if alignment is not None:
            type_rules.append(alignment)
        width = _majority(images, FormattingProperty.IMAGE_WIDTH, rules, target="Image")
        if width is not None:
            widths = [rules.effective(image, FormattingProperty.IMAGE_WIDTH) for image in images]
            same = sum(1 for found in widths if found is not None and found.value == width.value)
            if same * 2 > len(images):  # a width most pictures share is a rule; varying widths belong to each picture
                type_rules.append(width)

    for (target, prop), rule in rules.by_type.items():
        if target != "Document":
            continue
        if prop in (FormattingProperty.HEADER, FormattingProperty.FOOTER) and not _PAGE_FIELD.search(rule.value):
            where = "header" if prop == FormattingProperty.HEADER else "footer"
            all_notes.append(f"The reference's {where} text, “{_short(rule.value)}”, belongs to that document, so it wasn't copied.")
            continue
        type_rules.append(rule)

    style_system, conversion_notes = style_system_from_rules(type_rules)
    all_notes.extend(conversion_notes)

    heading_counts: dict[int, int] = defaultdict(int)
    for target, members in groups.items():
        if target.startswith("Heading "):
            heading_counts[int(target.split()[1])] += len(members)
    if heading_levels:
        source = headings_from or "look"
        how = "the AI picked out its headings" if source == "ai" else "its headings were recognised by their look (larger or bold text)"
        all_notes.append(f"The reference doesn't use Word's heading styles, so {how}.")
    else:
        source = "styles" if heading_counts else "none"
    counts = {
        "paragraphs": len(groups.get("Paragraph", [])),
        "lists": len(groups.get("List", [])),
        "tables": len(groups.get("Table", [])),
        "images": len(images),
        "captions": len(groups.get("Caption", [])),
    }
    return ReferenceStyle(
        style_system=style_system,
        notes=all_notes,
        headings_from=source,
        heading_counts=dict(sorted(heading_counts.items())),
        counts=counts,
    )
