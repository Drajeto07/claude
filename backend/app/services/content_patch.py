"""Saving what changed instead of the whole document (PERF-003).

A save used to send every top-level element and get the whole document back, so a
keystroke in a long document cost in step with its length both ways. The editor
now sends what changed since the revision it names -- elements changed (whole),
added (each after the element before it) and removed -- and gets back how the
stored document differs from that revision. The server builds the whole element
list from its own copy (`patched_elements`) and saves it exactly as a whole-list
save, through every check that has, so a patch can do nothing a whole save
can't. Anything it can't say -- an existing block moved, most of the document
changed -- the editor sends as the whole document, as before.
"""

from typing import Any

from app.models.document import Element


class PatchMismatchError(Exception):
    """The patch doesn't fit the stored document: an id it names isn't there (or
    already is), or a block it adds has no place. Nothing was written; the editor
    sends the whole document instead."""


def patched_elements(stored: list[Element], *, changed: list[Element], added: list[tuple[str | None, Element]], removed: list[str]) -> list[Element]:
    """The top-level elements after the patch: `stored` without `removed`, each of
    `changed` in place of the element with its id, and each of `added` right after
    the element it names (None: first). Each added element names the one just
    before it in the new list, so no two name the same one."""
    ids = {element.id for element in stored}
    gone = set(removed)
    if len(gone) != len(removed) or not gone <= ids:
        raise PatchMismatchError("The patch removes a block the document doesn't have.")
    replacing = {element.id: element for element in changed}
    if len(replacing) != len(changed) or not replacing.keys() <= ids - gone:
        raise PatchMismatchError("The patch changes a block the document doesn't have.")
    kept = [replacing.get(element.id, element) for element in stored if element.id not in gone]
    known = {element.id for element in kept}
    following: dict[str | None, Element] = {}
    for after, element in added:
        if element.id in ids or element.id in known:
            raise PatchMismatchError("The patch adds a block the document already has.")
        if after is not None and after not in known:
            raise PatchMismatchError("The patch adds a block after one the document doesn't have.")
        if after in following:
            raise PatchMismatchError("The patch adds two blocks in the same place.")
        following[after] = element
        known.add(element.id)

    result: list[Element] = []

    def chain(anchor: str | None) -> None:
        while anchor in following:
            element = following.pop(anchor)
            result.append(element)
            anchor = element.id

    chain(None)
    for element in kept:
        result.append(element)
        chain(element.id)
    return result


def _without_order(element: dict[str, Any]) -> dict[str, Any]:
    # A top-level element's order is its place in the list, which the editor knows.
    return {key: value for key, value in element.items() if key != "order"}


def content_delta(before: dict[str, Any], after: dict[str, Any], asked: list[str]) -> dict[str, Any]:
    """How the stored document `after` (dump_document) differs from `before`, the
    revision the patch was based on: the top-level elements that changed or are
    new, as stored; their order, only when it isn't `asked`, the order the patch
    made (which leaves out the removed ones); and every other part of the
    document that changed, whole. Applied to `before` (editor/contentPatch.ts),
    it gives `after`."""
    was = {element["id"]: element for element in before["elements"]}
    order = [element["id"] for element in after["elements"]]

    def differs(element: dict[str, Any]) -> bool:
        # What nearly every element does is come back as it was, so that is asked first,
        # in one comparison; only one that isn't equal as it stands is looked at again
        # without its order.
        earlier = was.get(element["id"])
        return earlier is None or (earlier != element and _without_order(earlier) != _without_order(element))

    return {
        "changed": [element for element in after["elements"] if differs(element)],
        "order": None if order == asked else order,
        "fields": {key: value for key, value in after.items() if key != "elements" and before.get(key) != value},
    }
