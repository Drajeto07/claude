"""How an uploaded .docx says it should look: its Word styles (followed through
basedOn and docDefaults, with theme fonts resolved the way Word resolves them),
its list numbering, and its page setup, header and footer.

extract_style_system() turns the styles into a StyleSystem, compiled by the
parser at the SOURCE_DOCUMENT tier: an import then looks like the original,
and any template applied later still wins. Formatting set directly on single
paragraphs and runs is handled in docx.py on top of this."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, replace
from typing import Any

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from lxml import etree
from pydantic import ValidationError

from app.formatting.colors import is_renderable_color, is_safe_font_name
from app.formatting.list_numbering import Counters, format_number, level_label
from app.formatting.render_spec import PAGE_SIZES_MM, TWIPS_PER_MM
from app.formatting.style_system import (
    FooterStyle,
    HeaderStyle,
    PageStyle,
    StyleSystem,
    TextStyle,
)
from app.security.files import parse_xml_part

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_TWIPS_PER_CM = 1440 / 2.54
_TWIPS_PER_PT = 20
# pgSz in twips, portrait. Matched with a tolerance: Word rounds these.
# From the render specification, in Word's unit (twentieths of a point).
_PAGE_SIZES_TWIPS = {name: (round(w * TWIPS_PER_MM), round(h * TWIPS_PER_MM)) for name, (w, h) in PAGE_SIZES_MM.items()}
_PAGE_SIZE_TOLERANCE_TWIPS = 120  # about 2 mm

# Header/footer fields the app can show live; any other field keeps the text Word last showed.
PAGE_TOKEN = "{PAGE}"
NUMPAGES_TOKEN = "{NUMPAGES}"
_FIELD_TOKENS = {"PAGE": PAGE_TOKEN, "NUMPAGES": NUMPAGES_TOKEN, "SECTIONPAGES": NUMPAGES_TOKEN}


def w(tag: str) -> str:
    return qn(f"w:{tag}")


def on_off(element: etree._Element | None) -> bool | None:
    """Word's boolean properties: present means on unless val says otherwise."""
    if element is None:
        return None
    return element.get(w("val"), "true").lower() not in ("0", "false", "off", "none")


def hex_color(value: str | None) -> str | None:
    if not value or value.lower() == "auto" or not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        return None
    return f"#{value.upper()}"


def twips_to_cm(value: str | None) -> float | None:
    try:
        return round(int(float(value)) / _TWIPS_PER_CM, 2) if value is not None else None
    except ValueError:
        return None


def twips_to_pt(value: str | None) -> float | None:
    try:
        return round(int(float(value)) / _TWIPS_PER_PT, 2) if value is not None else None
    except ValueError:
        return None


@dataclass(frozen=True)
class ParaProps:
    """Paragraph formatting; None = not set at this level."""

    alignment: str | None = None
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    # (value, unit): unit None is a multiple of the font size, "pt" an exact height.
    line_spacing: tuple[float, str | None] | None = None
    indent_left_cm: float | None = None
    first_line_cm: float | None = None
    # DOCX-014
    indent_right_cm: float | None = None
    shading: str | None = None  # w:shd/@w:fill
    keep_next: bool | None = None
    keep_lines: bool | None = None
    widow_control: bool | None = None
    contextual_spacing: bool | None = None
    bidi: bool | None = None  # right to left
    # Borders as rules have them ("solid 0.5pt #000000", "none"), and tab stops.
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    tab_stops: str | None = None

    def over(self, base: ParaProps) -> ParaProps:
        """These values, falling back to `base` wherever unset."""
        return ParaProps(**{f.name: getattr(self, f.name) if getattr(self, f.name) is not None else getattr(base, f.name) for f in fields(self)})


@dataclass(frozen=True)
class TextProps:
    """Character formatting; None = not set at this level."""

    font: str | None = None
    size_pt: float | None = None
    color: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    hidden: bool | None = None  # w:vanish
    # Kept on runs rather than in a block's look (DOCX-013): the underline's Word
    # style (w:u/@w:val), strikethrough, capitals, spacing and position in points.
    underline_style: str | None = None
    strike: bool | None = None
    double_strike: bool | None = None
    caps: bool | None = None
    small_caps: bool | None = None
    spacing_pt: float | None = None
    position_pt: float | None = None
    lang: str | None = None  # w:lang/@w:val

    def over(self, base: TextProps) -> TextProps:
        return TextProps(**{f.name: getattr(self, f.name) if getattr(self, f.name) is not None else getattr(base, f.name) for f in fields(self)})


# What Word draws where neither a style nor the document's defaults say (ECMA-376
# §17.7.2): no bold or italics, no spacing, single lines, left aligned, no indent, 10 pt
# Times New Roman. The styles the importer takes are completed with it, so the app's own
# defaults (formatting/render_spec.py) never stand in for what a file leaves to Word
# (tracker FMT-004).
WORD_DRAWS_PARA = ParaProps(alignment="left", space_before_pt=0.0, space_after_pt=0.0, line_spacing=(1.0, None), indent_left_cm=0.0)
WORD_DRAWS_TEXT = TextProps(font="Times New Roman", size_pt=10.0, bold=False, italic=False)


