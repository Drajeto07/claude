"""A Word picture's geometry and placement (tracker DOCX-018): the size it's drawn at
(wp:extent), what of it is cropped away (a:srcRect), how it's turned and flipped
(a:xfrm), and, for a floating picture (wp:anchor), how text wraps around it and where
it sits. Its name, alt text and title come from wp:docPr."""

from __future__ import annotations

from typing import Any

from docx.oxml.ns import qn
from lxml import etree

_EMU_PER_CM = 360_000
_WRAPS = {"wrapSquare": "square", "wrapTight": "tight", "wrapThrough": "through", "wrapTopAndBottom": "topAndBottom"}
_H_FROM = {"character", "column", "margin", "page", "leftMargin", "rightMargin", "insideMargin", "outsideMargin"}
_V_FROM = {"line", "paragraph", "margin", "page", "topMargin", "bottomMargin", "insideMargin", "outsideMargin"}
_H_ALIGN = {"left", "center", "right", "inside", "outside"}
_V_ALIGN = {"top", "center", "bottom", "inside", "outside"}


def _emu_cm(value: str | None, low: float, high: float) -> float | None:
    try:
        cm = round(int(value) / _EMU_PER_CM, 2)
    except (TypeError, ValueError):
        return None
    return cm if low <= cm <= high else None


def _share(value: str | None) -> float:
    """A crop side (a:srcRect, in thousandths of a percent) as a share, 0 for none or a stretch outwards."""
    try:
        return min(max(int(value) / 100_000, 0), 0.99)
    except (TypeError, ValueError):
        return 0


def picture_properties(drawing: etree._Element, *, text_left_cm: float = 2.0, text_width_cm: float = 17.0) -> dict[str, Any]:
    """ImageContent's fields a drawing gives: name, alt and title, size, crop, rotation,
    flips, placement -- with the side a floating one floats to, by the text column it is in
    (where it starts from the page's left edge, and its width)."""
    values: dict[str, Any] = {}
    doc_pr = next(drawing.iter(qn("wp:docPr")), None)
    if doc_pr is not None:
        values["name"] = (doc_pr.get("name") or "")[:255] or None
        values["alt"] = doc_pr.get("descr") or None
        values["title"] = doc_pr.get("title") or None
    extent = next(drawing.iter(qn("wp:extent")), None)
    if extent is not None:
        values["widthCm"] = _emu_cm(extent.get("cx"), 0.01, 200)
        values["heightCm"] = _emu_cm(extent.get("cy"), 0.01, 200)
    source = next(drawing.iter(qn("a:srcRect")), None)
    if source is not None:
        crop = {side: _share(source.get(key)) for side, key in (("left", "l"), ("top", "t"), ("right", "r"), ("bottom", "b"))}
        if any(crop.values()) and crop["left"] + crop["right"] < 1 and crop["top"] + crop["bottom"] < 1:
            values["crop"] = crop
    transform = next(drawing.iter(qn("a:xfrm")), None)
    if transform is not None:
        try:
            degrees = round((int(transform.get("rot", "0")) / 60_000) % 360, 2)
        except ValueError:
            degrees = 0
        if degrees:
            values["rotation"] = degrees
        values["flipHorizontal"] = transform.get("flipH") in ("1", "true")
        values["flipVertical"] = transform.get("flipV") in ("1", "true")
    anchor = drawing.find(qn("wp:anchor"))
    if anchor is not None:
        placement = _placement(anchor)
        placement["side"] = float_side(placement, values.get("widthCm"), text_left_cm, text_width_cm)
        values["placement"] = {key: value for key, value in placement.items() if value is not None}
    return {key: value for key, value in values.items() if value is not None}


_WPS = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}"
_EMU_PER_PT = 12_700


def _color_of(fill: etree._Element | None) -> str | None:
    """A solid fill's colour as #rrggbb (srgbClr, or the preset black/white Word uses)."""
    if fill is None:
        return None
    srgb = fill.find(qn("a:srgbClr"))
    if srgb is not None and len(srgb.get("val", "")) == 6:
        return f"#{srgb.get('val').upper()}"
    preset = fill.find(qn("a:prstClr"))
    return {"black": "#000000", "white": "#FFFFFF"}.get(preset.get("val", "")) if preset is not None else None


