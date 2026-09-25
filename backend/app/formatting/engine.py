from pydantic import BaseModel

from app.ai.schemas import AIDocumentOperation
from app.formatting.priorities import Priority
from app.formatting.render_spec import default_rules, inherit_from_body, line_height_css
from app.formatting.units import to_cm
from app.models.document import (
    COARSE_TARGETS,
    Document,
    DocumentSettings,
    Element,
    ElementType,
    FormattingProperty,
    FormattingRule,
    InlineRun,
    ListItem,
    Revision,
    TableCell,
    TableContent,
    TableRow,
    target_for_element,
)


class UnknownElementError(Exception):
    def __init__(self, element_id: str) -> None:
        super().__init__(f"Unknown element id: {element_id!r}")


class FormattingConflict(BaseModel):
    """Spec §7.10 -- a `/format` call's incoming template/instruction rules
    would change a property an existing live override (priority 1) already
    controls for one element. Surfaced to the user instead of silently
    resolved, even though priority alone would already pick a winner."""

    elementId: str
    property: FormattingProperty
    currentValue: str
    currentUnit: str | None = None
    requiredValue: str
    requiredUnit: str | None = None


# FormattingRule.source of rules that carry an uploaded file's own formatting.
SOURCE_DOCUMENT_SOURCE = "source_document"

# Baseline so every document resolves to *something* even with no template
# chosen and no instructions given: the render specification's defaults
# (formatting/render_spec.py), which the editor and both exports share.
DEFAULT_RULES: list[FormattingRule] = default_rules()

_PAGE_LEVEL_PROPERTIES = {
    FormattingProperty.PAGE_SIZE,
    FormattingProperty.ORIENTATION,
    FormattingProperty.MARGIN_TOP,
    FormattingProperty.MARGIN_BOTTOM,
    FormattingProperty.MARGIN_LEFT,
    FormattingProperty.MARGIN_RIGHT,
    FormattingProperty.HEADER,
    FormattingProperty.FOOTER,
    FormattingProperty.SHOW_PAGE_NUMBERS,
}


