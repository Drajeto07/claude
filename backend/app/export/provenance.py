"""Which blocks of a document are still as they came from their Word file
(tracker DOCX-028): the importer records the body children each top-level
element came from (Element.sourceBlocks), and when the file is kept for exports
the element's fingerprint as imported (Element.sourceHash). An element whose
fingerprint is still the same is unchanged -- a Word export written into the
original file can then copy those children as they are, fields, content
controls and formatting the model doesn't hold included.

The fingerprint covers what the element holds and how it looks: its resolved
style, its kind's and the body's (a template or an instruction that restyles
paragraphs restyles this one), and those of the blocks nested in it. Not how
the app or the editor spells it: ids, order, the style's key, empty values and
values a field has by default are left out, and adjacent runs with the same
marks count as one. A field the model gains later so leaves a stored
element's fingerprint as it was; one stamped before defaults were left out
(DOCX-018) is checked as the model stood when it was stamped (_STAMPED_BEFORE).

Provenance is the server's: what a client sends back for it is ignored
(keep_provenance) -- a block can't claim another's original XML."""

import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from app.models.document import Document, Element, ElementType, target_for_element, walk_elements

_NOT_CONTENT = frozenset({"id", "order", "parentId", "styleRef", "confidence", "sourceBlocks", "sourceHash"})
_BODY = "Paragraph"

# Fingerprints stamped before DOCX-018 counted every field, those at their defaults
# too: the fields with a default that isn't empty, as the model had them -- the
# first when fingerprints began (DOCX-028), then with what DOCX-017 added to tables
# that were there already. (Fields of classes added meanwhile count throughout: a
# block stored before they were added has none of them.)
_COUNTED_FROM_THE_START = frozenset({
    "Element.ordered", "ListItem.level", "ListNumbering.start", "ListNumbering.format", "TableCell.header",
    "TableCell.colspan", "TableCell.rowspan", "TableContent.hasHeaderRow",
    "SectionSettings.start", "ListLevel.format", "ListLevel.start", "ListLevel.legal", "ListLevel.suffix",
    "TableLook.firstRow", "TableLook.lastRow", "TableLook.firstColumn", "TableLook.lastColumn",
    "TableLook.bandedRows", "TableLook.bandedColumns", "TableFloat.horizontalAnchor", "TableFloat.verticalAnchor",
})
_COUNTED_FROM_DOCX_017 = _COUNTED_FROM_THE_START | {"TableContent.headerBold", "TableRow.heightRule", "TableRow.repeatHeader"}
_STAMPED_BEFORE = (_COUNTED_FROM_THE_START, _COUNTED_FROM_DOCX_017, _COUNTED_FROM_DOCX_017 | {"TableRow.cantSplit"})


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        kept = {key: _canonical(item) for key, item in value.items() if key not in _NOT_CONTENT}
        if isinstance(kept.get("inline"), list):
            kept["inline"] = _merged_runs(kept["inline"])
        return {key: item for key, item in kept.items() if item not in (None, [], {}, "")}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _merged_runs(runs: list) -> list:
    merged: list = []
    for run in runs:
        if merged and isinstance(run, dict) and isinstance(merged[-1], dict) and run.get("marks") == merged[-1].get("marks"):
            merged[-1] = {**merged[-1], "text": (merged[-1].get("text") or "") + (run.get("text") or "")}
        else:
            merged.append(run)
    return [run for run in merged if not isinstance(run, dict) or run.get("text")]


def _without_defaults(value: Any, data: Any, counted: frozenset[str]) -> Any:
    """`data`, the JSON dump of `value`, without the fields at their defaults -- but
    those `counted` names ("Class.field")."""
    if isinstance(value, BaseModel) and isinstance(data, dict):
        fields = type(value).model_fields
        kept = {}
        for name, item in data.items():
            field, own = fields.get(name), getattr(value, name, None)
            at_default = field is not None and field.default_factory is None and own == field.default
            if at_default and f"{type(value).__name__}.{name}" not in counted:
                continue
            kept[name] = _without_defaults(own, item, counted)
        return kept
    if isinstance(value, (list, tuple)) and isinstance(data, list):
        return [_without_defaults(own, item, counted) for own, item in zip(value, data)]
    if isinstance(value, dict) and isinstance(data, dict):
        return {key: _without_defaults(value.get(key), item, counted) for key, item in data.items()}
    return data


