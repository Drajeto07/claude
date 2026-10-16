"""Tracked changes resolved the way Word resolves them (tracker DOCX-022A), as measured in Word:

- Accepting: a paragraph whose mark was deleted while tracking runs into the next paragraph,
  which keeps its own properties (style, alignment...); one whose text was all deleted too is
  gone. The importer reads every other change as accepted on its own (insertions read,
  deletions skipped, the new formatting); `join_deleted_marks` does the joining, in the tree
  it reads.
- Rejecting (`reject_all`, the person's choice): insertions and moves to are taken out,
  deletions and moves from are text again, every formatting change goes back to what it was,
  an inserted row or cell is taken out and a deleted one kept, and a paragraph whose mark was
  inserted runs into the next one. What is left has no tracked changes at all.
"""

import io
import zipfile

from lxml import etree

from app.security.fields import STORIES
from app.security.files import parse_xml_part

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def w(name: str) -> str:
    return f"{_W}{name}"


# A change of properties: its element holds the properties as they were before it.
_PROPERTY_CHANGES = ("rPrChange", "pPrChange", "sectPrChange", "tblPrChange", "trPrChange", "tcPrChange", "tblGridChange", "tblPrExChange")
# What a paragraph's properties keep when their change is rejected: the old pPr holds neither.
_KEPT_IN_PPR = (w("rPr"), w("sectPr"))
# ...and a section's: its headers and footers aren't part of its change.
_KEPT_IN_SECTPR = (w("headerReference"), w("footerReference"))
_MOVE_RANGES = ("moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd")


def _mark(paragraph: etree._Element, *names: str) -> etree._Element | None:
    """The revision on a paragraph's mark (pPr/rPr/ins, del, moveFrom, moveTo), if one of `names`."""
    return next((found for name in names if (found := paragraph.find(f"{w('pPr')}/{w('rPr')}/{w(name)}")) is not None), None)


def _run_into_next(paragraph: etree._Element) -> bool:
    """The paragraph's content moved to the start of the next one, as Word does when its mark
    goes; False (nothing moved) when no paragraph follows it in the same place, or it ends a
    section -- then its mark stays."""
    following = paragraph.getnext()
    ppr = paragraph.find(w("pPr"))
    if following is None or following.tag != w("p") or (ppr is not None and ppr.find(w("sectPr")) is not None):
        return False
    content = [child for child in paragraph if child.tag != w("pPr")]
    at = 1 if (len(following) and following[0].tag == w("pPr")) else 0
    for offset, child in enumerate(content):
        following.insert(at + offset, child)
    return True


def join_deleted_marks(root: etree._Element) -> set[etree._Element]:
    """Accepted: each paragraph whose mark was deleted runs into the next one. Returns the
    paragraphs left empty by it, still in the tree (the importer skips them, and counts a
    top-level one as part of the paragraph it ran into)."""
    joined: set[etree._Element] = set()
    for paragraph in list(root.iter(w("p"))):
        if _mark(paragraph, "del", "moveFrom") is not None and _run_into_next(paragraph):
            for properties in paragraph.findall(w("pPr")):
                paragraph.remove(properties)  # nothing of it left to read: its style is the next one's now
            joined.add(paragraph)
    return joined


def _unwrap(element: etree._Element) -> None:
    """The element replaced by its children, where it was."""
    parent = element.getparent()
    at = parent.index(element)
    for offset, child in enumerate(list(element)):
        parent.insert(at + offset, child)
    _drop(element)


def _drop(element: etree._Element) -> None:
    """The element taken out of its parent."""
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _restore_properties(change: etree._Element) -> None:
    """A property change rejected: its parent's properties are the old ones it holds again."""
    owner = change.getparent()
    old = next(iter(change), None)
    kept = _KEPT_IN_PPR if owner.tag == w("pPr") else _KEPT_IN_SECTPR if owner.tag == w("sectPr") else ()
    for child in list(owner):
        if child is not change and child.tag not in kept:
            owner.remove(child)
    _drop(change)
    if old is None:
        return
    # The old ones in their place: before what is kept (rPr and sectPr come last in a pPr; a
    # section's header and footer references first in a sectPr).
    position = len([child for child in owner if child.tag in _KEPT_IN_SECTPR]) if owner.tag == w("sectPr") else 0
    for offset, child in enumerate(list(old)):
        owner.insert(position + offset, child)
    for attribute, value in old.attrib.items():
        owner.set(attribute, value)


