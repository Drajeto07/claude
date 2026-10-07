"""Word tables' geometry and look (tracker DOCX-017): grid column widths, the table's
width, alignment and indent, row heights, borders and cell margins -- a table style's
own, resolved through basedOn, under the table's direct ones -- vertical alignment,
header rows (Word's tblHeader, or a style's first row the table shows), and the style's
name and look. What a table style colours, bolds or italicises by position -- banded rows
and columns, the first and last row and column, the corner cells -- is resolved into each
cell's look as Word draws it (DOCX-017A, position_look); borders by position aren't, and
the importer says so."""

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
# A style's conditional formatting by position, in the order Word applies it (a later one wins).
_PRECEDENCE = ("wholeTable", "band1Vert", "band2Vert", "band1Horz", "band2Horz", "firstCol", "lastCol", "firstRow", "lastRow", "neCell", "nwCell", "seCell", "swCell")
# What of a conditional format is resolved into the cells (the rest -- borders, say -- is reported).
_RESOLVED_CELL = {"shd"}
_RESOLVED_RUN = {"b", "bCs", "i", "iCs", "color"}


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
class PositionLook:
    """What one of a table style's conditional formats gives a cell (None: nothing)."""

    fill: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    color: str | None = None

    def over(self, under: "PositionLook") -> "PositionLook":
        return PositionLook(*(mine if mine is not None else theirs for mine, theirs in zip(
            (self.fill, self.bold, self.italic, self.color), (under.fill, under.bold, under.italic, under.color), strict=True)))


@dataclass
class StyleLook:
    """What a table style gives a table: borders, cell margins, alignment, indent, whether it
    has a first row of its own (a header), and its conditional formats by position with the
    number of rows and columns in a band."""

    borders: dict[str, str] = field(default_factory=dict)
    margins: dict[str, float] = field(default_factory=dict)
    align: str | None = None
    indent_cm: float | None = None
    first_row: bool = False
    conditionals: dict[str, PositionLook] = field(default_factory=dict)
    row_band: int = 1
    column_band: int = 1
    # Conditional formatting by position this doesn't resolve (borders, say): reported.
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
                for name, attribute in (("tblStyleRowBandSize", "row_band"), ("tblStyleColBandSize", "column_band")):
                    band = tbl_pr.find(w(name))
                    if band is not None and (band.get(w("val")) or "").isdigit() and 1 <= int(band.get(w("val"))) <= 50:
                        setattr(look, attribute, int(band.get(w("val"))))
            for conditional in style.findall(w("tblStylePr")):
                kind = conditional.get(w("type"))
                if kind not in _PRECEDENCE:
                    continue
                if kind == "firstRow" and len(conditional):
                    look.first_row = True
                found = _position_look(conditional)
                look.conditionals[kind] = found.over(look.conditionals.get(kind, PositionLook()))  # the nearer style wins
                cell = conditional.find(w("tcPr"))
                run = conditional.find(w("rPr"))
                unresolved = [child for child in (cell if cell is not None else []) if etree.QName(child).localname not in _RESOLVED_CELL]
                unresolved += [child for child in (run if run is not None else []) if etree.QName(child).localname not in _RESOLVED_RUN]
                if unresolved and kind not in ("firstRow", "wholeTable"):
                    look.by_position = True
        return look


def _position_look(conditional: etree._Element) -> PositionLook:
    fill = conditional.find(f"{w('tcPr')}/{w('shd')}")
    bold = conditional.find(f"{w('rPr')}/{w('b')}")
    italic = conditional.find(f"{w('rPr')}/{w('i')}")
    color = conditional.find(f"{w('rPr')}/{w('color')}")
    return PositionLook(
        fill=hex_color(fill.get(w("fill"))) if fill is not None else None,
        bold=bool(on_off(bold)) if bold is not None else None,
        italic=bool(on_off(italic)) if italic is not None else None,
        color=hex_color(color.get(w("val"))) if color is not None else None,
    )


