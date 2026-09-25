"""Document Health (корекции.docx §38): how consistent a document's formatting
is, found by deterministic checks of its elements and their resolved styles.
The score comes from these checks alone -- never from an AI -- and each issue
names the elements it concerns, so the editor can point at them.

A check that doesn't apply (no tables, no links) is "skip" and doesn't count.
Score: the checks' weights, a pass counting fully and a warning half, as a
share of all that apply."""

import re
from collections import Counter
from collections.abc import Callable, Iterable
from typing import Literal
from urllib.parse import urlparse

from app.models.base import ApiModel
from app.models.document import Document, Element, ElementType, Mark, MarkType

Status = Literal["pass", "warn", "fail", "skip"]

_BODY_TYPES = {ElementType.PARAGRAPH, ElementType.LIST, ElementType.QUOTE, ElementType.TABLE, ElementType.CAPTION, ElementType.FOOTNOTE}
_MANUAL_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+\S")
_LIST_TEXT_NUMBER = re.compile(r"^\s*\d+[.)]\s")
_SAFE_SCHEMES = {"http", "https", "mailto", "tel", "ftp"}
_PREVIEW = 60


class HealthIssue(ApiModel):
    message: str
    elementIds: list[str]


class HealthCheck(ApiModel):
    id: str
    title: str
    status: Status
    summary: str
    issues: list[HealthIssue]
    weight: int


class HealthReport(ApiModel):
    score: int
    rating: Literal["good", "fair", "poor"]
    checks: list[HealthCheck]


def _preview(element: Element) -> str:
    text = " ".join(element.content.split())
    return f"“{text[:_PREVIEW]}…”" if len(text) > _PREVIEW else f"“{text}”"


def _css(document: Document, element: Element) -> dict[str, str]:
    return document.resolvedStyles.get(element.styleRef or "", {})


def _majority(values: Iterable[str]) -> str | None:
    counts = Counter(values)
    return counts.most_common(1)[0][0] if counts else None


def _text_elements(document: Document, types: set[ElementType] = _BODY_TYPES) -> list[Element]:
    return [element for element in document.elements if element.type in types and element.content.strip()]


def _marks(element: Element) -> Iterable[tuple[str, Mark]]:
    """(run text, mark) for every mark on the element's runs."""
    for run in element.inline or []:
        for mark in run.marks:
            yield run.text, mark


def _run_size(element: Element) -> float | None:
    """The size set on all of the element's text, when every run carries the same one."""
    sizes = set()
    for run in element.inline or []:
        if run.text.strip():
            sizes.add(next((mark.fontSizePt for mark in run.marks if mark.type == MarkType.TEXT_STYLE and mark.fontSizePt), None))
    return sizes.pop() if len(sizes) == 1 else None


def _check(id: str, title: str, weight: int, status: Status, summary: str, issues: list[HealthIssue] | None = None) -> HealthCheck:
    return HealthCheck(id=id, title=title, status=status, summary=summary, issues=issues or [], weight=weight)


def _fonts(document: Document) -> HealthCheck:
    """Body text in one font, as a document usually is; each extra font is a warning."""
    elements = _text_elements(document)
    if not elements:
        return _check("fonts", "Fonts", 3, "skip", "No body text to check.")
    by_font: dict[str, set[str]] = {}
    for element in elements:
        base = _css(document, element).get("font-family", "").split(",")[0].strip().strip("'\"")
        if base:
            by_font.setdefault(base, set()).add(element.id)
        for text, mark in _marks(element):
            if mark.type == MarkType.TEXT_STYLE and mark.fontFamily and text.strip():
                by_font.setdefault(mark.fontFamily.strip(), set()).add(element.id)
    if len(by_font) <= 1:
        return _check("fonts", "Fonts", 3, "pass", "Body text uses one font.")
    main = max(by_font, key=lambda font: len(by_font[font]))
    issues = [
        HealthIssue(message=f"{font} in {len(ids)} place{'s' if len(ids) != 1 else ''}", elementIds=sorted(ids))
        for font, ids in sorted(by_font.items())
        if font != main
    ]
    status: Status = "warn" if len(by_font) == 2 else "fail"
    return _check("fonts", "Fonts", 3, status, f"Body text uses {len(by_font)} fonts; most of it is {main}.", issues)


