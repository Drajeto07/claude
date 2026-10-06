"""A PDF as an editable document (tracker P2E-002): its structure rebuilt from where things
are on its pages (the geometry read, parsers/pdf_geometry.py) -- deterministically, no AI.

Page by page, as the geometry read hands each page over (so a long file's characters are
never all held at once), its characters become lines (`page_lines`):

  * characters on one baseline make a row, split into pieces where a gap is wider than
    words leave; text turned on the page is read in its own direction;
  * the pieces are put in reading order by cutting the page at its widest gaps (an XY
    cut): across, at the gap between a title and what follows, and down a gutter only
    when the text on both sides of it is column-like -- side by side, and wider than a
    table's cells -- so columns are read one after the other and a ruled table row by row;
  * the pieces of each part of the page left uncut are lines again, each with its runs of
    text (bold, italic, colour, the web link it is under).

Then the document (`build_pdf_document`), from all the pages' lines:

  * lines repeated at the top or the bottom of most pages are running headers, footers
    or page numbers: they become the document's header, footer and page numbering, and
    the report says so;
  * lines become paragraphs where the gap after a line is wider than the lines inside a
    paragraph leave, at a first-line indent, after a short line ending a sentence, at a
    change of size or weight -- and a paragraph continues into the next column or page
    when its last line doesn't end a sentence and the next starts in lower case;
  * a short block set larger than the body text is a heading, levelled by size (a bold
    line at body size, the level below those); a line starting with a bullet or a number
    is a list item, levelled by its indent, and items in a row make a list (numbers that
    don't count on from each other stay as text); "Figure 1", "Table 2"... or a short
    line under a picture is a caption;
  * a table drawn with ruling lines (parsers/pdf_tables.py, P2E-004) takes the text in its
    cells -- merged cells and a shaded or bold header row included -- and goes in where it
    stood, as the pictures do; rows set apart only by space stay a paragraph a row (reported);
  * the pictures go in where they stood -- before the first block below them on their
    page (P2E-003) -- decoded by parsers/pdf_pictures.py; a picture repeated in the header
    or footer of most pages (a logo), the scan under a text layer, and one too small to be
    more than a rule or a dot aren't put in, and the report says so.

Every block gets its layout (models/document.py ElementLayout: page, box, rotation,
column, lines, how its words were read) and a confidence for what it was made into. No
word is dropped: the import report compares the lines' words with the document's, with
only the list markers made into list numbering and the running headers and footers moved
into the document's taken out (both reported)."""

import base64
import math
import re
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.fidelity.content import words
from app.fidelity.report import FidelityItem, FidelityPolicy
from app.models.base import NOT_XML, xml_text
from app.models.document import (
    Document,
    DocumentMetadata,
    DocumentSettings,
    Element,
    ElementLayout,
    ElementType,
    ImageContent,
    InlineRun,
    ListItem,
    ListNumbering,
    Mark,
    MarkType,
    Section,
    TableCell,
    TableContent,
    TableRow,
    inline_runs,
    plain_text_from_inline,
)
from app.parsers.pdf_classify import HYBRID, font_name
from app.parsers.pdf_geometry import Box, PdfPage
from app.parsers.pdf_pictures import Picture, PictureRef
from app.parsers.pdf_tables import Grid, GridCell, find_grids

# --- tuning: in ems of the text's size unless said otherwise -----------------------------------

# A gap between two characters wider than this is a space (when no space is drawn there).
SPACE_GAP = 0.18
# A gap in a row wider than this splits it into pieces (a gutter, a table's cells, a tab).
PIECE_GAP = 1.2
# A gutter between columns is at least this wide (and at least GUTTER_MIN points).
GUTTER_GAP = 1.5
GUTTER_MIN = 9.0
# Text on each side of a gutter must be this wide (a share of the page) to be a column.
COLUMN_WIDTH = 0.12
# A page part is cut this many times at most, one inside another.
MAX_CUT_DEPTH = 200
# A gap between lines this much wider than the lines inside paragraphs leave starts a new one.
PARAGRAPH_GAP = 0.45
# A line starting this much further in than its paragraph starts a new one.
INDENT = 0.8
# A line ending this far short of its column's right edge, after a sentence, ends its paragraph.
SHORT_LINE = 3.0
# Sizes this close are one size.
SAME_SIZE = 0.6
# A heading: set this much larger than the body text...
HEADING_RATIO = 1.15
# ...in at most this many lines and characters.
HEADING_LINES, HEADING_CHARS = 3, 200
# A bold line at body size is a heading when it has at most this many words.
BOLD_HEADING_WORDS = 12
# A caption under a picture starts at most this far below it.
CAPTION_GAP = 2.5
# Running headers and footers: in this share of the page at its top or bottom, on at
# least this share of the pages with text (and on two at least).
BAND = 0.12
BAND_PAGES = 0.5
# A picture narrower or lower than this (points) is a rule or a dot, not a picture.
TINY_PICTURE = 4.0
# A picture covering this share of a hybrid page is the scan under its text layer.
SCAN_PICTURE = 0.5
_CM = 2.54 / 72

# How sure the reconstruction is of what it made of a block (Element.confidence).
SURE, LIKELY, GUESS = 0.9, 0.75, 0.55

_BOLD = re.compile(r"bold|black|heavy|semibold|demi", re.I)
_ITALIC = re.compile(r"italic|oblique", re.I)
_SENTENCE_END = re.compile(r"[.!?:;…]['\"”’)\]]*$")
_LOWER_START = re.compile(r"^[a-zа-яёα-ω(]")
# A bullet: a bullet character, a dash, an asterisk, a symbol font's private-use glyph,
# or a glyph the file gives no text for (what a bullet from a symbol font often is).
_BULLET = re.compile(r"^([\u2022\u25e6\u25aa\u25ab\u25cf\u25cb\u25a0\u25a1\u25ba\u25b8\u2023\u2043\u2219\u00b7\u2013\u2014*\-\uf000-\uf0ff\ufffd])\s+(?=\S)")
UNREADABLE = "\ufffd"
_NUMBERED = re.compile(r"^\(?(\d{1,3}|[a-zA-Z]|[а-яА-Я])([.)])\s+(?=\S)")
_CAPTION = re.compile(r"^(figure|fig\.|table|chart|image|picture|фигура|фиг\.|таблица|графика|изображение|σχήμα|πίνακας)\s*\d+", re.I)
_PAGE_NUMBER = re.compile(r"^\W*((page|p\.|стр\.?|страница|σελίδα)\s*)?#(\s*(of|from|/|от|από)\s*#)?\W*$", re.I)
_CID = re.compile(r"\(cid:(\d+)\)")
_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"\s+")
_A4, _LETTER, _LEGAL = (210.0, 297.0), (215.9, 279.4), (215.9, 355.6)
_MM = 25.4 / 72


