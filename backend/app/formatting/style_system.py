"""StyleSystem: the product-level description of how a document looks
(корекции.docx §19). It is what a template *is*, and what Format by Example will
extract from a reference document (§17).

FormattingRule stays the engine's internal mechanism. compile_rules() turns a
StyleSystem into rules (the same rules for the same input, every time), and
style_system_from_rules() goes back from the type-level rules of a template or a
formatted document."""

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.formatting.colors import is_renderable_color, is_safe_font_name
from app.formatting.priorities import Priority
from app.formatting.units import to_cm, to_pt
from app.models.base import ApiModel
from app.models.document import COARSE_TARGETS, FormattingProperty, FormattingRule

Alignment = Literal["left", "center", "right", "justify"]
# The sizes the editor and both exporters know the dimensions of.
PageSize = Literal["A4", "Letter", "Legal"]


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class _Section(ApiModel):
    # A typo in builtin_templates.json or an API payload must fail loudly, not
    # quietly style nothing.
    model_config = ConfigDict(extra="forbid")


class _Colored(_Section):
    # Non-strings fall through untouched, for the field's own type check to reject.
    @field_validator("color", mode="before", check_fields=False)
    @classmethod
    def _renderable_color(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if isinstance(value, str) and not is_renderable_color(value):
            raise ValueError("must be #rgb, #rrggbb or a basic colour name")
        return value

    @field_validator("fontFamily", mode="before", check_fields=False)
    @classmethod
    def _single_font_name(cls, value: Any) -> Any:
        value = _blank_to_none(value)
        if isinstance(value, str) and not is_safe_font_name(value):
            raise ValueError("must be one font name (letters, digits, spaces, '.' and '-')")
        return value


class TextStyle(_Colored):
    """How one kind of text block looks. None means "not set here": the
    document-wide values below, then the engine's defaults, decide instead."""

    fontFamily: str | None = Field(default=None, max_length=100)
    fontSizePt: float | None = Field(default=None, gt=0, le=400)
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    color: str | None = None
    alignment: Alignment | None = None
    lineSpacing: float | None = Field(default=None, gt=0, le=10)
    spaceBeforePt: float | None = Field(default=None, ge=0, le=500)
    spaceAfterPt: float | None = Field(default=None, ge=0, le=500)
    indentLeftCm: float | None = Field(default=None, ge=-10, le=20)
    firstLineIndentCm: float | None = Field(default=None, ge=-10, le=10)


class DocumentStyle(_Colored):
    """Document-wide typography: every text block uses these unless it sets its
    own. Code blocks keep their own (monospace) font and only take the colour."""

    fontFamily: str | None = Field(default=None, max_length=100)
    color: str | None = None


class HeadingStyles(_Section):
    h1: TextStyle = Field(default_factory=TextStyle)
    h2: TextStyle = Field(default_factory=TextStyle)
    h3: TextStyle = Field(default_factory=TextStyle)
    h4: TextStyle = Field(default_factory=TextStyle)
    h5: TextStyle = Field(default_factory=TextStyle)
    h6: TextStyle = Field(default_factory=TextStyle)


class PageStyle(_Section):
    size: PageSize | None = None
    orientation: Literal["portrait", "landscape"] | None = None
    marginTopCm: float | None = Field(default=None, ge=0, le=10)
    marginBottomCm: float | None = Field(default=None, ge=0, le=10)
    marginLeftCm: float | None = Field(default=None, ge=0, le=10)
    marginRightCm: float | None = Field(default=None, ge=0, le=10)


class ImageStyle(_Section):
    widthPercent: float | None = Field(default=None, gt=0, le=100)
    alignment: Literal["left", "center", "right"] | None = None


class _Captioned(_Section):
    @field_validator("text", mode="before", check_fields=False)
    @classmethod
    def _blank_text(cls, value: Any) -> Any:
        return _blank_to_none(value)


class HeaderStyle(_Captioned):
    text: str | None = Field(default=None, max_length=500)


class FooterStyle(_Captioned):
    text: str | None = Field(default=None, max_length=500)
    pageNumbers: bool | None = None


class StyleSystem(_Section):
    schemaVersion: int = 1
    page: PageStyle = Field(default_factory=PageStyle)
    document: DocumentStyle = Field(default_factory=DocumentStyle)
    paragraph: TextStyle = Field(default_factory=TextStyle)
    headings: HeadingStyles = Field(default_factory=HeadingStyles)
    lists: TextStyle = Field(default_factory=TextStyle)
    tables: TextStyle = Field(default_factory=TextStyle)
    captions: TextStyle = Field(default_factory=TextStyle)
    quotes: TextStyle = Field(default_factory=TextStyle)
    footnotes: TextStyle = Field(default_factory=TextStyle)
    code: TextStyle = Field(default_factory=TextStyle)
    images: ImageStyle = Field(default_factory=ImageStyle)
    header: HeaderStyle = Field(default_factory=HeaderStyle)
    footer: FooterStyle = Field(default_factory=FooterStyle)


# Engine target -> where its style lives in a StyleSystem, in compile order.
_TEXT_TARGETS: dict[str, tuple[str, ...]] = {
    "Paragraph": ("paragraph",),
    **{f"Heading {level}": ("headings", f"h{level}") for level in range(1, 7)},
    "List": ("lists",),
    "Table": ("tables",),
    "Caption": ("captions",),
    "Quote": ("quotes",),
    "Footnote": ("footnotes",),
    "CodeBlock": ("code",),
}

# (field, property, the unit the value is written in)
_Field = tuple[str, FormattingProperty, str | None]
_TEXT_FIELDS: list[_Field] = [
    ("fontFamily", FormattingProperty.FONT_FAMILY, None),
    ("fontSizePt", FormattingProperty.FONT_SIZE, "pt"),
    ("bold", FormattingProperty.BOLD, None),
    ("italic", FormattingProperty.ITALIC, None),
    ("underline", FormattingProperty.UNDERLINE, None),
    ("color", FormattingProperty.COLOR, None),
    ("alignment", FormattingProperty.ALIGNMENT, None),
    ("lineSpacing", FormattingProperty.LINE_SPACING, None),
    ("spaceBeforePt", FormattingProperty.SPACE_BEFORE, "pt"),
    ("spaceAfterPt", FormattingProperty.PARAGRAPH_SPACING, "pt"),
    ("indentLeftCm", FormattingProperty.INDENT_LEFT, "cm"),
    ("firstLineIndentCm", FormattingProperty.FIRST_LINE_INDENT, "cm"),
]
_IMAGE_FIELDS: list[_Field] = [
    ("widthPercent", FormattingProperty.IMAGE_WIDTH, "%"),
    ("alignment", FormattingProperty.IMAGE_ALIGNMENT, None),
]
# Everything aimed at the "Document" pseudo-target, by section.
_DOCUMENT_FIELDS: dict[str, list[_Field]] = {
    "page": [
        ("size", FormattingProperty.PAGE_SIZE, None),
        ("orientation", FormattingProperty.ORIENTATION, None),
        ("marginTopCm", FormattingProperty.MARGIN_TOP, "cm"),
        ("marginBottomCm", FormattingProperty.MARGIN_BOTTOM, "cm"),
        ("marginLeftCm", FormattingProperty.MARGIN_LEFT, "cm"),
        ("marginRightCm", FormattingProperty.MARGIN_RIGHT, "cm"),
    ],
    "header": [("text", FormattingProperty.HEADER, None)],
    "footer": [
        ("text", FormattingProperty.FOOTER, None),
        ("pageNumbers", FormattingProperty.SHOW_PAGE_NUMBERS, None),
    ],
}

_SECTION_MODELS: dict[str, type[_Section]] = {
    "page": PageStyle,
    "header": HeaderStyle,
    "footer": FooterStyle,
    "images": ImageStyle,
}


def _format_value(value: bool | float | str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return value


def _section(style: StyleSystem, path: tuple[str, ...]) -> BaseModel:
    node: BaseModel = style
    for key in path:
        node = getattr(node, key)
    return node


def compile_rules(style: StyleSystem, *, priority: Priority, source: str) -> list[FormattingRule]:
    """The FormattingRules that make a document look like `style`, all at one
    priority tier. A field left as None produces no rule at all, so lower tiers
    (the engine's defaults) still apply to it."""
    rules: list[FormattingRule] = []

    def emit(target: str, fields: list[_Field], values: BaseModel, inherited: dict[str, Any] | None = None) -> None:
        for field, prop, unit in fields:
            value = getattr(values, field)
            if value is None and inherited:
                value = inherited.get(field)
            if value is not None:
                rules.append(
                    FormattingRule(
                        target=target,
                        property=prop,
                        value=_format_value(value),
                        unit=unit,
                        priority=priority,
                        source=source,
                    )
                )

    base = style.document
    for target, path in _TEXT_TARGETS.items():
        inherited = {"color": base.color} if target == "CodeBlock" else {"fontFamily": base.fontFamily, "color": base.color}
        emit(target, _TEXT_FIELDS, _section(style, path), inherited)
    emit("Image", _IMAGE_FIELDS, style.images)
    for section, fields in _DOCUMENT_FIELDS.items():
        emit("Document", fields, getattr(style, section))
    return rules


def _parse(prop: FormattingProperty, unit_written: str | None, rule: FormattingRule) -> Any:
    """A rule's value converted to what the StyleSystem field holds."""
    if prop in (
        FormattingProperty.BOLD,
        FormattingProperty.ITALIC,
        FormattingProperty.UNDERLINE,
        FormattingProperty.SHOW_PAGE_NUMBERS,
    ):
        text = rule.value.strip().lower()
        if text in ("true", "1", "yes"):
            return True
        if text in ("false", "0", "no"):
            return False
        raise ValueError(f"{rule.value!r} is not true/false")
    if unit_written == "cm":
        return round(to_cm(rule.value, rule.unit), 4)
    if unit_written == "pt":
        return round(to_pt(rule.value, rule.unit), 4)
    if unit_written == "%":
        if (rule.unit or "%") != "%":
            raise ValueError(f"unsupported unit {rule.unit!r}")
        return float(rule.value)
    if prop == FormattingProperty.LINE_SPACING:
        return float(rule.value)
    return rule.value


def _locate(target: str, prop: FormattingProperty) -> tuple[tuple[str, ...], type[_Section], _Field] | None:
    if target in _TEXT_TARGETS:
        fields, path, model = _TEXT_FIELDS, _TEXT_TARGETS[target], TextStyle
    elif target == "Image":
        fields, path, model = _IMAGE_FIELDS, ("images",), ImageStyle
    elif target == "Document":
        for section, section_fields in _DOCUMENT_FIELDS.items():
            for entry in section_fields:
                if entry[1] == prop:
                    return (section,), _SECTION_MODELS[section], entry
        return None
    else:
        return None
    for entry in fields:
        if entry[1] == prop:
            return path, model, entry
    return None


def style_system_from_rules(rules: Iterable[FormattingRule]) -> tuple[StyleSystem, list[str]]:
    """The StyleSystem that the type-level rules describe: for each (target,
    property) the winning rule (lowest priority number, the first one on a tie,
    exactly as the engine resolves) fills the matching field.

    Rules aimed at one specific element (live overrides on a single paragraph)
    describe that element, not a style, and are left out. Anything else that
    can't be represented (a property with no field, an unconvertible unit, a
    value the StyleSystem would reject) is skipped and described in the
    returned notes, so nothing disappears without a trace."""
    winners: dict[tuple[str, FormattingProperty], FormattingRule] = {}
    for rule in rules:
        if rule.target not in COARSE_TARGETS:
            continue
        key = (rule.target, rule.property)
        if key not in winners or rule.priority < winners[key].priority:
            winners[key] = rule

    data: dict[str, Any] = {}
    notes: list[str] = []
    for (target, prop), rule in winners.items():
        located = _locate(target, prop)
        if located is None:
            notes.append(f"{target}: '{prop.value}' has no place in a style system")
            continue
        path, model, (field, _, unit_written) = located
        try:
            value = _parse(prop, unit_written, rule)
            model.model_validate({field: value})
        except (ValueError, ValidationError) as exc:
            reason = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
            notes.append(f"{target}: '{prop.value}' = {rule.value!r}{f' {rule.unit}' if rule.unit else ''} skipped ({reason})")
            continue
        node = data
        for key in path:
            node = node.setdefault(key, {})
        node[field] = value
    return StyleSystem.model_validate(data), notes
