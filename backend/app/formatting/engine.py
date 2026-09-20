from pydantic import BaseModel

from app.models.document import Document, DocumentSettings, FormattingProperty, FormattingRule, Revision, target_for_element

# Spec Section 7.9 defines 7 priority tiers; tier 6 (AI style inference) has
# no producer anywhere in the spec, so it's not built. Lower number wins.
PRIORITY_LIVE_OVERRIDE = 1
PRIORITY_INSTRUCTION = 2
PRIORITY_CUSTOM_TEMPLATE = 4
PRIORITY_BUILTIN_TEMPLATE = 5
PRIORITY_DEFAULT = 7


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


# Baseline so every document resolves to *something* even with no template
# chosen and no instructions given.
DEFAULT_RULES: list[FormattingRule] = [
    FormattingRule(target="Paragraph", property=FormattingProperty.FONT_FAMILY, value="Arial", priority=PRIORITY_DEFAULT, source="default"),
    FormattingRule(target="Paragraph", property=FormattingProperty.FONT_SIZE, value="11", unit="pt", priority=PRIORITY_DEFAULT, source="default"),
    FormattingRule(target="Paragraph", property=FormattingProperty.ALIGNMENT, value="left", priority=PRIORITY_DEFAULT, source="default"),
    FormattingRule(target="Paragraph", property=FormattingProperty.LINE_SPACING, value="1", priority=PRIORITY_DEFAULT, source="default"),
    FormattingRule(target="Document", property=FormattingProperty.PAGE_SIZE, value="A4", priority=PRIORITY_DEFAULT, source="default"),
    FormattingRule(target="Document", property=FormattingProperty.ORIENTATION, value="portrait", priority=PRIORITY_DEFAULT, source="default"),
]

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
        FormattingProperty.LINE_SPACING: lambda: {"line-height": value},
        FormattingProperty.PARAGRAPH_SPACING: lambda: {"margin-bottom": f"{value}{unit or 'pt'}"},
        FormattingProperty.FIRST_LINE_INDENT: lambda: {"text-indent": f"{value}{unit or 'cm'}"},
        FormattingProperty.IMAGE_WIDTH: lambda: {"width": f"{value}{unit or '%'}"},
        FormattingProperty.IMAGE_ALIGNMENT: lambda: _image_alignment_css(value),
    }
    build = mapping.get(rule.property)
    return build() if build else {}


def _resolve_single_target(rules: list[FormattingRule]) -> dict[str, str]:
    """Resolves a rule list as if every rule applied to the same one target,
    keeping only the lowest-priority (= highest precedence) rule per
    property, then converting the winners to CSS. Used both by
    resolve_styles (once per distinct target) and by _recompute_styles to
    merge a coarse type-level target with one element's own override rules."""
    best: dict[FormattingProperty, FormattingRule] = {}
    for rule in rules:
        current = best.get(rule.property)
        if current is None or rule.priority < current.priority:
            best[rule.property] = rule
    css: dict[str, str] = {}
    for rule in best.values():
        css.update(_rule_to_css(rule))
    return css


def resolve_styles(rules: list[FormattingRule]) -> dict[str, dict[str, str]]:
    """Groups rules by target and resolves each group independently.
    Document-level (page) properties are excluded -- those are resolved
    separately by extract_settings into DocumentSettings, since no single
    element owns them."""
    by_target: dict[str, list[FormattingRule]] = {}
    for rule in rules:
        if rule.target == "Document" or rule.property in _PAGE_LEVEL_PROPERTIES:
            continue
        by_target.setdefault(rule.target, []).append(rule)
    return {target: _resolve_single_target(target_rules) for target, target_rules in by_target.items()}


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
    if FormattingProperty.MARGIN_TOP in best:
        settings.marginTopCm = float(best[FormattingProperty.MARGIN_TOP].value)
    if FormattingProperty.MARGIN_BOTTOM in best:
        settings.marginBottomCm = float(best[FormattingProperty.MARGIN_BOTTOM].value)
    if FormattingProperty.MARGIN_LEFT in best:
        settings.marginLeftCm = float(best[FormattingProperty.MARGIN_LEFT].value)
    if FormattingProperty.MARGIN_RIGHT in best:
        settings.marginRightCm = float(best[FormattingProperty.MARGIN_RIGHT].value)
    if FormattingProperty.HEADER in best:
        settings.header = best[FormattingProperty.HEADER].value
    if FormattingProperty.FOOTER in best:
        settings.footer = best[FormattingProperty.FOOTER].value
    if FormattingProperty.SHOW_PAGE_NUMBERS in best:
        settings.showPageNumbers = _is_true(best[FormattingProperty.SHOW_PAGE_NUMBERS].value)
    return settings


def _recompute_styles(document: Document) -> None:
    """Rebuilds resolvedStyles/settings/styleRef from document.formattingRules
    as it currently stands. Shared by apply_formatting and the per-element
    override functions below so both mutation paths stay in lockstep."""
    rules = document.formattingRules
    element_ids = {element.id for element in document.elements}
    coarse_rules = [rule for rule in rules if rule.target not in element_ids]
    document.resolvedStyles = resolve_styles(coarse_rules)
    document.settings = extract_settings(rules)

    for element in document.elements:
        override_rules = [rule for rule in rules if rule.target == element.id]
        if not override_rules:
            element.styleRef = target_for_element(element)
            continue
        coarse_target = target_for_element(element)
        applicable = [
            rule
            for rule in rules
            if (rule.target == coarse_target or rule.target == element.id) and rule.property not in _PAGE_LEVEL_PROPERTIES
        ]
        document.resolvedStyles[element.id] = _resolve_single_target(applicable)
        element.styleRef = element.id


def detect_conflicts(
    document: Document, template_rules: list[FormattingRule], instruction_rules: list[FormattingRule]
) -> list[FormattingConflict]:
    """Compares incoming template/instruction rules against every existing
    live override. Only reports a conflict where the incoming value would
    actually *differ* from the override -- a template that happens to agree
    with what's already set is not a conflict."""
    incoming = [*template_rules, *instruction_rules]
    overrides = [rule for rule in document.formattingRules if rule.priority == PRIORITY_LIVE_OVERRIDE]
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
    hold across a *re*-format, not just within one.

    `drop_overrides` is how a resolved Conflict (spec §7.10, "Apply
    recommended") reaches this function: those specific (element, property)
    overrides are excluded from the preserved set, letting the incoming rule
    win instead. Anything not named is preserved exactly as before --
    "Keep current" is a no-op by construction, not a separate code path."""
    drop_set = set(drop_overrides or [])
    preserved_overrides = [
        rule
        for rule in document.formattingRules
        if rule.priority == PRIORITY_LIVE_OVERRIDE and (rule.target, rule.property) not in drop_set
    ]
    document.formattingRules = [*DEFAULT_RULES, *template_rules, *instruction_rules, *preserved_overrides]
    document.templateId = template_id
    _recompute_styles(document)

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
            priority=PRIORITY_LIVE_OVERRIDE,
            source="live_override",
        )
    )
    _recompute_styles(document)
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
    _recompute_styles(document)
    document.revisions.append(Revision(description=f"Cleared {property.value} override on one element"))
    return document