def as_word_draws(para: ParaProps, text: TextProps) -> tuple[ParaProps, TextProps]:
    return para.over(WORD_DRAWS_PARA), text.over(WORD_DRAWS_TEXT)


_JC_TO_ALIGNMENT = {
    "left": "left",
    "start": "left",
    "center": "center",
    "right": "right",
    "end": "right",
    "both": "justify",
    "distribute": "justify",
    "lowKashida": "justify",
    "mediumKashida": "justify",
    "highKashida": "justify",
}


def para_props_of(ppr: etree._Element | None) -> ParaProps:
    """Only what this pPr sets itself."""
    if ppr is None:
        return ParaProps()
    alignment = None
    jc = ppr.find(w("jc"))
    if jc is not None:
        alignment = _JC_TO_ALIGNMENT.get(jc.get(w("val"), ""))
    space_before = space_after = None
    line_spacing = None
    spacing = ppr.find(w("spacing"))
    if spacing is not None:
        space_before = twips_to_pt(spacing.get(w("before")))
        space_after = twips_to_pt(spacing.get(w("after")))
        line = spacing.get(w("line"))
        if line is not None:
            rule = spacing.get(w("lineRule"), "auto")
            try:
                value = int(float(line))
            except ValueError:
                value = None
            if value:
                line_spacing = (round(value / 240, 2), None) if rule == "auto" else (round(value / 20, 1), "pt")
    indent_left = first_line = indent_right = None
    ind = ppr.find(w("ind"))
    if ind is not None:
        indent_left = twips_to_cm(ind.get(w("left")) or ind.get(w("start")))
        indent_right = twips_to_cm(ind.get(w("right")) or ind.get(w("end")))
        if ind.get(w("hanging")) is not None:
            hanging = twips_to_cm(ind.get(w("hanging")))
            first_line = -hanging if hanging is not None else None
        else:
            first_line = twips_to_cm(ind.get(w("firstLine")))
    shd = ppr.find(w("shd"))
    fill = shd.get(w("fill")) if shd is not None else None
    borders = _borders(ppr.find(w("pBdr")))
    return ParaProps(
        alignment=alignment,
        space_before_pt=space_before,
        space_after_pt=space_after,
        line_spacing=line_spacing,
        indent_left_cm=indent_left,
        first_line_cm=first_line,
        indent_right_cm=indent_right,
        shading=hex_color(fill) if fill and fill.lower() != "auto" else None,
        keep_next=on_off(ppr.find(w("keepNext"))),
        keep_lines=on_off(ppr.find(w("keepLines"))),
        widow_control=on_off(ppr.find(w("widowControl"))),
        contextual_spacing=on_off(ppr.find(w("contextualSpacing"))),
        bidi=on_off(ppr.find(w("bidi"))),
        border_top=borders.get("top"),
        border_bottom=borders.get("bottom"),
        border_left=borders.get("left") or borders.get("start"),
        border_right=borders.get("right") or borders.get("end"),
        tab_stops=_tab_stops(ppr.find(w("tabs"))),
    )


# Word's border styles as the four a rule has (the closest for the others).
_BORDER_STYLES = {"single": "solid", "thick": "solid", "double": "double", "dotted": "dotted", "dashed": "dashed", "dashSmallGap": "dashed", "dotDash": "dashed", "dotDotDash": "dashed"}


def _borders(pbdr: etree._Element | None) -> dict[str, str]:
    """A paragraph's borders, side by side, as border rules write them (DOCX-014)."""
    found: dict[str, str] = {}
    for side in pbdr if pbdr is not None else []:
        name = etree.QName(side).localname
        if name not in ("top", "bottom", "left", "right", "start", "end"):
            continue  # "between" and "bar" aren't kept
        style = side.get(w("val"), "nil")
        if style in ("nil", "none"):
            found[name] = "none"
            continue
        try:
            width = min(max(int(side.get(w("sz"), "4")) / 8, 0.25), 12)
        except ValueError:
            width = 0.5
        color = hex_color(side.get(w("color"))) or "#000000"
        found[name] = f"{_BORDER_STYLES.get(style, 'solid')} {width:g}pt {color}"
    return found


_TAB_LEADERS = {"dot": "dot", "hyphen": "hyphen", "underscore": "underscore", "heavy": "heavy", "middleDot": "middleDot"}
_TAB_ALIGNMENTS = {"left": "left", "start": "left", "center": "center", "right": "right", "end": "right", "decimal": "decimal", "bar": "bar"}


def _tab_stops(tabs: etree._Element | None) -> str | None:
    """A paragraph's own tab stops as a rule writes them ("right 16cm dot; left 2cm")."""
    stops = []
    for tab in tabs if tabs is not None else []:
        alignment = _TAB_ALIGNMENTS.get(tab.get(w("val"), ""))
        position = twips_to_cm(tab.get(w("pos")))
        if alignment is None or position is None or not 0 <= position <= 60:
            continue  # "clear" and the like
        leader = _TAB_LEADERS.get(tab.get(w("leader"), ""))
        stops.append(" ".join(filter(None, (alignment, f"{position:g}cm", leader))))
    return "; ".join(stops[:30]) or None


