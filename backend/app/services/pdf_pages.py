"""PDF page operations, a service of their own (tracker PDF-020): reorder, rotate, delete,
duplicate and extract pages, split a PDF into parts, merge PDFs into one -- on the PDF's bytes,
not a document of the app's. pypdf copies the pages themselves (their content, fonts, pictures,
annotations), never the file's catalogue: no document-level JavaScript, open action, embedded
file or form comes along, and an annotation's action is kept only when it goes to a place in
the document or to an address a link may have (security/links.py, SEC-014).

Each input is read as an import reads one (parsers/pdf.py): a password-protected or damaged file,
or one of more than MAX_PDF_PAGES pages, is refused (PdfParseError). What is asked of it is
checked before anything is written (PdfPagesError, its message the person's to read). Pages are
numbered from 1, and each operation's page numbers are the pages as the operations before it
left them."""

import io
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from app.models.base import ApiModel
from app.parsers.pdf import MAX_PDF_PAGES, _open, _refusing
from app.security.links import safe_href

MAX_OPERATIONS = 100
MAX_MERGED_FILES = 20
MAX_SPLIT_PARTS = 100


class PdfPagesError(ValueError):
    """What was asked of the PDF can't be done: which pages, or how many."""


Pages = Annotated[list[Annotated[int, Field(ge=1)]], Field(min_length=1, max_length=MAX_PDF_PAGES)]


class Reorder(ApiModel):
    op: Literal["reorder"]
    order: Pages  # every page, once each, in its new order


class Rotate(ApiModel):
    op: Literal["rotate"]
    pages: Pages
    degrees: Literal[90, 180, 270]  # clockwise


class Delete(ApiModel):
    op: Literal["delete"]
    pages: Pages


class Duplicate(ApiModel):
    op: Literal["duplicate"]
    pages: Pages  # each followed by its copy


class Extract(ApiModel):
    op: Literal["extract"]
    pages: Pages  # these alone, in this order


Operation = Annotated[Reorder | Rotate | Delete | Duplicate | Extract, Field(discriminator="op")]


class PageInfo(ApiModel):
    number: int
    widthPt: float
    heightPt: float
    rotation: int


@dataclass(frozen=True)
class _Page:
    source: int  # its index in the file
    rotation: int = 0  # clockwise, added to its own


def page_info(data: bytes) -> list[PageInfo]:
    """Each page's size (as shown, points) and rotation."""

    def read() -> list[PageInfo]:
        reader = _open(data)
        found = []
        for number, page in enumerate(reader.pages, start=1):
            box = page.mediabox
            found.append(PageInfo(number=number, widthPt=round(float(box.width), 2), heightPt=round(float(box.height), 2), rotation=page.rotation % 360))
        return found

    return _refusing(read)


def _checked(pages: list[int], count: int, *, distinct: bool = False) -> list[int]:
    """The 0-based indices of 1-based page numbers, each one a page there is."""
    wrong = sorted({page for page in pages if page > count})
    if wrong:
        listed = ", ".join(str(page) for page in wrong[:5])
        raise PdfPagesError(f"This PDF has {count} page{'s' if count != 1 else ''}: there is no page {listed}.")
    if distinct and len(set(pages)) != len(pages):
        raise PdfPagesError("A page is named more than once.")
    return [page - 1 for page in pages]


def _applied(pages: list[_Page], operation) -> list[_Page]:
    count = len(pages)
    if isinstance(operation, Reorder):
        order = _checked(operation.order, count, distinct=True)
        if len(order) != count:
            raise PdfPagesError(f"A new order names every page once: this PDF has {count}.")
        return [pages[index] for index in order]
    if isinstance(operation, Rotate):
        chosen = set(_checked(operation.pages, count))
        return [_Page(page.source, (page.rotation + operation.degrees) % 360) if index in chosen else page for index, page in enumerate(pages)]
    if isinstance(operation, Delete):
        gone = set(_checked(operation.pages, count))
        if len(gone) >= count:
            raise PdfPagesError("A PDF keeps one page at least: not every page can be deleted.")
        return [page for index, page in enumerate(pages) if index not in gone]
    if isinstance(operation, Duplicate):
        copied = set(_checked(operation.pages, count))
        return [each for index, page in enumerate(pages) for each in ((page, page) if index in copied else (page,))]
    return [pages[index] for index in _checked(operation.pages, count)]  # Extract