def text_box_properties(drawing: etree._Element | None, *, text_left_cm: float = 2.0, text_width_cm: float = 17.0) -> dict[str, Any]:
    """TextBoxContent's fields a text box's drawing gives (DOCX-019A): its size, border, fill,
    insets, name and, floating, where it floats -- with its side, as a picture's."""
    if drawing is None:
        return {}
    values: dict[str, Any] = {}
    doc_pr = next(drawing.iter(qn("wp:docPr")), None)
    if doc_pr is not None:
        values["name"] = (doc_pr.get("name") or "")[:255] or None
    extent = next(drawing.iter(qn("wp:extent")), None)
    if extent is not None:
        values["widthCm"] = _emu_cm(extent.get("cx"), 0.01, 200)
        values["heightCm"] = _emu_cm(extent.get("cy"), 0.01, 200)
    shape = next(drawing.iter(f"{_WPS}spPr"), None)
    if shape is not None:
        if shape.find(qn("a:noFill")) is None:
            values["fill"] = _color_of(shape.find(qn("a:solidFill")))
        line = shape.find(qn("a:ln"))
        if line is not None:
            if line.find(qn("a:noFill")) is not None:
                values["border"] = "none"
            else:
                try:
                    width = min(max(int(line.get("w", "9525")) / _EMU_PER_PT, 0.25), 12)
                except ValueError:
                    width = 0.75
                values["border"] = f"solid {width:g}pt {_color_of(line.find(qn('a:solidFill'))) or '#000000'}"
    body = next(drawing.iter(f"{_WPS}bodyPr"), None)
    if body is not None:
        insets = {side: _emu_cm(body.get(key), 0, 10) for side, key in (("leftCm", "lIns"), ("topCm", "tIns"), ("rightCm", "rIns"), ("bottomCm", "bIns"))}
        if any(value is not None for value in insets.values()):
            values["insets"] = {key: value for key, value in insets.items() if value is not None}
    anchor = drawing.find(qn("wp:anchor"))
    if anchor is not None:
        placement = _placement(anchor)
        placement["side"] = float_side(placement, values.get("widthCm"), text_left_cm, text_width_cm)
        values["placement"] = {key: value for key, value in placement.items() if value is not None}
    return {key: value for key, value in values.items() if value is not None}


# Word's SVG picture, kept beside the PNG copy the model holds (DOCX-018C).
SVG_BLIP = "{http://schemas.microsoft.com/office/drawing/2016/SVG/main}svgBlip"

# Positions measured from the page's left edge, or from the left margin's (the text column's left is
# the margin's width in); the rest from the text column or the character.
_FROM_PAGE = {"page", "leftMargin", "outsideMargin"}
_WRAPPED = {"square", "tight", "through"}


def float_side(placement: dict[str, Any], width_cm: float | None, text_left_cm: float, text_width_cm: float) -> str | None:
    """The side a picture text wraps around floats to here and in a PDF (DOCX-018A): its
    alignment's (left or inside, right or outside; centred floats to neither), else the half of
    the text column its middle is in. Only square, tight and through wrapping floats it: behind or
    in front of the text, or with text above and below only, it is drawn in line."""
    if placement.get("wrap") not in _WRAPPED:
        return None
    align = placement.get("horizontalAlign")
    if align in ("right", "outside") or placement.get("horizontalFrom") == "rightMargin":
        return "right"
    if align in ("left", "inside"):
        return "left"
    if align == "center":
        return None
    offset = placement.get("horizontalCm")
    if offset is None:
        return "left"
    in_column = offset - text_left_cm if placement.get("horizontalFrom") in _FROM_PAGE else offset
    middle = in_column + (width_cm or 0) / 2
    return "right" if middle > text_width_cm / 2 else "left"


def _placement(anchor: etree._Element) -> dict[str, Any]:
    placement: dict[str, Any] = {}
    wrap = next((_WRAPS[etree.QName(child).localname] for child in anchor if etree.QName(child).localname in _WRAPS), None)
    if wrap is None:  # wrapNone: in front of the text, or behind it
        wrap = "behind" if anchor.get("behindDoc") in ("1", "true") else "inFront"
    placement["wrap"] = wrap
    for axis, tag, froms, aligns in (("horizontal", "wp:positionH", _H_FROM, _H_ALIGN), ("vertical", "wp:positionV", _V_FROM, _V_ALIGN)):
        position = anchor.find(qn(tag))
        if position is None:
            continue
        if position.get("relativeFrom") in froms:
            placement[f"{axis}From"] = position.get("relativeFrom")
        align = position.find(qn("wp:align"))
        offset = position.find(qn("wp:posOffset"))
        if align is not None and (align.text or "").strip() in aligns:
            placement[f"{axis}Align"] = align.text.strip()
        elif offset is not None:
            placement[f"{axis}Cm"] = _emu_cm((offset.text or "").strip(), -100, 100)
    for side, key in (("Top", "distT"), ("Bottom", "distB"), ("Left", "distL"), ("Right", "distR")):
        placement[f"distance{side}Cm"] = _emu_cm(anchor.get(key), 0, 50)
    placement["allowOverlap"] = anchor.get("allowOverlap", "1") in ("1", "true")
    placement["layoutInCell"] = anchor.get("layoutInCell", "1") in ("1", "true")
    return {key: value for key, value in placement.items() if value is not None}
