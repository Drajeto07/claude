"""Where things are on a PDF's pages (tracker PDF-010): each character with its font,
size, colour and box; the lines, rectangles, curves and pictures drawn; the links and
other annotations; each page's boxes and rotation; and the file's outline, form fields
and metadata. The PDF inspection (fidelity/pdf_inspection.py) reports it, and the
PDF -> editable phase is to build on it. The text import (parsers/pdf.py) doesn't use
it: this is a second read of the same bytes.

pdfminer.six reads what is drawn; pypdf, already hardened for the text read, reads
the file's structure. Boxes are in points on the page as it is shown -- turned by its
rotation -- from its top left corner, y growing down.

The file is untrusted, and pdfminer has none of pypdf's limits, so the read has its
own, after the text read's: its page cap and its content cap per page, a time budget,
a cap on what a stream (and the read in all) decodes to, on what one page holds, on
nesting, and on the objects in the file. A file past a file-level limit is refused
(PdfParseError, with the text read's messages); past a limit met on a page, the read
stops there and says why (`stopped`), keeping only the pages read whole."""

import io
import logging
import math
import time
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from itertools import islice
from typing import Any

from pdfminer import pdftypes
from pdfminer.converter import PDFLayoutAnalyzer
from pdfminer.layout import LTChar, LTCurve, LTFigure, LTImage, LTItem, LTLine, LTPage, LTRect
from pdfminer.lzw import LZWDecoder
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdffont import PDFUnicodeNotDefined
from pdfminer.pdfinterp import LITERAL_FORM, PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1, stream_value
from pdfminer.psparser import PSLiteral, literal_name
from pypdf import PdfReader
from pypdf.errors import LimitReachedError
from pypdf.filters import ZLIB_MAX_OUTPUT_LENGTH

from app.parsers import pdf as text_read  # its page and content caps are this read's too: one setting for both
from app.parsers.pdf import INVALID, PASSWORD, TOO_MUCH, PdfParseError
from app.parsers.trace import where

logger = logging.getLogger(__name__)

# pdfminer's warnings can quote the file, like pypdf's: never logged. Its debug calls
# (one per operator) cost little while its level is above them.
_PDFMINER = logging.getLogger("pdfminer")
_PDFMINER.addHandler(logging.NullHandler())
_PDFMINER.propagate = False
_PDFMINER.setLevel(logging.ERROR)

# Interpreting a page in Python is slower than pypdf's text read (about 1 s for a page
# holding the full 2 MB of content): a file is read for this long at most, checked as
# each thing is drawn.
MAX_PDF_GEOMETRY_SECONDS = 30.0
# Characters, paths and pictures on one page: more than a page of text holds many times over.
MAX_PDF_PAGE_ITEMS = 200_000
# Graphics states saved inside one another, and forms drawn inside forms (PDF's own
# implementation limit for the first is 28).
MAX_PDF_NESTING = 64
# Objects in the file: a 1,000-page file has some tens of thousands.
MAX_PDF_OBJECTS = 250_000
# What one stream decodes to (pypdf's own limit for the text read), and all of them in a read.
MAX_PDF_STREAM_DECODED = ZLIB_MAX_OUTPUT_LENGTH
MAX_PDF_DECODED = 200 * 1024 * 1024
# Outline entries and form fields kept (all are counted).
MAX_PDF_LISTED = 1000

# Why a read stopped before the end; the pages before it were read whole.
STOPPED_SLOW = "Reading where things are on the pages took too long: page {page} and the pages after it weren't read."
STOPPED_DENSE = "Page {page} has more drawn on it than can be read here: it and the pages after it weren't read."
STOPPED_DEEP = "Page {page} nests its drawing deeper than can be read here: it and the pages after it weren't read."
STOPPED_DATA = "Page {page} holds more data than can be read safely: it and the pages after it weren't read."
DAMAGED_PAGE = "This page is damaged and what is on it couldn't be read."
DAMAGED_STRUCTURE = "The file's outline, form fields or metadata are damaged and couldn't be read."

Box = tuple[float, float, float, float]  # x0, top, x1, bottom


@dataclass(frozen=True, slots=True)
class PdfChar:
    text: str
    font: str
    size: float
    colour: str | None  # "#rrggbb"; None: a pattern or a colour space it can't be told in
    box: Box
    # Drawn invisibly (text render mode 3, or 7: only a clipping path) -- what OCR
    # software lays over a scan, so the words can be found and copied.
    invisible: bool
    upright: bool