class ThemeFonts:
    def __init__(self, document_part) -> None:
        self.major: str | None = None
        self.minor: str | None = None
        try:
            theme = document_part.part_related_by(RT.THEME)
        except (KeyError, ValueError):
            return
        try:
            root = parse_xml_part(theme.blob)
        except etree.XMLSyntaxError:
            return
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        major = root.find(".//a:majorFont/a:latin", ns)
        minor = root.find(".//a:minorFont/a:latin", ns)
        self.major = (major.get("typeface") or None) if major is not None else None
        self.minor = (minor.get("typeface") or None) if minor is not None else None

    def resolve(self, theme_value: str) -> str | None:
        return self.major if theme_value.lower().startswith("major") else self.minor


def text_props_of(rpr: etree._Element | None, theme: ThemeFonts) -> TextProps:
    """Only what this rPr sets itself. A theme font attribute wins over an
    explicit font name at the same level, as in Word."""
    if rpr is None:
        return TextProps()
    font = None
    rfonts = rpr.find(w("rFonts"))
    if rfonts is not None:
        theme_attr = rfonts.get(w("asciiTheme")) or rfonts.get(w("hAnsiTheme"))
        font = theme.resolve(theme_attr) if theme_attr else (rfonts.get(w("ascii")) or rfonts.get(w("hAnsi")))
    size = None
    sz = rpr.find(w("sz"))
    if sz is not None:
        try:
            size = int(sz.get(w("val"))) / 2
        except (TypeError, ValueError):
            size = None
    color_el = rpr.find(w("color"))
    color = hex_color(color_el.get(w("val"))) if color_el is not None else None
    underline = underline_style = None
    u = rpr.find(w("u"))
    if u is not None:
        underline_style = u.get(w("val"), "single")
        underline = underline_style != "none"
    return TextProps(
        font=font,
        size_pt=size,
        color=color,
        bold=on_off(rpr.find(w("b"))),
        italic=on_off(rpr.find(w("i"))),
        underline=underline,
        hidden=on_off(rpr.find(w("vanish"))),
        underline_style=underline_style,
        strike=on_off(rpr.find(w("strike"))),
        double_strike=on_off(rpr.find(w("dstrike"))),
        caps=on_off(rpr.find(w("caps"))),
        small_caps=on_off(rpr.find(w("smallCaps"))),
        spacing_pt=_measure(rpr.find(w("spacing")), 20),
        position_pt=_measure(rpr.find(w("position")), 2),
        lang=(rpr.find(w("lang")).get(w("val")) or None) if rpr.find(w("lang")) is not None else None,
    )


def _measure(element: etree._Element | None, per_point: int) -> float | None:
    """A w:spacing (twentieths of a point) or w:position (half points) in points."""
    if element is None:
        return None
    try:
        return int(element.get(w("val"))) / per_point
    except (TypeError, ValueError):
        return None


class StyleResolver:
    """Word styles by id and name, and the effective formatting of a paragraph
    or character style: its own values, then its basedOn ancestors', then the
    document defaults."""

    def __init__(self, docx_document) -> None:
        styles_root = docx_document.styles.element
        self.theme = ThemeFonts(docx_document.part)
        self._by_id: dict[str, etree._Element] = {}
        self._id_by_name: dict[str, str] = {}
        self.default_paragraph_style: str | None = None
        for style in styles_root.findall(w("style")):
            style_id = style.get(w("styleId"))
            if not style_id:
                continue
            self._by_id[style_id] = style
            name_el = style.find(w("name"))
            if name_el is not None and name_el.get(w("val")):
                self._id_by_name[name_el.get(w("val")).lower()] = style_id
            if style.get(w("type")) == "paragraph" and on_off_attr(style.get(w("default"))):
                self.default_paragraph_style = style_id
        defaults = styles_root.find(w("docDefaults"))
        rpr_default = defaults.find(f"{w('rPrDefault')}/{w('rPr')}") if defaults is not None else None
        ppr_default = defaults.find(f"{w('pPrDefault')}/{w('pPr')}") if defaults is not None else None
        self._default_text = text_props_of(rpr_default, self.theme)
        self._default_para = para_props_of(ppr_default)

    @property
    def default_language(self) -> str | None:
        """The document's own language (its defaults' w:lang)."""
        return self._default_text.lang

    def id_for_name(self, name: str) -> str | None:
        return self._id_by_name.get(name.lower())

    def name_of(self, style_id: str | None) -> str:
        style = self._by_id.get(style_id or "")
        name_el = style.find(w("name")) if style is not None else None
        return name_el.get(w("val"), "") if name_el is not None else ""

    def chain(self, style_id: str | None) -> list[etree._Element]:
        """The style, then each style it is based on (cycles cut)."""
        result: list[etree._Element] = []
        seen: set[str] = set()
        while style_id and style_id not in seen and style_id in self._by_id:
            seen.add(style_id)
            style = self._by_id[style_id]
            result.append(style)
            based = style.find(w("basedOn"))
            style_id = based.get(w("val")) if based is not None else None
        return result

    def paragraph_style(self, style_id: str | None) -> tuple[ParaProps, TextProps]:
        """Effective formatting of a paragraph style (the default one if None)."""
        para, text = ParaProps(), TextProps()
        for style in self.chain(style_id or self.default_paragraph_style):
            para = para.over(para_props_of(style.find(w("pPr"))))
            text = text.over(text_props_of(style.find(w("rPr")), self.theme))
        return para.over(self._default_para), text.over(self._default_text)

    def character_style(self, style_id: str | None) -> TextProps:
        text = TextProps()
        for style in self.chain(style_id):
            text = text.over(text_props_of(style.find(w("rPr")), self.theme))
        return text

    def numbering_of_style(self, style_id: str | None) -> tuple[str | None, str | None]:
        """(numId, ilvl) a paragraph style attaches, following basedOn."""
        for style in self.chain(style_id):
            num_pr = style.find(f"{w('pPr')}/{w('numPr')}")
            if num_pr is not None:
                num_id = num_pr.find(w("numId"))
                ilvl = num_pr.find(w("ilvl"))
                return (
                    num_id.get(w("val")) if num_id is not None else None,
                    ilvl.get(w("val")) if ilvl is not None else None,
                )
        return None, None

    def outline_level(self, style_id: str | None) -> int | None:
        for style in self.chain(style_id):
            level = style.find(f"{w('pPr')}/{w('outlineLvl')}")
            if level is not None:
                try:
                    return int(level.get(w("val")))
                except (TypeError, ValueError):
                    return None
        return None

    def page_break_before(self, style_id: str | None) -> bool:
        for style in self.chain(style_id):
            value = on_off(style.find(f"{w('pPr')}/{w('pageBreakBefore')}"))
            if value is not None:
                return value
        return False


