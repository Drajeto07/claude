"""Document Health (корекции.docx §38): how consistent a document's formatting
is, found by deterministic checks of its elements and their resolved styles.
The score comes from these checks alone -- never from an AI -- and each issue
names the elements it concerns, so the editor can point at them.

A check that doesn't apply (no tables, no links) is "skip" and doesn't count.
Score: the checks' weights, a pass counting fully and a warning half, as a
share of all that apply.

Health 2.0 (HLTH-001) adds pictures without alt text, hidden text, text in another
language than the document's, what the import couldn't keep, sections set up almost
alike, broken lists, empty paragraphs, pictures and tables wider than the page's text,
and formatting that repeats what the style already gives. What can be put right
deterministically is offered as fixes to review (formatting/health_fixes.py, HLTH-002):
`fixes` counts them."""

import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from app.formatting.render_spec import page_size_mm
from app.models.base import ApiModel
from app.models.document import Document, Element, ElementType, Mark, MarkType, inline_runs, walk_elements
from app.security.links import safe_href
from app.translation.language import detect, language_name

Status = Literal["pass", "warn", "fail", "skip"]

_BODY_TYPES = {ElementType.PARAGRAPH, ElementType.LIST, ElementType.QUOTE, ElementType.TABLE, ElementType.CAPTION, ElementType.FOOTNOTE}
_MANUAL_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+\S")
_LIST_TEXT_NUMBER = re.compile(r"^\s*\d+[.)]\s")
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
    # How many fixes for it can be proposed now (HLTH-002), not counting ones already waiting.
    fixes: int = 0


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


def body_fonts(document: Document) -> dict[str, set[str]]:
    """Font -> the body blocks using it, through their style or set on their text."""
    by_font: dict[str, set[str]] = {}
    for element in _text_elements(document):
        base = _css(document, element).get("font-family", "").split(",")[0].strip().strip("'\"")
        if base:
            by_font.setdefault(base, set()).add(element.id)
        for text, mark in _marks(element):
            if mark.type == MarkType.TEXT_STYLE and mark.fontFamily and text.strip():
                by_font.setdefault(mark.fontFamily.strip(), set()).add(element.id)
    return by_font


def _fonts(document: Document) -> HealthCheck:
    """Body text in one font, as a document usually is; each extra font is a warning."""
    if not _text_elements(document):
        return _check("fonts", "Fonts", 3, "skip", "No body text to check.")
    by_font = body_fonts(document)
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
    """Paragraphs spaced alike (space made with empty paragraphs: _empty_paragraphs)."""
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


def page_break_check(document: Document) -> HealthCheck:
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
    """Every link has a usable address (checked as written, not by visiting it) --
    in list items, table cells and nested blocks too, reported against the block
    the editor shows."""
    links: list[tuple[Element, str | None]] = []
    for element in document.elements:
        for run in inline_runs(element):
            for mark in run.marks:
                if mark.type == MarkType.LINK:
                    links.append((element, mark.href))
    if not links:
        return _check("links", "Links", 1, "skip", "No links.")
    broken = [element.id for element, href in links if not _usable_link(href)]
    if not broken:
        return _check("links", "Links", 1, "pass", f"{len(links)} link{'s' if len(links) != 1 else ''}, all with a usable address.")
    return _check("links", "Links", 1, "fail", f"{len(broken)} of {len(links)} links have no usable address.", [HealthIssue(message="Link without a usable address", elementIds=sorted(set(broken)))])


def _usable_link(href: str | None) -> bool:
    href = safe_href(href)  # one a link may have at all (SEC-014)
    if href is None:
        return False
    parsed = urlparse(href)
    scheme, host = parsed.scheme.lower(), parsed.hostname or ""
    if scheme in {"http", "https", "ftp", "ftps"}:
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


# --- Health 2.0 (HLTH-001) ------------------------------------------------------------------------


def empty_paragraphs(document: Document) -> list[Element]:
    """Paragraphs with nothing in them: no text, nothing kept for export."""
    return [
        element
        for element in document.elements
        if element.type == ElementType.PARAGRAPH and not element.content.strip() and not element.preservedAttributes
    ]