@dataclass(frozen=True, slots=True)
class PdfPath:
    """A line, a rectangle or any other path drawn on the page."""

    box: Box
    width: float
    stroke: str | None  # its outline's colour, None when it isn't stroked
    fill: str | None  # its fill colour, None when it isn't filled


@dataclass(frozen=True, slots=True)
class PdfImage:
    box: Box
    pixels: tuple[int, int] | None  # its own width and height, as the file says


@dataclass(frozen=True, slots=True)
class PdfAnnotation:
    kind: str  # the annotation's subtype: "Link", "Text", "Widget", "Highlight"...
    box: Box | None
    # A link's: "web" (an address a document may open, security/links.py), "unsafe"
    # (any other address), "internal" (a place in the file) or "other" (an action).
    link: str | None = None
    target: str | int | None = None  # the web address, or the page an internal link goes to


@dataclass(slots=True)
class PdfPage:
    number: int  # from 1
    width: float  # as shown
    height: float
    rotation: int  # 0, 90, 180 or 270
    # The boxes the file sets, in its own coordinates (x0, y0, x1, y1): media and crop
    # always (crop defaults to media), bleed, trim and art when given.
    boxes: dict[str, tuple[float, float, float, float]]
    chars: list[PdfChar] = field(default_factory=list)
    lines: list[PdfPath] = field(default_factory=list)
    rects: list[PdfPath] = field(default_factory=list)
    curves: list[PdfPath] = field(default_factory=list)
    images: list[PdfImage] = field(default_factory=list)
    annotations: list[PdfAnnotation] = field(default_factory=list)

    @property
    def links(self) -> list[PdfAnnotation]:
        return [annotation for annotation in self.annotations if annotation.link is not None]


@dataclass(frozen=True, slots=True)
class PdfOutlineEntry:
    title: str
    level: int  # 0: top level
    page: int | None  # from 1; None when it goes nowhere in the file


@dataclass(frozen=True, slots=True)
class PdfFormField:
    name: str
    kind: str  # text, button, choice, signature or other


@dataclass(slots=True)
class PdfGeometry:
    page_count: int
    version: str | None
    # The document information dictionary's entries, values as text; XMP is only noted.
    metadata: dict[str, str]
    xmp: bool
    outline: list[PdfOutlineEntry]
    outline_count: int
    fields: list[PdfFormField]
    field_count: int
    # None: the outline, fields and metadata were read; else why not.
    structure_problem: str | None = None
    # The pages read whole, unless they were handed to `on_page` instead.
    pages: list[PdfPage] = field(default_factory=list)
    # Pages that couldn't be read (damaged), with why; the read went on after them.
    unread: dict[int, str] = field(default_factory=dict)
    # Why the read stopped before the last page; None when it didn't.
    stopped: str | None = None
    read_pages: int = 0

    @property
    def complete(self) -> bool:
        return self.stopped is None and not self.unread and self.structure_problem is None