def _safe_action(action) -> bool:
    """An annotation's action a page may keep: to a place in the document, or to a link's address."""
    try:
        kind = action.get("/S")
        if kind in ("/GoTo",):
            return True
        if kind == "/URI":
            return safe_href(str(action.get("/URI") or "")) is not None
    except Exception:  # noqa: BLE001 -- an action that can't be read isn't kept
        return False
    return False


def _cleaned(page) -> None:
    """A page with no actions of its own (/AA) and no annotation action but safe ones."""
    if "/AA" in page:
        del page[NameObject("/AA")]
    for annotation in page.get("/Annots") or []:
        try:
            item = annotation.get_object()
        except Exception:  # noqa: BLE001
            continue
        if "/AA" in item:
            del item[NameObject("/AA")]
        if "/A" in item and not _safe_action(item["/A"].get_object()):
            del item[NameObject("/A")]


def _written(reader: PdfReader, pages: list[_Page]) -> bytes:
    """The pages copied from the file, with their rotation, as a PDF. A page used twice is two
    pages (pypdf gives each its own page dictionary; they share only their content)."""
    if len(pages) > MAX_PDF_PAGES:
        raise PdfPagesError(f"The result would have more than {MAX_PDF_PAGES} pages.")
    writer = PdfWriter()
    for page in pages:
        added = writer.add_page(reader.pages[page.source])
        if page.rotation:
            added.rotate(page.rotation)
        _cleaned(added)
    return _bytes(writer)


def _bytes(writer: PdfWriter) -> bytes:
    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)  # what the copies share, once
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def apply_operations(data: bytes, operations: list) -> bytes:
    """The PDF with the operations done, one after the other."""
    if not operations:
        raise PdfPagesError("Say what to do with the pages.")
    if len(operations) > MAX_OPERATIONS:
        raise PdfPagesError(f"At most {MAX_OPERATIONS} operations at once.")

    def run() -> bytes:
        reader = _open(data)
        pages = [_Page(index) for index in range(len(reader.pages))]
        for operation in operations:
            pages = _applied(pages, operation)
        return _written(reader, pages)

    return _refusing_but(run)


def split(data: bytes, ranges: list[tuple[int, int]] | None = None, every: int | None = None) -> list[bytes]:
    """The PDF in parts: each range of pages (first, last; 1-based, inclusive), or every `every` pages."""

    def run() -> list[bytes]:
        reader = _open(data)
        count = len(reader.pages)
        if (ranges is None) == (every is None):
            raise PdfPagesError("Split by ranges of pages, or every so many pages.")
        parts = [(start, min(start + every - 1, count)) for start in range(1, count + 1, every)] if every else list(ranges or [])
        if not parts or len(parts) > MAX_SPLIT_PARTS:
            raise PdfPagesError(f"A PDF splits into 1 to {MAX_SPLIT_PARTS} parts.")
        for first, last in parts:
            if first > last:
                raise PdfPagesError(f"Pages {first}-{last}: the first page comes before the last.")
            _checked([first, last], count)
        return [_written(reader, [_Page(index) for index in range(first - 1, last)]) for first, last in parts]

    return _refusing_but(run)


def merge(files: list[bytes]) -> bytes:
    """The PDFs one after the other, as one."""
    if not 2 <= len(files) <= MAX_MERGED_FILES:
        raise PdfPagesError(f"Merge 2 to {MAX_MERGED_FILES} PDFs.")

    def run() -> bytes:
        readers = [_open(data) for data in files]
        if sum(len(reader.pages) for reader in readers) > MAX_PDF_PAGES:
            raise PdfPagesError(f"The result would have more than {MAX_PDF_PAGES} pages.")
        writer = PdfWriter()
        for reader in readers:
            for page in reader.pages:
                _cleaned(writer.add_page(page))
        return _bytes(writer)

    return _refusing_but(run)


def _refusing_but(run):
    """As parsers/pdf._refusing -- whatever a malformed file makes pypdf throw is a refusal --
    with what was wrongly asked (PdfPagesError) passed on as it is."""
    asked: list[PdfPagesError] = []

    def guarded():
        try:
            return run()
        except PdfPagesError as exc:
            asked.append(exc)
            return None

    result = _refusing(guarded)
    if asked:
        raise asked[0]
    return result