def _empty_paragraphs(document: Document) -> HealthCheck:
    """Space made with spacing, not with empty paragraphs (they move when the text does)."""
    if not _text_elements(document):
        return _check("empty_paragraphs", "Empty paragraphs", 1, "skip", "No text yet.")
    empty = empty_paragraphs(document)
    if not empty:
        return _check("empty_paragraphs", "Empty paragraphs", 1, "pass", "No empty paragraphs.")
    position = {element.id: index for index, element in enumerate(document.elements)}
    places = sum(1 for index, element in enumerate(empty) if index == 0 or position[element.id] != position[empty[index - 1].id] + 1)
    status: Status = "warn" if len(empty) <= 3 else "fail"
    return _check(
        "empty_paragraphs",
        "Empty paragraphs",
        1,
        status,
        f"{len(empty)} empty paragraph{'s' if len(empty) != 1 else ''}, in {places} place{'s' if places != 1 else ''}.",
        [HealthIssue(message="Empty paragraphs used as spacing", elementIds=[element.id for element in empty])],
    )


_FILE_NAME = re.compile(r"^[\w\s.-]+\.(png|jpe?g|gif|bmp|tiff?|webp|svg|emf|wmf)$", re.IGNORECASE)
_PLACEHOLDER_ALT = {"image", "picture", "photo", "figure", "graphic", "img"}


def _describes(element: Element) -> bool:
    alt = " ".join((element.image.alt or "").split()) if element.image else ""
    return bool(alt) and not _FILE_NAME.match(alt) and alt.lower() not in _PLACEHOLDER_ALT


def _shown(document: Document, ids: Iterable[str]) -> list[str]:
    """The top-level blocks (what the editor shows) holding the elements `ids`, in order."""
    wanted = set(ids)
    return [element.id for element in document.elements if any(inner.id in wanted for inner in walk_elements([element]))]


def _alt_text(document: Document) -> HealthCheck:
    """Every picture says what it shows (alt text): what a screen reader reads, and what shows
    where the picture can't. A file name or "image" isn't a description. Only a person can say
    what a picture shows, so there is no fix."""
    images = [element for element in walk_elements(document.elements) if element.type == ElementType.IMAGE and element.image]
    if not images:
        return _check("alt_text", "Alt text", 2, "skip", "No pictures.")
    missing = [element.id for element in images if not _describes(element)]
    if not missing:
        return _check("alt_text", "Alt text", 2, "pass", f"{len(images)} picture{'s' if len(images) != 1 else ''}, all described.")
    status: Status = "fail" if len(missing) * 2 > len(images) else "warn"
    return _check(
        "alt_text",
        "Alt text",
        2,
        status,
        f"{len(missing)} of {len(images)} pictures have no alt text.",
        [HealthIssue(message="Without alt text", elementIds=_shown(document, missing))],
    )


def _hidden_text(document: Document) -> HealthCheck:
    """Hidden text (Word's hidden font) is kept, but easily overlooked: it doesn't print and
    travels with the file. Not removed here -- a clean copy does that on request."""
    hidden = [
        element.id
        for element in document.elements
        if any(mark.type == MarkType.HIDDEN for run in inline_runs(element) if run.text.strip() for mark in run.marks)
    ]
    if not hidden:
        return _check("hidden_text", "Hidden text", 1, "skip", "No hidden text.")
    return _check(
        "hidden_text",
        "Hidden text",
        1,
        "warn",
        f"Hidden text in {len(hidden)} block{'s' if len(hidden) != 1 else ''}: it doesn't print, but anyone with the file can read it.",
        [HealthIssue(message="Holds hidden text", elementIds=hidden)],
    )


_LANGUAGE_TYPES = {ElementType.PARAGRAPH, ElementType.HEADING, ElementType.LIST, ElementType.QUOTE, ElementType.CAPTION, ElementType.FOOTNOTE}
_LANGUAGE_WORDS = 6
LANGUAGE_CONFIDENCE = 0.5


def document_language(document: Document) -> str | None:
    """The language the user set, else the one the text reads as (TRAN-007)."""
    if document.metadata.language:
        return document.metadata.language
    return detect(" ".join(element.content for element in document.elements[:200])[:20_000]).language


def _primary(tag: str | None) -> str:
    return (tag or "").split("-")[0].lower()


def other_language_blocks(document: Document) -> list[tuple[Element, str]]:
    """(block, its language) for blocks whose text clearly reads as another language than the
    document's and isn't marked as it -- its spelling is then checked, and its words hyphenated,
    as the wrong language."""
    main = _primary(document_language(document))
    if not main:
        return []
    found = []
    for element in document.elements:
        if element.type not in _LANGUAGE_TYPES or len(element.content.split()) < _LANGUAGE_WORDS:
            continue
        guess = detect(element.content)
        if not guess.language or guess.confidence < LANGUAGE_CONFIDENCE or _primary(guess.language) == main:
            continue
        runs = [run for run in inline_runs(element) if run.text.strip()]
        if not all(any(_primary(mark.lang) == _primary(guess.language) for mark in run.marks) for run in runs):
            found.append((element, guess.language))
    return found


