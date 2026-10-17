"""Document Health fixes (tracker HLTH-002): what the checks find that can be put right
deterministically, as proposals to review -- each a ProposedChange (source "health") with the
block as it would be, applied only when the user accepts it, and only to the block as it was
when the fix was worked out (its fingerprint). No AI is involved: an AI may explain an issue,
never fix or score it.

One proposal per block and check: everything a check would change in a block goes together.
Pictures without alt text and hidden text have no fix -- only a person can say what a picture
shows, and removing hidden text is a clean copy's job (REV-005)."""

import hashlib
import re
from collections.abc import Callable, Iterator

from app.formatting import health
from app.models.document import ChangeCategory, Document, Element, ElementType, InlineRun, ListNumbering, Mark, MarkType, ProposedChange, child_blocks, plain_text_from_inline

_PREVIEW = 2000
_TYPED_NUMBER = re.compile(r"^\s*\d+[.)]\s+")
_STYLE_FIELDS = ("fontFamily", "fontSizePt", "color", "backgroundColor", "caps", "smallCaps", "letterSpacingPt", "baselineShiftPt", "lang")


def element_fingerprint(element: Element) -> str:
    """The block as it is -- what a fix was worked out for. Where the engine puts it (order) and
    the style key it derives (styleRef) don't count."""
    return hashlib.sha256(element.model_dump_json(exclude={"order", "styleRef"}).encode("utf-8")).hexdigest()


def _proposal(element: Element, check_id: str, category: ChangeCategory, reason: str, *, replacement: Element | None = None, kind: str) -> ProposedChange:
    return ProposedChange(
        type="replace_content" if replacement is not None else "delete_element",
        category=category,
        elementId=element.id,
        property=kind,
        before=element.content[:_PREVIEW],
        after=replacement.content[:10_000] if replacement is not None else None,
        reason=reason[:500],
        source="health",
        checkId=check_id,
        elementHash=element_fingerprint(element),
        replacement=replacement,
    )


def _all_runs(element: Element) -> Iterator[InlineRun]:
    """Every run in the block, its nested blocks' too (on a copy, to change them in place)."""
    yield from element.inline or []
    for item in element.listItems or []:
        yield from item.inline
    if element.table:
        for row in element.table.rows:
            for cell in row.cells:
                yield from cell.inline
    for child in child_blocks(element):
        yield from _all_runs(child)


def _empty_style(mark: Mark) -> bool:
    return mark.type == MarkType.TEXT_STYLE and all(getattr(mark, name) is None for name in _STYLE_FIELDS)


def _refresh(element: Element) -> Element:
    """The block's plain text again, after its runs or items changed."""
    if element.listItems is not None:
        element.content = "\n".join(plain_text_from_inline(item.inline) for item in element.listItems)
    elif element.inline is not None:
        element.content = plain_text_from_inline(element.inline)
    return element


def _short(text: str, limit: int = 50) -> str:
    text = " ".join(text.split())
    return f"“{text[:limit]}…”" if len(text) > limit else f"“{text}”"


# --- the fixes, check by check ---------------------------------------------------------------------


def _empty_paragraphs(document: Document) -> list[ProposedChange]:
    return [
        _proposal(element, "empty_paragraphs", ChangeCategory.STRUCTURE, "Delete an empty paragraph (space paragraphs with spacing instead)", kind="delete")
        for element in health.empty_paragraphs(document)
    ]


def _page_breaks(document: Document) -> list[ProposedChange]:
    ids = [element_id for issue in health.page_break_check(document).issues for element_id in issue.elementIds]
    elements = {element.id: element for element in document.elements}
    return [
        _proposal(elements[element_id], "page_breaks", ChangeCategory.STRUCTURE, "Delete a page break with nothing before, after or between it and the next", kind="delete")
        for element_id in dict.fromkeys(ids)
        if element_id in elements
    ]


def _hierarchy(document: Document) -> list[ProposedChange]:
    """Each heading at most one level below the heading before it, as that one would be after
    its own fix."""
    found = []
    previous = 0
    for element in document.elements:
        if element.type != ElementType.HEADING:
            continue
        level = element.level or 1
        if previous and level > previous + 1:
            fixed = previous + 1
            replacement = element.model_copy(deep=True, update={"level": fixed})
            found.append(_proposal(element, "hierarchy", ChangeCategory.STRUCTURE, f"Heading {level} → Heading {fixed}: levels go down one at a time {_short(element.content)}", replacement=replacement, kind="level"))
            level = fixed
        previous = level
    return found


def _strip_typed_number(runs: list[InlineRun]) -> bool:
    text = "".join(run.text for run in runs)
    match = _TYPED_NUMBER.match(text)
    if not match:
        return False
    left = match.end()
    for run in runs:
        cut = min(left, len(run.text))
        run.text, left = run.text[cut:], left - cut
    runs[:] = [run for run in runs if run.text] or runs[:1]
    return True


