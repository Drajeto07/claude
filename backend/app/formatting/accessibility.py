"""The accessibility checker (brief §97, tracker FEAT-010): whether a document can be read with a
screen reader and by people who see less well -- heading hierarchy, alt text, link labels,
table headers, reading order, language and contrast. Deterministic checks of the saved
document, reported like Document Health's (formatting/health.py), each issue naming its blocks;
no score, and no AI. Contrast follows WCAG 2.2's AA thresholds: 4.5:1 for text, 3:1 for large
text (18 pt, or 14 pt bold)."""

import re

from app.formatting.colors import NAMED_COLORS
from app.formatting.health import HealthCheck, HealthIssue, _alt_text, _check, _points, _text_elements, document_language, other_language_blocks
from app.models.base import ApiModel
from app.models.document import Document, Element, ElementType, InlineRun, Mark, MarkType, inline_runs
from app.translation.language import language_name

_HEADINGS_NEEDED_WORDS = 300
# Link text that doesn't say where the link goes, read out of context by a screen reader.
_VAGUE_LABELS = {
    "click here", "here", "link", "this link", "read more", "more", "learn more", "see here", "this", "details", "go",
    "тук", "натиснете тук", "кликнете тук", "виж тук", "вижте тук", "още", "повече", "линк", "връзка", "прочетете още",
}
_ADDRESS = re.compile(r"^(https?://|www\.|mailto:)", re.IGNORECASE)
_ADDRESS_LABEL_LENGTH = 30
_BOLD_WEIGHTS = {"bold", "bolder", "600", "700", "800", "900"}
_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class AccessibilityReport(ApiModel):
    checks: list[HealthCheck]
    # How many checks found something (a warning or a failure).
    problems: int


def _headings(document: Document) -> HealthCheck:
    """Headings are how a screen reader moves through a document: a long one has them, they start
    at Heading 1, go down one level at a time, and none is empty."""
    headings = [element for element in document.elements if element.type == ElementType.HEADING]
    words = sum(len(element.content.split()) for element in _text_elements(document))
    if not headings:
        if words > _HEADINGS_NEEDED_WORDS:
            return _check("a11y_headings", "Heading hierarchy", 1, "fail", f"{words} words and no headings to move through them by.")
        return _check("a11y_headings", "Heading hierarchy", 1, "skip", "Short enough not to need headings.")
    issues = []
    first = headings[0]
    if (first.level or 1) != 1:
        issues.append(HealthIssue(message=f"The first heading is Heading {first.level}: start at Heading 1", elementIds=[first.id]))
    previous = 0
    skipped = []
    for heading in headings:
        level = heading.level or 1
        if previous and level > previous + 1:
            skipped.append(heading.id)
        previous = level
    if skipped:
        issues.append(HealthIssue(message="Heading levels skipped (a level goes down more than one step)", elementIds=skipped))
    empty = [heading.id for heading in headings if not heading.content.strip()]
    if empty:
        issues.append(HealthIssue(message="Empty headings: read out as headings with nothing in them", elementIds=empty))
    if not issues:
        return _check("a11y_headings", "Heading hierarchy", 1, "pass", f"{len(headings)} heading{'s' if len(headings) != 1 else ''}, in order from Heading 1.")
    return _check("a11y_headings", "Heading hierarchy", 1, "warn", "The headings don't form a clean outline.", issues)


def _link_labels(document: Document) -> list[tuple[str, str, str]]:
    """(block id, link text, address) for every link, its runs joined."""
    found = []
    for element in document.elements:
        label, href = "", None
        for run in [*inline_runs(element), InlineRun(text="")]:
            link = next((mark for mark in run.marks if mark.type == MarkType.LINK), None)
            if link is not None and link.href == href:
                label += run.text
                continue
            if href is not None:
                found.append((element.id, " ".join(label.split()), href))
            label, href = (run.text, link.href) if link is not None else ("", None)
    return found


def _links(document: Document) -> HealthCheck:
    """Each link's text says where it goes: "click here" or a long address read out letter by
    letter tells a screen-reader user nothing when links are listed apart from the text."""
    links = _link_labels(document)
    if not links:
        return _check("a11y_links", "Link labels", 1, "skip", "No links.")
    vague = sorted({element_id for element_id, label, _ in links if label.lower().strip(" .:!") in _VAGUE_LABELS or not label})
    addresses = sorted({element_id for element_id, label, _ in links if _ADDRESS.match(label) and len(label) > _ADDRESS_LABEL_LENGTH})
    issues = []
    if vague:
        issues.append(HealthIssue(message="Links whose text doesn't say where they go (“click here”, “more”)", elementIds=vague))
    if addresses:
        issues.append(HealthIssue(message="Links shown as a long address: name what they lead to instead", elementIds=addresses))
    if not issues:
        return _check("a11y_links", "Link labels", 1, "pass", f"{len(links)} link{'s' if len(links) != 1 else ''}, each saying where it goes.")
    return _check("a11y_links", "Link labels", 1, "warn", "Some links don't say where they go.", issues)


def _table_headers(document: Document) -> HealthCheck:
    """A data table has a header row, so a screen reader can say which column a cell is in."""
    tables = [element for element in document.elements if element.type == ElementType.TABLE and element.table]
    if not tables:
        return _check("a11y_tables", "Table headers", 1, "skip", "No tables.")
    missing = [
        element.id
        for element in tables
        if len(element.table.rows) > 1 and not element.table.hasHeaderRow and not any(cell.header for cell in element.table.rows[0].cells)
    ]
    if not missing:
        return _check("a11y_tables", "Table headers", 1, "pass", f"{len(tables)} table{'s' if len(tables) != 1 else ''}, with header rows where they hold data.")
    return _check(
        "a11y_tables", "Table headers", 1, "warn", f"{len(missing)} of {len(tables)} tables have no header row.",
        [HealthIssue(message="No header row: mark the first row as the header", elementIds=missing)],
    )