def _language(document: Document) -> HealthCheck:
    """Text in another language than the document's is marked as that language."""
    main = document_language(document)
    if not main or not _text_elements(document):
        return _check("language", "Language", 1, "skip", "The document's language can't be told; set it to check this.")
    found = other_language_blocks(document)
    if not found:
        return _check("language", "Language", 1, "pass", f"The text is in {language_name(main)}, or marked as the language it is in.")
    by_language: dict[str, list[str]] = {}
    for element, language in found:
        by_language.setdefault(language, []).append(element.id)
    issues = [
        HealthIssue(message=f"{len(ids)} block{'s' if len(ids) != 1 else ''} in {language_name(language)}, not marked as it", elementIds=ids)
        for language, ids in sorted(by_language.items())
    ]
    return _check("language", "Language", 1, "warn", f"Some text isn't in {language_name(main)} and isn't marked as its language.", issues)


def _unsupported(document: Document) -> HealthCheck:
    """What the import couldn't keep as it was -- its report's approximated, left-out and refused
    items, else the document's notes: worth checking against the original before relying on it."""
    from app.fidelity.report import REVIEW_POLICIES  # the report module imports the document model

    items = [item for item in (document.importReport.items if document.importReport else []) if item.policy in REVIEW_POLICIES]
    notes = [note for note in document.unsupportedFeatures if note.strip()] if not items else []
    if not items and not notes:
        if document.importReport is None:
            return _check("unsupported", "Kept from the original", 1, "skip", "Not imported from a file.")
        return _check("unsupported", "Kept from the original", 1, "pass", "Everything the import found was kept.")
    issues = [HealthIssue(message=item.reason[:200], elementIds=item.elementIds[:50]) for item in items[:20]]
    issues += [HealthIssue(message=note[:200], elementIds=[]) for note in notes[:20]]
    count = len(items) or len(notes)
    status: Status = "fail" if any(item.contentChanged for item in items) else "warn"
    return _check("unsupported", "Kept from the original", 1, status, f"{count} thing{'s' if count != 1 else ''} from the original weren't kept as they were.", issues)


@dataclass(frozen=True)
class SectionSetup:
    element: Element | None  # the section break ending the section; None: the last section
    widthMm: float
    heightMm: float
    margins: tuple[float, float, float, float]  # top, right, bottom, left (cm)


def sections(document: Document) -> list[tuple[SectionSetup, list[Element]]]:
    """Each section's page setup and its elements, in order (a section break ends its section)."""
    settings = document.settings
    width, height = page_size_mm(settings.pageSize, settings.orientation)
    base = (settings.marginTopCm, settings.marginRightCm, settings.marginBottomCm, settings.marginLeftCm)
    found: list[tuple[SectionSetup, list[Element]]] = []
    current: list[Element] = []
    for element in document.elements:
        if element.type != ElementType.SECTION_BREAK or element.sectionBreak is None:
            current.append(element)
            continue
        own = element.sectionBreak
        sized = bool(own.pageWidthMm and own.pageHeightMm)
        own_margins = (own.marginTopCm, own.marginRightCm, own.marginBottomCm, own.marginLeftCm)
        margins = tuple(value if value is not None else default for value, default in zip(own_margins, base, strict=True))
        found.append((SectionSetup(element, own.pageWidthMm if sized else width, own.pageHeightMm if sized else height, margins), current))  # type: ignore[arg-type]
        current = []
    last = document.lastSection
    if last is not None and last.pageWidthMm and last.pageHeightMm:
        width, height = last.pageWidthMm, last.pageHeightMm
    found.append((SectionSetup(None, width, height, base), current))
    return found


SECTION_SLACK_CM = 0.5


def odd_sections(document: Document) -> list[tuple[SectionSetup, tuple[float, float, float, float]]]:
    """(section, the margins most sections have) for sections whose margins are almost, but not
    quite, those: a slip rather than a choice. Margins further apart are taken as meant."""
    found = sections(document)
    if len(found) < 2:
        return []
    usual = Counter(setup.margins for setup, _ in found).most_common(1)[0][0]
    return [
        (setup, usual)
        for setup, _ in found
        if setup.margins != usual and all(abs(a - b) <= SECTION_SLACK_CM for a, b in zip(setup.margins, usual, strict=True))
    ]