def reject_story(root: etree._Element) -> bool:
    """Every tracked change in one story (a body, a header, notes...) rejected, in place.
    Whether there was any."""
    changed = False
    for name in ("ins", "moveTo"):
        for element in list(root.iter(w(name))):
            if element.getparent() is not None and element.getparent().tag not in (w("rPr"), w("trPr"), w("tcPr")):
                _drop(element)  # inserted text, a moved text's new place
                changed = True
    for name in ("del", "moveFrom"):
        for element in list(root.iter(w(name))):
            if element.getparent() is not None and element.getparent().tag not in (w("rPr"), w("trPr"), w("tcPr")):
                _unwrap(element)  # deleted text back
                changed = True
    for name, plain in (("delText", "t"), ("delInstrText", "instrText")):
        for element in root.iter(w(name)):
            element.tag = w(plain)
    for name in _MOVE_RANGES:
        for element in list(root.iter(w(name))):
            _drop(element)
            changed = True
    # Rows, cells and paragraph marks before the property changes: restoring a row's, a cell's
    # or a mark's old properties would take their insertion and deletion markers with them.
    changed |= _reject_rows_and_cells(root)
    for paragraph in list(root.iter(w("p"))):
        inserted = _mark(paragraph, "ins", "moveTo")
        deleted = _mark(paragraph, "del", "moveFrom")
        if deleted is not None:
            _drop(deleted)  # its mark back
            changed = True
        if inserted is not None:
            _drop(inserted)
            changed = True
            if _run_into_next(paragraph):
                _drop(paragraph)
    for name in _PROPERTY_CHANGES:
        for element in list(root.iter(w(name))):
            _restore_properties(element)
            changed = True
    for element in list(root.iter(w("numberingChange"))):
        _drop(element)
        changed = True
    return changed


def _reject_rows_and_cells(root: etree._Element) -> bool:
    changed = False
    for row in list(root.iter(w("tr"))):
        properties = row.find(w("trPr"))
        if properties is None:
            continue
        if properties.find(w("ins")) is not None:
            _drop(row)  # an inserted row out
            changed = True
            continue
        for marker in properties.findall(w("del")):
            properties.remove(marker)  # a deleted one kept
            changed = True
    for cell in list(root.iter(w("tc"))):
        properties = cell.find(w("tcPr"))
        if properties is None:
            continue
        if properties.find(w("cellIns")) is not None and len(cell.getparent().findall(w("tc"))) > 1:
            _drop(cell)
            changed = True
            continue
        for name in ("cellIns", "cellDel", "cellMerge"):
            for marker in properties.findall(w(name)):
                properties.remove(marker)
                changed = True
    for table in list(root.iter(w("tbl"))):
        if table.find(w("tr")) is None:  # every row of it was inserted
            parent = table.getparent()
            _drop(table)
            if parent is not None and parent.tag == w("tc") and parent.find(w("p")) is None:
                etree.SubElement(parent, w("p"))  # a cell holds a paragraph at least
            changed = True
    return changed


def reject_all(data: bytes) -> bytes:
    """The Word file with every tracked change rejected, in each story it has; the same bytes
    when there were none. Its other parts as they were."""
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        entries = package.infolist()
        parts = {entry.filename: package.read(entry) for entry in entries}
    rewritten: dict[str, bytes] = {}
    for name, content in parts.items():
        if not name.endswith(".xml"):
            continue
        root = parse_xml_part(content)
        if root.tag in STORIES and reject_story(root):
            rewritten[name] = etree.tostring(root.getroottree(), xml_declaration=True, encoding="UTF-8", standalone=True)
    if not rewritten:
        return data
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for entry in entries:
            package.writestr(entry, rewritten.get(entry.filename, parts[entry.filename]))
    return buffer.getvalue()