def on_off_attr(value: str | None) -> bool:
    return value is not None and value.lower() not in ("0", "false", "off")


@dataclass(frozen=True)
class LevelDef:
    """A w:lvl (DOCX-016): how the level counts and its label, where it starts, its
    indent and hanging (twips), legal numbering, when it restarts (lvlRestart), what
    follows the label, and the label's font (for bullets drawn from symbol fonts)."""

    fmt: str = "decimal"
    text: str = ""
    start: int = 1
    indent: int | None = None
    hanging: int | None = None
    legal: bool = False
    restart: int | None = None
    suffix: str = "tab"
    font: str | None = None


class Numbering:
    """numbering.xml: each list instance's levels (its abstractNum's, with the
    instance's own overrides), and the counters Word would show for numbered headings."""

    def __init__(self, docx_document) -> None:
        self._abstract_of: dict[str, str] = {}
        self._levels: dict[str, dict[int, LevelDef]] = {}  # absId -> ilvl -> level
        # A list instance's own changes to a level: a whole new level, or just where it starts.
        self._level_overrides: dict[tuple[str, int], LevelDef] = {}
        self._start_overrides: dict[tuple[str, int], int] = {}
        self._counters: dict[str, Counters] = {}
        try:
            root = docx_document.part.numbering_part.element
        except (KeyError, NotImplementedError, ValueError):
            return
        defined_by: dict[str, str] = {}  # a numbering style -> the abstractNum that defines its levels
        linked: dict[str, str] = {}  # an abstractNum -> the numbering style whose levels it takes
        for abstract in root.findall(w("abstractNum")):
            abstract_id = abstract.get(w("abstractNumId"))
            levels: dict[int, LevelDef] = {}
            for lvl in abstract.findall(w("lvl")):
                parsed = _numbering_level(lvl)
                if parsed is not None:
                    levels[parsed[0]] = parsed[1]
            self._levels[abstract_id] = levels
            style_link, num_style_link = abstract.find(w("styleLink")), abstract.find(w("numStyleLink"))
            if style_link is not None and style_link.get(w("val")):
                defined_by[style_link.get(w("val"))] = abstract_id
            if num_style_link is not None and num_style_link.get(w("val")):
                linked[abstract_id] = num_style_link.get(w("val"))
        for abstract_id, style in linked.items():  # a list that uses a numbering style's levels
            if not self._levels.get(abstract_id) and style in defined_by:
                self._levels[abstract_id] = self._levels.get(defined_by[style], {})
        for num in root.findall(w("num")):
            num_id = num.get(w("numId"))
            abstract = num.find(w("abstractNumId"))
            if abstract is not None:
                self._abstract_of[num_id] = abstract.get(w("val"))
            for override in num.findall(w("lvlOverride")):
                ilvl = _int(override.get(w("ilvl")))
                if ilvl is None:
                    continue
                start = override.find(w("startOverride"))
                if start is not None and _int(start.get(w("val"))) is not None:
                    self._start_overrides[(num_id, ilvl)] = _int(start.get(w("val")))
                lvl = override.find(w("lvl"))
                parsed = _numbering_level(lvl) if lvl is not None else None
                if parsed is not None:
                    self._level_overrides[(num_id, ilvl)] = parsed[1]

    def counted_with(self, num_id: str) -> str:
        """What a list instance numbers on with: its definition -- every instance of one
        numbers on together in Word -- or, with no definition, itself."""
        return f"abstract:{self._abstract_of[num_id]}" if num_id in self._abstract_of else f"num:{num_id}"

    def restarts(self, num_id: str, ilvl: int) -> bool:
        """Whether this instance starts its level again (a startOverride), as Word's
        "Restart numbering" makes one."""
        return (num_id, ilvl) in self._start_overrides

    def level(self, num_id: str, ilvl: int) -> LevelDef | None:
        override = self._level_overrides.get((num_id, ilvl))
        return override or self._levels.get(self._abstract_of.get(num_id, ""), {}).get(ilvl)

    def start(self, num_id: str, ilvl: int) -> int:
        """The number a list instance's level starts at: its own override, else the level's start."""
        if (num_id, ilvl) in self._start_overrides:
            return self._start_overrides[(num_id, ilvl)]
        level = self.level(num_id, ilvl)
        return level.start if level else 1

    def is_bullet(self, num_id: str, ilvl: int) -> bool | None:
        level = self.level(num_id, ilvl)
        return None if level is None else level.fmt in ("bullet", "none")

    def next_label(self, num_id: str, ilvl: int) -> str | None:
        """Advances this list's counter at `ilvl` and returns the label Word would
        show ("1.2."), or None for bullets and unknown lists."""
        level = self.level(num_id, ilvl)
        if level is None or level.fmt in ("bullet", "none"):
            return None
        key = self._abstract_of.get(num_id, num_id)
        levels = [self.level(num_id, index) for index in range(_LIST_LEVELS)]
        counters = self._counters.get(key)
        if counters is None:
            starts = [self.start(num_id, index) for index in range(_LIST_LEVELS)]
            counters = self._counters[key] = Counters(starts, [each.restart if each else None for each in levels])
        values = counters.advance(ilvl)
        formats = [each.fmt if each else "decimal" for each in levels[: ilvl + 1]]
        return level_label(level.text, values, formats, legal=level.legal).strip() or None


