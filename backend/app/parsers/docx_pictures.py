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


def picture_properties(drawing: etree._Element) -> dict[str, Any]:
    """ImageContent's fields a drawing gives: name, alt and title, size, crop, rotation,
    flips, placement."""
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
        values["placement"] = _placement(anchor)
    return {key: value for key, value in values.items() if value is not None}


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
