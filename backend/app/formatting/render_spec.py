"""The Document Render Specification (корекции.docx §23): the one place that
says how big a page is and how each kind of block looks by default. The editor
preview, the DOCX export and the PDF export all draw from it -- the page sizes
directly (the editor through DocumentSettings.pageWidthMm/pageHeightMm), the
block defaults through the engine's resolved styles, which all three render.
No renderer keeps its own copy of any of this."""

from app.formatting.priorities import Priority
from app.models.document import FormattingProperty, FormattingRule

# Word's own sizes: A4 210 x 297 mm, Letter 8.5 x 11 in, Legal 8.5 x 14 in.
PAGE_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
}
DEFAULT_PAGE_SIZE = "A4"
TWIPS_PER_MM = 1440 / 25.4

# Word's "single" line spacing is a font's own line height -- ascent, descent
# and line gap -- about 1.15 x its size for Arial, Times New Roman and most
# others. A line spacing of N (as Word counts it) is drawn N x this x the font
# size in the editor and the PDF, so their pages hold what Word's do.
WORD_LINE_HEIGHT = 1.15


def line_height_css(value: str, unit: str | None) -> dict[str, str]:
    """CSS for a line spacing rule: `line-height` as a browser or PDF draws it,
    and `--line-spacing`, the value as Word counts it (read back by the DOCX
    export and the Properties panel)."""
    if unit:  # an exact height, the same everywhere
        return {"line-height": f"{value}{unit}", "--line-spacing": f"{value}{unit}"}
    try:
        drawn = float(value) * WORD_LINE_HEIGHT
    except ValueError:
        return {"line-height": value, "--line-spacing": value}
    return {"line-height": f"{drawn:.4f}".rstrip("0").rstrip("."), "--line-spacing": value}


def page_size_mm(size: str, orientation: str) -> tuple[float, float]:
    """(width, height) in mm; an unknown size is A4."""
    width, height = PAGE_SIZES_MM.get(size, PAGE_SIZES_MM[DEFAULT_PAGE_SIZE])
    return (height, width) if orientation == "landscape" else (width, height)


_P = FormattingProperty

# How each kind of block looks where nothing else (template, instructions, the
# uploaded file, a manual change) says otherwise. (value, unit) per property.
BASE_STYLES: dict[str, dict[FormattingProperty, tuple[str, str | None]]] = {
    "Paragraph": {
        _P.FONT_FAMILY: ("Arial", None),
        _P.FONT_SIZE: ("11", "pt"),
        _P.ALIGNMENT: ("left", None),
        _P.LINE_SPACING: ("1", None),
        _P.PARAGRAPH_SPACING: ("8", "pt"),
    },
    **{
        f"Heading {level}": {
            _P.FONT_SIZE: (size, "pt"),
            _P.BOLD: ("true", None),
            _P.LINE_SPACING: ("1", None),
            _P.SPACE_BEFORE: (before, "pt"),
            _P.PARAGRAPH_SPACING: (after, "pt"),
            **({_P.ITALIC: ("true", None)} if level == 6 else {}),
        }
        for level, size, before, after in (
            (1, "20", "18", "6"),
            (2, "16", "14", "6"),
            (3, "14", "12", "4"),
            (4, "12", "10", "4"),
            (5, "11", "10", "4"),
            (6, "11", "10", "4"),
        )
    },
    "List": {_P.PARAGRAPH_SPACING: ("8", "pt")},
    "Table": {_P.PARAGRAPH_SPACING: ("8", "pt")},
    "Quote": {_P.ITALIC: ("true", None), _P.INDENT_LEFT: ("1", "cm"), _P.PARAGRAPH_SPACING: ("8", "pt")},
    "Caption": {_P.FONT_SIZE: ("9", "pt"), _P.ITALIC: ("true", None), _P.PARAGRAPH_SPACING: ("8", "pt")},
    "Footnote": {_P.FONT_SIZE: ("9", "pt")},
    "CodeBlock": {
        _P.FONT_FAMILY: ("Courier New", None),
        _P.FONT_SIZE: ("10", "pt"),
        _P.LINE_SPACING: ("1", None),
        _P.PARAGRAPH_SPACING: ("8", "pt"),
    },
}

# What the other kinds of text take from the body text when nothing sets it
# for them -- as Word's styles are "based on Normal". CSS property names, since
# this applies to resolved styles.
_LINE = ("line-height", "--line-spacing")
_BODY_TEXT = ("font-family", "font-size", "color", *_LINE, "text-align")
FROM_BODY: dict[str, tuple[str, ...]] = {
    **{f"Heading {level}": ("font-family", "color") for level in range(1, 7)},
    "List": _BODY_TEXT,
    "Quote": _BODY_TEXT,
    "Table": ("font-family", "font-size", "color", *_LINE),
    "Caption": ("font-family", "color", "text-align", *_LINE),
    "Footnote": ("font-family", "color", *_LINE),
    "CodeBlock": ("color",),
}


def default_rules() -> list[FormattingRule]:
    """BASE_STYLES and the default page, as the engine's lowest-priority rules."""
    rules = [
        FormattingRule(target=target, property=prop, value=value, unit=unit, priority=Priority.DEFAULT, source="default")
        for target, properties in BASE_STYLES.items()
        for prop, (value, unit) in properties.items()
    ]
    rules += [
        FormattingRule(target="Document", property=_P.PAGE_SIZE, value=DEFAULT_PAGE_SIZE, priority=Priority.DEFAULT, source="default"),
        FormattingRule(target="Document", property=_P.ORIENTATION, value="portrait", priority=Priority.DEFAULT, source="default"),
    ]
    return rules


def inherit_from_body(target: str, css: dict[str, str], body: dict[str, str]) -> dict[str, str]:
    """`css` with what `target` takes from the body text filled in where it sets nothing itself."""
    inherited = {key: body[key] for key in FROM_BODY.get(target, ()) if key not in css and key in body}
    return {**css, **inherited} if inherited else css