_LIST_LEVELS = 9  # Word's


def _int(value: str | None) -> int | None:
    return int(value) if value is not None and value.lstrip("-").isdigit() else None


def _numbering_level(lvl: etree._Element) -> tuple[int, LevelDef] | None:
    """A w:lvl as (ilvl, its definition)."""
    ilvl = _int(lvl.get(w("ilvl"), "0"))
    if ilvl is None or not 0 <= ilvl < _LIST_LEVELS:
        return None

    def value(tag: str, default: str | None = None) -> str | None:
        element = lvl.find(w(tag))
        return element.get(w("val"), default) if element is not None else default

    start = _int(value("start"))
    restart = _int(value("lvlRestart"))
    indent = hanging = None
    ind = lvl.find(f"{w('pPr')}/{w('ind')}")
    if ind is not None:
        indent = _int(ind.get(w("left"))) if ind.get(w("left")) is not None else _int(ind.get(w("start")))
        hanging = _int(ind.get(w("hanging")))
        if hanging is None and _int(ind.get(w("firstLine"))) is not None:
            hanging = -_int(ind.get(w("firstLine")))
    fonts = lvl.find(f"{w('rPr')}/{w('rFonts')}")
    return ilvl, LevelDef(
        fmt=value("numFmt", "decimal") or "decimal",
        text=value("lvlText", "") or "",
        start=start if start is not None and start >= 0 else 1,
        indent=indent,
        hanging=hanging,
        legal=bool(on_off(lvl.find(w("isLgl")))),
        restart=restart if restart is not None and 0 <= restart <= _LIST_LEVELS else None,
        suffix=value("suff", "tab") if value("suff", "tab") in ("tab", "space", "nothing") else "tab",
        font=(fonts.get(w("ascii")) or fonts.get(w("hAnsi"))) if fonts is not None else None,
    )


@dataclass(frozen=True)
class PageSetup:
    size: str | None
    orientation: str
    margins_cm: tuple[float, float, float, float] | None  # top, right, bottom, left
    content_width_twips: int | None
    columns: int
    notes: tuple[str, ...]