# --- a page's lines --------------------------------------------------------------------------


@dataclass(slots=True)
class Run:
    text: str
    bold: bool
    italic: bool
    colour: str | None
    href: str | None


@dataclass(slots=True)
class Line:
    page: int
    runs: list[Run]
    box: Box  # in the text's own direction: x along it, y down across it
    shown: Box  # on the page as shown
    size: float
    bold: bool  # most of its characters are
    rotation: int
    part: int  # the part of its page the reading-order cut left it in
    column: int | None
    invisible: bool  # all of it drawn invisibly (a text layer over a scan)
    control: int = 0  # control codes left out (no document can hold them)
    pieces: int = 1  # more than one: gaps wider than words leave run through it (a table's row, a form)

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass(frozen=True, slots=True)
class PagePicture:
    index: int  # among the page's pictures, as the geometry read lists them
    box: Box  # on the page as shown
    name: str | None
    pixels: tuple[int, int] | None


@dataclass(slots=True)
class CellText:
    cell: GridCell
    lines: list[Line]  # its text, line by line


@dataclass(slots=True)
class PageTable:
    grid: Grid
    cells: list[CellText]


@dataclass(slots=True)
class PageLines:
    number: int
    width: float
    height: float
    lines: list[Line]
    pictures: list[PagePicture]
    tables: list[PageTable] = field(default_factory=list)
    hybrid: bool = False
    columns: int = 1


@dataclass(slots=True)
class _Glyph:
    text: str
    size: float
    bold: bool
    italic: bool
    colour: str | None
    href: str | None
    box: Box  # in the text's own direction
    shown: Box
    invisible: bool

    @property
    def middle(self) -> float:
        return (self.box[1] + self.box[3]) / 2


@dataclass(slots=True)
class _Piece:
    glyphs: list[_Glyph]
    box: Box

    @property
    def size(self) -> float:
        return max(glyph.size for glyph in self.glyphs)


def _union(boxes: Iterable[Box]) -> Box:
    x0s, tops, x1s, bottoms = zip(*boxes, strict=True)
    return (min(x0s), min(tops), max(x1s), max(bottoms))


def _turned(box: Box, rotation: int, width: float, height: float) -> Box:
    """A box on the shown page in the frame of text running `rotation` degrees: x along the text."""
    x0, top, x1, bottom = box
    if rotation == 90:  # running down the page, its lines going right to left
        return (top, width - x1, bottom, width - x0)
    if rotation == 270:  # running up the page, its lines going left to right
        return (height - bottom, x0, height - top, x1)
    return box


def _direction(chars: list) -> int:
    """Which way text that isn't upright runs: down the page (90) or up it (270)."""
    steps = 0.0
    for before, after in zip(chars, chars[1:]):
        step = after.box[1] - before.box[1]
        if abs(step) < 2 * max(before.size, 1.0):
            steps += step
    return 90 if steps >= 0 else 270


def _web_link(page: PdfPage, shown: Box) -> str | None:
    middle_x, middle_y = (shown[0] + shown[2]) / 2, (shown[1] + shown[3]) / 2
    for annotation in page.annotations:
        if annotation.link == "web" and annotation.box is not None and isinstance(annotation.target, str):
            x0, top, x1, bottom = annotation.box
            if x0 <= middle_x <= x1 and top <= middle_y <= bottom:
                return annotation.target
    return None


def _glyphs(page: PdfPage, rotation: int, chars: list) -> list[_Glyph]:
    result: list[_Glyph] = []
    links = bool(page.links)
    for char in chars:
        box = _turned(char.box, rotation, page.width, page.height)
        if result and char.text == result[-1].text and all(abs(a - b) < 0.6 for a, b in zip(box, result[-1].box, strict=True)):
            continue  # the same character drawn again over itself (a "bold" by overprinting)
        name = font_name(char.font)
        result.append(
            _Glyph(
                text=char.text,
                size=char.size or 1.0,
                bold=_BOLD.search(name) is not None,
                italic=_ITALIC.search(name) is not None,
                colour=char.colour,
                href=_web_link(page, char.box) if links and char.text.strip() else None,
                box=box,
                shown=char.box,
                invisible=char.invisible,
            )
        )
    return result


def _rows(glyphs: list[_Glyph]) -> list[list[_Glyph]]:
    """Glyphs on one baseline together, each row left to right."""
    rows: list[list[_Glyph]] = []
    band: tuple[float, float] | None = None
    for glyph in sorted(glyphs, key=lambda g: g.middle):
        top, bottom = glyph.box[1], glyph.box[3]
        if band is not None:
            overlap = min(band[1], bottom) - max(band[0], top)
            if overlap >= 0.5 * min(band[1] - band[0], bottom - top):
                rows[-1].append(glyph)
                if bottom - top > band[1] - band[0]:
                    band = (top, bottom)  # the row's tallest glyph sets its band
                continue
        rows.append([glyph])
        band = (top, bottom)
    for row in rows:
        row.sort(key=lambda g: g.box[0])
    return rows


def _pieces(row: list[_Glyph]) -> list[_Piece]:
    pieces: list[_Piece] = []
    current: list[_Glyph] = []
    for glyph in row:
        if not glyph.text.strip():
            if current:
                current.append(glyph)  # a drawn space: kept, to tell words apart
            continue
        printed = [g for g in current if g.text.strip()]
        if printed and glyph.box[0] - printed[-1].box[2] > PIECE_GAP * max(glyph.size, printed[-1].size):
            pieces.append(_piece(current))
            current = []
        current.append(glyph)
    if current and any(g.text.strip() for g in current):
        pieces.append(_piece(current))
    return pieces


def _piece(glyphs: list[_Glyph]) -> _Piece:
    while glyphs and not glyphs[-1].text.strip():
        glyphs = glyphs[:-1]
    return _Piece(glyphs=glyphs, box=_union(g.box for g in glyphs if g.text.strip()))