def _is_true(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def _image_alignment_css(value: str) -> dict[str, str]:
    if value == "center":
        return {"display": "block", "margin-left": "auto", "margin-right": "auto"}
    if value == "right":
        return {"display": "block", "margin-left": "auto", "margin-right": "0"}
    return {"display": "block", "margin-left": "0", "margin-right": "auto"}


def _rule_to_css(rule: FormattingRule) -> dict[str, str]:
    value, unit = rule.value, rule.unit
    mapping = {
        FormattingProperty.FONT_FAMILY: lambda: {"font-family": value},
        FormattingProperty.FONT_SIZE: lambda: {"font-size": f"{value}{unit or 'pt'}"},
        FormattingProperty.BOLD: lambda: {"font-weight": "bold" if _is_true(value) else "normal"},
        FormattingProperty.ITALIC: lambda: {"font-style": "italic" if _is_true(value) else "normal"},
        FormattingProperty.UNDERLINE: lambda: {"text-decoration": "underline" if _is_true(value) else "none"},
        FormattingProperty.COLOR: lambda: {"color": value},
        FormattingProperty.ALIGNMENT: lambda: {"text-align": value},
        # A unitless value is Word's multiple (drawn at Word's single height, see
        # render_spec.WORD_LINE_HEIGHT); "pt" is an exact height.
        FormattingProperty.LINE_SPACING: lambda: line_height_css(value, unit),
        FormattingProperty.SPACE_BEFORE: lambda: {"margin-top": f"{value}{unit or 'pt'}"},
        FormattingProperty.PARAGRAPH_SPACING: lambda: {"margin-bottom": f"{value}{unit or 'pt'}"},
        FormattingProperty.INDENT_LEFT: lambda: {"margin-left": f"{value}{unit or 'cm'}"},
        FormattingProperty.FIRST_LINE_INDENT: lambda: {"text-indent": f"{value}{unit or 'cm'}"},
        FormattingProperty.IMAGE_WIDTH: lambda: {"width": f"{value}{unit or '%'}"},
        FormattingProperty.IMAGE_ALIGNMENT: lambda: _image_alignment_css(value),
    }
    build = mapping.get(rule.property)
    return build() if build else {}


def _resolve_single_target(rules: list[FormattingRule], specific_target: str | None = None) -> dict[str, str]:
    """Resolves a rule list as if every rule applied to the same one target,
    keeping only the lowest-priority (= highest precedence) rule per
    property, then converting the winners to CSS. Used both by
    resolve_styles (once per distinct target) and by recompute_styles to
    merge a coarse type-level target with one element's own override rules.

    Within one priority tier, a rule for `specific_target` (one element)
    beats a rule for its whole type, as the more specific one; otherwise the
    first rule wins a tie."""
    best: dict[FormattingProperty, FormattingRule] = {}
    for rule in rules:
        current = best.get(rule.property)
        if current is None or _outranks(rule, current, specific_target):
            best[rule.property] = rule
    css: dict[str, str] = {}
    for rule in best.values():
        css.update(_rule_to_css(rule))
    return css


def _outranks(rule: FormattingRule, current: FormattingRule, specific_target: str | None) -> bool:
    if rule.priority != current.priority:
        return rule.priority < current.priority
    return specific_target is not None and rule.target == specific_target and current.target != specific_target


def resolve_styles(rules: list[FormattingRule]) -> dict[str, dict[str, str]]:
    """Groups rules by target and resolves each group independently.
    Document-level (page) properties are excluded -- those are resolved
    separately by extract_settings into DocumentSettings, since no single
    element owns them.

    The defaults always take part, after the given rules (so a document's own
    stored copy of them wins the tie; the values are the same), which also gives
    documents saved before a default existed the full base look. Then each kind
    of text takes from the body text what it doesn't set itself, as Word styles
    are based on Normal (render_spec.FROM_BODY)."""
    by_target: dict[str, list[FormattingRule]] = {}
    for rule in [*rules, *DEFAULT_RULES]:
        if rule.target == "Document" or rule.property in _PAGE_LEVEL_PROPERTIES:
            continue
        by_target.setdefault(rule.target, []).append(rule)
    resolved = {target: _resolve_single_target(target_rules) for target, target_rules in by_target.items()}
    body = resolved.get("Paragraph", {})
    return {target: inherit_from_body(target, css, body) for target, css in resolved.items()}


_MARGIN_FIELDS = {
    FormattingProperty.MARGIN_TOP: "marginTopCm",
    FormattingProperty.MARGIN_BOTTOM: "marginBottomCm",
    FormattingProperty.MARGIN_LEFT: "marginLeftCm",
    FormattingProperty.MARGIN_RIGHT: "marginRightCm",
}


def extract_settings(rules: list[FormattingRule]) -> DocumentSettings:
    best: dict[FormattingProperty, FormattingRule] = {}
    for rule in rules:
        if rule.target != "Document" or rule.property not in _PAGE_LEVEL_PROPERTIES:
            continue
        current = best.get(rule.property)
        if current is None or rule.priority < current.priority:
            best[rule.property] = rule

    settings = DocumentSettings()
    if FormattingProperty.PAGE_SIZE in best:
        settings.pageSize = best[FormattingProperty.PAGE_SIZE].value
    if FormattingProperty.ORIENTATION in best:
        settings.orientation = best[FormattingProperty.ORIENTATION].value
    for prop, field in _MARGIN_FIELDS.items():
        if prop in best:
            try:
                setattr(settings, field, to_cm(best[prop].value, best[prop].unit))
            except ValueError:
                pass  # not a length (e.g. "2em"): the default margin stays
    if FormattingProperty.HEADER in best:
        settings.header = best[FormattingProperty.HEADER].value
    if FormattingProperty.FOOTER in best:
        settings.footer = best[FormattingProperty.FOOTER].value
    if FormattingProperty.SHOW_PAGE_NUMBERS in best:
        settings.showPageNumbers = _is_true(best[FormattingProperty.SHOW_PAGE_NUMBERS].value)
    return settings


def prune_dangling_element_rules(document: Document) -> None:
    """Drops any FormattingRule whose target is a specific element id that no
    longer exists (e.g. after a structural delete) -- otherwise these rules
    just accumulate forever, since resolve_styles() silently tolerates a
    target that matches nothing (it would misclassify the stale id as a
    coarse target and produce a harmless but useless resolvedStyles entry).
    Call this any time document.elements shrinks."""
    element_ids = {element.id for element in document.elements}
    document.formattingRules = [
        rule for rule in document.formattingRules if rule.target in element_ids or rule.target in COARSE_TARGETS
    ]


def recompute_styles(document: Document) -> None:
    """Rebuilds resolvedStyles/settings/styleRef from document.formattingRules
    as it currently stands. Shared by apply_formatting, the per-element
    override functions below, and (via the public name) other mutators
    elsewhere in the service layer that touch elements/rules directly, so
    every mutation path stays in lockstep."""
    rules = document.formattingRules
    element_ids = {element.id for element in document.elements}
    coarse_rules = [rule for rule in rules if rule.target not in element_ids]
    document.resolvedStyles = resolve_styles(coarse_rules)
    document.settings = extract_settings(rules)
    body = document.resolvedStyles.get("Paragraph", {})

    for element in document.elements:
        override_rules = [rule for rule in rules if rule.target == element.id]
        if not override_rules:
            element.styleRef = target_for_element(element)
            continue
        coarse_target = target_for_element(element)
        applicable = [
            rule
            for rule in [*rules, *DEFAULT_RULES]
            if (rule.target == coarse_target or rule.target == element.id) and rule.property not in _PAGE_LEVEL_PROPERTIES
        ]
        resolved = _resolve_single_target(applicable, specific_target=element.id)
        document.resolvedStyles[element.id] = inherit_from_body(coarse_target, resolved, body)
        element.styleRef = element.id


def detect_conflicts(
    document: Document, template_rules: list[FormattingRule], instruction_rules: list[FormattingRule]
) -> list[FormattingConflict]:
    """Compares incoming template/instruction rules against every existing
    live override. Only reports a conflict where the incoming value would
    actually *differ* from the override -- a template that happens to agree
    with what's already set is not a conflict."""
    incoming = [*template_rules, *instruction_rules]
    overrides = [rule for rule in document.formattingRules if rule.priority == Priority.LIVE_OVERRIDE]
    elements_by_id = {element.id: element for element in document.elements}

    conflicts: list[FormattingConflict] = []
    for override in overrides:
        element = elements_by_id.get(override.target)
        if element is None:
            continue
        coarse_target = target_for_element(element)
        competing = [rule for rule in incoming if rule.target == coarse_target and rule.property == override.property]
        if not competing:
            continue
        winner = min(competing, key=lambda rule: rule.priority)
        if winner.value == override.value and winner.unit == override.unit:
            continue
        conflicts.append(
            FormattingConflict(
                elementId=element.id,
                property=override.property,
                currentValue=override.value,
                currentUnit=override.unit,
                requiredValue=winner.value,
                requiredUnit=winner.unit,
            )
        )
    return conflicts


def apply_formatting(
    document: Document,
    *,
    template_id: str | None,
    template_rules: list[FormattingRule],
    instruction_rules: list[FormattingRule],
    drop_overrides: list[tuple[str, FormattingProperty]] | None = None,
) -> Document:
    """The formatting-engine orchestrator (NFR-007: deterministic, no AI
    involved here -- instruction_rules already arrived pre-resolved from the
    AI-backed extraction step, if any). Fully recomputes the default/
    template/instruction layer from scratch every call, rather than
    accumulating, so re-applying with a different template/instructions can
    never leave stale state behind -- except existing live per-element
    overrides (priority 1), which are preserved: NFR-008 requires manual
    changes to take precedence over automatic suggestions, and that has to
    hold across a *re*-format, not just within one. The uploaded file's own
    formatting (SOURCE_DOCUMENT rules) is kept too, below the templates: it
    shows wherever the template sets nothing.

    `drop_overrides` is how a resolved Conflict (spec §7.10, "Apply
    recommended") reaches this function: those specific (element, property)
    overrides are excluded from the preserved set, letting the incoming rule
    win instead. Anything not named is preserved exactly as before --
    "Keep current" is a no-op by construction, not a separate code path."""
    drop_set = set(drop_overrides or [])
    preserved_overrides = [
        rule
        for rule in document.formattingRules
        if rule.priority == Priority.LIVE_OVERRIDE and (rule.target, rule.property) not in drop_set
    ]
    source_rules = [rule for rule in document.formattingRules if rule.source == SOURCE_DOCUMENT_SOURCE]
    document.formattingRules = [
        *DEFAULT_RULES,
        *source_rules,
        *template_rules,
        *instruction_rules,
        *preserved_overrides,
    ]
    document.templateId = template_id
    recompute_styles(document)

    description = "Applied formatting"
    if template_id:
        description += f" (template: {template_id})"
    if instruction_rules:
        description += " with custom instructions"
    document.revisions.append(Revision(description=description))

    return document


def set_element_override(
    document: Document, *, element_id: str, property: FormattingProperty, value: str, unit: str | None
) -> Document:
    """Spec §7.9 tier 1 -- an explicit user change to one specific element,
    the highest-priority tier. Reuses the element's own id as a
    FormattingRule.target (see module docs in the Phase 5b plan for why this
    needed no schema change)."""
    if not any(element.id == element_id for element in document.elements):
        raise UnknownElementError(element_id)

    document.formattingRules = [
        rule for rule in document.formattingRules if not (rule.target == element_id and rule.property == property)
    ]
    document.formattingRules.append(
        FormattingRule(
            target=element_id,
            property=property,
            value=value,
            unit=unit,
            priority=Priority.LIVE_OVERRIDE,
            source="live_override",
        )
    )
    recompute_styles(document)
    document.revisions.append(Revision(description=f"Set {property.value} override on one element"))
    return document


def clear_element_override(document: Document, *, element_id: str, property: FormattingProperty) -> Document:
    """Removes one element's override for one property, falling back to
    whatever the coarse type-level target (template/instructions/default)
    already resolves to."""
    if not any(element.id == element_id for element in document.elements):
        raise UnknownElementError(element_id)

    document.formattingRules = [
        rule for rule in document.formattingRules if not (rule.target == element_id and rule.property == property)
    ]
    recompute_styles(document)
    document.revisions.append(Revision(description=f"Cleared {property.value} override on one element"))
    return document


def set_document_setting(document: Document, *, property: FormattingProperty, value: str, unit: str | None) -> Document:
    """The page-level twin of set_element_override -- same priority tier
    (spec §7.9 tier 1: wins over template/instructions, survives a
    reformat), same replace-then-append shape, just targeting the
    "Document" pseudo-target (extract_settings' domain) instead of one
    element's id. No new resolution path: extract_settings() already picks
    the lowest-priority-number rule per property for "Document", exactly
    like resolve_styles() does per element target."""
    document.formattingRules = [
        rule for rule in document.formattingRules if not (rule.target == "Document" and rule.property == property)
    ]
    document.formattingRules.append(
        FormattingRule(
            target="Document",
            property=property,
            value=value,
            unit=unit,
            priority=Priority.LIVE_OVERRIDE,
            source="live_override",
        )
    )
    recompute_styles(document)
    document.revisions.append(Revision(description=f"Set page {property.value}"))
    return document


def clear_document_setting(document: Document, *, property: FormattingProperty) -> Document:
    document.formattingRules = [
        rule for rule in document.formattingRules if not (rule.target == "Document" and rule.property == property)
    ]
    recompute_styles(document)
    document.revisions.append(Revision(description=f"Reset page {property.value}"))
    return document


# --- Structural mutations: real pages (explicit page-break elements) and ---
# --- AI-driven structural instructions (delete/insert/move/add-page). ---
# Both the standalone "New Page" button and an AI operation batch route
# through the same _insert_at helper, so there's one place that keeps
# `order` contiguous after an insert.


def _insert_at(document: Document, new_element: Element, *, after_element_id: str | None) -> None:
    """Inserts `new_element` into document.elements, renumbering `order` to
    stay contiguous. `after_element_id=None` appends at the end."""
    ordered = sorted(document.elements, key=lambda el: el.order)
    if after_element_id is None:
        index = len(ordered)
    else:
        index = next((i for i, el in enumerate(ordered) if el.id == after_element_id), len(ordered) - 1) + 1
    ordered.insert(index, new_element)
    for i, el in enumerate(ordered):
        el.order = i
    document.elements = ordered


def insert_page_break(document: Document, *, after_element_id: str | None) -> Document:
    """New Page / Add Page (spec: real document-state pages, not a visual-
    only marker) -- a genuine Element, so "which page is element X on" is a
    pure function of where the PAGE_BREAK elements sit in document.elements,
    with nothing separate to fall out of sync."""
    if after_element_id is not None and not any(el.id == after_element_id for el in document.elements):
        raise UnknownElementError(after_element_id)
    new_break = Element(type=ElementType.PAGE_BREAK, content="", inline=[], order=0)
    _insert_at(document, new_break, after_element_id=after_element_id)
    recompute_styles(document)
    document.revisions.append(Revision(description="Added a page break"))
    return document


def _new_element_for_insert(element_type: ElementType, text: str) -> Element:
    """Shared by insert_element() below and apply_operations()'s own
    insert_element op -- one shape for "what does a freshly-inserted
    element of this type look like" regardless of whether a human or the
    AI asked for it. list/table get real (if empty) structure rather than
    a bare paragraph standing in for one; the AI is never actually allowed
    to request those two (see instruction_extraction._VALID_INSERT_TYPES),
    so this only matters for the manual Add-element UI today."""
    if element_type == ElementType.LIST:
        return Element(
            type=element_type,
            content=text,
            listItems=[ListItem(inline=[InlineRun(text=text)] if text else [], level=0)],
            ordered=False,
            order=0,
        )
    if element_type == ElementType.TABLE:
        return Element(
            type=element_type,
            content=text,
            table=TableContent(
                rows=[
                    TableRow(cells=[TableCell(inline=[], header=False), TableCell(inline=[], header=False)]),
                    TableRow(cells=[TableCell(inline=[], header=False), TableCell(inline=[], header=False)]),
                ],
                hasHeaderRow=False,
            ),
            order=0,
        )
    return Element(
        type=element_type,
        content=text,
        inline=[InlineRun(text=text, marks=[])] if text else [],
        level=1 if element_type == ElementType.HEADING else None,
        order=0,
    )


def insert_element(document: Document, *, element_type: ElementType, after_element_id: str | None, text: str = "") -> Document:
    """Manual, non-AI element insertion (the editor's own Add-element UI,
    triggered directly by the user rather than derived from an instruction)
    -- same dedicated-function-per-direct-UI-action shape as
    insert_page_break above, rather than going through apply_operations
    (which is specifically the AI-operations-batch applier, one call per
    instruction)."""
    if after_element_id is not None and not any(el.id == after_element_id for el in document.elements):
        raise UnknownElementError(after_element_id)
    new_element = _new_element_for_insert(element_type, text)
    _insert_at(document, new_element, after_element_id=after_element_id)
    recompute_styles(document)
    document.revisions.append(Revision(description=f"Inserted {element_type.value}"))
    return document


class InvalidOperationError(Exception):
    """One or more AI-derived structural operations referenced an element id
    that doesn't exist in the *current* document. Raised before anything is
    applied, so a batch is all-or-nothing -- the same "validate everything,
    mutate nothing until it's clean" shape as detect_conflicts, chosen
    because structural operations (unlike style rules) aren't order-
    independent or idempotent: silently dropping op 3 of 5 changes what the
    remaining ops mean."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def validate_operations(document: Document, operations: list[AIDocumentOperation]) -> None:
    element_ids = {el.id for el in document.elements}
    for op in operations:
        for field_name in ("element_id", "after_element_id"):
            value = getattr(op, field_name)
            if value is not None and value not in element_ids:
                raise InvalidOperationError(f"{op.op!r} operation references unknown element id {value!r} ({field_name})")
        if op.op == "set_style" and (op.property is None or op.value is None or op.element_id is None):
            raise InvalidOperationError("'set_style' operation is missing element_id/property/value")
        if op.op == "insert_element" and not op.element_type:
            raise InvalidOperationError("'insert_element' operation is missing element_type")


def apply_operations(document: Document, operations: list[AIDocumentOperation]) -> Document:
    """Assumes validate_operations() already passed. Structural ops mutate
    document.elements directly; set_style ops append a targeted, element-id
    FormattingRule (the same mechanism live per-element overrides use, just
    sourced from an instruction instead of the Properties panel). One call
    here corresponds to one instruction, applied as a single caller-side
    undo snapshot -- Undo reverts the whole instruction, not one operation
    within it."""
    for op in operations:
        if op.op == "delete_element":
            document.elements = [el for el in document.elements if el.id != op.element_id]
            prune_dangling_element_rules(document)
        elif op.op == "insert_element":
            new_element = _new_element_for_insert(ElementType(op.element_type), op.text or "")
            _insert_at(document, new_element, after_element_id=op.after_element_id)
        elif op.op == "move_element":
            moving = next((el for el in document.elements if el.id == op.element_id), None)
            if moving is None:
                continue
            document.elements = [el for el in document.elements if el.id != op.element_id]
            _insert_at(document, moving, after_element_id=op.after_element_id)
        elif op.op == "add_page_break":
            new_break = Element(type=ElementType.PAGE_BREAK, content="", inline=[], order=0)
            _insert_at(document, new_break, after_element_id=op.after_element_id)
        elif op.op == "set_style":
            document.formattingRules = [
                rule
                for rule in document.formattingRules
                if not (rule.target == op.element_id and rule.property == FormattingProperty(op.property))
            ]
            document.formattingRules.append(
                FormattingRule(
                    target=op.element_id,
                    property=FormattingProperty(op.property),
                    value=op.value,
                    unit=op.unit,
                    priority=Priority.INSTRUCTION,
                    source="instruction",
                )
            )

    recompute_styles(document)
    document.revisions.append(Revision(description=f"Applied {len(operations)} instruction operation(s)"))
    return document
