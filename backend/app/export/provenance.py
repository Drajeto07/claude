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
the app or the editor spells it: ids, order, the style's key, and empty values
are left out, and adjacent runs with the same marks count as one.

Provenance is the server's: what a client sends back for it is ignored
(keep_provenance) -- a block can't claim another's original XML."""

import hashlib
import json
from collections.abc import Iterator
from typing import Any

from app.models.document import Document, Element, ElementType, target_for_element

_NOT_CONTENT = frozenset({"id", "order", "parentId", "styleRef", "confidence", "sourceBlocks", "sourceHash"})
_BODY = "Paragraph"


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
    """What decides how the element looks in an export. A page break has no look:
    restyling the document leaves it -- and a section ending with it -- as it was."""
    if element.type == ElementType.PAGE_BREAK:
        return {}
    styles = document.resolvedStyles
    kinds = sorted({_BODY, target_for_element(element), *(target_for_element(block) for block in _nested(element))})
    return {
        "own": styles.get(element.styleRef or target_for_element(element), {}),
        "kinds": {kind: styles.get(kind, {}) for kind in kinds},
        "nested": [styles.get(block.styleRef, {}) for block in _nested(element) if block.styleRef and block.styleRef not in kinds],
    }


def fingerprint(element: Element, appearance: dict[str, Any] | None = None) -> str:
    data = {"element": _canonical(element.model_dump(mode="json")), "look": _canonical(appearance or {})}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def stamp(document: Document) -> None:
    """Each element that knows where it came from gets its fingerprint as it is now."""
    for element in document.elements:
        element.sourceHash = fingerprint(element, look(document, element)) if element.sourceBlocks else None


def unchanged(document: Document, element: Element) -> bool:
    return (
        bool(element.sourceBlocks)
        and element.sourceHash is not None
        and fingerprint(element, look(document, element)) == element.sourceHash
    )


def keep_provenance(stored: list[Element], incoming: list[Element]) -> None:
    """Elements saved from the editor keep the provenance the server has for their
    ids, whatever was sent; a new element, or a second one with the same id, has none."""
    known = {element.id: (element.sourceBlocks, element.sourceHash) for element in stored}
    seen: set[str] = set()
    for element in incoming:
        blocks, digest = known.get(element.id, (None, None)) if element.id not in seen else (None, None)
        seen.add(element.id)
        element.sourceBlocks, element.sourceHash = blocks, digest