def page_setup(sect_pr: etree._Element | None) -> PageSetup:
    if sect_pr is None:
        return PageSetup(None, "portrait", None, None, 1, ())
    notes: list[str] = []
    size = None
    orientation = "portrait"
    width = height = None
    pg_sz = sect_pr.find(w("pgSz"))
    if pg_sz is not None:
        try:
            width, height = int(pg_sz.get(w("w"))), int(pg_sz.get(w("h")))
        except (TypeError, ValueError):
            width = height = None
        if width and height:
            orientation = "landscape" if (pg_sz.get(w("orient")) == "landscape" or width > height) else "portrait"
            short, long_ = sorted((width, height))
            for name, (page_w, page_h) in _PAGE_SIZES_TWIPS.items():
                if abs(short - page_w) <= _PAGE_SIZE_TOLERANCE_TWIPS and abs(long_ - page_h) <= _PAGE_SIZE_TOLERANCE_TWIPS:
                    size = name
            if size is None:
                notes.append(
                    f"The page size ({round(short / 56.7)} x {round(long_ / 56.7)} mm) isn't one the app supports; A4 is used."
                )
    margins = None
    content_width = None
    pg_mar = sect_pr.find(w("pgMar"))
    if pg_mar is not None:
        values = [twips_to_cm(pg_mar.get(w(side))) for side in ("top", "right", "bottom", "left")]
        if all(value is not None for value in values):
            margins = tuple(abs(value) for value in values)  # negative top/bottom = "don't move text"
            if width:
                try:
                    content_width = width - int(pg_mar.get(w("left"))) - int(pg_mar.get(w("right")))
                except (TypeError, ValueError):
                    content_width = None
    columns = 1
    cols = sect_pr.find(w("cols"))
    if cols is not None:
        try:
            columns = int(cols.get(w("num"), "1"))
        except ValueError:
            columns = 1
    return PageSetup(size, orientation, margins, content_width, columns, tuple(notes))


_SECTION_STARTS = ("nextPage", "continuous", "evenPage", "oddPage")
_PAGE_NUMBER_FORMATS = ("decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman")


_HEADER_KEYS = {
    ("header", "default"): "header",
    ("footer", "default"): "footer",
    ("header", "first"): "firstHeader",
    ("footer", "first"): "firstFooter",
    ("header", "even"): "evenHeader",
    ("footer", "even"): "evenFooter",
}


def section_texts(docx_document, sect_pr: etree._Element, notes: list[str] | None = None) -> dict[str, Any]:
    """A section's own headers and footers (DOCX-015): each kind it has a reference
    for, as its text (fields as {PAGE}/{NUMPAGES}); one it has none for is linked
    to the previous section's, and left out. And whether its first page has its own."""
    values: dict[str, Any] = {}
    part = docx_document.part
    for kind in ("header", "footer"):
        for reference in sect_pr.findall(w(f"{kind}Reference")):
            key = _HEADER_KEYS.get((kind, reference.get(w("type"), "default")))
            try:
                related = part.related_parts[reference.get(qn("r:id"))]
            except KeyError:
                continue
            if key is None:
                continue
            root = parse_xml_part(related.blob) if not hasattr(related, "element") else related.element
            values[key] = field_aware_text(part_paragraphs(root))[:500]
            if notes is not None:
                xml = etree.tostring(root, encoding="unicode")
                if "textpath" in xml or "PowerPlusWaterMarkObject" in xml:
                    notes.append("The watermark isn't supported and was left out.")
                elif "<w:drawing" in xml or "<w:pict" in xml:
                    notes.append(f"Pictures in the {kind} aren't supported and were left out.")
    if on_off(sect_pr.find(w("titlePg"))):
        values["differentFirstPage"] = True
    return values


def section_break_of(sect_pr: etree._Element, start: str, docx_document=None, notes: list[str] | None = None) -> dict[str, Any]:
    """A section's own settings, from the sectPr that ends it, as Element.sectionBreak
    has them (DOCX-015); `start` is how the section after it starts. With the Word
    document, its headers and footers too."""
    values: dict[str, Any] = {"start": start if start in _SECTION_STARTS else "nextPage"}
    if docx_document is not None:
        values.update(section_texts(docx_document, sect_pr, notes))

    def twips(element: etree._Element | None, name: str, per_unit: float) -> float | None:
        try:
            return round(abs(int(element.get(w(name)))) / per_unit, 2) if element is not None and element.get(w(name)) else None
        except ValueError:
            return None

    pg_sz = sect_pr.find(w("pgSz"))
    width, height = twips(pg_sz, "w", 56.6929), twips(pg_sz, "h", 56.6929)
    if width and height and 50 <= width <= 1600 and 50 <= height <= 1600:
        values.update(pageWidthMm=width, pageHeightMm=height)
        values["orientation"] = "landscape" if (pg_sz.get(w("orient")) == "landscape" or width > height) else "portrait"
    pg_mar = sect_pr.find(w("pgMar"))
    for key, name in (
        ("marginTopCm", "top"),
        ("marginBottomCm", "bottom"),
        ("marginLeftCm", "left"),
        ("marginRightCm", "right"),
        ("headerDistanceCm", "header"),
        ("footerDistanceCm", "footer"),
    ):
        value = twips(pg_mar, name, 566.929)
        if value is not None and value <= 20:
            values[key] = value
    cols = sect_pr.find(w("cols"))
    if cols is not None:
        try:
            count = int(cols.get(w("num"), "1"))
        except ValueError:
            count = 1
        if 1 < count <= 10:
            values["columns"] = count
            spacing = twips(cols, "space", 566.929)
            if spacing is not None and spacing <= 20:
                values["columnSpacingCm"] = spacing
    numbering = sect_pr.find(w("pgNumType"))
    if numbering is not None:
        try:
            start_at = int(numbering.get(w("start"))) if numbering.get(w("start")) else None
        except ValueError:
            start_at = None
        if start_at is not None and 0 <= start_at <= 99_999:
            values["pageNumberStart"] = start_at
        if numbering.get(w("fmt")) in _PAGE_NUMBER_FORMATS:
            values["pageNumberFormat"] = numbering.get(w("fmt"))
    return values


