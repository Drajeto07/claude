"""A document's text as translation segments (tracker TRAN-001, brief §46): never the whole
document as one string -- each paragraph, heading, caption, list item and table cell is a
segment of its own, and keeps where it came from (element, list item or cell, run indices),
its marks, its style, its languages, its status.

The formatting travels as tags a translator moves with the words they belong to but never
sees the meaning of: a run with marks is <mN>...</mN> (N, the run's index -- its marks stay
here), a run of code, a web or e-mail address is a placeholder <xN/> that is never
translated, a line break is <br/>; &, < and > in the text are escaped. A translation is
parsed back into runs, each tag's text taking its source run's marks, each placeholder its
source text: the formatting comes back exactly, wherever the words moved."""

import re
from dataclasses import dataclass, field

from app.models.document import Element, ElementType, InlineRun, Mark, MarkType

# Blocks with nothing to translate, or whose text must not change.
SKIPPED = frozenset({ElementType.CODE_BLOCK, ElementType.IMAGE, ElementType.PAGE_BREAK, ElementType.SECTION_BREAK, ElementType.HORIZONTAL_RULE})
# Text kept as it is, inside any run: web and e-mail addresses.
_KEPT = re.compile(r"(?:https?://|www\.)[^\s<>]+[^\s<>.,;:!?)\]'\"]|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_TAG = re.compile(r"<m(\d+)>|</m(\d+)>|<x(\d+)/>|<br/>")
# Any other tag: markup a translator added (the text's own < and > are escaped).
_INVENTED = re.compile(r"</?[A-Za-z][^<>]*>")


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def unescape(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


@dataclass(frozen=True, slots=True)
class Placeholder:
    text: str
    marks: tuple[Mark, ...]


@dataclass(slots=True)
class Segment:
    """One piece of text to translate, and everything needed to put its translation back."""

    id: str  # "<element id>" or "<element id>/item/<item id>" or "<element id>/cell/<cell id>"
    element_id: str
    path: str  # "" | "item/<id>" | "cell/<id>"
    source: str  # tagged
    marks: dict[int, tuple[Mark, ...]]  # each <mN>'s marks
    placeholders: dict[int, Placeholder]
    style_ref: str | None = None
    source_language: str | None = None
    target_language: str | None = None
    status: str = "pending"  # pending, translated, invalid, failed, accepted, rejected
    provider: str | None = None
    glossary_terms: list[str] = field(default_factory=list)
    target: str | None = None  # tagged
    problems: list[str] = field(default_factory=list)

    @property
    def plain(self) -> str:
        return plain_text(self.source, self)


def tag_runs(runs: list[InlineRun]) -> tuple[str, dict[int, tuple[Mark, ...]], dict[int, Placeholder]]:
    """Runs as tagged text, their marks by tag, and the placeholders."""
    parts: list[str] = []
    marks: dict[int, tuple[Mark, ...]] = {}
    placeholders: dict[int, Placeholder] = {}

    def keep(text: str, run_marks: tuple[Mark, ...]) -> str:
        index = len(placeholders)
        placeholders[index] = Placeholder(text, run_marks)
        return f"<x{index}/>"

    for index, run in enumerate(runs):
        run_marks = tuple(run.marks)
        if any(mark.type == MarkType.CODE for mark in run_marks):
            parts.append(keep(run.text, run_marks))
            continue
        pieces: list[str] = []
        last = 0
        for match in _KEPT.finditer(run.text):
            pieces.append(escape(run.text[last : match.start()]).replace("\n", "<br/>"))
            pieces.append(keep(match.group(), run_marks))
            last = match.end()
        pieces.append(escape(run.text[last:]).replace("\n", "<br/>"))
        text = "".join(pieces)
        if run_marks and text:
            marks[index] = run_marks
            parts.append(f"<m{index}>{text}</m{index}>")
        else:
            parts.append(text)
    return "".join(parts), marks, placeholders


class TagError(ValueError):
    """A translation's tags don't make sense: unknown, unclosed, nested or crossed."""


def untag(tagged: str, marks: dict[int, tuple[Mark, ...]], placeholders: dict[int, Placeholder]) -> list[InlineRun]:
    """Tagged text back into runs (TagError when its tags don't fit the segment's)."""
    runs: list[InlineRun] = []
    open_tag: int | None = None
    last = 0

    def text(chunk: str) -> None:
        if _INVENTED.search(chunk):
            raise TagError("markup the segment didn't have")
        if chunk:
            add(unescape(chunk), marks[open_tag] if open_tag is not None else ())

    def add(value: str, run_marks: tuple[Mark, ...]) -> None:
        if runs and tuple(runs[-1].marks) == run_marks:
            runs[-1] = InlineRun(text=runs[-1].text + value, marks=list(run_marks))
        else:
            runs.append(InlineRun(text=value, marks=list(run_marks)))

    for match in _TAG.finditer(tagged):
        text(tagged[last : match.start()])
        last = match.end()
        opened, closed, kept = match.group(1), match.group(2), match.group(3)
        if opened is not None:
            if open_tag is not None or int(opened) not in marks:
                raise TagError(f"<m{opened}> where it can't open")
            open_tag = int(opened)
        elif closed is not None:
            if open_tag != int(closed):
                raise TagError(f"</m{closed}> that closes nothing open")
            open_tag = None
        elif kept is not None:
            if int(kept) not in placeholders:
                raise TagError(f"<x{kept}/> that isn't the segment's")
            placeholder = placeholders[int(kept)]
            add(placeholder.text, placeholder.marks)
        else:
            add("\n", marks[open_tag] if open_tag is not None else ())
    text(tagged[last:])
    if open_tag is not None:
        raise TagError(f"<m{open_tag}> never closed")
    return [run for run in runs if run.text]


def plain_text(tagged: str, segment: "Segment") -> str:
    """What a tagged text reads as, tags gone, placeholders their text."""

    def put(match: re.Match[str]) -> str:
        if match.group(3) is not None:
            placeholder = segment.placeholders.get(int(match.group(3)))
            return placeholder.text if placeholder is not None else ""
        return "\n" if match.group(0) == "<br/>" else ""

    return unescape(_TAG.sub(put, tagged))


def _segment(element: Element, path: str, runs: list[InlineRun]) -> Segment | None:
    tagged, marks, placeholders = tag_runs(runs)
    if not plain_text(tagged, Segment("", "", "", tagged, marks, placeholders)).strip():
        return None
    segment_id = element.id if not path else f"{element.id}/{path}"
    return Segment(id=segment_id, element_id=element.id, path=path, source=tagged, marks=marks, placeholders=placeholders, style_ref=element.styleRef)


def segments_of(element: Element) -> list[Segment]:
    """The element's segments, in reading order: its own text, its list items', its table
    cells' (a cell holding blocks: none yet -- reported by the caller as skipped)."""
    if element.type in SKIPPED:
        return []
    found: list[Segment | None] = []
    if element.listItems:
        found.extend(_segment(element, f"item/{item.id}", item.inline) for item in element.listItems)
    elif element.table:
        for row in element.table.rows:
            for cell in row.cells:
                if not cell.blocks:
                    found.append(_segment(element, f"cell/{cell.id}", cell.inline))
    elif element.inline:
        found.append(_segment(element, "", element.inline))
    elif element.content and element.children is None:
        found.append(_segment(element, "", [InlineRun(text=element.content)]))
    return [segment for segment in found if segment is not None]


def untranslatable(element: Element) -> bool:
    """Whether the element holds text a segment can't carry yet: blocks nested in a
    quote, a list item or a cell (said, not skipped silently)."""
    if element.children:
        return True
    if any(item.blocks for item in element.listItems or []):
        return True
    return bool(element.table and any(cell.blocks for row in element.table.rows for cell in row.cells))
