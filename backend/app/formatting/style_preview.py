"""A look tried on a document before it is kept (tracker FMT-003): what this document would
resolve to with a StyleSystem applied -- a template made from a reference document, say -- as
the real engine computes it on a copy (apply_formatting, apply_structure), with what changes in
words. Nothing is saved: the document stays as it is until the user applies the look."""

from dataclasses import dataclass, field

from app.formatting.engine import apply_formatting
from app.formatting.priorities import Priority
from app.formatting.structure import apply_structure, applies
from app.formatting.style_system import StyleSystem, compile_rules
from app.models.document import Document, DocumentSettings, ElementType, target_for_element, walk_elements

# The parts of a text style a person notices, by name.
_SHOWN = {
    "font-family": "font",
    "font-size": "size",
    "font-weight": "weight",
    "font-style": "style",
    "color": "colour",
    "text-align": "alignment",
    "line-height": "line spacing",
    "margin-top": "space before",
    "margin-bottom": "space after",
    "text-indent": "first-line indent",
}
_SETTINGS = {
    "pageSize": "page size",
    "orientation": "orientation",
    "marginTopCm": "top margin",
    "marginBottomCm": "bottom margin",
    "marginLeftCm": "left margin",
    "marginRightCm": "right margin",
}
MAX_CHANGES = 40


@dataclass
class StylePreview:
    before: dict[str, dict[str, str]]
    after: dict[str, dict[str, str]]
    settings_before: DocumentSettings
    settings_after: DocumentSettings
    changes: list[str] = field(default_factory=list)
    tables: int = 0
    lists: int = 0


def preview_on(document: Document, style_system: StyleSystem) -> StylePreview:
    """`document` as it would look with `style_system`, and what that changes (see the module's docstring)."""
    trial = document.model_copy(deep=True)
    rules = compile_rules(style_system, priority=Priority.CUSTOM_TEMPLATE, source="custom_template")
    apply_formatting(trial, template_id=None, template_rules=rules, instruction_rules=[], drop_overrides=[])
    tables = lists = 0
    if applies(style_system.structure):
        structure = style_system.structure
        apply_structure(trial, structure)
        if any(value is not None for value in (structure.tables.border, structure.tables.headerShading, structure.tables.headerBold)):
            tables = sum(1 for element in walk_elements(document.elements) if element.type == ElementType.TABLE)
        lists = sum(
            1
            for element in walk_elements(document.elements)
            if element.type == ElementType.LIST and (structure.lists.numberedLevels if element.ordered else structure.lists.bulletLevels)
        )
    used = list(dict.fromkeys(target_for_element(element) for element in document.elements if element.type not in (ElementType.PAGE_BREAK, ElementType.SECTION_BREAK)))
    changes: list[str] = []
    for target in used:
        old, new = document.resolvedStyles.get(target, {}), trial.resolvedStyles.get(target, {})
        for key, name in _SHOWN.items():
            if old.get(key) != new.get(key) and (old.get(key) or new.get(key)):
                changes.append(f"{target}: {name} {old.get(key) or 'not set'} → {new.get(key) or 'not set'}")
    for key, name in _SETTINGS.items():
        old, new = getattr(document.settings, key), getattr(trial.settings, key)
        if old != new:
            changes.append(f"Page: {name} {old} → {new}")
    if tables:
        changes.append(f"{tables} table{'s' if tables != 1 else ''}: borders and header row as the look has them")
    if lists:
        changes.append(f"{lists} list{'s' if lists != 1 else ''}: numbered or bulleted as the look counts them")
    if trial.headingNumbering != document.headingNumbering:
        changes.append("Headings: numbered as the look numbers them" if trial.headingNumbering else "Headings: no longer numbered")
    return StylePreview(
        before=document.resolvedStyles, after=trial.resolvedStyles, settings_before=document.settings, settings_after=trial.settings,
        changes=changes[:MAX_CHANGES], tables=tables, lists=lists,
    )