class _Stop(Exception):
    """A limit met on a page: the read ends there."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _TooMuchData(Exception):
    pass


# --- what pdfminer decodes, bounded -------------------------------------------------------
# pdfminer inflates a stream whole, with no limit, so a few compressed kilobytes could
# become gigabytes. Its decoders are swapped, in pdfminer's own module (nothing else
# here uses pdfminer), for ones that stop at MAX_PDF_STREAM_DECODED a stream and
# MAX_PDF_DECODED a read. Pictures are never decoded here.

_DECODED: ContextVar[list[int] | None] = ContextVar("pdf_decoded", default=None)


def _spend(size: int) -> None:
    spent = _DECODED.get()
    if spent is not None:
        spent[0] += size
        if spent[0] > MAX_PDF_DECODED:
            raise _TooMuchData


class _BoundedZlib:
    """zlib as pdfminer uses it. A damaged stream gives what decoded before the damage
    (as pypdf does), so pdfminer's byte-at-a-time repair -- slow, and quadratic in what
    it decodes -- never runs."""

    error = zlib.error

    @staticmethod
    def decompress(data: bytes) -> bytes:
        decompressor = zlib.decompressobj()
        parts: list[bytes] = []
        size = 0
        try:
            pending = data
            while pending and not decompressor.eof:
                out = decompressor.decompress(pending, 1 << 20)
                size += len(out)
                if size > MAX_PDF_STREAM_DECODED:
                    raise _TooMuchData
                _spend(len(out))
                parts.append(out)
                pending = decompressor.unconsumed_tail
        except zlib.error:
            pass
        return b"".join(parts)

    @staticmethod
    def decompressobj() -> "_BoundedDecompressor":
        return _BoundedDecompressor()


class _BoundedDecompressor:
    def __init__(self) -> None:
        self._decompressor = zlib.decompressobj()
        self._size = 0

    def decompress(self, data: bytes) -> bytes:
        out = self._decompressor.decompress(data, MAX_PDF_STREAM_DECODED + 1 - self._size)
        self._size += len(out)
        if self._size > MAX_PDF_STREAM_DECODED or self._decompressor.unconsumed_tail:
            raise _TooMuchData
        _spend(len(out))
        return out


def _lzwdecode(data: bytes) -> bytes:
    parts: list[bytes] = []
    size = 0
    for part in LZWDecoder(io.BytesIO(data)).run():
        size += len(part)
        if size > MAX_PDF_STREAM_DECODED:
            raise _TooMuchData
        parts.append(part)
    _spend(size)
    return b"".join(parts)


def _rldecode(data: bytes) -> bytes:
    """Run-length decoding (PDF 1.7, 7.4.5), as pdfminer's, but bounded."""
    out = bytearray()
    index = 0
    while index < len(data) and data[index] != 128:
        length = data[index]
        if length < 128:
            out += data[index + 1 : index + 2 + length]
            index += length + 2
        else:
            out += data[index + 1 : index + 2] * (257 - length)
            index += 2
        if len(out) > MAX_PDF_STREAM_DECODED:
            raise _TooMuchData
    _spend(len(out))
    return bytes(out)


pdftypes.zlib = _BoundedZlib  # type: ignore[assignment]
pdftypes.lzwdecode = _lzwdecode
pdftypes.rldecode = _rldecode


@contextmanager
def _decoding(spent: list[int]) -> Iterator[None]:
    token = _DECODED.set(spent)
    try:
        yield
    finally:
        _DECODED.reset(token)


# --- reading a page ---------------------------------------------------------------------


class _Budget:
    """What one read may still spend: its time, and on the current page its items and content."""

    def __init__(self) -> None:
        self.deadline = time.monotonic() + MAX_PDF_GEOMETRY_SECONDS
        self.decoded = [0]
        self.page = 0
        self.items = 0
        self.content = 0

    def start(self, page: int, content: int) -> None:
        self.page, self.items, self.content = page, 0, 0
        self.add_content(content)

    def tick(self) -> None:
        self.items += 1
        if self.items > MAX_PDF_PAGE_ITEMS:
            raise _Stop(STOPPED_DENSE.format(page=self.page))
        self.check_time()

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise _Stop(STOPPED_SLOW.format(page=self.page))

    def add_content(self, size: int) -> None:
        """The page's own content and every form it draws, each time it draws it."""
        self.content += size
        if self.content > text_read.MAX_PDF_PAGE_CONTENT:
            raise _Stop(STOPPED_DENSE.format(page=self.page))


