"""Word tables' geometry and look (tracker DOCX-017): grid column widths, the table's
width, alignment and indent, row heights, borders and cell margins -- a table style's
own, resolved through basedOn, under the table's direct ones -- vertical alignment,
header rows (Word's tblHeader, or a style's first row the table shows), and the style's
name and look. What a table style colours by position (banded rows, first or last
columns) isn't resolved; the importer says so."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from app.parsers.docx_styles import StyleResolver, hex_color, on_off, twips_to_cm, w

_BORDER_STYLES = {
    "single": "solid",
    "thick": "solid",
    "double": "double",
    "dotted": "dotted",
    "dashed": "dashed",
    "dashSmallGap": "dashed",
    "dotDash": "dashed",
    "dotDotDash": "dashed",
}
_SIDES = {"top": "top", "bottom": "bottom", "left": "left", "start": "left", "right": "right", "end": "right", "insideH": "insideH", "insideV": "insideV"}
_ALIGNMENTS = {"left": "left", "start": "left", "center": "center", "right": "right", "end": "right"}
_VERTICAL = {"top": "top", "center": "center", "bottom": "bottom", "both": "center"}
# tblLook's old bit field (w:val), for files without its attributes.
_LOOK_BITS = {"firstRow": 0x0020, "lastRow": 0x0040, "firstColumn": 0x0080, "lastColumn": 0x0100, "noHBand": 0x0200, "noVBand": 0x0400}
# A style's conditional formatting this doesn't resolve (a table showing them is reported).
_BY_POSITION = ("lastRow", "firstCol", "lastCol", "band1Vert", "band2Vert", "band1Horz", "band2Horz", "neCell", "nwCell", "seCell", "swCell")


def borders_of(element: etree._Element | None) -> dict[str, str]:
    """Border sides (tblBorders/tcBorders), as border values: "<style> <width>pt <colour>" or "none"."""
    found: dict[str, str] = {}
    for side in element if element is not None else []:
        name = _SIDES.get(etree.QName(side).localname)
        if name is None:
            continue  # diagonals aren't kept
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


def margins_of(element: etree._Element | None) -> dict[str, float]:
    """Cell margins (tblCellMar/tcMar), cm, by side."""
    found: dict[str, float] = {}
    for side in element if element is not None else []:
        name = _SIDES.get(etree.QName(side).localname)
        if name not in ("top", "bottom", "left", "right") or side.get(w("type"), "dxa") != "dxa":
            continue
        value = twips_to_cm(side.get(w("w")))
        if value is not None and 0 <= value <= 10:
            found[f"{name}Cm"] = value
    return found


@dataclass
class StyleLook:
    """What a table style gives a table: borders, cell margins, alignment, indent, and its
    first row's look -- whether it has one, its shading and whether its text is bold."""

    borders: dict[str, str] = field(default_factory=dict)
    margins: dict[str, float] = field(default_factory=dict)
    align: str | None = None
    indent_cm: float | None = None
    first_row: bool = False
    first_row_fill: str | None = None
    first_row_bold: bool | None = None
    by_position: bool = False


class TableStyles:
    """A document's table styles, each resolved through basedOn (nearest wins)."""

    def __init__(self, resolver: StyleResolver) -> None:
        self.resolver = resolver
        self._cache: dict[str, StyleLook] = {}

    def look(self, style_id: str | None) -> StyleLook:
        if not style_id:
            return StyleLook()
        if style_id not in self._cache:
            self._cache[style_id] = self._resolve(style_id)
        return self._cache[style_id]

    def _resolve(self, style_id: str) -> StyleLook:
        look = StyleLook()
        for style in reversed(self.resolver.chain(style_id)):  # the base first, so the nearest wins
            tbl_pr = style.find(w("tblPr"))
            if tbl_pr is not None:
                look.borders.update(borders_of(tbl_pr.find(w("tblBorders"))))
                look.margins.update(margins_of(tbl_pr.find(w("tblCellMar"))))
                jc = tbl_pr.find(w("jc"))
                if jc is not None and jc.get(w("val")) in _ALIGNMENTS:
                    look.align = _ALIGNMENTS[jc.get(w("val"))]
                indent = tbl_pr.find(w("tblInd"))
                if indent is not None and indent.get(w("type"), "dxa") == "dxa":
                    look.indent_cm = twips_to_cm(indent.get(w("w")))
            for conditional in style.findall(w("tblStylePr")):
                kind = conditional.get(w("type"))
                if kind == "firstRow" and len(conditional):
                    look.first_row = True
                    fill = conditional.find(f"{w('tcPr')}/{w('shd')}")
                    if fill is not None and hex_color(fill.get(w("fill"))):
                        look.first_row_fill = hex_color(fill.get(w("fill")))
                    bold = conditional.find(f"{w('rPr')}/{w('b')}")
                    if bold is not None:
                        look.first_row_bold = bool(on_off(bold))
                elif kind in _BY_POSITION and (conditional.find(f"{w('tcPr')}/{w('shd')}") is not None or conditional.find(w("rPr")) is not None):
                    look.by_position = True
        return look