def _gaps(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The gaps between intervals laid on one axis: (start, end) of each empty stretch."""
    gaps = []
    reach = None
    for start, end in sorted(intervals):
        if reach is not None and start > reach:
            gaps.append((reach, start))
        reach = end if reach is None else max(reach, end)
    return gaps


def _side_by_side(pieces: list[_Piece]) -> bool:
    """Whether any two pieces share a row: only then can a gutter run between them."""
    ordered = sorted(pieces, key=lambda p: p.box[1])
    for before, after in zip(ordered, ordered[1:]):
        if min(before.box[3], after.box[3]) - max(before.box[1], after.box[1]) > 0.3 * min(before.size, after.size):
            return True
    return False


def _column_cut(pieces: list[_Piece], page_width: float) -> float | None:
    """Where a gutter runs down these pieces, if one does between column-like text."""
    size = statistics.median(p.size for p in pieces)
    best = None
    for start, end in _gaps([(p.box[0], p.box[2]) for p in pieces]):
        if end - start < max(GUTTER_GAP * size, GUTTER_MIN):
            continue
        middle = (start + end) / 2
        left = [p for p in pieces if p.box[2] <= middle]
        right = [p for p in pieces if p.box[0] >= middle]
        if len(left) < 2 or len(right) < 2:
            continue
        if min(statistics.median(p.box[2] - p.box[0] for p in side) for side in (left, right)) < COLUMN_WIDTH * page_width:
            continue  # a table's cells, a form's labels: not columns
        spans = [(min(p.box[1] for p in side), max(p.box[3] for p in side)) for side in (left, right)]
        shared = min(spans[0][1], spans[1][1]) - max(spans[0][0], spans[1][0])
        if shared < 0.5 * min(span[1] - span[0] for span in spans):
            continue  # one above the other, not side by side
        if best is None or end - start > best[1] - best[0]:
            best = (start, end)
    return None if best is None else (best[0] + best[1]) / 2


@dataclass(slots=True)
class _Part:
    pieces: list[_Piece]
    joinable: bool  # not a column: may be joined to the parts above and below it


def _cut(pieces: list[_Piece], page_width: float, cuts: list[float], depth: int = 0) -> list[_Part]:
    """The pieces in reading order, as the parts of the page an XY cut leaves."""
    if len(pieces) < 2 or depth >= MAX_CUT_DEPTH or not _side_by_side(pieces):
        return [_Part(pieces, True)]
    at = _column_cut(pieces, page_width)
    if at is not None:
        cuts.append(at)
        parts = []
        for side in ([p for p in pieces if p.box[2] <= at], [p for p in pieces if p.box[0] >= at]):
            for part in _cut(side, page_width, cuts, depth + 1):
                part.joinable = False
                parts.append(part)
        return parts
    gaps = _gaps([(p.box[1], p.box[3]) for p in pieces])
    if not gaps:
        return [_Part(pieces, True)]
    start, end = max(gaps, key=lambda gap: gap[1] - gap[0])
    middle = (start + end) / 2
    above = _cut([p for p in pieces if p.box[3] <= middle], page_width, cuts, depth + 1)
    below = _cut([p for p in pieces if p.box[1] >= middle], page_width, cuts, depth + 1)
    parts = above[:-1]
    if above[-1].joinable and below[0].joinable:  # no column between them: one part of the page
        parts.append(_Part(above[-1].pieces + below[0].pieces, True))
        parts.extend(below[1:])
    else:
        parts.extend([above[-1], *below])
    return parts


def _runs(glyphs: list[_Glyph]) -> tuple[list[Run], int]:
    """The glyphs' runs of text, and how many control codes were left out of them."""
    runs: list[Run] = []
    control = 0
    previous: _Glyph | None = None
    space = False
    for glyph in glyphs:
        if not glyph.text.strip():
            space = previous is not None
            continue
        text = glyph.text
        if _CID.search(text):  # a glyph the file gives no text for: a control code below 32, else unreadable
            control += sum(int(code) < 32 for code in _CID.findall(text))
            text = _CID.sub(lambda match: "" if int(match.group(1)) < 32 else UNREADABLE, text)
            if not text:
                continue
        if previous is not None and (space or glyph.box[0] - previous.box[2] > SPACE_GAP * glyph.size):
            text = " " + text
        space = False
        colour = None if glyph.invisible else glyph.colour
        if runs and (runs[-1].bold, runs[-1].italic, runs[-1].colour, runs[-1].href) == (glyph.bold, glyph.italic, colour, glyph.href):
            runs[-1].text += text
        elif runs and text.startswith(" ") and len(text) > 1 and runs[-1].href is None:
            runs[-1].text += " "  # the space between words goes with the run before it, unless that is a link's
            runs.append(Run(text[1:], glyph.bold, glyph.italic, colour, glyph.href))
        else:
            runs.append(Run(text, glyph.bold, glyph.italic, colour, glyph.href))
        previous = glyph
    return runs, control


def _line(page: PdfPage, pieces: list[_Piece], rotation: int, part: int, column: int | None) -> Line:
    glyphs = [g for piece in pieces for g in piece.glyphs]
    runs: list[Run] = []
    control = 0
    for index, piece in enumerate(pieces):
        piece_runs, codes = _runs(piece.glyphs)
        control += codes
        if index and piece_runs:
            runs[-1].text += " "
        runs.extend(piece_runs)
    printed = [g for g in glyphs if g.text.strip()]
    sizes = Counter(round(g.size * 2) / 2 for g in printed)
    gaps = len(pieces) - 1
    if gaps and _marker("".join(run.text for run in _runs(pieces[0].glyphs)[0]).strip() + " x") is not None:
        gaps -= 1  # a list item's bullet set apart from its text: no table's gap
    return Line(
        page=page.number,
        runs=runs,
        box=_union(p.box for p in pieces),
        shown=_union(g.shown for g in printed),
        size=sizes.most_common(1)[0][0],
        bold=sum(g.bold for g in printed) * 2 > len(printed),
        rotation=rotation,
        part=part,
        column=column,
        invisible=all(g.invisible for g in printed),
        control=control,
        pieces=gaps + 1,
    )


def _inside(glyph: _Glyph, box: Box) -> bool:
    x, y = (glyph.box[0] + glyph.box[2]) / 2, glyph.middle
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def _fill_tables(page: PdfPage, grids: list[Grid], glyphs: list[_Glyph], result: PageLines) -> list[_Glyph]:
    """The text inside each ruled table into its cells, line by line; the rest, for the flow."""
    rest = list(glyphs)
    for grid in grids:
        inside = [glyph for glyph in rest if _inside(glyph, grid.box)]
        if not inside:
            continue  # lines crossing with no text: a drawing, not a table
        taken = {id(glyph) for glyph in inside}
        rest = [glyph for glyph in rest if id(glyph) not in taken]
        cells = []
        for cell in grid.cells:
            own = [glyph for glyph in inside if _inside(glyph, grid.rect(cell))]
            lines = [_line(page, _pieces(row), 0, -1, None) for row in _rows(own) if any(g.text.strip() for g in row)]
            cells.append(CellText(cell, [line for line in lines if line.runs]))
        result.tables.append(PageTable(grid, cells))
    return rest


def page_lines(page: PdfPage, kind: str | None = None) -> PageLines:
    """A page's text as lines in reading order (see the module's docstring)."""
    pictures = [PagePicture(index, image.box, image.name, image.pixels) for index, image in enumerate(page.images)]
    result = PageLines(number=page.number, width=page.width, height=page.height, lines=[], pictures=pictures, hybrid=kind == HYBRID)
    chars = [char for char in page.chars if char.text]
    upright = [char for char in chars if char.upright]
    turned = [char for char in chars if not char.upright]
    groups = [(0, upright)]
    if turned:
        groups.append((_direction(turned), turned))
    part = 0
    grids = find_grids(page)
    for rotation, group in groups:
        glyphs = _glyphs(page, rotation, group)
        if rotation == 0 and grids:
            glyphs = _fill_tables(page, grids, glyphs, result)
        pieces = [piece for row in _rows(glyphs) for piece in _pieces(row)]
        if not pieces:
            continue
        across = page.width if rotation == 0 else page.height
        cuts: list[float] = []
        parts = _cut(pieces, across, cuts)
        gutters = sorted(set(round(cut) for cut in cuts))
        if rotation == 0:
            result.columns = max(result.columns, len(gutters) + 1)
        for each in parts:
            column = None if not gutters or each.joinable else sum(1 for cut in gutters if cut < min(p.box[0] for p in each.pieces))
            rows: list[list[_Piece]] = []
            for piece in sorted(each.pieces, key=lambda p: ((p.box[1] + p.box[3]) / 2, p.box[0])):
                if rows:
                    last = rows[-1]
                    top, bottom = min(p.box[1] for p in last), max(p.box[3] for p in last)
                    if min(bottom, piece.box[3]) - max(top, piece.box[1]) >= 0.5 * min(bottom - top, piece.box[3] - piece.box[1]):
                        last.append(piece)
                        continue
                rows.append([piece])
            for row in rows:
                row.sort(key=lambda p: p.box[0])
                result.lines.append(_line(page, row, rotation, part, column))
            part += 1
    return result


# --- the document ------------------------------------------------------------------------------


@dataclass(slots=True)
class _Block:
    lines: list[Line]
    marker: str | None = None  # a list item's bullet or number, as printed
    marker_x: float = 0.0
    text_x: float = 0.0  # where an item's text starts, after its marker
    kind: str = "paragraph"  # paragraph, heading, item, caption
    level: int = 0
    confidence: float = SURE
    note: str | None = None

    @property
    def size(self) -> float:
        return Counter(line.size for line in self.lines).most_common(1)[0][0]

    @property
    def bold(self) -> bool:
        return all(line.bold for line in self.lines)


@dataclass(slots=True)
class PdfStructure:
    """What the reconstruction made of a PDF's pages."""

    document: Document
    # The lines' words, in reading order, as the document should hold them: without the
    # list markers made into list numbering and the lines moved into the header and footer.
    source_words: list[str]
    items: list[FidelityItem] = field(default_factory=list)
    # Every word on the pages' lines, running headers and list markers included: what the
    # import checks against the text read's, to know the layout read missed nothing.
    line_words: Counter[str] = field(default_factory=Counter)
    # For the conversion's confidence (fidelity/pdf_conversion.py): rows split by wide gaps
    # (a table's), pictures, pages set in columns, lines of turned text, blocks run on into
    # another column or page.
    table_rows: int = 0
    tables: int = 0
    table_confidence: float = 0.0  # the tables' own, on average
    pictures: int = 0
    pictures_placed: int = 0
    column_pages: int = 0
    turned_lines: int = 0
    run_on: int = 0


def _key(text: str) -> str:
    return _SPACES.sub(" ", _DIGITS.sub("#", text)).strip().lower()


def _bands(pages: list[PageLines]) -> tuple[set[int], dict[str, list[str]], dict[str, int]]:
    """The lines (by id) that are running headers, footers and page numbers; the header's
    and footer's text; how many pages carried each."""
    with_text = [page for page in pages if page.lines]
    taken: set[int] = set()
    texts: dict[str, list[str]] = {"header": [], "footer": []}
    counts: dict[str, int] = {}
    if len(with_text) < 2:
        return taken, texts, counts
    found: dict[tuple[str, str], list[Line]] = {}
    for page in with_text:
        seen: set[tuple[str, str]] = set()
        for line in page.lines:
            if line.rotation:
                continue
            zone = "header" if line.shown[1] < BAND * page.height else "footer" if line.shown[3] > (1 - BAND) * page.height else None
            if zone is None or not line.text.strip():
                continue
            key = (zone, _key(line.text))
            if key not in seen:
                seen.add(key)
                found.setdefault(key, []).append(line)
    needed = max(2, math.ceil(BAND_PAGES * len(with_text)))
    for (zone, key), lines in found.items():
        if len(lines) < needed:
            continue
        same = len({line.text.strip() for line in lines}) == 1
        if _PAGE_NUMBER.match(key):
            counts["numbers"] = max(counts.get("numbers", 0), len(lines))
        elif same:
            texts[zone].append(lines[0].text.strip())
            counts[zone] = max(counts.get(zone, 0), len(lines))
        else:
            continue  # it changes from page to page (a chapter's name): it stays in the text
        taken.update(id(line) for line in lines)
    return taken, texts, counts


def _marker(text: str) -> tuple[str, str] | None:
    """A list item's marker ("•", "3.", "b)") and the text after it."""
    for pattern in (_BULLET, _NUMBERED):
        match = pattern.match(text)
        if match:
            return match.group(0).strip(), text[match.end() :]
    return None


def _ends_sentence(line: Line) -> bool:
    return _SENTENCE_END.search(line.text.rstrip()) is not None


def _blocks(pages: list[PageLines], taken: set[int]) -> list[_Block]:
    lines = [line for page in pages for line in page.lines if id(line) not in taken and line.text.strip()]
    rights: dict[tuple[int, int], float] = {}
    for line in lines:
        key = (line.page, line.part)
        rights[key] = max(rights.get(key, 0.0), line.box[2])
    # The gap lines inside a paragraph leave, in ems: the lower quartile of those seen.
    ratios = [
        (after.box[1] - before.box[3]) / after.size
        for before, after in zip(lines, lines[1:])
        if (before.page, before.part) == (after.page, after.part) and abs(before.size - after.size) <= SAME_SIZE and 0 <= after.box[1] - before.box[3] < 2 * after.size
    ]
    inside = statistics.quantiles(ratios, n=4)[0] if len(ratios) >= 4 else (min(ratios) if ratios else 0.3)

    blocks: list[_Block] = []
    for line in lines:
        marker = _marker(line.text)
        block = blocks[-1] if blocks else None
        previous = block.lines[-1] if block else None
        if block is None or previous is None:
            blocks.append(_new_block(line, marker))
            continue
        same_part = (line.page, line.part, line.rotation) == (previous.page, previous.part, previous.rotation)
        alike = abs(line.size - previous.size) <= SAME_SIZE and line.bold == previous.bold
        if marker is not None:
            blocks.append(_new_block(line, marker))
        elif line.pieces > 1 or previous.pieces > 1:
            blocks.append(_new_block(line, None))  # a row of a table: a paragraph of its own (tables come with P2E-004)
        elif same_part:
            gap = line.box[1] - previous.box[3]
            left = min(l.box[0] for l in block.lines[1:]) if len(block.lines) > 1 else block.lines[0].box[0]
            short = previous.box[2] < rights[(previous.page, previous.part)] - SHORT_LINE * previous.size and _ends_sentence(previous)
            if block.marker is not None:
                ends = not alike or gap > (inside + PARAGRAPH_GAP) * line.size or line.box[0] < block.text_x - 0.5 * line.size or short
            else:
                ends = (
                    not alike
                    or gap > (inside + PARAGRAPH_GAP) * line.size
                    or gap < -0.5 * line.size
                    or line.box[0] > left + INDENT * line.size
                    or short
                )
            if ends:
                blocks.append(_new_block(line, None))
            else:
                block.lines.append(line)
        elif alike and not _ends_sentence(previous) and _LOWER_START.match(line.text.lstrip()):
            block.lines.append(line)  # a paragraph running on into the next column or page
            block.confidence = min(block.confidence, LIKELY)
        else:
            blocks.append(_new_block(line, None))
    return blocks


def _new_block(line: Line, marker: tuple[str, str] | None) -> _Block:
    if marker is None:
        return _Block(lines=[line])
    printed, rest = marker
    # Where the item's text starts: its share of the line's width past the marker.
    text_x = line.box[0] + (line.box[2] - line.box[0]) * (1 - len(rest) / max(len(line.text), 1))
    # An unreadable glyph taken for a bullet is a guess.
    confidence = GUESS if printed == UNREADABLE else SURE
    return _Block(lines=[line], marker=printed, marker_x=line.box[0], text_x=text_x, kind="item", confidence=confidence)


def _body_size(blocks: list[_Block], pages: dict[int, PageLines]) -> float:
    """The size most of the text is set in -- the tables' text counted too."""
    sizes: Counter[float] = Counter()
    cells = (line for page in pages.values() for table in page.tables for cell in table.cells for line in cell.lines)
    for line in [*(line for block in blocks for line in block.lines), *cells]:
        sizes[line.size] += len(line.text)
    return sizes.most_common(1)[0][0] if sizes else 10.0


def _classify(blocks: list[_Block], pages: dict[int, PageLines]) -> None:
    body = _body_size(blocks, pages)
    by_size: list[_Block] = []
    by_weight: list[_Block] = []
    for index, block in enumerate(blocks):
        text = " ".join(line.text.strip() for line in block.lines)
        if block.marker is None and len(block.lines) <= HEADING_LINES and len(text) <= HEADING_CHARS and all(line.pieces == 1 for line in block.lines):
            if block.size >= HEADING_RATIO * body:
                block.kind = "heading"
                block.confidence = min(block.confidence, SURE if block.size >= 1.3 * body else LIKELY)
                by_size.append(block)
                continue
            following = blocks[index + 1] if index + 1 < len(blocks) else None
            if (
                block.bold
                and len(block.lines) == 1
                and block.size >= 0.95 * body
                and len(text.split()) <= BOLD_HEADING_WORDS
                and not re.search(r"[.,;]$", text)
                and following is not None
                and not following.bold
            ):
                block.kind = "heading"
                block.confidence = min(block.confidence, GUESS)
                by_weight.append(block)
                continue
        if block.marker is None and len(block.lines) <= 3:
            if _CAPTION.match(text):
                block.kind, block.confidence = "caption", min(block.confidence, LIKELY)
            elif len(block.lines) <= 2 and _under_picture(block, pages.get(block.lines[0].page)):
                block.kind, block.confidence = "caption", min(block.confidence, GUESS)
    sizes = sorted({round(block.size) for block in by_size}, reverse=True)
    for block in by_size:
        block.level = min(sizes.index(round(block.size)) + 1, 6)
    for block in by_weight:
        block.level = min(len(sizes) + 1, 6)


def _under_picture(block: _Block, page: PageLines | None) -> bool:
    if page is None or block.lines[0].rotation:
        return False
    x0, top, x1, _ = block.lines[0].shown
    size = block.size
    return any(
        0 <= top - picture.box[3] <= CAPTION_GAP * size and min(x1, picture.box[2]) > max(x0, picture.box[0])
        for picture in page.pictures
    )


def _marks(run: Run, plain_bold: bool) -> list[Mark]:
    marks = []
    if run.bold and not plain_bold:
        marks.append(Mark(type=MarkType.BOLD))
    if run.italic:
        marks.append(Mark(type=MarkType.ITALIC))
    if run.href:
        marks.append(Mark(type=MarkType.LINK, href=run.href))
    if run.colour and run.colour != "#000000":
        marks.append(Mark(type=MarkType.TEXT_STYLE, color=run.colour))
    return marks


def _inline(lines: list[Line], skip: int = 0, plain_bold: bool = False) -> list[InlineRun]:
    """The lines' runs as one paragraph's: lines joined by a space (none after a word
    broken with a hyphen); `skip` characters (a list marker) left off the first."""
    runs: list[Run] = []
    for index, line in enumerate(lines):
        line_runs = [Run(run.text, run.bold, run.italic, run.colour, run.href) for run in line.runs]
        if index == 0 and skip:
            left = skip
            while line_runs and left:
                first = line_runs[0]
                if len(first.text) <= left:
                    left -= len(first.text)
                    line_runs.pop(0)
                else:
                    first.text = first.text[left:]
                    left = 0
            if line_runs:
                line_runs[0].text = line_runs[0].text.lstrip()
        if not line_runs:
            continue
        if runs:
            before = runs[-1].text.rstrip()
            runs[-1].text = before if re.search(r"\w-$", before) and _LOWER_START.match(line_runs[0].text) else before + " "
        runs.extend(line_runs)
    merged: list[InlineRun] = []
    for run in runs:
        text = xml_text(run.text)
        if not text:
            continue
        marks = _marks(run, plain_bold)
        if merged and merged[-1].marks == marks:
            merged[-1] = InlineRun(text=merged[-1].text + text, marks=marks)
        else:
            merged.append(InlineRun(text=text, marks=marks))
    if merged:
        merged[-1] = InlineRun(text=merged[-1].text.rstrip(), marks=merged[-1].marks)
    return [run for run in merged if run.text]


def _layout(lines: list[Line], pages: dict[int, PageLines]) -> ElementLayout:
    first = lines[0]
    on_first = [line for line in lines if line.page == first.page]
    x0, top, x1, bottom = _union(line.shown for line in on_first)
    last = lines[-1].page
    page = pages[first.page]
    return ElementLayout(
        page=first.page,
        x=round(x0, 2),
        y=round(top, 2),
        width=round(x1 - x0, 2),
        height=round(bottom - top, 2),
        rotation=first.rotation,  # type: ignore[arg-type]
        lastPage=last if last != first.page else None,
        column=first.column if page.columns > 1 else None,
        lines=len(lines),
        source="pdf-text-layer" if all(line.invisible for line in lines) else "pdf-text",
    )


_LETTERS = "abcdefghijklmnopqrstuvwxyz"
_CYRILLIC = "абвгдежзийклмнопрстуфхцчшщъьюя"


def _number(marker: str) -> tuple[str, int] | None:
    """An ordered marker's format and number ("3." -> decimal 3, "b)" -> lowerLetter 2)."""
    core = marker.strip("().")
    if core.isdigit():
        return "decimal", int(core)
    lower = core.lower()
    if len(core) == 1 and lower in _LETTERS:
        return ("lowerLetter" if core.islower() else "upperLetter"), _LETTERS.index(lower) + 1
    if len(core) == 1 and lower in _CYRILLIC:
        return ("russianLower" if core.islower() else "russianUpper"), _CYRILLIC.index(lower) + 1
    return None


def _lists(blocks: list[_Block]) -> list[list[_Block] | _Block]:
    """Items in a row grouped into lists; items that don't make a list become paragraphs again."""
    grouped: list[list[_Block] | _Block] = []
    run: list[_Block] = []

    def flush() -> None:
        if run:
            grouped.extend(_one_list(list(run)))
            run.clear()

    for block in blocks:
        if block.kind == "item":
            run.append(block)
        else:
            flush()
            grouped.append(block)
    flush()
    return grouped


def _one_list(items: list[_Block]) -> list[list[_Block] | _Block]:
    indents: list[float] = []
    for item in sorted(items, key=lambda i: i.marker_x):
        if not indents or item.marker_x - indents[-1] > 0.5 * item.size:
            indents.append(item.marker_x)
    for item in items:
        item.level = min(max(i for i, x in enumerate(indents) if item.marker_x >= x - 0.5 * item.size), 8)
    # Split where the top level changes between bullets and numbers (or numbering formats).
    result: list[list[_Block] | _Block] = []
    current: list[_Block] = []
    kind = None
    for item in items:
        number = _number(item.marker or "")
        this = number[0] if number else "bullet"
        if item.level == 0:
            if current and kind is not None and this != kind:
                result.extend(_checked(current))
                current = []
            kind = this
        current.append(item)
    result.extend(_checked(current))
    return result


def _checked(items: list[_Block]) -> list[list[_Block] | _Block]:
    """A list whose numbers count on (1, 2, 3 at each level, a sub-list starting again
    under each item): otherwise its markers stay in the text, as paragraphs."""
    counts: dict[int, int] = {}
    formats: dict[int, str] = {}
    fine = True
    for item in items:
        number = _number(item.marker or "")
        for deeper in [level for level in counts if level > item.level]:
            del counts[deeper]
        if number is None:
            counts.pop(item.level, None)
            continue
        form, value = number
        if item.level in counts and (formats.get(item.level) != form or value != counts[item.level] + 1):
            fine = False
            break
        if item.level not in counts and form != "decimal" and value != 1:
            fine = False  # a lone "C." starting a sentence isn't a list
            break
        counts[item.level], formats[item.level] = value, form
    lone_letter = len(items) == 1 and (number := _number(items[0].marker or "")) is not None and number[0] != "decimal"
    if fine and not lone_letter:
        return [items]
    for item in items:
        item.kind, item.marker = "paragraph", None
        item.confidence = min(item.confidence, LIKELY)
    return list(items)


def _element(block: _Block, order: int, pages: dict[int, PageLines]) -> Element:
    plain_bold = block.kind == "heading" and block.bold
    inline = _inline(block.lines, plain_bold=plain_bold)
    kind = {"heading": ElementType.HEADING, "caption": ElementType.CAPTION}.get(block.kind, ElementType.PARAGRAPH)
    return Element(
        type=kind,
        content=plain_text_from_inline(inline),
        inline=inline,
        order=order,
        level=block.level if kind == ElementType.HEADING else None,
        confidence=block.confidence,
        layout=_layout(block.lines, pages),
    )


def _list_element(items: list[_Block], order: int, pages: dict[int, PageLines]) -> Element:
    list_items = []
    for item in items:
        skip = len(item.lines[0].text) - len(item.lines[0].text.lstrip()) + len(item.marker or "")
        list_items.append(ListItem(inline=_inline(item.lines, skip=skip), level=item.level))
    top = [item for item in items if item.level == 0] or items
    number = _number(top[0].marker or "")
    numbering = None
    if number is not None and (number[0] != "decimal" or number[1] != 1):
        numbering = ListNumbering(start=number[1], format=number[0])  # type: ignore[arg-type]
    return Element(
        type=ElementType.LIST,
        content="\n".join(plain_text_from_inline(item.inline) for item in list_items),
        listItems=list_items,
        ordered=number is not None,
        numbering=numbering,
        order=order,
        confidence=min(min(item.confidence for item in items), LIKELY if len(items) == 1 else SURE),
        layout=_layout([line for item in items for line in item.lines], pages),
    )


def _page_setup(pages: list[PageLines], lines: list[Line]) -> DocumentSettings:
    settings = DocumentSettings()
    if not pages:
        return settings
    first = pages[0]
    width, height = first.width * _MM, first.height * _MM
    portrait = (min(width, height), max(width, height))
    for name, size in (("A4", _A4), ("Letter", _LETTER), ("Legal", _LEGAL)):
        if abs(portrait[0] - size[0]) <= 3 and abs(portrait[1] - size[1]) <= 3:
            settings.pageSize = name
            settings.orientation = "landscape" if width > height else "portrait"
            break
    # The margins: as far out as the text goes on the pages the size of the first.
    alike = {page.number for page in pages if (page.width, page.height) == (first.width, first.height)}
    upright = [line for line in lines if not line.rotation and line.page in alike]
    if upright:

        def margin(points: float) -> float:
            return round(min(max(points * _MM / 10, 0.5), 5.0), 1)

        settings.marginLeftCm = margin(min(line.shown[0] for line in upright))
        settings.marginRightCm = margin(first.width - max(line.shown[2] for line in upright))
        settings.marginTopCm = margin(min(line.shown[1] for line in upright))
        settings.marginBottomCm = margin(first.height - max(line.shown[3] for line in upright))
    return settings


def _pages_text(count: int) -> str:
    return f"{count} page{'s' if count != 1 else ''}"


def picture_plan(pages: list[PageLines]) -> tuple[list[PictureRef], dict[tuple[int, int], str]]:
    """The pictures to put in the document, and those not to, each with why: a rule or a dot,
    the scan under a hybrid page's text layer, a picture repeated in the header or footer of
    most pages (a logo, say)."""
    left_out: dict[tuple[int, int], str] = {}
    repeats: dict[tuple, list[tuple[int, int]]] = {}
    with_text = [page for page in pages if page.lines]
    for page in pages:
        for picture in page.pictures:
            key = (page.number, picture.index)
            x0, top, x1, bottom = picture.box
            if x1 - x0 < TINY_PICTURE or bottom - top < TINY_PICTURE:
                left_out[key] = "tiny"
            elif page.hybrid and (x1 - x0) * (bottom - top) >= SCAN_PICTURE * page.width * page.height:
                left_out[key] = "scan"
            elif top < BAND * page.height or bottom > (1 - BAND) * page.height:
                repeats.setdefault((tuple(round(v / 2) for v in picture.box), picture.pixels), []).append(key)
    needed = max(2, math.ceil(BAND_PAGES * len(with_text)))
    for keys in repeats.values():
        if len({page for page, _ in keys}) >= needed:
            left_out.update({key: "running" for key in keys})
    wanted = [
        PictureRef(page.number, picture.index, picture.name, picture.pixels)
        for page in pages
        for picture in page.pictures
        if (page.number, picture.index) not in left_out
    ]
    return wanted, left_out


def _picture_element(page: PageLines, picture: PagePicture, decoded: Picture, widest_cm: float) -> Element:
    x0, top, x1, bottom = picture.box
    width, height = (x1 - x0) * _CM, (bottom - top) * _CM
    if width > widest_cm:  # no wider than the text: a full-page scan shrinks to the margins
        width, height = widest_cm, height * widest_cm / width
    return Element(
        type=ElementType.IMAGE,
        content="",
        order=0,
        image=ImageContent(
            src=f"data:{decoded.mime};base64,{base64.b64encode(decoded.data).decode('ascii')}",
            mime=decoded.mime,
            name=f"Page {page.number}, picture {picture.index + 1}",
            widthCm=round(min(max(width, 0.05), 200), 2),
            heightCm=round(min(max(height, 0.05), 200), 2),
        ),
        confidence=LIKELY,  # where it stood, as near as the text around it allows
        layout=ElementLayout(page=page.number, x=round(x0, 2), y=round(top, 2), width=round(x1 - x0, 2), height=round(bottom - top, 2), source="pdf-picture"),
    )


def _table_element(page: PageLines, table: PageTable) -> tuple[Element, list[str]]:
    """A ruled table as the document's, and its words in order (row by row, cell by cell)."""
    grid = table.grid
    first_row = [cell for cell in table.cells if cell.cell.row == 0]
    shaded = len(grid.ys) > 2 and bool(first_row) and all(cell.cell.shade for cell in first_row)
    later = [cell for cell in table.cells if cell.cell.row > 0 and cell.lines]
    bold = (
        len(grid.ys) > 2
        and any(cell.lines for cell in first_row)
        and all(all(line.bold for line in cell.lines) for cell in first_row if cell.lines)
        and any(not all(line.bold for line in cell.lines) for cell in later)
    )
    header = shaded or bold
    rows: list[TableRow] = []
    words_in_order: list[str] = []
    texts: list[str] = []
    for row in range(len(grid.ys) - 1):
        cells = []
        row_texts = []
        for cell in sorted((c for c in table.cells if c.cell.row == row), key=lambda c: c.cell.column):
            is_header = header and row == 0
            inline = _inline(cell.lines, plain_bold=is_header and all(line.bold for line in cell.lines))
            cells.append(
                TableCell(
                    inline=inline,
                    header=is_header,
                    colspan=cell.cell.colspan,
                    rowspan=cell.cell.rowspan,
                    background=cell.cell.shade,
                )
            )
            row_texts.append(plain_text_from_inline(inline))
            words_in_order.extend(words(xml_text(" ".join(line.text for line in cell.lines))))
        if cells:
            rows.append(TableRow(cells=cells))
            texts.append(" | ".join(row_texts))
    x0, top, x1, bottom = grid.box
    element = Element(
        type=ElementType.TABLE,
        content="\n".join(texts),
        order=0,
        table=TableContent(
            rows=rows,
            hasHeaderRow=header,
            columnWidthsCm=[round((right - left) * _CM, 2) for left, right in zip(grid.xs, grid.xs[1:])],
        ),
        confidence=LIKELY if grid.spans else SURE,
        layout=ElementLayout(
            page=page.number, x=round(x0, 2), y=round(top, 2), width=round(x1 - x0, 2), height=round(bottom - top, 2),
            lines=max(1, len(grid.ys) - 1), source="pdf-text",
        ),
    )
    return element, words_in_order


def _place(elements: list[Element], picture: Element) -> None:
    """Before the first block on the picture's page below its top and beside it (a column
    elsewhere on the page doesn't count); else before the first anywhere below its bottom
    (pictures side by side go before the caption under them both); else before the next
    page's first block."""
    at = picture.layout
    assert at is not None

    def first(test) -> int | None:
        for index, element in enumerate(elements):
            layout = element.layout
            if layout is not None and (layout.page > at.page or (layout.page == at.page and test(layout))):
                return index
        return None

    beside = first(lambda layout: layout.y >= at.y and min(layout.x + layout.width, at.x + at.width) > max(layout.x, at.x))
    below = first(lambda layout: layout.y >= at.y + at.height)
    candidates = [index for index in (beside, below) if index is not None]
    elements.insert(min(candidates) if candidates else len(elements), picture)


_LEFT_OUT = {
    "tiny": "too small to be more than a rule or a dot",
}


def _picture_items(placed: int, left_out: dict[tuple[int, int], str], undecoded: dict[tuple[int, int], str]) -> list[FidelityItem]:
    items: list[FidelityItem] = []
    if placed:
        items.append(
            FidelityItem(
                feature="pdf.picture_position",
                policy=FidelityPolicy.LOSSY,
                reason=f"{placed} picture{'s' if placed != 1 else ''} went into the text where {'they' if placed != 1 else 'it'} stood -- "
                "before the text below -- not at the exact place on the page.",
                count=placed,
                confidence=LIKELY,
            )
        )
    running = sum(1 for why in left_out.values() if why == "running")
    if running:
        items.append(
            FidelityItem(
                feature="pdf.running_pictures",
                policy=FidelityPolicy.LOSSY,
                reason=f"A picture repeated at the top or bottom of the pages (a logo, say) wasn't put in the text: {running} time{'s' if running != 1 else ''}.",
                count=running,
                contentChanged=True,
            )
        )
    scans = sum(1 for why in left_out.values() if why == "scan")
    if scans:
        items.append(
            FidelityItem(
                feature="pdf.scan_backgrounds",
                policy=FidelityPolicy.LOSSY,
                reason=f"The scan under the text layer on {_pages_text(scans)} wasn't added: its words came in as text.",
                count=scans,
            )
        )
    reasons = Counter([_LEFT_OUT[why] for why in left_out.values() if why in _LEFT_OUT] + list(undecoded.values()))
    if reasons:
        total = sum(reasons.values())
        why = "; ".join(f"{count} {reason}" for reason, count in reasons.most_common())
        items.append(
            FidelityItem(
                feature="pdf.images",
                policy=FidelityPolicy.UNSUPPORTED,
                reason=f"{total} of the PDF's pictures {'weren' if total != 1 else 'wasn'}'t imported: {why}.",
                count=total,
                contentChanged=True,
            )
        )
    return items


def build_pdf_document(pages: list[PageLines], title: str | None, pictures: dict[tuple[int, int], Picture | str] | None = None) -> PdfStructure:
    """The document a PDF's pages make (see the module's docstring). `pictures`: those
    picture_plan wanted, decoded (parsers/pdf_pictures.py) or why not; None: none decoded."""
    by_number = {page.number: page for page in pages}
    taken, band_texts, band_counts = _bands(pages)
    blocks = _blocks(pages, taken)
    _classify(blocks, by_number)
    elements: list[Element] = []
    origin: dict[int, list[str]] = {}  # each element's words as the PDF has them, by id(element)
    markers = 0
    for group in _lists(blocks):
        if isinstance(group, list):
            elements.append(_list_element(group, len(elements), by_number))
            said: list[str] = []
            for item in group:
                markers += 1
                first = item.lines[0].text.lstrip()[len(item.marker or "") :]
                said.extend(words(xml_text(" ".join([first, *(line.text for line in item.lines[1:])]))))
            origin[id(elements[-1])] = said
        else:
            elements.append(_element(group, len(elements), by_number))
            origin[id(elements[-1])] = words(xml_text(" ".join(line.text for line in group.lines)))
    table_confidences = []
    for page in pages:
        for table in page.tables:
            element, said = _table_element(page, table)
            origin[id(element)] = said
            table_confidences.append(element.confidence or SURE)
            _place(elements, element)

    kept_lines = [line for block in blocks for line in block.lines]
    settings = _page_setup(pages, kept_lines)
    wanted, left_out = picture_plan(pages)
    undecoded: dict[tuple[int, int], str] = {}
    widest = settings.pageWidthMm / 10 - settings.marginLeftCm - settings.marginRightCm
    placed = 0
    for ref in wanted:
        decoded = (pictures or {}).get((ref.page, ref.index), "not read")
        if isinstance(decoded, str):
            undecoded[(ref.page, ref.index)] = decoded
            continue
        page = by_number[ref.page]
        _place(elements, _picture_element(page, page.pictures[ref.index], decoded, widest))
        placed += 1
    for order, element in enumerate(elements):
        element.order = order
    source = [word for element in elements for word in origin.get(id(element), [])]
    items: list[FidelityItem] = _picture_items(placed, left_out, undecoded)
    unruled = sum(1 for line in kept_lines if line.pieces > 1)
    if unruled:
        items.append(
            FidelityItem(
                feature="pdf.unruled_tables",
                policy=FidelityPolicy.LOSSY,
                reason=f"{unruled} line{'s' if unruled != 1 else ''} set apart in columns by space alone (a table drawn without "
                f"lines, say) came in as {'a paragraph each' if unruled != 1 else 'a paragraph'}, the columns' text in a row.",
                count=unruled,
            )
        )
    for zone in ("header", "footer"):
        if band_texts[zone]:
            text = " · ".join(band_texts[zone])[:500]
            setattr(settings, zone, text)
            items.append(
                FidelityItem(
                    feature="pdf.running_header" if zone == "header" else "pdf.running_footer",
                    policy=FidelityPolicy.LOSSY,
                    reason=f"“{text[:120]}”, repeated at the {'top' if zone == 'header' else 'bottom'} of {_pages_text(band_counts[zone])}, "
                    f"became the document's {zone}.",
                    count=band_counts[zone],
                    confidence=LIKELY,
                )
            )
    if band_counts.get("numbers"):
        settings.showPageNumbers = True
        items.append(
            FidelityItem(
                feature="pdf.page_numbers",
                policy=FidelityPolicy.LOSSY,
                reason=f"The page numbers on {_pages_text(band_counts['numbers'])} became the document's page numbering.",
                count=band_counts["numbers"],
                confidence=LIKELY,
            )
        )
    if markers:
        items.append(
            FidelityItem(
                feature="pdf.list_markers",
                policy=FidelityPolicy.LOSSY,
                reason=f"{markers} line{'s' if markers != 1 else ''} starting with a bullet or a number became list items: "
                "the list numbers them now.",
                count=markers,
                confidence=LIKELY,
            )
        )
    cell_lines = [line for page in pages for table in page.tables for cell in table.cells for line in cell.lines]
    control = sum(line.control + len(NOT_XML.findall(line.text)) for line in kept_lines + cell_lines)
    if control:  # as the text import says it (ingestion_service.build_document_from_text)
        items.append(
            FidelityItem(
                feature="text.control_characters",
                policy=FidelityPolicy.UNSUPPORTED,
                reason=f"The text held {control} control code{'s' if control != 1 else ''}, which no document can hold: left out.",
                count=control,
            )
        )
    # Those left in the text: one taken for a bullet is the list's now.
    unreadable = sum(run.text.count(UNREADABLE) for element in elements for run in inline_runs(element))
    if unreadable:
        items.append(
            FidelityItem(
                feature="pdf.unreadable_characters",
                policy=FidelityPolicy.LOSSY,
                reason=f"{unreadable} character{'s' if unreadable != 1 else ''} in the PDF {'have' if unreadable != 1 else 'has'} no text "
                "the file gives (a font without a map to letters): shown as �.",
                count=unreadable,
                contentChanged=True,
            )
        )
    derived = next((element.content for element in elements if element.type == ElementType.HEADING), None)
    document = Document(
        metadata=DocumentMetadata(title=title or (derived or "Untitled Document")[:500]),
        settings=settings,
        sections=[Section(order=0)],
        elements=elements,
    )
    for element in document.elements:
        element.parentId = document.sections[0].id
    every = Counter(word for page in pages for line in page.lines for word in words(line.text))
    every.update(word for page in pages for table in page.tables for cell in table.cells for line in cell.lines for word in words(line.text))
    return PdfStructure(
        document=document,
        source_words=source,
        items=items,
        line_words=every,
        table_rows=unruled,
        tables=len(table_confidences),
        table_confidence=round(sum(table_confidences) / len(table_confidences), 2) if table_confidences else 0.0,
        pictures=sum(len(page.pictures) for page in pages),
        pictures_placed=placed,
        column_pages=sum(1 for page in pages if page.columns > 1),
        turned_lines=sum(1 for line in kept_lines if line.rotation),
        run_on=sum(1 for block in blocks if len({(line.page, line.part) for line in block.lines}) > 1),
    )
