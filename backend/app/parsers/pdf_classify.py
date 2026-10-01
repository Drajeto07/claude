"""What kind of page each PDF page is (tracker PDF-011), from what the geometry read
(parsers/pdf_geometry.py) found on it, with the evidence:

  text     its words are drawn as text, to be read as they are;
  scanned  a picture with no text over it: its words, if any, are only in the picture
           (OCR would be needed to read them);
  hybrid   text over a picture covering most of the page -- typically a scan under the
           invisible text layer OCR software writes, whose words may hold OCR's mistakes;
  empty    no text and no picture: blank, or only drawn lines and shapes.

The evidence: how much of the page text and pictures cover, the characters drawn
visibly and invisibly (text render mode 3, or 7), and the fonts."""

import math
from dataclasses import dataclass

from app.parsers.pdf_geometry import Box, PdfPage

TEXT, SCANNED, HYBRID, EMPTY = "text", "scanned", "hybrid", "empty"
# A picture covering this share of the page or more is taken for a scan of it.
PAGE_PICTURE = 0.5
# Coverage is measured on a grid of this many cells a side: a cell counts as covered
# when its centre is inside a box.
GRID = 100


@dataclass(frozen=True, slots=True)
class PageEvidence:
    text_coverage: float  # 0..1 of the page under visible characters
    image_coverage: float  # 0..1 of the page under pictures
    visible_chars: int  # characters other than spaces, drawn visibly
    invisible_chars: int  # characters other than spaces, drawn invisibly
    fonts: tuple[str, ...]  # of the characters, without a subset's prefix
    images: int
    paths: int  # lines, rectangles and curves


@dataclass(frozen=True, slots=True)
class PageKind:
    kind: str
    confidence: float  # how sure the verdict is, 0..1
    reason: str
    evidence: PageEvidence


def font_name(name: str) -> str:
    """A font's name without the six-letter tag a subset carries ("ABCDEF+DejaVuSans")."""
    tag, plus, rest = name.partition("+")
    return rest if plus and len(tag) == 6 and tag.isalpha() and tag.isupper() else name


def coverage(boxes: list[Box], width: float, height: float) -> float:
    """The share of the page the boxes cover together (overlaps counted once), on a GRID x GRID raster."""
    if width <= 0 or height <= 0 or not boxes:
        return 0.0
    cell_width, cell_height = width / GRID, height / GRID
    covered = bytearray(GRID * GRID)
    for x0, top, x1, bottom in boxes:
        # The cells whose centre ((i + 0.5) * size) lies inside the box.
        first_column, last_column = max(math.ceil(x0 / cell_width - 0.5), 0), min(math.floor(x1 / cell_width - 0.5), GRID - 1)
        first_row, last_row = max(math.ceil(top / cell_height - 0.5), 0), min(math.floor(bottom / cell_height - 0.5), GRID - 1)
        if first_column > last_column:
            continue
        span = last_column - first_column + 1
        for row in range(first_row, last_row + 1):
            start = row * GRID + first_column
            covered[start : start + span] = b"\x01" * span
    return round(sum(covered) / (GRID * GRID), 4)


def _percent(share: float) -> str:
    return f"{round(share * 100)}%"


def classify_page(page: PdfPage) -> PageKind:
    visible = [char for char in page.chars if not char.invisible and char.text.strip()]
    invisible = sum(1 for char in page.chars if char.invisible and char.text.strip())
    evidence = PageEvidence(
        text_coverage=coverage([char.box for char in visible], page.width, page.height),
        image_coverage=coverage([image.box for image in page.images], page.width, page.height),
        visible_chars=len(visible),
        invisible_chars=invisible,
        fonts=tuple(sorted({font_name(char.font) for char in page.chars if char.text.strip()})),
        images=len(page.images),
        paths=len(page.lines) + len(page.rects) + len(page.curves),
    )
    pictures = evidence.image_coverage
    if not visible and not invisible:
        if not page.images:
            return PageKind(EMPTY, 1.0, "No text and no pictures on this page.", evidence)
        if pictures >= PAGE_PICTURE:
            return PageKind(SCANNED, 0.9, f"A picture covers {_percent(pictures)} of the page and there is no text: a scan.", evidence)
        return PageKind(
            SCANNED, 0.6, f"No text, only pictures covering {_percent(pictures)} of the page: any words are in the pictures.", evidence
        )
    if pictures >= PAGE_PICTURE:
        if invisible >= len(visible):
            return PageKind(
                HYBRID, 0.95, f"Invisible text over a picture covering {_percent(pictures)} of the page: a scan with a text layer.", evidence
            )
        return PageKind(
            HYBRID,
            0.6,
            f"Text over a picture covering {_percent(pictures)} of the page: a scan with text added, or text on a background picture.",
            evidence,
        )
    if invisible > len(visible):
        return PageKind(TEXT, 0.7, "Text, most of it drawn invisibly, with no page-sized picture under it.", evidence)
    return PageKind(TEXT, 1.0, "The page's words are drawn as text.", evidence)


def document_kind(kinds: list[str]) -> str | None:
    """The file's kind from its pages': one kind throughout is that kind (empty pages
    aside); text and scanned pages together are hybrid. None when no page was read."""
    if not kinds:
        return None
    found = set(kinds) - {EMPTY}
    if not found:
        return EMPTY
    return found.pop() if len(found) == 1 else HYBRID
