"""Frames: where a block is meant to sit on its page when it isn't simply in the flow of the
text (tracker P2E-020, brief §42; docs/architecture/layout-preserving.md). The hook the
layout-preserving work builds on -- one question every renderer can ask of any block, from what
the model already holds, so no coordinates are added to the semantic document:

- a floating picture or text box from Word: its anchor (ImagePlacement) -- what its position is
  measured from, across and down, the offset or the named place, its size and how text wraps;
- a block of a PDF imported layout-focused (PdfConversion.mode "layout", P2E-007): its box on
  its page (ElementLayout), in points from the page's top left corner.

Everything else -- in line, or a PDF imported as an editable document, whose boxes say only
where the text came from -- has none: it is laid out in the flow. Nothing here draws a frame
yet; the editor and both exports keep drawing these blocks as they do (a floating picture or
text box beside the text, P2E blocks in the flow), and a renderer that honours frames asks
`frame_of` instead of each source's own fields.
"""

from typing import Literal, Optional

from pydantic import Field

from app.models.base import ApiModel
from app.models.document import Document, Element, ElementType, ImagePlacement

PT_PER_CM = 72 / 2.54

# What a frame's position is measured from: Word's anchors (wp:positionH/V relativeFrom), and a
# PDF page's top left corner.
RelativeTo = Literal[
    "page", "margin", "column", "character", "paragraph", "line",
    "leftMargin", "rightMargin", "topMargin", "bottomMargin", "insideMargin", "outsideMargin",
]  # fmt: skip


class FramePosition(ApiModel):
    """Along one direction: from what, and how far (points) or to which named place."""

    relativeTo: RelativeTo
    offsetPt: Optional[float] = None
    align: Optional[Literal["left", "center", "right", "top", "bottom", "inside", "outside"]] = None


class Frame(ApiModel):
    source: Literal["docx-anchor", "pdf-layout"]
    # The page it is on, for a frame placed on a page of its own (a PDF's); None: the page its
    # anchor paragraph falls on.
    page: Optional[int] = Field(default=None, ge=1)
    horizontal: FramePosition
    vertical: FramePosition
    widthPt: Optional[float] = Field(default=None, ge=0)
    heightPt: Optional[float] = Field(default=None, ge=0)
    rotation: float = 0
    # How the text around it goes: beside it (square, tight, through), above and below it, or
    # not at all -- it lies behind or in front of the text, or on a page of its own (none).
    wrap: Literal["square", "tight", "through", "topAndBottom", "behind", "inFront", "none"]
    # How far the text keeps from it, points: top, right, bottom, left.
    distancePt: tuple[float, float, float, float] = (0, 0, 0, 0)


def _pt(cm: float | None) -> float | None:
    return None if cm is None else round(cm * PT_PER_CM, 2)


def _anchored(placement: ImagePlacement, width_cm: float | None, height_cm: float | None, rotation: float | None) -> Frame:
    return Frame(
        source="docx-anchor",
        horizontal=FramePosition(relativeTo=placement.horizontalFrom, offsetPt=_pt(placement.horizontalCm), align=placement.horizontalAlign),
        vertical=FramePosition(relativeTo=placement.verticalFrom, offsetPt=_pt(placement.verticalCm), align=placement.verticalAlign),
        widthPt=_pt(width_cm),
        heightPt=_pt(height_cm),
        rotation=rotation or 0,
        wrap=placement.wrap,
        distancePt=tuple(_pt(value) or 0 for value in (placement.distanceTopCm, placement.distanceRightCm, placement.distanceBottomCm, placement.distanceLeftCm)),
    )


def frame_of(document: Document, element: Element) -> Frame | None:
    """Where the block is meant to sit when it isn't in the flow of the text; None when it is."""
    if element.type == ElementType.IMAGE and element.image and element.image.placement:
        image = element.image
        return _anchored(image.placement, image.widthCm, image.heightCm, image.rotation)
    if element.type == ElementType.TEXT_BOX and element.textBox and element.textBox.placement:
        box = element.textBox
        return _anchored(box.placement, box.widthCm, box.heightCm, None)
    conversion = document.pdfConversion
    if element.layout is not None and conversion is not None and conversion.mode == "layout":
        layout = element.layout
        return Frame(
            source="pdf-layout",
            page=layout.page,
            horizontal=FramePosition(relativeTo="page", offsetPt=round(layout.x, 2)),
            vertical=FramePosition(relativeTo="page", offsetPt=round(layout.y, 2)),
            widthPt=round(layout.width, 2),
            heightPt=round(layout.height, 2),
            rotation=layout.rotation,
            wrap="none",
        )
    return None


def frames(document: Document) -> dict[str, Frame]:
    """Every top-level block's frame that has one, by its id."""
    return {element.id: frame for element in document.elements if (frame := frame_of(document, element)) is not None}