def _colour(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        value = (value,)
    if not isinstance(value, (list, tuple)) or not all(isinstance(part, (int, float)) for part in value):
        return None
    if len(value) == 1:
        red = green = blue = value[0]
    elif len(value) == 3:
        red, green, blue = value
    elif len(value) == 4:  # CMYK, naively: enough to tell colours apart
        cyan, magenta, yellow, black = value
        red, green, blue = ((1 - part) * (1 - black) for part in (cyan, magenta, yellow))
    else:
        return None
    return "#" + "".join(f"{round(min(max(float(part), 0.0), 1.0) * 255):02x}" for part in (red, green, blue))


class _Device(PDFLayoutAnalyzer):
    """pdfminer's layout device, keeping each character as it is drawn (with the text
    render mode, which pdfminer leaves out) and counting everything against the budget."""

    def __init__(self, rsrcmgr: PDFResourceManager, budget: _Budget) -> None:
        super().__init__(rsrcmgr, laparams=None)
        self.budget = budget
        self.chars: list[tuple[LTChar, float, bool]] = []
        self.layout: LTPage | None = None
        self._render = 0
        self._depth = 0

    def render_string(self, textstate: Any, seq: Any, ncs: Any, graphicstate: Any) -> None:
        self._render = textstate.render
        super().render_string(textstate, seq, ncs, graphicstate)

    def render_char(self, matrix: Any, font: Any, fontsize: float, scaling: float, rise: float, cid: int, ncs: Any, graphicstate: Any) -> float:
        self.budget.tick()
        try:
            text = font.to_unichr(cid)
        except PDFUnicodeNotDefined:
            text = self.handle_undefined_char(font, cid)
        item = LTChar(matrix, font, fontsize, scaling, rise, text, font.char_width(cid), font.char_disp(cid), ncs, graphicstate)
        # The size as drawn: the font size scaled by the text's own up direction, which
        # pdfminer's `size` (the box's height) isn't on a turned page or for turned text.
        size = fontsize * math.hypot(matrix[2], matrix[3])
        self.chars.append((item, size, self._render in (3, 7)))
        return item.adv

    def paint_path(self, gstate: Any, stroke: bool, fill: bool, evenodd: bool, path: Any) -> None:
        self.budget.tick()
        super().paint_path(gstate, stroke, fill, evenodd, path)

    def begin_figure(self, name: str, bbox: Any, matrix: Any) -> None:
        self.budget.tick()
        self._depth += 1
        if self._depth > MAX_PDF_NESTING:
            raise _Stop(STOPPED_DEEP.format(page=self.budget.page))
        super().begin_figure(name, bbox, matrix)

    def end_figure(self, name: str) -> None:
        self._depth -= 1
        super().end_figure(name)

    def receive_layout(self, ltpage: LTPage) -> None:
        self.layout = ltpage


class _Interpreter(PDFPageInterpreter):
    device: _Device

    def do_q(self) -> None:
        self.device.budget.check_time()  # saving states draws nothing, but takes time all the same
        if len(self.gstack) >= MAX_PDF_NESTING:
            raise _Stop(STOPPED_DEEP.format(page=self.device.budget.page))
        super().do_q()

    def do_Do(self, xobjid_arg: Any) -> None:
        self.device.budget.tick()
        xobj = self.xobjmap.get(literal_name(xobjid_arg))
        if xobj is not None:
            stream = stream_value(xobj)
            if stream.get("Subtype") is LITERAL_FORM:
                self.device.budget.add_content(len(stream.get_data()))
        super().do_Do(xobjid_arg)


def _transform(rotation: int, mediabox: Any) -> Callable[[float, float], tuple[float, float]]:
    """PDF coordinates to the shown page's, as pdfminer turns them (PDFPageInterpreter.process_page)."""
    x0, y0, x1, y1 = mediabox
    a, b, c, d, e, f = {
        90: (0, -1, 1, 0, -y0, x1),
        180: (-1, 0, 0, -1, x1, y1),
        270: (0, 1, -1, 0, y1, -x0),
    }.get(rotation, (1, 0, 0, 1, -x0, -y0))
    return lambda x, y: (a * x + c * y + e, b * x + d * y + f)


def _box(x0: float, y0: float, x1: float, y1: float, height: float) -> Box:
    return (round(min(x0, x1), 2), round(height - max(y0, y1), 2), round(max(x0, x1), 2), round(height - min(y0, y1), 2))


def _rect(value: Any) -> tuple[float, float, float, float] | None:
    value = resolve1(value)
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(resolve1(part)) for part in value)
    except (TypeError, ValueError):
        return None
    return (round(min(x0, x1), 2), round(min(y0, y1), 2), round(max(x0, x1), 2), round(max(y0, y1), 2))


def _text(value: Any) -> str:
    value = resolve1(value)
    if isinstance(value, bytes):
        if value.startswith((b"\xfe\xff", b"\xff\xfe")):
            return value.decode("utf-16", errors="replace")
        return value.decode("latin-1")
    if isinstance(value, PSLiteral):
        return literal_name(value)
    return str(value) if value is not None else ""


def _link(annotation: dict, pages: dict[int, int], document: PDFDocument) -> tuple[str, str | int | None]:
    from app.security.links import safe_href

    action = resolve1(annotation.get("A"))
    destination = annotation.get("Dest")
    if isinstance(action, dict):
        kind = _text(action.get("S"))
        if kind == "URI":
            address = _text(action.get("URI"))
            safe = safe_href(address)
            return ("web", safe) if safe else ("unsafe", None)
        if kind != "GoTo":
            return "other", None
        destination = action.get("D")
    destination = resolve1(destination)
    if isinstance(destination, (bytes, PSLiteral)):  # a named destination
        try:
            destination = resolve1(document.get_dest(_text(destination)))
        except Exception:  # noqa: BLE001 -- a name the file doesn't define: a link to nowhere known
            destination = None
    if isinstance(destination, dict):
        destination = resolve1(destination.get("D"))
    target = None
    if isinstance(destination, list) and destination:
        reference = destination[0]
        target = pages.get(getattr(reference, "objid", -1))
    return "internal", target