def table_look(tbl_pr: etree._Element | None) -> dict[str, bool] | None:
    """Which parts of its style a table shows (w:tblLook), as TableLook has them."""
    element = tbl_pr.find(w("tblLook")) if tbl_pr is not None else None
    if element is None:
        return None
    try:
        bits = int(element.get(w("val"), "0"), 16)
    except ValueError:
        bits = 0

    def flag(name: str) -> bool:
        value = element.get(w(name))
        return value.lower() in ("1", "true", "on") if value is not None else bool(bits & _LOOK_BITS[name])

    return {
        "firstRow": flag("firstRow"),
        "lastRow": flag("lastRow"),
        "firstColumn": flag("firstColumn"),
        "lastColumn": flag("lastColumn"),
        "bandedRows": not flag("noHBand"),
        "bandedColumns": not flag("noVBand"),
    }


def table_properties(tbl: etree._Element, styles: TableStyles) -> dict[str, Any]:
    """A table's own geometry and look, its style's under its direct formatting:
    TableContent's fields, and "_style_look" -- the style's StyleLook."""
    tbl_pr = tbl.find(w("tblPr"))
    style_el = tbl_pr.find(w("tblStyle")) if tbl_pr is not None else None
    style_id = style_el.get(w("val")) if style_el is not None else None
    look = styles.look(style_id)
    values: dict[str, Any] = {"_style_look": look}
    if style_id:
        values["style"] = (styles.resolver.name_of(style_id) or style_id)[:100]
    widths = [twips_to_cm(col.get(w("w"))) for col in tbl.findall(f"{w('tblGrid')}/{w('gridCol')}")]
    if widths and all(width is not None and 0 <= width <= 200 for width in widths):
        values["columnWidthsCm"] = widths[:64]
    borders = {**look.borders, **borders_of(tbl_pr.find(w("tblBorders")) if tbl_pr is not None else None)}
    if borders:
        values["borders"] = borders
    margins = {**look.margins, **margins_of(tbl_pr.find(w("tblCellMar")) if tbl_pr is not None else None)}
    if margins:
        values["cellMargins"] = margins
    align, indent = look.align, look.indent_cm
    if tbl_pr is not None:
        width = tbl_pr.find(w("tblW"))
        if width is not None:
            kind, amount = width.get(w("type"), "auto"), width.get(w("w"), "0")
            if kind == "dxa" and (cm := twips_to_cm(amount)) and 0 < cm <= 200:
                values["widthCm"] = cm
            elif kind == "pct":
                try:
                    percent = float(amount[:-1]) if amount.endswith("%") else int(amount) / 50
                except ValueError:
                    percent = 0
                if 0 < percent <= 100:
                    values["widthPercent"] = round(percent, 2)
        jc = tbl_pr.find(w("jc"))
        if jc is not None and jc.get(w("val")) in _ALIGNMENTS:
            align = _ALIGNMENTS[jc.get(w("val"))]
        indent_el = tbl_pr.find(w("tblInd"))
        if indent_el is not None and indent_el.get(w("type"), "dxa") == "dxa":
            indent = twips_to_cm(indent_el.get(w("w")))
    if align:
        values["align"] = align
    if indent is not None and -50 <= indent <= 50 and indent != 0:
        values["indentCm"] = indent
    if (flags := table_look(tbl_pr)) is not None:
        values["look"] = flags
    return values


def row_properties(tr: etree._Element) -> dict[str, Any]:
    """A row's height and rule, and whether it repeats as a header (TableRow's fields)."""
    tr_pr = tr.find(w("trPr"))
    values: dict[str, Any] = {}
    if tr_pr is None:
        return values
    height = tr_pr.find(w("trHeight"))
    if height is not None and height.get(w("hRule"), "atLeast") != "auto":
        cm = twips_to_cm(height.get(w("val")))
        if cm and 0 < cm <= 100:
            values["heightCm"] = cm
            values["heightRule"] = "exact" if height.get(w("hRule")) == "exact" else "atLeast"
    if on_off(tr_pr.find(w("tblHeader"))):
        values["repeatHeader"] = True
    return values


def cell_properties(tc_pr: etree._Element | None) -> dict[str, Any]:
    """A cell's own vertical alignment, borders and margins (TableCell's fields)."""
    values: dict[str, Any] = {}
    if tc_pr is None:
        return values
    v_align = tc_pr.find(w("vAlign"))
    if v_align is not None and v_align.get(w("val")) in _VERTICAL:
        values["verticalAlign"] = _VERTICAL[v_align.get(w("val"))]
    if borders := borders_of(tc_pr.find(w("tcBorders"))):
        values["borders"] = {side: value for side, value in borders.items() if side in ("top", "bottom", "left", "right")} or None
    if margins := margins_of(tc_pr.find(w("tcMar"))):
        values["margins"] = margins
    return {key: value for key, value in values.items() if value is not None}