def _nested(element: Element) -> Iterator[Element]:
    blocks = list(element.children or [])
    for item in element.listItems or []:
        blocks.extend(item.blocks or [])
    for row in element.table.rows if element.table else []:
        for cell in row.cells:
            blocks.extend(cell.blocks or [])
    for block in blocks:
        yield block
        yield from _nested(block)


def look(document: Document, element: Element) -> dict[str, Any]:
    """What decides how the element looks in an export. A page or section break has
    no look: restyling the document leaves it -- and a section ending with it -- as it was."""
    if element.type in (ElementType.PAGE_BREAK, ElementType.SECTION_BREAK):
        return {}
    styles = document.resolvedStyles
    kinds = sorted({_BODY, target_for_element(element), *(target_for_element(block) for block in _nested(element))})
    return {
        "own": styles.get(element.styleRef or target_for_element(element), {}),
        "kinds": {kind: styles.get(kind, {}) for kind in kinds},
        "nested": [styles.get(block.styleRef, {}) for block in _nested(element) if block.styleRef and block.styleRef not in kinds],
    }


def fingerprint(element: Element, appearance: dict[str, Any] | None = None, *, counted: frozenset[str] = frozenset()) -> str:
    held = _without_defaults(element, element.model_dump(mode="json"), counted)
    data = {"element": _canonical(held), "look": _canonical(appearance or {})}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def block_use(elements: list[Element]) -> list[int] | None:
    """How many of the elements each body child was read into, child by child; None
    when none came from a file."""
    counts = Counter(child for element in elements for child in set(element.sourceBlocks or []) if child >= 0)
    return [counts[child] for child in range(max(counts) + 1)] if counts else None


def stamp(document: Document) -> None:
    """Each element that knows where it came from gets its fingerprint as it is now,
    and the document how many of them each body child was read into (DOCX-028B)."""
    for element in document.elements:
        element.sourceHash = fingerprint(element, look(document, element)) if element.sourceBlocks else None
    document.sourceBlockUse = block_use(document.elements)


def unchanged(document: Document, element: Element) -> bool:
    if not element.sourceBlocks or element.sourceHash is None:
        return False
    appearance = look(document, element)
    stamped = (fingerprint(element, appearance, counted=counted) for counted in (frozenset(), *_STAMPED_BEFORE))
    return element.sourceHash in stamped


def keep_provenance(stored: list[Element], incoming: list[Element]) -> None:
    """Elements saved from the editor keep the provenance the server has for their
    ids -- the Word blocks they came from, or where they were on a PDF's page --
    whatever was sent; a new element, or a second one with the same id, has none."""
    known = {element.id: (element.sourceBlocks, element.sourceHash, element.layout) for element in stored}
    seen: set[str] = set()
    for element in incoming:
        blocks, digest, layout = known.get(element.id, (None, None, None)) if element.id not in seen else (None, None, None)
        seen.add(element.id)
        if element.sourceBlocks != blocks or element.sourceHash != digest:  # a model's setattr isn't free
            element.sourceBlocks, element.sourceHash = blocks, digest
        if element.layout != layout:  # and where a PDF's block was on its page (P2E-001)
            element.layout = layout


def keep_preserved(stored: list[Element], incoming: list[Element]) -> None:
    """What the import kept of each block's source (preservedAttributes: fields, bookmarks,
    comments, content controls, notes) is the server's too: saved from the editor, a block
    at any depth keeps the stored one for its id, whatever was sent, and a new one -- or a
    second with the same id -- has none. So no client can put a DDE field, or any other
    fragment, into the next Word export (SEC-015)."""
    known = {holder.id: holder.preservedAttributes for holder in _holders(stored)}
    seen: set[str] = set()
    for holder in _holders(incoming):
        holder.preservedAttributes = known.get(holder.id) if holder.id not in seen else None
        seen.add(holder.id)


def _holders(elements: list[Element]) -> Iterator[Any]:
    """Everything that holds what the import kept, at any depth: blocks, and the list items,
    table rows and cells inside them (DOCX-023A)."""
    for element in walk_elements(elements):
        yield element
        yield from element.listItems or []
        for row in element.table.rows if element.table else []:
            yield row
            yield from row.cells