def _heading_sizes(document: Document) -> HealthCheck:
    """Headings of one level all the same size, and a level never larger than the one above it."""
    headings = [element for element in document.elements if element.type == ElementType.HEADING and element.content.strip()]
    if len(headings) < 2:
        return _check("heading_sizes", "Heading sizes", 3, "skip", "Fewer than two headings.")
    sizes: dict[int, dict[str, list[str]]] = {}
    for heading in headings:
        run_size = _run_size(heading)
        size = f"{run_size:g}pt" if run_size else _css(document, heading).get("font-size", "")
        sizes.setdefault(heading.level or 1, {}).setdefault(size, []).append(heading.id)
    issues: list[HealthIssue] = []
    for level, by_size in sorted(sizes.items()):
        if len(by_size) > 1:
            main = max(by_size, key=lambda size: len(by_size[size]))
            odd = [element_id for size, ids in by_size.items() if size != main for element_id in ids]
            issues.append(HealthIssue(message=f"Heading {level} comes in {len(by_size)} sizes ({', '.join(sorted(by_size))})", elementIds=odd))
    status: Status = "fail" if issues else "pass"
    majority = {level: max(by_size, key=lambda size: len(by_size[size])) for level, by_size in sizes.items()}
    levels = sorted(majority)
    for upper, lower in zip(levels, levels[1:]):
        if _points(majority[lower]) > _points(majority[upper]):
            issues.append(HealthIssue(message=f"Heading {lower} is larger than Heading {upper}", elementIds=sizes[lower][majority[lower]]))
            status = "fail" if status == "fail" else "warn"
    summary = "Each heading level has one size, getting smaller level by level." if not issues else f"{len(issues)} heading size problem{'s' if len(issues) != 1 else ''}."
    return _check("heading_sizes", "Heading sizes", 3, status, summary, issues)


def _points(size: str) -> float:
    match = re.match(r"([\d.]+)\s*(pt|px)?", size or "")
    if not match:
        return 0.0
    value = float(match.group(1))
    return value * 0.75 if match.group(2) == "px" else value


def _spacing(document: Document) -> HealthCheck:
    """Paragraphs spaced alike, and space made with spacing rather than empty paragraphs."""
    paragraphs = [element for element in document.elements if element.type == ElementType.PARAGRAPH]
    filled = [element for element in paragraphs if element.content.strip()]
    if len(filled) < 2:
        return _check("spacing", "Spacing", 2, "skip", "Fewer than two paragraphs.")
    key = lambda element: (_css(document, element).get("line-height", ""), _css(document, element).get("margin-bottom", ""))  # noqa: E731
    main = _majority(key(element) for element in filled)
    odd = [element.id for element in filled if key(element) != main]
    issues = []
    if odd:
        issues.append(HealthIssue(message=f"{len(odd)} paragraph{'s' if len(odd) != 1 else ''} spaced differently from the rest", elementIds=odd))
    empty_runs: list[list[str]] = []
    run: list[str] = []
    for element in document.elements:
        if element.type == ElementType.PARAGRAPH and not element.content.strip():
            run.append(element.id)
            continue
        if len(run) >= 2:
            empty_runs.append(run)
        run = []
    if len(run) >= 2:
        empty_runs.append(run)
    if empty_runs:
        ids = [element_id for group in empty_runs for element_id in group]
        issues.append(HealthIssue(message=f"Empty paragraphs used as spacing in {len(empty_runs)} place{'s' if len(empty_runs) != 1 else ''}", elementIds=ids))
    if not issues:
        return _check("spacing", "Spacing", 2, "pass", "Paragraphs are spaced consistently.")
    status: Status = "fail" if len(odd) > len(filled) / 4 else "warn"
    return _check("spacing", "Spacing", 2, status, "Spacing isn't consistent.", issues)


def _numbering(document: Document) -> HealthCheck:
    """Headings numbered by hand count up without gaps; lists aren't numbered twice."""
    numbered = [(element, _MANUAL_NUMBER.match(element.content)) for element in document.elements if element.type == ElementType.HEADING]
    numbered = [(element, match.group(1)) for element, match in numbered if match]
    ordered_lists = [element for element in document.elements if element.type == ElementType.LIST and element.ordered]
    if not numbered and not ordered_lists:
        return _check("numbering", "Numbering", 2, "skip", "Nothing is numbered.")
    issues: list[HealthIssue] = []
    # The last number used under each parent number: "2.3" is 3 under (2,).
    last: dict[tuple[int, ...], int] = {}
    for element, number in numbered:
        parts = tuple(int(part) for part in number.split("."))
        parent, own = parts[:-1], parts[-1]
        previous = last.get(parent, 0)
        if own != previous + 1:
            after = ".".join(map(str, parent + (previous,))) if previous else "the start of its level"
            issues.append(HealthIssue(message=f"{number} comes after {after} {_preview(element)}", elementIds=[element.id]))
        last[parent] = own
    doubled = [
        element.id
        for element in ordered_lists
        if any(_LIST_TEXT_NUMBER.match(" ".join(run.text for run in item.inline)) for item in element.listItems or [])
    ]
    if doubled:
        issues.append(HealthIssue(message="Numbered lists whose items also start with a typed number", elementIds=doubled))
    if not issues:
        return _check("numbering", "Numbering", 2, "pass", "Numbering is in order.")
    out_of_order = len(issues) - (1 if doubled else 0)
    return _check("numbering", "Numbering", 2, "fail" if out_of_order else "warn", "Numbering has gaps or doubles.", issues)


