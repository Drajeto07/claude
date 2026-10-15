"""Repairs made in the Word file itself (Doctor v0): for defects the editor's model never holds, because the
importer keeps them for export only -- above all empty paragraphs used as spacing.

A repair here is a minimal edit of the file's body: the empty paragraphs removed and about the same space given
to the neighbouring paragraph as spacing (Word's own "space after/before"). Nothing else in the file is
rewritten; safe_edit.verify then checks that every other block is byte for byte the same.

Never removed: an empty paragraph that carries anything (a bookmark, a field, a section break, a page break,
"page break before", a frame, a picture...), one next to a table (Word keeps adjacent tables apart, and a table
needs a paragraph after it), and the body's last paragraph.
"""

import difflib
import io
import zipfile
from dataclasses import dataclass

from lxml import etree

from app.doctor.safe_edit import PRESERVED

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_TWIPS_PER_POINT = 20
_DEFAULT_SIZE_PT = 11.0


def _w(name: str) -> str:
    return f"{{{_W}}}{name}"


@dataclass(frozen=True)
class BlockRepair:
    id: str
    kind: str  # "empty_paragraphs", "wide_picture", "wide_table"
    blocks: tuple[int, ...]  # the blocks removed (empty paragraphs) or resized (indexes in the original body)
    neighbour: int | None  # the paragraph given the space (index), or None
    side: str  # "after" (the paragraph before gets space after) or "before"
    points: float
    where: str  # where it is, as words a person recognises (the neighbouring text, shortened)
    target: int = 0  # wide_picture: the width to fit (EMU); wide_table: (twips)


def _body(data: bytes) -> tuple[etree._Element, etree._Element]:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    return root, root.find(_w("body"))


def _text(block: etree._Element) -> str:
    return "".join(block.itertext()).strip()


def _is_empty_paragraph(block: etree._Element) -> bool:
    if block.tag != _w("p") or _text(block):
        return False
    for tag in [*PRESERVED.values(), _w("br"), _w("cr"), _w("tab"), _w("pageBreakBefore"), _w("framePr"), _w("sym"), _w("ptab")]:
        if block.find(f".//{tag}") is not None:
            return False
    return True


def _size_pt(block: etree._Element) -> float:
    size = block.find(f"{_w('pPr')}/{_w('rPr')}/{_w('sz')}")
    try:
        return int(size.get(_w("val"))) / 2 if size is not None else _DEFAULT_SIZE_PT
    except (TypeError, ValueError):
        return _DEFAULT_SIZE_PT


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def find_empty_spacing(data: bytes) -> list[BlockRepair]:
    """Each run of empty paragraphs between content, as one repair."""
    _, body = _body(data)
    children = list(body)
    last_paragraph = max((index for index, child in enumerate(children) if child.tag == _w("p")), default=-1)
    repairs: list[BlockRepair] = []
    index = 0
    while index < len(children):
        if not _is_empty_paragraph(children[index]) or index == last_paragraph:
            index += 1
            continue
        start = index
        while index < len(children) and _is_empty_paragraph(children[index]) and index != last_paragraph:
            index += 1
        run = list(range(start, index))
        before = children[start - 1] if start > 0 else None
        after = children[index] if index < len(children) else None
        if (before is not None and before.tag == _w("tbl")) or (after is not None and after.tag == _w("tbl")):
            continue  # next to a table: Word needs it
        points = sum(_size_pt(children[position]) * 1.15 for position in run)
        if before is not None and before.tag == _w("p"):
            neighbour, side, where = start - 1, "after", f"after “{_short(_text(before))}”"
        elif after is not None and after.tag == _w("p"):
            neighbour, side, where = index, "before", f"before “{_short(_text(after))}”"
        else:
            continue
        repairs.append(BlockRepair(f"empty:{start}", "empty_paragraphs", tuple(run), neighbour, side, round(points, 1), where))
    return repairs