_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def part_paragraphs(root: etree._Element) -> list[etree._Element]:
    """A header's or footer's paragraphs, in order, each once: those in its tables and
    text boxes too, but not the copy of a text box Word keeps for older programs."""
    return [paragraph for paragraph in root.iter(w("p")) if not any(ancestor.tag == _FALLBACK for ancestor in paragraph.iterancestors())]


def field_aware_text(paragraphs: list[etree._Element]) -> str:
    """Header/footer text with PAGE/NUMPAGES fields as tokens the app fills in;
    other fields keep the text Word last showed. Paragraphs are joined by a space."""
    lines: list[str] = []
    for paragraph in paragraphs:
        pieces: list[str] = []
        _collect_field_text(paragraph, pieces, [])
        line = re.sub(r"\s+", " ", "".join(pieces)).strip()
        if line:
            lines.append(line)
    return " ".join(lines)


def _collect_field_text(node: etree._Element, pieces: list[str], fields_open: list[dict[str, Any]]) -> None:
    for child in node:
        tag = child.tag
        if tag == w("fldSimple"):
            token = _FIELD_TOKENS.get(_field_name(child.get(w("instr"), "")))
            if token:
                pieces.append(token)
            else:
                _collect_field_text(child, pieces, fields_open)
        elif tag == w("fldChar"):
            kind = child.get(w("fldCharType"))
            if kind == "begin":
                fields_open.append({"instr": "", "result": False, "token": None})
            elif kind == "separate" and fields_open:
                entry = fields_open[-1]
                entry["result"] = True
                entry["token"] = _FIELD_TOKENS.get(_field_name(entry["instr"]))
                if entry["token"]:
                    pieces.append(entry["token"])
            elif kind == "end" and fields_open:
                entry = fields_open.pop()
                if not entry["result"]:
                    token = _FIELD_TOKENS.get(_field_name(entry["instr"]))
                    if token:
                        pieces.append(token)  # a field with no shown result yet
        elif tag == w("instrText"):
            if fields_open:
                fields_open[-1]["instr"] += child.text or ""
        elif tag == w("t"):
            if not fields_open or (fields_open[-1]["result"] and not fields_open[-1]["token"]):
                pieces.append(child.text or "")
        elif tag in (w("tab"), w("ptab"), w("br")):
            pieces.append(" ")
        elif tag in (w("del"), w("moveFrom"), w("txbxContent"), _FALLBACK):
            continue  # a text box's paragraphs are read on their own (part_paragraphs)
        else:
            _collect_field_text(child, pieces, fields_open)


def _field_name(instr: str) -> str:
    stripped = instr.strip()
    return stripped.split()[0].upper() if stripped else ""


def header_footer(docx_document, sect_pr: etree._Element | None) -> tuple[str | None, str | None, list[str]]:
    """The section's main (default) header and footer text, plus notes on what
    of them couldn't be kept (other variants, watermarks, pictures)."""
    notes: list[str] = []
    if sect_pr is None:
        return None, None, notes
    part = docx_document.part
    found: dict[str, str | None] = {"header": None, "footer": None}
    for kind in ("header", "footer"):
        for reference in sect_pr.findall(w(f"{kind}Reference")):
            ref_type = reference.get(w("type"), "default")
            try:
                related = part.related_parts[reference.get(qn("r:id"))]
            except KeyError:
                continue
            root = parse_xml_part(related.blob) if not hasattr(related, "element") else related.element
            if ref_type != "default":
                continue  # first-page and even-page ones are kept with the section (section_texts, DOCX-015)
            xml = etree.tostring(root, encoding="unicode")
            if "textpath" in xml or "PowerPlusWaterMarkObject" in xml:
                notes.append("The watermark isn't supported and was left out.")
            elif "<w:drawing" in xml or "<w:pict" in xml:
                notes.append(f"Pictures in the {kind} aren't supported and were left out.")
            found[kind] = field_aware_text(part_paragraphs(root)) or None
    return found["header"], found["footer"], notes


def _style_values(para: ParaProps, text: TextProps, *, with_indent: bool = True) -> dict[str, Any]:
    values: dict[str, Any] = {
        "fontFamily": text.font,
        "fontSizePt": text.size_pt,
        "bold": text.bold,
        "italic": text.italic,
        "underline": text.underline,
        "color": text.color,
        "alignment": para.alignment,
        "spaceBeforePt": para.space_before_pt,
        "spaceAfterPt": para.space_after_pt,
    }
    if para.line_spacing is not None and para.line_spacing[1] is None:
        values["lineSpacing"] = para.line_spacing[0]  # exact heights have no StyleSystem field
    if with_indent:
        values["indentLeftCm"] = para.indent_left_cm
        values["firstLineIndentCm"] = para.first_line_cm
        values["indentRightCm"] = para.indent_right_cm
    values.update(
        shading=para.shading,
        keepWithNext=para.keep_next,
        keepLinesTogether=para.keep_lines,
        widowControl=para.widow_control,
        contextualSpacing=para.contextual_spacing,
        direction=None if para.bidi is None else ("rtl" if para.bidi else "ltr"),
        borderTop=para.border_top,
        borderBottom=para.border_bottom,
        borderLeft=para.border_left,
        borderRight=para.border_right,
        tabStops=para.tab_stops,
    )
    return {key: value for key, value in values.items() if value is not None}


