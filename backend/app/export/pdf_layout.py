"""A PDF of a layout-focused PDF import with each block at its place (tracker P2E-021, brief §42;
docs/architecture/layout-preserving.md): every page of the PDF a page of its own size, every
block drawn in its frame (app/formatting/frames.py) -- its box on its page, turned as its text
was -- rather than flowed down the pages.

A block's look is the export's usual (export/pdf_export.py builds it); only where it goes is the
frame's. Its fonts may set it a little wider than the PDF's own did, so a block gets some room
past its box's right edge (never past the page's); what is taller than its box runs on below it.
A block with no frame -- one added in the editor -- goes under the block before it, onto a page
of its own after that one when the page is full. The page's own text (numbers, running heads) is
in its blocks, so nothing is added to the pages."""

from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import dataclass, field

from reportlab.pdfgen.canvas import Canvas

from app.formatting.frames import frame_of
from app.formatting.list_numbering import heading_labels
from app.models.document import Document, Element, ElementType

# How much wider than its box a block may be set (its fonts may run wider than the PDF's), and the
# most of that in points.
_ROOM_SHARE = 0.25
_ROOM_MAX_PT = 72.0
_PAGE_EDGE_PT = 18.0  # never closer than this to the page's right edge
_GAP_PT = 6.0  # between a block with no frame and the one above it
_MARGIN_PT = 72.0  # where blocks with no frame start on a page of their own


@dataclass
class _Placed:
    element: Element
    x: float
    y: float  # from the page's top
    width: float  # the line length: across for 0/180, down or up the page for 90/270
    height: float
    rotation: int = 0


@dataclass
class _Page:
    width: float
    height: float
    placed: list[_Placed] = field(default_factory=list)


def is_layout_document(document: Document) -> bool:
    """A layout-focused PDF import whose blocks have frames to draw them at."""
    conversion = document.pdfConversion
    return conversion is not None and conversion.mode == "layout" and any(frame_of(document, element) for element in document.elements)


def _page_sizes(document: Document) -> dict[int, tuple[float, float]]:
    inspection = document.pdfInspection
    return {page.number: (page.width, page.height) for page in (inspection.pages if inspection else [])}


def _pages(document: Document) -> list[_Page]:
    """The pages and what goes where on each, in order."""
    sizes = _page_sizes(document)
    default = next(iter(sizes.values()), (595.28, 841.89))
    pages: dict[tuple[int, int], _Page] = {}
    current: tuple[int, int] = (1, 0)
    below: tuple[float, float, float] | None = None  # under the last block: (x, y, width)

    def page(key: tuple[int, int]) -> _Page:
        if key not in pages:
            width, height = sizes.get(key[0], default)
            pages[key] = _Page(width, height)
        return pages[key]

    for element in document.elements:
        if element.type in (ElementType.PAGE_BREAK, ElementType.SECTION_BREAK):
            continue  # the pages are the PDF's
        frame = frame_of(document, element)
        if frame is not None and frame.source == "pdf-layout" and frame.page:
            current = (frame.page, 0)
            target = page(current)
            rotation = int(frame.rotation) % 360
            across = rotation in (0, 180)
            box_width = (frame.widthPt or 0) if across else (frame.heightPt or 0)
            box_height = (frame.heightPt or 0) if across else (frame.widthPt or 0)
            x, y = frame.horizontal.offsetPt or 0, frame.vertical.offsetPt or 0
            room = target.width - x - _PAGE_EDGE_PT if rotation == 0 else box_width
            width = max(1.0, min(box_width + min(box_width * _ROOM_SHARE, _ROOM_MAX_PT), room)) if rotation == 0 else max(1.0, box_width)
            target.placed.append(_Placed(element, x, y, width, box_height, rotation))
            below = (x, y + (frame.heightPt or 0), max(box_width, 1.0)) if rotation == 0 else None
            continue
        # No frame of its own (added here): under the block before it, or on a page of its own.
        target = page(current)
        if below is None:
            below = (_MARGIN_PT, _MARGIN_PT, target.width - 2 * _MARGIN_PT)
        x, y, width = below
        target.placed.append(_Placed(element, x, y + _GAP_PT, width, 0))  # its place down the page: _with_overflow's
        below = (x, y, width)  # the next one at its left edge too
    return [pages[key] for key in sorted(pages)]