# w:pPr's children in the order the schema requires (CT_PPr): Word may call a file damaged otherwise.
_AFTER_SPACING = (
    "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment",
    "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange",
)


def _add_spacing(paragraph: etree._Element, side: str, points: float) -> None:
    properties = paragraph.find(_w("pPr"))
    if properties is None:
        properties = etree.Element(_w("pPr"))
        paragraph.insert(0, properties)
    spacing = properties.find(_w("spacing"))
    if spacing is None:
        spacing = etree.Element(_w("spacing"))
        later = next((child for child in properties if etree.QName(child).localname in _AFTER_SPACING), None)
        if later is None:
            properties.append(spacing)
        else:
            later.addprevious(spacing)
    current = int(spacing.get(_w(side), "0") or 0)
    spacing.set(_w(side), str(current + round(points * _TWIPS_PER_POINT)))


def _canonical(element: etree._Element) -> bytes:
    return etree.tostring(element, method="c14n")


def apply(original: bytes, result: bytes, repairs: list[BlockRepair]) -> tuple[bytes, set[int], list[str]]:
    """The repairs made in `result` (the file the export wrote, which carries the original's untouched blocks
    as they were). Each repair's blocks are found in the result by lining the two bodies up; a repair whose blocks
    or neighbour don't line up exactly (something around them changed) is skipped, never guessed.
    Returns the new file, the original's block indexes that were touched, and the ids skipped."""
    _, original_body = _body(original)
    root, body = _body(result)
    original_children, result_children = list(original_body), list(body)
    matcher = difflib.SequenceMatcher(a=[_canonical(child) for child in original_children], b=[_canonical(child) for child in result_children], autojunk=False)
    position: dict[int, int] = {}
    for tag, a0, a1, b0, _ in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(a1 - a0):
                position[a0 + offset] = b0 + offset
    touched: set[int] = set()
    skipped: list[str] = []
    removals: list[etree._Element] = []
    for repair in repairs:
        needed = [*repair.blocks, *([repair.neighbour] if repair.neighbour is not None else [])]
        if any(index not in position for index in needed):
            skipped.append(repair.id)
            continue
        if repair.kind == "wide_picture":
            _scale_picture(result_children[position[repair.blocks[0]]], repair.target)
        elif repair.kind == "wide_table":
            _scale_table(result_children[position[repair.blocks[0]]], repair.target)
        else:
            if repair.neighbour is not None:
                _add_spacing(result_children[position[repair.neighbour]], repair.side, repair.points)
                touched.add(repair.neighbour)
            removals.extend(result_children[position[index]] for index in repair.blocks)
        touched.update(repair.blocks)
    for element in removals:
        body.remove(element)
    with zipfile.ZipFile(io.BytesIO(result)) as source:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                content = source.read(item.filename)
                if item.filename == "word/document.xml":
                    content = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                target.writestr(item, content)
    return buffer.getvalue(), touched, skipped


# -- Pictures and tables wider than the page's text ---------------------------------------------------------------

_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_EMU_PER_TWIP = 635
_TOLERANCE_TWIPS = 28  # about 0.05 cm, as the editor's own check allows


def _section_widths(children: list[etree._Element], body_section: etree._Element | None) -> list[int | None]:
    """The text width (twips) of the section each top-level block is in: a paragraph carrying w:sectPr ends its
    section (it is in it); the body's own w:sectPr is the last section's."""

    def width(section: etree._Element | None) -> int | None:
        if section is None:
            return None
        size, margins = section.find(_w("pgSz")), section.find(_w("pgMar"))
        try:
            page = int(size.get(_w("w")))
            left, right = int(margins.get(_w("left"), 0)), int(margins.get(_w("right"), 0))
            gutter = int(margins.get(_w("gutter"), 0) or 0)
        except (AttributeError, TypeError, ValueError):
            return None
        return page - left - right - gutter

    widths: list[int | None] = [None] * len(children)
    pending: list[int] = []
    for index, child in enumerate(children):
        pending.append(index)
        carried = child.find(f"{_w('pPr')}/{_w('sectPr')}") if child.tag == _w("p") else None
        if carried is not None:
            for position in pending:
                widths[position] = width(carried)
            pending = []
    for position in pending:
        widths[position] = width(body_section)
    return widths


