from app.models.document import Document, DocumentSettings, FormattingProperty, FormattingRule, Revision, target_for_element

# Spec Section 7.9 defines 7 priority tiers; tiers 1 (live per-element user
# override) and 6 (AI style inference) have no producer yet in this phase --
# see docs/spec.md and the Phase 4 plan for why. Lower number wins.
PRIORITY_INSTRUCTION = 2
PRIORITY_CUSTOM_TEMPLATE = 4
PRIORITY_BUILTIN_TEMPLATE = 5
PRIORITY_DEFAULT = 7

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


def resolve_styles(rules: list[FormattingRule]) -> dict[str, dict[str, str]]:
    """Groups rules by target, keeping only the lowest-priority (= highest
    precedence) rule per (target, property) pair, then converts the winners
    to real CSS. Document-level (page) properties are excluded -- those are
    resolved separately by extract_settings into DocumentSettings, since no
    single element owns them."""
    best: dict[tuple[str, FormattingProperty], FormattingRule] = {}
    for rule in rules:
        if rule.target == "Document" or rule.property in _PAGE_LEVEL_PROPERTIES:
            continue
        key = (rule.target, rule.property)
        current = best.get(key)
        if current is None or rule.priority < current.priority:
            best[key] = rule

    resolved: dict[str, dict[str, str]] = {}
    for (target, _prop), rule in best.items():
        resolved.setdefault(target, {}).update(_rule_to_css(rule))
    return resolved


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


def apply_formatting(
    document: Document,
    *,
    template_id: str | None,
    template_rules: list[FormattingRule],
    instruction_rules: list[FormattingRule],
) -> Document:
    """The formatting-engine orchestrator (NFR-007: deterministic, no AI
    involved here -- instruction_rules already arrived pre-resolved from the
    AI-backed extraction step, if any). Fully recomputes everything from the
    three rule sources every call, rather than accumulating, so re-applying
    with a different template/instructions can never leave stale state
    behind."""
    merged = [*DEFAULT_RULES, *template_rules, *instruction_rules]
    document.formattingRules = merged
    document.templateId = template_id
    document.resolvedStyles = resolve_styles(merged)
    document.settings = extract_settings(merged)
    for element in document.elements:
        element.styleRef = target_for_element(element)

    description = "Applied formatting"
    if template_id:
        description += f" (template: {template_id})"
    if instruction_rules:
        description += " with custom instructions"
    document.revisions.append(Revision(description=description))

    return document
