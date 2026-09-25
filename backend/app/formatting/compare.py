"""Comparing two versions of a document (корекции.docx §31 "compare versions",
§39 "before/after") at the semantic level: which elements were added, removed,
moved, retyped or edited (matched by their ids, which survive every edit), which
resolved style properties changed per kind of text and per element, and which
page settings changed. A visual diff can later build on the same structure."""

from typing import Literal

from app.models.base import ApiModel
from app.models.document import COARSE_TARGETS, Document, Element, ElementType

_PREVIEW = 80
# Above this, moves aren't worked out (the sequence comparison is quadratic in time and memory).
_MAX_ELEMENTS_FOR_MOVES = 1000
_TARGET_LABELS = {
    "Paragraph": "Body text",
    "List": "Lists",
    "Table": "Tables",
    "Quote": "Quotes",
    "Caption": "Captions",
    "Footnote": "Footnotes",
    "CodeBlock": "Code",
    "Image": "Images",
    "PageBreak": "Page breaks",
    "HorizontalRule": "Horizontal lines",
}
_SETTINGS = ("pageSize", "orientation", "marginTopCm", "marginBottomCm", "marginLeftCm", "marginRightCm", "header", "footer", "showPageNumbers")


class ElementChange(ApiModel):
    elementId: str
    change: Literal["added", "removed", "moved", "retyped", "edited"]
    beforeType: ElementType | None
    afterType: ElementType | None
    beforeText: str | None
    afterText: str | None


class StyleChange(ApiModel):
    """A resolved style property that changed: for a kind of text ("Heading 1"),
    or for one element that is formatted on its own (`target` is then its id)."""

    target: str
    label: str
    property: str
    before: str | None
    after: str | None


class SettingChange(ApiModel):
    property: str
    before: str | None
    after: str | None


class DocumentComparison(ApiModel):
    fromVersion: int
    toVersion: int
    structure: list[ElementChange]
    styles: list[StyleChange]
    settings: list[SettingChange]


def _preview(element: Element | None) -> str | None:
    if element is None:
        return None
    text = " ".join(element.content.split())
    return text[:_PREVIEW] + "…" if len(text) > _PREVIEW else text


def _moved(before_ids: list[str], after_ids: list[str]) -> set[str]:
    """Elements in both whose place relative to the others changed: those outside
    the longest run of elements kept in the same order."""
    if len(before_ids) > _MAX_ELEMENTS_FOR_MOVES or len(after_ids) > _MAX_ELEMENTS_FOR_MOVES:
        return set()
    common = set(before_ids) & set(after_ids)
    a = [element_id for element_id in before_ids if element_id in common]
    b = [element_id for element_id in after_ids if element_id in common]
    # Longest common subsequence, keeping the lengths row by row.
    lengths = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) - 1, -1, -1):
        for j in range(len(b) - 1, -1, -1):
            lengths[i][j] = lengths[i + 1][j + 1] + 1 if a[i] == b[j] else max(lengths[i + 1][j], lengths[i][j + 1])
    kept, i, j = set(), 0, 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            kept.add(a[i])
            i, j = i + 1, j + 1
        elif lengths[i + 1][j] >= lengths[i][j + 1]:
            i += 1
        else:
            j += 1
    return common - kept


def _structure(before: Document, after: Document) -> list[ElementChange]:
    old = {element.id: element for element in before.elements}
    new = {element.id: element for element in after.elements}
    moved = _moved([element.id for element in before.elements], [element.id for element in after.elements])
    changes: list[ElementChange] = []

    def change(kind: str, element_id: str, was: Element | None, now: Element | None) -> None:
        changes.append(
            ElementChange(
                elementId=element_id,
                change=kind,
                beforeType=was.type if was else None,
                afterType=now.type if now else None,
                beforeText=_preview(was),
                afterText=_preview(now),
            )
        )

    for element in after.elements:
        was = old.get(element.id)
        if was is None:
            change("added", element.id, None, element)
        elif was.type != element.type or (was.type == ElementType.HEADING and was.level != element.level):
            change("retyped", element.id, was, element)
        elif was.content != element.content:
            change("edited", element.id, was, element)
        elif element.id in moved:
            change("moved", element.id, was, element)
    for element in before.elements:
        if element.id not in new:
            change("removed", element.id, element, None)
    return changes


def _label(target: str, document: Document) -> str:
    if target in _TARGET_LABELS:
        return _TARGET_LABELS[target]
    if target in COARSE_TARGETS:
        return target
    element = next((element for element in document.elements if element.id == target), None)
    if element is None:
        return "An element"
    kind = f"Heading {element.level or 1}" if element.type == ElementType.HEADING else element.type.value.replace("_", " ").capitalize()
    return f"{kind} “{_preview(element)}”"


def _as_set(css: dict[str, str], image: bool) -> dict[str, str]:
    """A resolved style as the settings people change: line-height is left out
    where it only follows from the line spacing (x 1.15), and a picture's margins
    become its alignment."""
    settings = dict(css)
    if "--line-spacing" in settings:
        settings.pop("line-height", None)
    if image:
        left, right = settings.pop("margin-left", None), settings.pop("margin-right", None)
        settings.pop("display", None)
        settings["alignment"] = "center" if left == right == "auto" else "right" if left == "auto" else "left"
    return settings


def _styles(before: Document, after: Document) -> list[StyleChange]:
    changes: list[StyleChange] = []

    def compare(target: str, was: dict[str, str], now: dict[str, str], label: str, image: bool = False) -> None:
        was, now = _as_set(was, image), _as_set(now, image)
        for prop in sorted(set(was) | set(now)):
            if was.get(prop) != now.get(prop):
                changes.append(StyleChange(target=target, label=label, property=prop, before=was.get(prop), after=now.get(prop)))

    for target in sorted((set(before.resolvedStyles) | set(after.resolvedStyles)) & COARSE_TARGETS):
        compare(target, before.resolvedStyles.get(target, {}), after.resolvedStyles.get(target, {}), _label(target, after), image=target == "Image")
    # Elements formatted on their own in either version, compared as each looked.
    old = {element.id: element for element in before.elements}
    for element in after.elements:
        was = old.get(element.id)
        if was is None or (was.styleRef != was.id and element.styleRef != element.id):
            continue
        compare(
            element.id,
            before.resolvedStyles.get(was.styleRef or "", {}),
            after.resolvedStyles.get(element.styleRef or "", {}),
            _label(element.id, after),
            image=element.type == ElementType.IMAGE,
        )
    return changes


def _settings(before: Document, after: Document) -> list[SettingChange]:
    changes = []
    for prop in _SETTINGS:
        was, now = getattr(before.settings, prop), getattr(after.settings, prop)
        if was != now:
            changes.append(SettingChange(property=prop, before=None if was is None else str(was), after=None if now is None else str(now)))
    return changes


def compare_documents(before: Document, after: Document, *, from_version: int, to_version: int) -> DocumentComparison:
    return DocumentComparison(
        fromVersion=from_version,
        toVersion=to_version,
        structure=_structure(before, after),
        styles=_styles(before, after),
        settings=_settings(before, after),
    )