def _section_anchor(setup: SectionSetup, elements: list[Element]) -> str | None:
    """What the editor can show for a section: its break, else (the last section) its last block."""
    return setup.element.id if setup.element else (elements[-1].id if elements else None)


def _section_key(setup: SectionSetup) -> str | None:
    return setup.element.id if setup.element else None


def _paper(setup: SectionSetup) -> tuple[int, int]:
    return round(min(setup.widthMm, setup.heightMm)), round(max(setup.widthMm, setup.heightMm))


def _sections(document: Document) -> HealthCheck:
    """Sections set up alike, unless clearly meant to differ (a landscape page is meant)."""
    found = sections(document)
    if len(found) < 2:
        return _check("sections", "Sections", 1, "skip", "One section.")
    anchors = {_section_key(setup): _section_anchor(setup, elements) for setup, elements in found}
    issues = []
    odd = odd_sections(document)
    if odd:
        ids = [anchor for setup, _ in odd if (anchor := anchors[_section_key(setup)])]
        issues.append(HealthIssue(message=f"{len(odd)} section{'s' if len(odd) != 1 else ''} with margins slightly different from the rest", elementIds=ids))
    papers = Counter(_paper(setup) for setup, _ in found)
    if len(papers) > 1:
        usual = papers.most_common(1)[0][0]
        ids = [anchor for setup, _ in found if _paper(setup) != usual and (anchor := anchors[_section_key(setup)])]
        issues.append(HealthIssue(message="Sections on another paper size than the rest", elementIds=ids))
    if not issues:
        return _check("sections", "Sections", 1, "pass", f"{len(found)} sections, set up consistently.")
    return _check("sections", "Sections", 1, "warn", "Sections aren't set up alike.", issues)


def empty_list_items(element: Element) -> list[int]:
    """The indices of a list's items with nothing in them."""
    return [index for index, item in enumerate(element.listItems or []) if not "".join(run.text for run in item.inline).strip() and not item.blocks]


def skipped_list_levels(element: Element) -> list[int]:
    """The indices of items nested more than one level deeper than the item before them."""
    items = element.listItems or []
    return [index for index, item in enumerate(items) if item.level > (items[index - 1].level + 1 if index else 0)]


def _format(element: Element) -> str:
    return element.numbering.format if element.numbering and element.numbering.format else "decimal"


def restarted_lists(document: Document) -> list[tuple[Element, Element]]:
    """(list, the numbered list right before it) for numbered lists starting again at 1 right
    after a numbered list of the same kind: one list split in two."""
    found = []
    for previous, element in zip(document.elements, document.elements[1:]):
        if element.type == previous.type == ElementType.LIST and element.ordered and previous.ordered:
            if _format(element) == _format(previous) and (element.numbering.start if element.numbering else 1) == 1:
                found.append((element, previous))
    return found


def _lists(document: Document) -> HealthCheck:
    """Lists without empty items or skipped levels, and none split in two."""
    lists = [element for element in document.elements if element.type == ElementType.LIST]
    if not lists:
        return _check("lists", "Lists", 1, "skip", "No lists.")
    issues = []
    empty = [element.id for element in lists if empty_list_items(element)]
    if empty:
        issues.append(HealthIssue(message=f"Empty items in {len(empty)} list{'s' if len(empty) != 1 else ''}", elementIds=empty))
    skipped = [element.id for element in lists if skipped_list_levels(element)]
    if skipped:
        issues.append(HealthIssue(message="Items nested more than one level deeper than the one before", elementIds=skipped))
    restarted = [element.id for element, _ in restarted_lists(document)]
    if restarted:
        issues.append(HealthIssue(message="Numbering starts again at 1 right after another numbered list", elementIds=restarted))
    if not issues:
        return _check("lists", "Lists", 1, "pass", f"{len(lists)} list{'s' if len(lists) != 1 else ''}, in order.")
    return _check("lists", "Lists", 1, "warn", "Some lists are broken.", issues)


def text_width_cm(setup: SectionSetup) -> float:
    return round(setup.widthMm / 10 - setup.margins[1] - setup.margins[3], 2)


