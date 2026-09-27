"""What a formatting rule's value may be, property by property: the limits the
StyleSystem sets (style_system.py), for rules that come from anywhere else --
the toolbar and Properties panel, page settings, an instruction, the editor's
own formatting on save. A rule's value is written into CSS, and into Word and
PDF styles, as text, so a value that doesn't pass here is never resolved: the
API refuses it, an instruction's rule is dropped, a stored one is skipped."""

import re

from app.formatting.colors import is_renderable_color, is_safe_font_name
from app.formatting.units import to_cm, to_pt
from app.models.document import FormattingProperty

_P = FormattingProperty
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)")
_TRUE, _FALSE = frozenset({"true", "1", "yes"}), frozenset({"false", "0", "no"})
_SWITCHES = frozenset(
    {
        _P.BOLD,
        _P.ITALIC,
        _P.UNDERLINE,
        _P.SHOW_PAGE_NUMBERS,
        _P.KEEP_WITH_NEXT,
        _P.KEEP_LINES_TOGETHER,
        _P.WIDOW_CONTROL,
        _P.CONTEXTUAL_SPACING,
    }
)
_CHOICES = {
    _P.ALIGNMENT: ("left", "center", "right", "justify"),
    _P.DIRECTION: ("ltr", "rtl"),
    _P.IMAGE_ALIGNMENT: ("left", "center", "right"),
    _P.ORIENTATION: ("portrait", "landscape"),
}
_PAGE_SIZES = {"a4": "A4", "letter": "Letter", "legal": "Legal"}
_MARGINS = frozenset({_P.MARGIN_TOP, _P.MARGIN_BOTTOM, _P.MARGIN_LEFT, _P.MARGIN_RIGHT})
_HEADER_FOOTER_LIMIT = 500  # as HeaderStyle/FooterStyle


class InvalidRuleValue(ValueError):
    pass


_BORDERS = frozenset({_P.BORDER_TOP, _P.BORDER_BOTTOM, _P.BORDER_LEFT, _P.BORDER_RIGHT})
_BORDER = re.compile(r"(solid|double|dotted|dashed) (\d+(?:\.\d+)?)pt (\S+)")
_TAB_STOP = re.compile(r"(left|center|right|decimal|bar) (\d+(?:\.\d+)?)cm(?: (dot|hyphen|underscore|heavy|middleDot))?")
TAB_ALIGNMENTS = ("left", "center", "right", "decimal", "bar")
TAB_LEADERS = ("dot", "hyphen", "underscore", "heavy", "middleDot")


def border_value(text: str) -> str:
    """A paragraph border on one side (DOCX-014): "<style> <width>pt <colour>", or "none"."""
    text = " ".join(text.split())
    if text.lower() == "none":
        return "none"
    match = _BORDER.fullmatch(text)
    if not match:
        raise InvalidRuleValue("a border is solid, double, dotted or dashed, a width in pt and a colour, or none")
    width = float(match.group(2))
    _within(width, 0.25, 12)
    if not is_renderable_color(match.group(3)):
        raise InvalidRuleValue("must be #rgb, #rrggbb or a basic colour name")
    return f"{match.group(1)} {_number_text(width)}pt {match.group(3)}"


def tab_stops_value(text: str) -> str:
    """Tab stops (DOCX-014): up to 30 of "<alignment> <position>cm [<leader>]", separated by ";"."""
    stops = [" ".join(stop.split()) for stop in text.split(";") if stop.strip()]
    if not stops or len(stops) > 30:
        raise InvalidRuleValue("1 to 30 tab stops, separated by ';'")
    written = []
    for stop in stops:
        match = _TAB_STOP.fullmatch(stop)
        if not match:
            raise InvalidRuleValue(f"{stop!r} isn't '<left|center|right|decimal|bar> <position>cm [<leader>]'")
        position = float(match.group(2))
        _within(position, 0, 60)
        written.append(" ".join(filter(None, (match.group(1), f"{_number_text(position)}cm", match.group(3)))))
    return "; ".join(written)


