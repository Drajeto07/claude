"""The content check: a document's words against its source's, in order.

Words are runs of letters and digits (any script); punctuation, spacing, line
breaks and markup (Markdown's "#" and "*", list numbers Word draws itself) don't
count, so a result can only differ in its words. "Verified" means the two word
sequences are identical -- nothing weaker. The differences are for people: where
words went missing, were added, changed or moved."""

import re
from collections.abc import Iterable
from difflib import SequenceMatcher

from app.fidelity.report import ContentCheck, ContentDifference
from app.models.document import Element, ElementType, child_blocks

_WORD = re.compile(r"\w+", re.UNICODE)
_MAX_SAMPLES = 20
_CONTEXT_WORDS = 4


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def _element_text(element: Element) -> Iterable[str]:
    """An element's text in reading order, nested blocks included."""
    if element.type == ElementType.CODE_BLOCK:
        yield element.content
        return
    if element.type == ElementType.LIST:
        for item in element.listItems or []:
            yield "".join(run.text for run in item.inline)
            for block in item.blocks or []:
                yield from _element_text(block)
        return
    if element.type == ElementType.TABLE and element.table:
        for row in element.table.rows:
            for cell in row.cells:
                if cell.blocks:
                    for block in cell.blocks:
                        yield from _element_text(block)
                else:
                    yield "".join(run.text for run in cell.inline)
        return
    if element.children:
        for child in child_blocks(element):
            yield from _element_text(child)
        return
    if element.inline is not None:
        yield "".join(run.text for run in element.inline)
    elif element.type != ElementType.IMAGE:
        yield element.content


def document_words(elements: Iterable[Element]) -> list[str]:
    """Every word a reader sees in the document body, in reading order."""
    result: list[str] = []
    for element in sorted(elements, key=lambda el: el.order):
        for text in _element_text(element):
            result.extend(words(text))
    return result


def compare_words(source: list[str], result: list[str], *, method: str) -> ContentCheck:
    if source == result:
        return ContentCheck(method=method, verified=True, sourceWords=len(source), resultWords=len(result))

    # Differences cluster; the long equal start and end need no diffing.
    start = 0
    while start < len(source) and start < len(result) and source[start] == result[start]:
        start += 1
    end = 0
    while end < len(source) - start and end < len(result) - start and source[-1 - end] == result[-1 - end]:
        end += 1
    left, right = source[start : len(source) - end], result[start : len(result) - end]

    removed: list[tuple[int, tuple[str, ...]]] = []  # (position in source, words)
    inserted: list[tuple[int, tuple[str, ...]]] = []  # (position in source, words)
    changed: list[tuple[int, tuple[str, ...], tuple[str, ...]]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, left, right, autojunk=len(left) > 20_000).get_opcodes():
        if tag == "delete":
            removed.append((start + i1, tuple(left[i1:i2])))
        elif tag == "insert":
            inserted.append((start + i1, tuple(right[j1:j2])))
        elif tag == "replace":
            changed.append((start + i1, tuple(left[i1:i2]), tuple(right[j1:j2])))

    # A run of words gone from one place and found, the same, at another moved.
    moved: list[tuple[int, tuple[str, ...]]] = []
    for entry in list(removed):
        match = next((other for other in inserted if other[1] == entry[1]), None)
        if match is not None:
            removed.remove(entry)
            inserted.remove(match)
            moved.append(entry)

    def context(position: int) -> str:
        return " ".join(source[max(0, position - _CONTEXT_WORDS) : position])

    located = [
        *((at, ContentDifference(kind="missing", source=" ".join(w), context=context(at))) for at, w in removed),
        *((at, ContentDifference(kind="added", result=" ".join(w), context=context(at))) for at, w in inserted),
        *((at, ContentDifference(kind="changed", source=" ".join(a), result=" ".join(b), context=context(at))) for at, a, b in changed),
        *((at, ContentDifference(kind="moved", source=" ".join(w), context=context(at))) for at, w in moved),
    ]
    samples = [sample for _, sample in sorted(located, key=lambda pair: pair[0])]
    return ContentCheck(
        method=method,
        verified=False,
        sourceWords=len(source),
        resultWords=len(result),
        missing=sum(len(w) for _, w in removed) + sum(len(a) for _, a, _ in changed),
        added=sum(len(w) for _, w in inserted) + sum(len(b) for _, _, b in changed),
        moved=sum(len(w) for _, w in moved),
        samples=[_shorten(sample) for sample in samples[:_MAX_SAMPLES]],
    )


def _shorten(sample: ContentDifference, limit: int = 300) -> ContentDifference:
    return sample.model_copy(
        update={"source": sample.source[:limit], "result": sample.result[:limit], "context": sample.context[:limit]}
    )