def _annotations(page: PDFPage, pages: dict[int, int], document: PDFDocument, to_shown: Callable, height: float, budget: _Budget) -> list[PdfAnnotation]:
    found: list[PdfAnnotation] = []
    annotations = resolve1(page.annots)
    if not isinstance(annotations, list):
        return found
    for reference in annotations:
        budget.tick()
        annotation = resolve1(reference)
        if not isinstance(annotation, dict):
            continue
        rect = _rect(annotation.get("Rect"))
        box = None
        if rect is not None:
            (ax, ay), (bx, by) = to_shown(rect[0], rect[1]), to_shown(rect[2], rect[3])
            box = _box(ax, ay, bx, by, height)
        kind = _text(annotation.get("Subtype")) or "Unknown"
        if kind == "Link":
            link, target = _link(annotation, pages, document)
            found.append(PdfAnnotation(kind=kind, box=box, link=link, target=target))
        else:
            found.append(PdfAnnotation(kind=kind[:50], box=box))
    return found


def _collect(item: LTItem, page: PdfPage, height: float) -> None:
    for child in item:  # type: ignore[attr-defined]
        if isinstance(child, LTFigure):
            _collect(child, page, height)
        elif isinstance(child, LTImage):
            width_px, height_px = child.srcsize
            pixels = (int(width_px), int(height_px)) if isinstance(width_px, int) and isinstance(height_px, int) else None
            page.images.append(PdfImage(box=_box(child.x0, child.y0, child.x1, child.y1, height), pixels=pixels))
        elif isinstance(child, LTCurve):
            path = PdfPath(
                box=_box(child.x0, child.y0, child.x1, child.y1, height),
                width=round(float(child.linewidth or 0), 2),
                stroke=_colour(child.stroking_color) if child.stroke else None,
                fill=_colour(child.non_stroking_color) if child.fill else None,
            )
            (page.lines if isinstance(child, LTLine) else page.rects if isinstance(child, LTRect) else page.curves).append(path)


def _read_page(number: int, page: PDFPage, rsrcmgr: PDFResourceManager, pages: dict[int, int], document: PDFDocument, budget: _Budget) -> PdfPage:
    contents = sum(len(stream_value(stream).get_data()) for stream in page.contents)
    budget.start(number, contents)
    device = _Device(rsrcmgr, budget)
    _Interpreter(rsrcmgr, device).process_page(page)
    layout = device.layout
    assert layout is not None
    rotation = page.rotate if page.rotate in (90, 180, 270) else 0
    width, height = float(layout.width), float(layout.height)
    boxes = {"media": _rect(page.mediabox), "crop": _rect(page.cropbox)}
    for name, key in (("bleed", "BleedBox"), ("trim", "TrimBox"), ("art", "ArtBox")):
        if key in page.attrs:
            boxes[name] = _rect(page.attrs[key])
    result = PdfPage(
        number=number, width=round(width, 2), height=round(height, 2), rotation=rotation, boxes={k: v for k, v in boxes.items() if v is not None}
    )
    for char, size, invisible in device.chars:
        result.chars.append(
            PdfChar(
                text=char.get_text(),
                font=str(char.fontname)[:100],
                size=round(size, 2),
                colour=_colour(char.graphicstate.ncolor),
                box=_box(char.x0, char.y0, char.x1, char.y1, height),
                invisible=invisible,
                upright=bool(char.upright),
            )
        )
    _collect(layout, result, height)
    result.annotations = _annotations(page, pages, document, _transform(rotation, page.mediabox), height, budget)
    return result


# --- the file's structure -----------------------------------------------------------------

_FIELD_KINDS = {"/Tx": "text", "/Btn": "button", "/Ch": "choice", "/Sig": "signature"}