def _neighbour_text(children: list[etree._Element], index: int) -> str:
    for position in (*range(index - 1, -1, -1), *range(index + 1, len(children))):
        text = _text(children[position])
        if text:
            return ("after" if position < index else "before") + f" “{_short(text)}”"
    return "in the document"


def _inline_picture_width(block: etree._Element) -> int | None:
    """The width (EMU) of the block's one inline picture -- a paragraph holding exactly one, and no floating one."""
    if block.tag != _w("p") or block.find(f".//{{{_WP}}}anchor") is not None:
        return None
    inlines = block.findall(f".//{{{_WP}}}inline")
    if len(inlines) != 1:
        return None
    extent = inlines[0].find(f"{{{_WP}}}extent")
    try:
        return int(extent.get("cx"))
    except (AttributeError, TypeError, ValueError):
        return None


def _table_width(block: etree._Element) -> int | None:
    width = block.find(f"{_w('tblPr')}/{_w('tblW')}") if block.tag == _w("tbl") else None
    if width is None or width.get(_w("type")) != "dxa":
        return None
    try:
        return int(width.get(_w("w")))
    except (TypeError, ValueError):
        return None


def find_too_wide(data: bytes) -> list[BlockRepair]:
    """Inline pictures and tables (top level) set wider than their section's text: each scaled to fit."""
    _, body = _body(data)
    children = list(body)
    widths = _section_widths(children, body.find(_w("sectPr")))
    repairs: list[BlockRepair] = []
    for index, child in enumerate(children):
        text_width = widths[index]
        if not text_width or text_width <= 0:
            continue
        picture = _inline_picture_width(child)
        if picture is not None and picture > (text_width + _TOLERANCE_TWIPS) * _EMU_PER_TWIP:
            repairs.append(BlockRepair(f"picture:{index}", "wide_picture", (index,), None, "", 0.0, _neighbour_text(children, index), target=text_width * _EMU_PER_TWIP))
            continue
        table = _table_width(child)
        if table is not None and table > text_width + _TOLERANCE_TWIPS:
            repairs.append(BlockRepair(f"table:{index}", "wide_table", (index,), None, "", 0.0, _neighbour_text(children, index), target=text_width))
    return repairs


def _scale_picture(block: etree._Element, target_emu: int) -> None:
    inline = block.find(f".//{{{_WP}}}inline")
    extent = inline.find(f"{{{_WP}}}extent")
    scale = target_emu / int(extent.get("cx"))
    for element in (extent, *inline.iterfind(f".//{{{_A}}}xfrm/{{{_A}}}ext")):
        element.set("cx", str(round(int(element.get("cx")) * scale)))
        element.set("cy", str(round(int(element.get("cy")) * scale)))


def _scale_table(block: etree._Element, target_twips: int) -> None:
    width = block.find(f"{_w('tblPr')}/{_w('tblW')}")
    scale = target_twips / int(width.get(_w("w")))
    width.set(_w("w"), str(target_twips))
    for column in block.iter(_w("gridCol")):
        if column.get(_w("w")):
            column.set(_w("w"), str(round(int(column.get(_w("w"))) * scale)))
    for cell in block.iter(_w("tcW")):
        if cell.get(_w("type"), "dxa") == "dxa" and cell.get(_w("w")):
            cell.set(_w("w"), str(round(int(cell.get(_w("w"))) * scale)))


def find_all(data: bytes) -> list[BlockRepair]:
    """Every Word-level repair Doctor v0 can propose for this file."""
    return [*find_empty_spacing(data), *find_too_wide(data)]