def _reading_order(document: Document) -> HealthCheck:
    """What floats on the page is read where it is anchored in the text, which may not be where it
    is seen: worth checking that it still reads in order."""
    floating = [
        element.id
        for element in document.elements
        if (element.type == ElementType.IMAGE and element.image and element.image.placement is not None)
        or (element.type == ElementType.TABLE and element.table and element.table.floating is not None)
    ]
    if not any(element.type in (ElementType.IMAGE, ElementType.TABLE) for element in document.elements):
        return _check("a11y_order", "Reading order", 1, "skip", "Nothing placed apart from the text.")
    if not floating:
        return _check("a11y_order", "Reading order", 1, "pass", "Everything sits in the text, read in the order it is seen.")
    return _check(
        "a11y_order", "Reading order", 1, "warn", f"{len(floating)} picture{'s or tables' if len(floating) != 1 else ' or table'} placed on the page apart from the text.",
        [HealthIssue(message="Read where it is anchored, not where it is seen", elementIds=floating)],
    )


def _language(document: Document) -> HealthCheck:
    """The document says its language (a screen reader picks its voice and pronunciation by it),
    and text in another language is marked as that language."""
    if not _text_elements(document):
        return _check("a11y_language", "Language", 1, "skip", "No text yet.")
    issues = []
    if not document.metadata.language:
        guess = document_language(document)
        reads = f" (it reads as {language_name(guess)})" if guess else ""
        issues.append(HealthIssue(message=f"The document's language isn't set{reads}: set it in the Превод panel", elementIds=[]))
    other = other_language_blocks(document) if document_language(document) else []
    if other:
        issues.append(HealthIssue(message="Text in another language, not marked as it", elementIds=[element.id for element, _ in other]))
    if not issues:
        return _check("a11y_language", "Language", 1, "pass", f"Set to {language_name(document.metadata.language)}.")
    return _check("a11y_language", "Language", 1, "warn", "The language isn't fully said.", issues)


def _rgb(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    value = value.strip()
    named = NAMED_COLORS.get(value.lower())
    if named:
        value = f"#{named}"
    match = _HEX.match(value)
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        value_ = value / 255
        return value_ / 12.92 if value_ <= 0.04045 else ((value_ + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    """WCAG's contrast ratio, 1 to 21."""
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _low_contrast(document: Document, element: Element) -> float | None:
    """The lowest contrast below WCAG AA among the element's text, else None."""
    css = document.resolvedStyles.get(element.styleRef or "", {})
    base_color = _rgb(css.get("color")) or (0, 0, 0)
    base_size = _points(css.get("font-size", "")) or 11.0
    base_bold = css.get("font-weight", "") in _BOLD_WEIGHTS
    white = (255, 255, 255)
    runs: list[tuple[InlineRun, tuple[int, int, int]]] = [(run, white) for run in [*(element.inline or []), *(run for item in element.listItems or [] for run in item.inline)]]
    if element.table:
        runs += [(run, _rgb(cell.background) or white) for row in element.table.rows for cell in row.cells for run in cell.inline]
    lowest = None
    for run, background in runs:
        if not run.text.strip() or any(mark.type == MarkType.HIDDEN for mark in run.marks):
            continue
        style: Mark | None = next((mark for mark in run.marks if mark.type == MarkType.TEXT_STYLE), None)
        color = (_rgb(style.color) if style else None) or base_color
        behind = (_rgb(style.backgroundColor) if style else None) or background
        size = (style.fontSizePt if style and style.fontSizePt else None) or base_size
        bold = base_bold or any(mark.type == MarkType.BOLD for mark in run.marks)
        needed = 3.0 if size >= 18 or (bold and size >= 14) else 4.5
        ratio = contrast_ratio(color, behind)
        if ratio < needed and (lowest is None or ratio < lowest):
            lowest = ratio
    return lowest


def _contrast(document: Document) -> HealthCheck:
    """Text stands out from what is behind it (WCAG AA: 4.5:1, 3:1 for large text)."""
    elements = [element for element in document.elements if element.content.strip()]
    if not elements:
        return _check("a11y_contrast", "Contrast", 1, "skip", "No text yet.")
    low = [(element, ratio) for element in elements if (ratio := _low_contrast(document, element)) is not None]
    if not low:
        return _check("a11y_contrast", "Contrast", 1, "pass", "Text stands out enough from what is behind it.")
    worst = min(ratio for _, ratio in low)
    return _check(
        "a11y_contrast", "Contrast", 1, "fail", f"{len(low)} block{'s' if len(low) != 1 else ''} with text too faint for its background (lowest {worst:.1f}:1).",
        [HealthIssue(message="Below WCAG AA contrast (4.5:1, or 3:1 for large text)", elementIds=[element.id for element, _ in low])],
    )


def _alt(document: Document) -> HealthCheck:
    check = _alt_text(document)
    return check.model_copy(update={"id": "a11y_alt_text", "weight": 1})


CHECKS = [_headings, _alt, _links, _table_headers, _reading_order, _language, _contrast]


def check_accessibility(document: Document) -> AccessibilityReport:
    checks = [check(document) for check in CHECKS]
    return AccessibilityReport(checks=checks, problems=sum(1 for check in checks if check.status in ("warn", "fail")))