def _structure(reader: PdfReader, geometry: PdfGeometry, deadline: float) -> None:
    """The outline, form fields and metadata, through pypdf; what is damaged is said, not fatal."""
    try:
        info = reader.metadata or {}
        geometry.metadata = {str(key).lstrip("/")[:100]: str(value)[:500] for key, value in info.items()}
        geometry.xmp = "/Metadata" in reader.trailer["/Root"]

        def walk(entries: list, level: int) -> None:
            for entry in entries:
                if time.monotonic() > deadline:
                    raise TimeoutError
                if isinstance(entry, list):
                    if level < MAX_PDF_NESTING:
                        walk(entry, level + 1)
                    continue
                geometry.outline_count += 1
                if len(geometry.outline) < MAX_PDF_LISTED:
                    page = reader.get_destination_page_number(entry)
                    geometry.outline.append(PdfOutlineEntry(title=str(entry.title or "")[:200], level=level, page=page + 1 if page is not None and page >= 0 else None))

        walk(reader.outline, 0)
        for name, value in (reader.get_fields() or {}).items():
            if "/FT" not in value:  # a group of fields, not a field
                continue
            geometry.field_count += 1
            if len(geometry.fields) < MAX_PDF_LISTED:
                geometry.fields.append(PdfFormField(name=str(name)[:200], kind=_FIELD_KINDS.get(str(value["/FT"]), "other")))
    except Exception as exc:  # noqa: BLE001 -- a damaged outline or form costs the inspection that part, never the import
        logger.info("A PDF's structure couldn't be read: %s at %s", type(exc).__name__, where(exc))
        geometry.structure_problem = DAMAGED_STRUCTURE


# --- the read -----------------------------------------------------------------------------


def read_pdf_geometry(file_bytes: bytes, on_page: Callable[[PdfPage], None] | None = None) -> PdfGeometry:
    """Where everything is on the PDF's pages. Each page read whole goes to `on_page`
    when given (so a long file's characters aren't all held at once), else into
    `pages`. PdfParseError for a file the text read would refuse, or with more objects
    than MAX_PDF_OBJECTS."""
    budget = _Budget()
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            raise PdfParseError(PASSWORD)
        page_count = len(reader.pages)
        if page_count > text_read.MAX_PDF_PAGES:
            raise PdfParseError(f"This PDF has more than {text_read.MAX_PDF_PAGES} pages, more than can be imported at once.")
        geometry = PdfGeometry(page_count=page_count, version=reader.pdf_header.removeprefix("%PDF-")[:10] or None, metadata={}, xmp=False, outline=[], outline_count=0, fields=[], field_count=0)
        with _decoding(budget.decoded):
            parser = PDFParser(io.BytesIO(file_bytes))
            document = PDFDocument(parser)
            objects = sum(len(list(xref.get_objids())) for xref in document.xrefs)
            if objects > MAX_PDF_OBJECTS:
                raise PdfParseError(TOO_MUCH)
            pages_in_order = islice(PDFPage.create_pages(document), text_read.MAX_PDF_PAGES)
            numbers = {page.pageid: number for number, page in enumerate(pages_in_order, start=1)}
    except PdfParseError:
        raise
    except (LimitReachedError, _TooMuchData) as exc:
        raise PdfParseError(TOO_MUCH) from exc
    except Exception as exc:  # noqa: BLE001 -- whatever a malformed file makes either library throw: a refusal, never a 500
        logger.info("Unreadable PDF geometry: %s at %s", type(exc).__name__, where(exc))
        raise PdfParseError(INVALID) from exc

    _structure(reader, geometry, budget.deadline)
    rsrcmgr = PDFResourceManager(caching=True)
    pages = PDFPage.create_pages(document)
    number = 0
    while True:
        number += 1
        if number > text_read.MAX_PDF_PAGES:
            break
        try:
            with _decoding(budget.decoded):
                page = next(pages, None)
                if page is None:
                    break
                if time.monotonic() > budget.deadline:
                    raise _Stop(STOPPED_SLOW.format(page=number))
                read = _read_page(number, page, rsrcmgr, numbers, document, budget)
        except _Stop as stop:
            geometry.stopped = stop.message
            break
        except _TooMuchData:
            geometry.stopped = STOPPED_DATA.format(page=number)
            break
        except Exception as exc:  # noqa: BLE001 -- one damaged page costs that page, not the read
            logger.info("A PDF page couldn't be read for its geometry: %s at %s", type(exc).__name__, where(exc))
            geometry.unread[number] = DAMAGED_PAGE
            continue
        geometry.read_pages += 1
        if on_page is not None:
            on_page(read)
        else:
            geometry.pages.append(read)
    return geometry