def _alignment(document: Document) -> HealthCheck:
    """Body paragraphs aligned alike (short centred lines like titles aside)."""
    long_paragraphs = [element for element in document.elements if element.type == ElementType.PARAGRAPH and len(element.content.strip()) > 80]
    if len(long_paragraphs) < 2:
        return _check("alignment", "Alignment", 1, "skip", "Too little body text to compare.")
    main = _majority(_css(document, element).get("text-align", "left") for element in long_paragraphs)
    odd = [element.id for element in long_paragraphs if _css(document, element).get("text-align", "left") != main]
    if not odd:
        return _check("alignment", "Alignment", 1, "pass", f"Body text is aligned the same way ({main}).")
    return _check("alignment", "Alignment", 1, "warn", f"Most body text is aligned {main}, but not all of it.", [HealthIssue(message=f"{len(odd)} paragraph{'s' if len(odd) != 1 else ''} aligned otherwise", elementIds=odd)])


def _page_breaks(document: Document) -> HealthCheck:
    """No page break at the very start or end, and none right after another (an empty page)."""
    elements = document.elements
    breaks = [index for index, element in enumerate(elements) if element.type == ElementType.PAGE_BREAK]
    if not breaks:
        return _check("page_breaks", "Page breaks", 1, "skip", "No page breaks.")
    content = [index for index, element in enumerate(elements) if element.type != ElementType.PAGE_BREAK and (element.content.strip() or element.type in {ElementType.IMAGE, ElementType.TABLE})]
    issues = []
    first, last_content = (content[0], content[-1]) if content else (len(elements), -1)
    edges = [elements[index].id for index in breaks if index < first or index > last_content]
    if edges:
        issues.append(HealthIssue(message="Page break before any content or after all of it", elementIds=edges))
    doubled = [elements[b].id for a, b in zip(breaks, breaks[1:]) if not any(a < index < b for index in content)]
    if doubled:
        issues.append(HealthIssue(message="Page breaks with nothing between them (an empty page)", elementIds=doubled))
    if not issues:
        return _check("page_breaks", "Page breaks", 1, "pass", f"{len(breaks)} page break{'s' if len(breaks) != 1 else ''}, all between content.")
    return _check("page_breaks", "Page breaks", 1, "warn", "Some page breaks look out of place.", issues)


def _tables(document: Document) -> HealthCheck:
    """Tables alike: all with a header row or none, none styled apart from the rest."""
    tables = [element for element in document.elements if element.type == ElementType.TABLE and element.table]
    if not tables:
        return _check("tables", "Tables", 1, "skip", "No tables.")
    issues = []
    with_header = [table.id for table in tables if table.table and table.table.hasHeaderRow]
    if 0 < len(with_header) < len(tables):
        without = [table.id for table in tables if table.id not in with_header]
        issues.append(HealthIssue(message=f"{len(with_header)} of {len(tables)} tables have a header row", elementIds=without))
    own_style = [table.id for table in tables if table.styleRef == table.id]
    if own_style and len(tables) > 1:
        issues.append(HealthIssue(message=f"{len(own_style)} table{'s' if len(own_style) != 1 else ''} formatted apart from the others", elementIds=own_style))
    if not issues:
        return _check("tables", "Tables", 1, "pass", f"{len(tables)} table{'s' if len(tables) != 1 else ''}, formatted alike.")
    return _check("tables", "Tables", 1, "warn", "Tables aren't formatted alike.", issues)


def _captions(document: Document) -> HealthCheck:
    """Once some figures or tables have a caption, all should."""
    elements = document.elements
    captioned_types = {ElementType.IMAGE, ElementType.TABLE}
    figures = [index for index, element in enumerate(elements) if element.type in captioned_types]
    if not figures:
        return _check("captions", "Captions", 1, "skip", "No figures or tables.")

    def has_caption(index: int) -> bool:
        return any(0 <= near < len(elements) and elements[near].type == ElementType.CAPTION for near in (index - 1, index + 1))

    missing = [elements[index].id for index in figures if not has_caption(index)]
    captions = sum(1 for element in elements if element.type == ElementType.CAPTION)
    if not missing:
        return _check("captions", "Captions", 1, "pass", "Every figure and table has a caption.")
    if captions == 0 and len(figures) == 1:
        return _check("captions", "Captions", 1, "pass", "One figure or table, without a caption.")
    return _check(
        "captions",
        "Captions",
        1,
        "warn",
        f"{len(missing)} of {len(figures)} figures and tables have no caption.",
        [HealthIssue(message="Without a caption", elementIds=missing)],
    )