def _draw_block(canvas: Canvas, placed: _Placed, page_height: float, document: Document, assets: Mapping[str, bytes]) -> None:
    """Draws one block in its place."""
    from app.export.pdf_export import _build_flowables

    flowables = _build_flowables(placed.element, document, assets, width=placed.width, in_cell=True)
    canvas.saveState()
    # Where the block's top left corner is, and which way its lines run (ReportLab turns anticlockwise).
    if placed.rotation == 90:
        canvas.translate(placed.x + placed.height, page_height - placed.y)
        canvas.rotate(-90)
    elif placed.rotation == 270:
        canvas.translate(placed.x, page_height - placed.y - placed.width)
        canvas.rotate(90)
    elif placed.rotation == 180:
        canvas.translate(placed.x + placed.width, page_height - placed.y - placed.height)
        canvas.rotate(180)
    else:
        canvas.translate(placed.x, page_height - placed.y)
    down = 0.0
    for index, flowable in enumerate(flowables):
        if index:
            down += flowable.getSpaceBefore()
        _, height = flowable.wrap(placed.width, 100_000)
        flowable.drawOn(canvas, 0, -down - height)
        down += height + (flowable.getSpaceAfter() if index < len(flowables) - 1 else 0)
    canvas.restoreState()


def build_layout_pdf(document: Document, assets: Mapping[str, bytes]) -> bytes:
    """Every page of the PDF with its blocks at their places (see the module's note)."""
    from app.export.pdf_export import _HEADING_LABELS

    headings = [(element.id, element.level or 1, element.numbered is not False) for element in document.elements if element.type == ElementType.HEADING]
    labels = _HEADING_LABELS.set(heading_labels(headings, document.headingNumbering))
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(595.28, 841.89))
    canvas.setTitle(document.metadata.title)
    try:
        pages = _pages(document) or [_Page(595.28, 841.89)]
        for page in _with_overflow(pages, document, assets):
            canvas.setPageSize((page.width, page.height))
            for placed in page.placed:
                _draw_block(canvas, placed, page.height, document, assets)
            canvas.showPage()
        canvas.save()
    finally:
        _HEADING_LABELS.reset(labels)
    return buffer.getvalue()


def _with_overflow(pages: list[_Page], document: Document, assets: Mapping[str, bytes]) -> list[_Page]:
    """The pages, a block with no frame that would run off its page's bottom moved -- with those
    after it on that page -- onto a page of its own after it, at its top margin."""
    from app.export.pdf_export import _build_flowables

    out: list[_Page] = []
    for page in pages:
        current = page
        out.append(current)
        reached = 0.0
        kept: list[_Placed] = []
        moved: list[_Placed] = []
        for placed in page.placed:
            if moved:
                moved.append(placed)
                continue
            height = placed.height
            if height == 0 and placed.rotation == 0:
                height = sum(flowable.wrap(placed.width, 100_000)[1] for flowable in _build_flowables(placed.element, document, assets, width=placed.width, in_cell=True))
                top = max(placed.y, reached + _GAP_PT) if reached else placed.y
                if top + height > page.height - _MARGIN_PT / 2 and top > _MARGIN_PT:
                    placed.y = _MARGIN_PT
                    moved.append(placed)
                    continue
                placed.y = top  # under what is above it
                reached = top + height
            elif placed.rotation == 0:
                reached = placed.y + height
            kept.append(placed)
        current.placed = kept
        while moved:
            extra = _Page(page.width, page.height)
            out.append(extra)
            y = _MARGIN_PT
            rest: list[_Placed] = []
            for placed in moved:
                if rest:
                    rest.append(placed)
                    continue
                height = sum(flowable.wrap(placed.width, 100_000)[1] for flowable in _build_flowables(placed.element, document, assets, width=placed.width, in_cell=True))
                if y + height > page.height - _MARGIN_PT / 2 and y > _MARGIN_PT:
                    rest.append(placed)
                    continue
                placed.y = y
                extra.placed.append(placed)
                y += height + _GAP_PT
            moved = rest
            for placed in moved:
                placed.y = _MARGIN_PT
    return out


__all__ = ["build_layout_pdf", "is_layout_document"]