def _numbering(document: Document) -> list[ProposedChange]:
    found = []
    for element in document.elements:
        if element.type != ElementType.LIST or not element.ordered or not element.listItems:
            continue
        replacement = element.model_copy(deep=True)
        changed = [_strip_typed_number(item.inline) for item in replacement.listItems or []]
        if any(changed):
            found.append(_proposal(element, "numbering", ChangeCategory.CONTENT, f"Remove the numbers typed at the start of {sum(changed)} numbered item{'s' if sum(changed) != 1 else ''} (the list numbers them)", replacement=_refresh(replacement), kind="typed_numbers"))
    return found


def _links(document: Document) -> list[ProposedChange]:
    found = []
    for element in document.elements:
        replacement = element.model_copy(deep=True)
        removed = 0
        for run in _all_runs(replacement):
            kept = [mark for mark in run.marks if not (mark.type == MarkType.LINK and not health._usable_link(mark.href))]
            removed += len(run.marks) - len(kept)
            run.marks = kept
        if removed:
            found.append(_proposal(element, "links", ChangeCategory.CONTENT, f"Unlink {removed} link{'s' if removed != 1 else ''} without a usable address (the text stays)", replacement=replacement, kind="unlink"))
    return found


def _fonts(document: Document) -> list[ProposedChange]:
    """Fonts set on pieces of text other than the body's main font, cleared: the text then
    takes its style's font."""
    by_font = health.body_fonts(document)
    if len(by_font) <= 1:
        return []
    main = max(by_font, key=lambda font: len(by_font[font]))
    found = []
    for element in document.elements:
        if element.id not in {element_id for font, ids in by_font.items() if font != main for element_id in ids}:
            continue
        replacement = element.model_copy(deep=True)
        cleared = set()
        for run in replacement.inline or []:
            marks = []
            for mark in run.marks:
                if mark.type == MarkType.TEXT_STYLE and mark.fontFamily and mark.fontFamily.strip() != main:
                    cleared.add(mark.fontFamily.strip())
                    mark = mark.model_copy(update={"fontFamily": None})
                if not _empty_style(mark):
                    marks.append(mark)
            run.marks = marks
        if cleared:
            found.append(_proposal(element, "fonts", ChangeCategory.FORMAT, f"Set text in {', '.join(sorted(cleared))} back to the style's font {_short(element.content)}", replacement=replacement, kind="font"))
    return found


def _language(document: Document) -> list[ProposedChange]:
    from app.translation.language import language_name

    found = []
    for element, language in health.other_language_blocks(document):
        replacement = element.model_copy(deep=True)
        for run in _all_runs(replacement):
            if not run.text.strip():
                continue
            style = next((mark for mark in run.marks if mark.type == MarkType.TEXT_STYLE), None)
            if style is None:
                run.marks = [*run.marks, Mark(type=MarkType.TEXT_STYLE, lang=language)]
            else:
                run.marks = [mark.model_copy(update={"lang": language}) if mark is style else mark for mark in run.marks]
        found.append(_proposal(element, "language", ChangeCategory.METADATA, f"Mark as {language_name(language)} {_short(element.content)}", replacement=replacement, kind="lang"))
    return found


def _sections(document: Document) -> list[ProposedChange]:
    """A section break's margins set to the ones most sections have (the last section's are the
    document's page settings: not a block, so not fixed here)."""
    found = []
    for setup, usual in health.odd_sections(document):
        if setup.element is None or setup.element.sectionBreak is None:
            continue
        top, right, bottom, left = usual
        own = setup.element.sectionBreak.model_copy(update={"marginTopCm": top, "marginRightCm": right, "marginBottomCm": bottom, "marginLeftCm": left})
        replacement = setup.element.model_copy(deep=True, update={"sectionBreak": own})
        margins = ", ".join(f"{value:g}" for value in usual)
        found.append(_proposal(setup.element, "sections", ChangeCategory.FORMAT, f"Give a section the margins the others have ({margins} cm)", replacement=replacement, kind="margins"))
    return found


def _lists(document: Document) -> list[ProposedChange]:
    restarted = {element.id: previous for element, previous in health.restarted_lists(document)}
    found = []
    for element in document.elements:
        if element.type != ElementType.LIST:
            continue
        empty, skipped = health.empty_list_items(element), health.skipped_list_levels(element)
        if not (empty or skipped or element.id in restarted):
            continue
        if empty and len(empty) == len(element.listItems or []):
            found.append(_proposal(element, "lists", ChangeCategory.STRUCTURE, "Delete a list with nothing in it", kind="delete"))
            continue
        replacement = element.model_copy(deep=True)
        done = []
        if empty:
            replacement.listItems = [item for index, item in enumerate(replacement.listItems or []) if index not in set(empty)]
            done.append(f"remove {len(empty)} empty item{'s' if len(empty) != 1 else ''}")
        items = replacement.listItems or []
        if health.skipped_list_levels(replacement):
            for index, item in enumerate(items):
                item.level = min(item.level, items[index - 1].level + 1 if index else 0)
            done.append("nest items one level at a time")
        if element.id in restarted:
            previous = restarted[element.id]
            top = min((item.level for item in previous.listItems or []), default=0)
            start = (previous.numbering.start if previous.numbering else 1) + sum(1 for item in previous.listItems or [] if item.level == top)
            replacement.numbering = (replacement.numbering or ListNumbering()).model_copy(update={"start": start})
            done.append(f"continue the numbering from the list before (from {start})")
        reason = "Lists: " + ", ".join(done)
        found.append(_proposal(element, "lists", ChangeCategory.STRUCTURE, f"{reason} {_short(element.content)}", replacement=_refresh(replacement), kind="list"))
    return found