def _hierarchy(document: Document) -> HealthCheck:
    """Longer documents have headings, and heading levels go down one at a time."""
    headings = [element for element in document.elements if element.type == ElementType.HEADING]
    words = sum(len(element.content.split()) for element in _text_elements(document))
    if not headings:
        if words > 600:
            return _check("hierarchy", "Structure", 3, "fail", f"{words} words and no headings: the document has no structure to navigate.")
        return _check("hierarchy", "Structure", 3, "pass" if words else "skip", "Short enough not to need headings." if words else "No text yet.")
    issues = []
    previous = 0
    for heading in headings:
        level = heading.level or 1
        if previous and level > previous + 1:
            issues.append(HealthIssue(message=f"Heading {level} right after Heading {previous} {_preview(heading)}", elementIds=[heading.id]))
        previous = level
    if not issues:
        return _check("hierarchy", "Structure", 3, "pass", f"{len(headings)} heading{'s' if len(headings) != 1 else ''}, nested in order.")
    return _check("hierarchy", "Structure", 3, "warn", "Some heading levels are skipped.", issues)


def _links(document: Document) -> HealthCheck:
    """Every link has a usable address (checked as written, not by visiting it)."""
    links: list[tuple[Element, str | None]] = []
    for element in document.elements:
        for _, mark in _marks(element):
            if mark.type == MarkType.LINK:
                links.append((element, mark.href))
    if not links:
        return _check("links", "Links", 1, "skip", "No links.")
    broken = [element.id for element, href in links if not _usable_link(href)]
    if not broken:
        return _check("links", "Links", 1, "pass", f"{len(links)} link{'s' if len(links) != 1 else ''}, all with a usable address.")
    return _check("links", "Links", 1, "fail", f"{len(broken)} of {len(links)} links have no usable address.", [HealthIssue(message="Link without a usable address", elementIds=sorted(set(broken)))])


def _usable_link(href: str | None) -> bool:
    if not href or not href.strip():
        return False
    parsed = urlparse(href.strip())
    scheme, host = parsed.scheme.lower(), parsed.hostname or ""
    if scheme not in _SAFE_SCHEMES:
        return False
    if scheme in {"http", "https", "ftp"}:
        return "." in host or host == "localhost"
    if scheme == "mailto":
        return "@" in parsed.path
    return bool(parsed.path.strip())


def _direct_formatting(document: Document) -> HealthCheck:
    """Formatting set on single paragraphs or pieces of text, instead of in the styles."""
    elements = _text_elements(document)
    if not elements:
        return _check("direct_formatting", "Direct formatting", 2, "skip", "No body text to check.")
    own_style = {element.id for element in elements if element.styleRef == element.id}
    marked = {
        element.id
        for element in elements
        for text, mark in _marks(element)
        if mark.type == MarkType.TEXT_STYLE and text.strip() and (mark.fontFamily or mark.fontSizePt or mark.color)
    }
    affected = own_style | marked
    if not affected:
        return _check("direct_formatting", "Direct formatting", 2, "pass", "All body text is formatted through its styles.")
    share = len(affected) / len(elements)
    issues = []
    if own_style:
        issues.append(HealthIssue(message=f"{len(own_style)} block{'s' if len(own_style) != 1 else ''} formatted on their own", elementIds=sorted(own_style)))
    if marked:
        issues.append(HealthIssue(message=f"Fonts, sizes or colours set on text in {len(marked)} block{'s' if len(marked) != 1 else ''}", elementIds=sorted(marked)))
    status: Status = "warn" if share > 0.2 else "pass"
    return _check("direct_formatting", "Direct formatting", 2, status, f"{len(affected)} of {len(elements)} blocks carry their own formatting.", issues)


CHECKS: list[Callable[[Document], HealthCheck]] = [
    _hierarchy,
    _fonts,
    _heading_sizes,
    _spacing,
    _direct_formatting,
    _numbering,
    _alignment,
    _tables,
    _captions,
    _page_breaks,
    _links,
]


def check_health(document: Document) -> HealthReport:
    checks = [check(document) for check in CHECKS]
    counted = [check for check in checks if check.status != "skip"]
    total = sum(check.weight for check in counted)
    earned = sum(check.weight * {"pass": 1.0, "warn": 0.5, "fail": 0.0}[check.status] for check in counted)
    score = round(100 * earned / total) if total else 100
    rating = "good" if score >= 85 else "fair" if score >= 60 else "poor"
    return HealthReport(score=score, rating=rating, checks=checks)