def valid_text_style(values: dict[str, Any], where: str, notes: list[str]) -> dict[str, Any]:
    """Keeps each value the StyleSystem accepts; says which ones it didn't."""
    kept: dict[str, Any] = {}
    for key, value in values.items():
        try:
            TextStyle.model_validate({key: value})
        except ValidationError:
            notes.append(f"{where}: {key} {value!r} isn't supported and was left out.")
            continue
        kept[key] = value
    return kept


@dataclass
class ExtractedStyles:
    style_system: StyleSystem
    notes: list[str]
    # Per engine target, the (paragraph, text) formatting the StyleSystem was
    # built from: what single paragraphs are compared with.
    base: dict[str, tuple[ParaProps, TextProps]]
    page: PageSetup


def extract_style_system(
    docx_document, resolver: StyleResolver, *, quote_style: str | None, list_style: str | None
) -> ExtractedStyles:
    notes: list[str] = []
    data: dict[str, Any] = {"headings": {}}
    base: dict[str, tuple[ParaProps, TextProps]] = {}

    def take(target: str, style_id: str | None, section: str, *, with_indent: bool = True, level: str | None = None) -> None:
        para, text = as_word_draws(*resolver.paragraph_style(style_id))
        if not with_indent:
            para = replace(para, indent_left_cm=None, first_line_cm=None)
        values = valid_text_style(_style_values(para, text, with_indent=with_indent), f"Style {resolver.name_of(style_id) or 'Normal'}", notes)
        if level:
            data["headings"][level] = values
        else:
            data[section] = values
        base[target] = (para, text)

    normal = resolver.default_paragraph_style
    take("Paragraph", normal, "paragraph")
    for level in range(1, 7):
        style_id = resolver.id_for_name(f"heading {level}")
        if style_id:
            take(f"Heading {level}", style_id, "headings", level=f"h{level}")
    take("Quote", quote_style or resolver.id_for_name("quote") or normal, "quotes")
    take("Caption", resolver.id_for_name("caption") or normal, "captions")
    # List indentation comes from the numbering definition, which the editor draws itself.
    take("List", list_style or resolver.id_for_name("list paragraph") or normal, "lists", with_indent=False)
    take("Footnote", resolver.id_for_name("footnote text") or normal, "footnotes", with_indent=False)
    # Word tables use the Normal style's text (spacing comes from the table style), and
    # leave no gap after them: the next paragraph's own spacing does.
    normal_para, normal_text = as_word_draws(*resolver.paragraph_style(normal))
    table_values = {key: value for key, value in _style_values(normal_para, normal_text).items() if key in ("fontFamily", "fontSizePt", "color")}
    table_values["spaceAfterPt"] = 0.0
    data["tables"] = valid_text_style(table_values, "Tables", notes)
    base["Table"] = (ParaProps(), TextProps(font=normal_text.font, size_pt=normal_text.size_pt, color=normal_text.color))
    base["CodeBlock"] = (ParaProps(), TextProps())
    base["Image"] = (ParaProps(), TextProps())

    body = docx_document.element.body
    sect_pr = body.find(w("sectPr"))
    page = page_setup(sect_pr)
    notes.extend(page.notes)
    page_values: dict[str, Any] = {"orientation": page.orientation}
    if page.size:
        page_values["size"] = page.size
    if page.margins_cm:
        top, right, bottom, left = page.margins_cm
        page_values.update(marginTopCm=top, marginRightCm=right, marginBottomCm=bottom, marginLeftCm=left)
    try:
        data["page"] = PageStyle.model_validate(page_values).model_dump(exclude_none=True)
    except ValidationError:
        notes.append("The page margins are outside what the app supports; default margins are used.")
        data["page"] = {key: value for key, value in page_values.items() if key in ("size", "orientation")}
    if page.columns > 1:
        notes.append(f"The document is laid out in {page.columns} columns: a Word export and a PDF keep them; the pages here show one.")

    header, footer, header_notes = header_footer(docx_document, sect_pr)
    notes.extend(header_notes)
    if header:
        data["header"] = HeaderStyle.model_validate({"text": header[:500]}).model_dump(exclude_none=True)
    if footer:
        data["footer"] = FooterStyle.model_validate({"text": footer[:500]}).model_dump(exclude_none=True)

    return ExtractedStyles(style_system=StyleSystem.model_validate(data), notes=notes, base=base, page=page)


def safe_font(value: str | None) -> str | None:
    return value.strip() if value and is_safe_font_name(value) else None


def safe_color(value: str | None) -> str | None:
    return value if value and is_renderable_color(value) else None