def _layout(document: Document) -> list[ProposedChange]:
    found = []
    for element, width in health.too_wide(document):
        replacement = element.model_copy(deep=True)
        if replacement.image is not None and replacement.image.widthCm:
            scale = width / replacement.image.widthCm
            replacement.image.widthCm = width
            if replacement.image.heightCm:
                replacement.image.heightCm = round(replacement.image.heightCm * scale, 2)
            what = "picture"
        elif replacement.table is not None and replacement.table.widthCm:
            scale = width / replacement.table.widthCm
            replacement.table.widthCm = width
            if replacement.table.columnWidthsCm:
                replacement.table.columnWidthsCm = [round(column * scale, 2) for column in replacement.table.columnWidthsCm]
            what = "table"
        else:
            continue
        found.append(_proposal(element, "layout", ChangeCategory.FORMAT, f"Shrink a {what} to the page's text width ({width:g} cm)", replacement=replacement, kind="width"))
    return found


def _repeated(document: Document) -> list[ProposedChange]:
    """Formatting the text repeats from its style, cleared: the text then follows the style."""
    found = []
    for element in document.elements:
        if not element.inline:
            continue
        what = health.repeated_formatting(document, element)
        if not what:
            continue
        css = document.resolvedStyles.get(element.styleRef or "", {})
        style_font = css.get("font-family", "").split(",")[0].strip().strip("'\"").lower()
        style_size = health._points(css.get("font-size", ""))
        style_color = css.get("color", "").lower()
        replacement = element.model_copy(deep=True)
        for run in replacement.inline or []:
            marks = []
            for mark in run.marks:
                if mark.type == MarkType.BOLD and "bold" in what:
                    continue
                if mark.type == MarkType.TEXT_STYLE:
                    update = {}
                    if mark.fontFamily and mark.fontFamily.strip().lower() == style_font:
                        update["fontFamily"] = None
                    if mark.fontSizePt and style_size and abs(mark.fontSizePt - style_size) < 0.01:
                        update["fontSizePt"] = None
                    if mark.color and mark.color.lower() == style_color:
                        update["color"] = None
                    mark = mark.model_copy(update=update)
                    if _empty_style(mark):
                        continue
                marks.append(mark)
            run.marks = marks
        found.append(_proposal(element, "duplicated_formatting", ChangeCategory.FORMAT, f"Clear the {', '.join(what)} the style already gives {_short(element.content)}", replacement=replacement, kind="repeated"))
    return found


def _broken_tables(document: Document) -> list[ProposedChange]:
    """Each broken top-level table put right (REV-004): short rows filled, spans ended, empty rows gone."""
    from app.formatting.table_repair import describe, repaired, table_problems

    found = []
    for element in document.elements:
        replacement = repaired(element)
        if replacement is not None:
            what = ", ".join(describe(table_problems(element.table)))
            found.append(_proposal(element, "broken_tables", ChangeCategory.STRUCTURE, f"Repair a table: {what}", replacement=replacement, kind="table"))
    return found


FIXERS: dict[str, Callable[[Document], list[ProposedChange]]] = {
    "empty_paragraphs": _empty_paragraphs,
    "page_breaks": _page_breaks,
    "hierarchy": _hierarchy,
    "numbering": _numbering,
    "links": _links,
    "fonts": _fonts,
    "language": _language,
    "sections": _sections,
    "lists": _lists,
    "layout": _layout,
    "duplicated_formatting": _repeated,
    "broken_tables": _broken_tables,
}


def _waiting(document: Document) -> set[tuple[str | None, str | None]]:
    return {(proposal.checkId, proposal.elementId) for proposal in document.proposals if proposal.source == "health"}


def fixes(document: Document, check_ids: list[str] | None = None) -> list[ProposedChange]:
    """The fixes for the given checks (all, when None) not already waiting for review, among
    the checks that found something (a check that passes proposes nothing)."""
    report = {check.id: check.status for check in (fn(document) for fn in health.CHECKS)}
    wanted = [check_id for check_id in (check_ids if check_ids is not None else list(FIXERS)) if check_id in FIXERS and report.get(check_id) in ("warn", "fail")]
    waiting = _waiting(document)
    return [proposal for check_id in wanted for proposal in FIXERS[check_id](document) if (proposal.checkId, proposal.elementId) not in waiting]


def fix_counts(document: Document, check_ids: list[str]) -> dict[str, int]:
    """How many fixes each of these checks could propose now."""
    waiting = _waiting(document)
    counts = {}
    for check_id in check_ids:
        if check_id in FIXERS:
            counts[check_id] = sum(1 for proposal in FIXERS[check_id](document) if (proposal.checkId, proposal.elementId) not in waiting)
    return counts