def _number(text: str) -> float:
    if not _NUMBER.fullmatch(text):
        raise InvalidRuleValue(f"{text!r} is not a number")
    return float(text)


def _within(amount: float, low: float, high: float, *, above_low: bool = False) -> None:
    if amount > high or amount < low or (above_low and amount == low):
        raise InvalidRuleValue(f"{amount:g} is outside {low:g}..{high:g}")


def _number_text(amount: float) -> str:
    return f"{amount:.4f}".rstrip("0").rstrip(".")  # as style_system._format_value writes numbers


def clean_rule_value(property: FormattingProperty, value: str, unit: str | None) -> tuple[str, str | None]:
    """The value and unit as they are stored and rendered (lower-case choices,
    "true"/"false", plain numbers). Raises InvalidRuleValue (a ValueError)."""
    text = value.strip() if isinstance(value, str) else ""
    unit = unit.strip().lower() or None if isinstance(unit, str) else None
    if not text:
        raise InvalidRuleValue("the value is empty")

    if property in (_P.HEADER, _P.FOOTER):  # text, never CSS
        if unit or len(value) > _HEADER_FOOTER_LIMIT:
            raise InvalidRuleValue(f"at most {_HEADER_FOOTER_LIMIT} characters, without a unit")
        return value, None
    if property in _CHOICES:
        if unit or text.lower() not in _CHOICES[property]:
            raise InvalidRuleValue(f"must be one of {', '.join(_CHOICES[property])}")
        return text.lower(), None
    if property in _SWITCHES:
        if unit or text.lower() not in _TRUE | _FALSE:
            raise InvalidRuleValue("must be true or false")
        return ("true" if text.lower() in _TRUE else "false"), None
    if property == _P.FONT_FAMILY:
        if unit or len(text) > 100 or not is_safe_font_name(text):
            raise InvalidRuleValue("must be one font name (letters, digits, spaces, '.' and '-')")
        return text, None
    if property in (_P.COLOR, _P.SHADING):
        if unit or not is_renderable_color(text):
            raise InvalidRuleValue("must be #rgb, #rrggbb or a basic colour name")
        return text, None
    if property in _BORDERS:
        if unit:
            raise InvalidRuleValue("a border has no unit of its own")
        return border_value(text), None
    if property == _P.TAB_STOPS:
        if unit:
            raise InvalidRuleValue("tab stops have no unit of their own")
        return tab_stops_value(text), None
    if property == _P.PAGE_SIZE:
        if unit or text.lower() not in _PAGE_SIZES:
            raise InvalidRuleValue(f"must be one of {', '.join(_PAGE_SIZES.values())}")
        return _PAGE_SIZES[text.lower()], None

    amount = _number(text)
    # to_pt / to_cm raise ValueError for a unit that isn't one of theirs.
    if property == _P.FONT_SIZE:
        _within(to_pt(text, unit), 0, 400, above_low=True)
    elif property == _P.LINE_SPACING:
        if unit is None:  # Word's multiple
            _within(amount, 0, 10, above_low=True)
        else:
            _within(to_pt(text, unit), 0, 500, above_low=True)
    elif property in (_P.SPACE_BEFORE, _P.PARAGRAPH_SPACING):
        _within(to_pt(text, unit), 0, 500)
    elif property in (_P.INDENT_LEFT, _P.INDENT_RIGHT):
        _within(to_cm(text, unit), -10, 20)
    elif property == _P.FIRST_LINE_INDENT:
        _within(to_cm(text, unit), -10, 10)
    elif property in _MARGINS:
        _within(to_cm(text, unit), 0, 10)
    elif property == _P.IMAGE_WIDTH:
        if unit not in (None, "%"):
            raise InvalidRuleValue("a picture's width is a percentage of the text width")
        _within(amount, 0, 100, above_low=True)
    else:
        raise InvalidRuleValue(f"no limits are known for {property.value}")
    return _number_text(amount), unit


def is_valid_rule_value(property: FormattingProperty, value: str, unit: str | None) -> bool:
    try:
        clean_rule_value(property, value, unit)
    except ValueError:
        return False
    return True