def too_wide(document: Document) -> list[tuple[Element, float]]:
    """(picture or table, the text width it should fit) for top-level pictures and tables set
    wider than their page's text: they run into the margin or are cut off. A picture with a
    width rule is drawn to that, and a floating one is placed on its own, so neither counts."""
    found = []
    for setup, elements in sections(document):
        width = text_width_cm(setup)
        for element in elements:
            if element.type == ElementType.IMAGE and element.image and element.image.widthCm and element.image.placement is None:
                if element.image.widthCm > width + 0.05 and "width" not in document.resolvedStyles.get(element.id, {}):
                    found.append((element, width))
            elif element.type == ElementType.TABLE and element.table and element.table.widthCm and element.table.widthCm > width + 0.05:
                found.append((element, width))
    return found


def _layout(document: Document) -> HealthCheck:
    """Pictures and tables fit the page's text width."""
    if not any(element.type in (ElementType.IMAGE, ElementType.TABLE) for element in document.elements):
        return _check("layout", "Layout", 1, "skip", "No pictures or tables.")
    wide = too_wide(document)
    if not wide:
        return _check("layout", "Layout", 1, "pass", "Pictures and tables fit the page.")
    return _check(
        "layout",
        "Layout",
        1,
        "warn",
        f"{len(wide)} picture{'s or tables' if len(wide) != 1 else ' or table'} wider than the page's text.",
        [HealthIssue(message="Runs into the margin", elementIds=[element.id for element, _ in wide])],
    )


_BOLD_WEIGHTS = {"bold", "bolder", "600", "700", "800", "900"}


def repeated_formatting(document: Document, element: Element) -> list[str]:
    """What the element's own text sets that its style already gives (font, size, colour, bold):
    set twice, it stops following the style when the style changes."""
    css = _css(document, element)
    style_font = css.get("font-family", "").split(",")[0].strip().strip("'\"").lower()
    style_size = _points(css.get("font-size", ""))
    style_color = css.get("color", "").lower()
    bold_style = css.get("font-weight", "") in _BOLD_WEIGHTS
    found = set()
    for run in element.inline or []:
        if not run.text.strip():
            continue
        for mark in run.marks:
            if mark.type == MarkType.TEXT_STYLE:
                if mark.fontFamily and style_font and mark.fontFamily.strip().lower() == style_font:
                    found.add("font")
                if mark.fontSizePt and style_size and abs(mark.fontSizePt - style_size) < 0.01:
                    found.add("size")
                if mark.color and style_color and mark.color.lower() == style_color:
                    found.add("colour")
            elif mark.type == MarkType.BOLD and bold_style:
                found.add("bold")
    return sorted(found)


def _repeated(document: Document) -> HealthCheck:
    """Text formatted with what its style already gives."""
    elements = [element for element in document.elements if element.inline and element.content.strip()]
    if not elements:
        return _check("duplicated_formatting", "Repeated formatting", 1, "skip", "No text to check.")
    repeated = [(element, what) for element in elements if (what := repeated_formatting(document, element))]
    if not repeated:
        return _check("duplicated_formatting", "Repeated formatting", 1, "pass", "Text doesn't repeat its style's formatting.")
    kinds = sorted({kind for _, what in repeated for kind in what})
    status: Status = "warn" if len(repeated) * 5 > len(elements) else "pass"
    return _check(
        "duplicated_formatting",
        "Repeated formatting",
        1,
        status,
        f"{len(repeated)} block{'s' if len(repeated) != 1 else ''} set {', '.join(kinds)} their style already gives.",
        [HealthIssue(message=f"Sets {', '.join(kinds)} its style already gives", elementIds=[element.id for element, _ in repeated])],
    )


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
    page_break_check,
    _links,
    _empty_paragraphs,
    _alt_text,
    _hidden_text,
    _language,
    _unsupported,
    _sections,
    _lists,
    _layout,
    _repeated,
]


def check_health(document: Document) -> HealthReport:
    from app.formatting.health_fixes import fix_counts  # it builds on this module's findings

    checks = [check(document) for check in CHECKS]
    counts = fix_counts(document, [check.id for check in checks if check.status in ("warn", "fail")])
    for check in checks:
        check.fixes = counts.get(check.id, 0)
    counted = [check for check in checks if check.status != "skip"]
    total = sum(check.weight for check in counted)
    earned = sum(check.weight * {"pass": 1.0, "warn": 0.5, "fail": 0.0}[check.status] for check in counted)
    score = round(100 * earned / total) if total else 100
    rating = "good" if score >= 85 else "fair" if score >= 60 else "poor"
    return HealthReport(score=score, rating=rating, checks=checks)