def position_look(look: StyleLook, shows: dict[str, bool], row: int, rows: int, column: int, span: int, columns: int) -> PositionLook:
    """What the table style gives the cell at (row, column) -- spanning `span` grid columns, in a
    table of `rows` rows and `columns` grid columns -- from the parts the table shows (tblLook):
    its conditional formats in Word's order, a later one over an earlier (DOCX-017A). Banded rows
    leave out a first and last row the table shows, banded columns a first and last column."""
    if not look.conditionals:
        return PositionLook()
    first_row, last_row = shows.get("firstRow", True) and row == 0, shows.get("lastRow", False) and row == rows - 1
    first_col, last_col = shows.get("firstColumn", True) and column == 0, shows.get("lastColumn", False) and column + span >= columns
    applies = {"wholeTable"}
    if shows.get("bandedRows", True) and not first_row and not last_row:
        banded_row = row - (1 if shows.get("firstRow", True) else 0)
        applies.add("band1Horz" if (banded_row // look.row_band) % 2 == 0 else "band2Horz")
    if shows.get("bandedColumns", False) and not first_col and not last_col:
        banded_column = column - (1 if shows.get("firstColumn", True) else 0)
        applies.add("band1Vert" if (banded_column // look.column_band) % 2 == 0 else "band2Vert")
    for kind, on in (("firstRow", first_row), ("lastRow", last_row), ("firstCol", first_col), ("lastCol", last_col)):
        if on:
            applies.add(kind)
    for kind, on in (("nwCell", first_row and first_col), ("neCell", first_row and last_col), ("swCell", last_row and first_col), ("seCell", last_row and last_col)):
        if on:
            applies.add(kind)
    result = PositionLook()
    for kind in _PRECEDENCE:
        if kind in applies and kind in look.conditionals:
            result = look.conditionals[kind].over(result)
    return result


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
    if (floating := table_float(tbl_pr.find(w("tblpPr")) if tbl_pr is not None else None)) is not None:
        values["floating"] = floating
    return values


_ANCHORS = ("text", "margin", "page")
_X_ALIGN = ("left", "center", "right", "inside", "outside")
_Y_ALIGN = ("inline", "top", "center", "bottom", "inside", "outside")


def table_float(element: etree._Element | None) -> dict[str, Any] | None:
    """Where a floating table sits (w:tblpPr), as TableFloat has it."""
    if element is None:
        return None

    def cm(name: str, low: float, high: float) -> float | None:
        value = twips_to_cm(element.get(w(name)))
        return value if value is not None and low <= value <= high else None

    values: dict[str, Any] = {
        "horizontalAnchor": element.get(w("horzAnchor")) if element.get(w("horzAnchor")) in _ANCHORS else "text",
        "verticalAnchor": element.get(w("vertAnchor")) if element.get(w("vertAnchor")) in _ANCHORS else "text",
        "xCm": cm("tblpX", -100, 100),
        "yCm": cm("tblpY", -100, 100),
        "xAlign": element.get(w("tblpXSpec")) if element.get(w("tblpXSpec")) in _X_ALIGN else None,
        "yAlign": element.get(w("tblpYSpec")) if element.get(w("tblpYSpec")) in _Y_ALIGN else None,
    }
    for side in ("left", "right", "top", "bottom"):
        values[f"{side}FromTextCm"] = cm(f"{side}FromText", 0, 50)
    return values


# A table this share of the text column wide or wider leaves no room for text beside it.
_FLOAT_MAX_SHARE = 0.85


def table_side(floating: dict[str, Any], width_cm: float | None, text_left_cm: float, text_width_cm: float) -> str | None:
    """The side a floating table floats to here and in a PDF (DOCX-017B), as a floating picture's
    (docx_pictures.float_side): its alignment's (left or inside, right or outside; centred floats to
    neither), else the half of the text column its middle is in. One too wide for text beside it
    -- or whose width isn't known -- is drawn in line."""
    if not width_cm or width_cm >= _FLOAT_MAX_SHARE * text_width_cm:
        return None
    align = floating.get("xAlign")
    if align in ("right", "outside"):
        return "right"
    if align in ("left", "inside"):
        return "left"
    if align == "center":
        return None
    offset = floating.get("xCm")
    if offset is None:
        return "left"
    in_column = offset - text_left_cm if floating.get("horizontalAnchor") == "page" else offset
    return "right" if in_column + width_cm / 2 > text_width_cm / 2 else "left"


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
    if on_off(tr_pr.find(w("cantSplit"))):
        values["cantSplit"] = True
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
