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

    def over(self, base: TextProps) -> TextProps:
        return TextProps(**{f.name: getattr(self, f.name) if getattr(self, f.name) is not None else getattr(base, f.name) for f in fields(self)})


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
    indent_left = first_line = None
    ind = ppr.find(w("ind"))
    if ind is not None:
        indent_left = twips_to_cm(ind.get(w("left")) or ind.get(w("start")))
        if ind.get(w("hanging")) is not None:
            hanging = twips_to_cm(ind.get(w("hanging")))
            first_line = -hanging if hanging is not None else None
        else:
            first_line = twips_to_cm(ind.get(w("firstLine")))
    return ParaProps(alignment, space_before, space_after, line_spacing, indent_left, first_line)


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
    underline = None
    u = rpr.find(w("u"))
    if u is not None:
        underline = u.get(w("val"), "single") != "none"
    return TextProps(
        font=font,
        size_pt=size,
        color=color,
        bold=on_off(rpr.find(w("b"))),
        italic=on_off(rpr.find(w("i"))),
        underline=underline,
    )


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


class Numbering:
    """numbering.xml: which list levels are bullets, and the counters Word
    would show for numbered headings."""

    def __init__(self, docx_document) -> None:
        self._abstract_of: dict[str, str] = {}
        self._levels: dict[str, dict[int, tuple[str, str, int]]] = {}  # absId -> ilvl -> (numFmt, lvlText, start)
        self._counters: dict[str, list[int]] = {}
        try:
            root = docx_document.part.numbering_part.element
        except (KeyError, NotImplementedError, ValueError):
            return
        for abstract in root.findall(w("abstractNum")):
            abstract_id = abstract.get(w("abstractNumId"))
            levels: dict[int, tuple[str, str, int]] = {}
            for lvl in abstract.findall(w("lvl")):
                try:
                    ilvl = int(lvl.get(w("ilvl"), "0"))
                except ValueError:
                    continue
                fmt_el, text_el, start_el = lvl.find(w("numFmt")), lvl.find(w("lvlText")), lvl.find(w("start"))
                start = int(start_el.get(w("val"), "1")) if start_el is not None and start_el.get(w("val"), "").isdigit() else 1
                levels[ilvl] = (
                    fmt_el.get(w("val"), "decimal") if fmt_el is not None else "decimal",
                    text_el.get(w("val"), "") if text_el is not None else "",
                    start,
                )
            self._levels[abstract_id] = levels
        for num in root.findall(w("num")):
            abstract = num.find(w("abstractNumId"))
            if abstract is not None:
                self._abstract_of[num.get(w("numId"))] = abstract.get(w("val"))

    def level(self, num_id: str, ilvl: int) -> tuple[str, str, int] | None:
        return self._levels.get(self._abstract_of.get(num_id, ""), {}).get(ilvl)

    def is_bullet(self, num_id: str, ilvl: int) -> bool | None:
        level = self.level(num_id, ilvl)
        return None if level is None else level[0] in ("bullet", "none")

    def next_label(self, num_id: str, ilvl: int) -> str | None:
        """Advances this list's counter at `ilvl` and returns the label Word would
        show ("1.2."), or None for bullets and unknown lists."""
        level = self.level(num_id, ilvl)
        if level is None or level[0] in ("bullet", "none"):
            return None
        key = self._abstract_of.get(num_id, num_id)
        counters = self._counters.setdefault(key, [])
        while len(counters) <= ilvl:
            counters.append(0)
        counters[ilvl] += 1
        del counters[ilvl + 1 :]
        label = level[1]
        for index, count in enumerate(counters):
            level_info = self.level(num_id, index)
            start = level_info[2] if level_info else 1
            label = label.replace(f"%{index + 1}", format_number(count + start - 1, level_info[0] if level_info else "decimal"))
        return re.sub(r"%\d", "", label).strip() or None


def format_number(value: int, fmt: str) -> str:
    if fmt in ("lowerLetter", "upperLetter"):
        letters = ""
        while value > 0:
            value, remainder = divmod(value - 1, 26)
            letters = chr(ord("a") + remainder) + letters
        return letters.upper() if fmt == "upperLetter" else letters
    if fmt in ("lowerRoman", "upperRoman"):
        numerals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
        result = ""
        for amount, numeral in numerals:
            while value >= amount:
                result += numeral
                value -= amount
        return result.upper() if fmt == "upperRoman" else result
    return str(value)


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
        elif tag in (w("del"), w("moveFrom")):
            continue
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
                if field_aware_text(root.findall(f".//{w('p')}")):
                    notes.append(f"Only the main {kind} is kept; the first-page/even-page {kind} was left out.")
                continue
            xml = etree.tostring(root, encoding="unicode")
            if "textpath" in xml or "PowerPlusWaterMarkObject" in xml:
                notes.append("The watermark isn't supported and was left out.")
            elif "<w:drawing" in xml or "<w:pict" in xml:
                notes.append(f"Pictures in the {kind} aren't supported and were left out.")
            found[kind] = field_aware_text(root.findall(f".//{w('p')}")) or None
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
        para, text = resolver.paragraph_style(style_id)
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
    # Word tables use the Normal style's text (spacing comes from the table style).
    normal_para, normal_text = resolver.paragraph_style(normal)
    table_values = {key: value for key, value in _style_values(normal_para, normal_text).items() if key in ("fontFamily", "fontSizePt", "color")}
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
        notes.append(f"The document is laid out in {page.columns} columns; the app shows it in one.")

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
