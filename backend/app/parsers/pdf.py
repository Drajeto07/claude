import io
import logging
import re
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TypeVar

from pypdf import PdfReader
from pypdf.errors import LimitReachedError

from app.parsers.trace import where

T = TypeVar("T")

logger = logging.getLogger(__name__)

# More pages than a document here plausibly has; a file past it is refused
# before its text is read (each page's extraction costs time and memory).
MAX_PDF_PAGES = 1000
# Reading a page's text takes longer the more is drawn on it, and faster than in step
# with it: a page is read only up to this much content (about 13 s at worst), and a file
# only for this long in all -- checked between pages (SEC-013).
MAX_PDF_PAGE_CONTENT = 2 * 1024 * 1024
MAX_PDF_SECONDS = 60.0

INVALID = "This file isn't a valid PDF."
PASSWORD = "This PDF is password-protected and can't be read."
TOO_MUCH = "This PDF holds more data than can be read safely."
NO_TEXT = "No extractable text found in this PDF -- scanned/image-based PDFs aren't supported yet."
DAMAGED = "This PDF is damaged and its text can't be read."
PARTLY_DAMAGED = "This PDF is damaged: part of its text can't be read."
TOO_DENSE = "This PDF has a page with more drawn on it than can be read here. Only its text would be imported: try a copy saved as text."
TOO_SLOW = "This PDF takes too long to read here. Split it into smaller files."


class PdfParseError(Exception):
    """Raised when the uploaded bytes aren't a readable, text-based PDF."""


@dataclass(frozen=True)
class PdfText:
    text: str
    # Damage pypdf worked around that can leave text out -- a stream that didn't
    # decode, an object that isn't there (SEC-011): `text` is what could be read.
    damaged: bool


# What pypdf says while this context reads a PDF; None while it reads none.
_REPAIRS: ContextVar[list[logging.LogRecord] | None] = ContextVar("pdf_repairs", default=None)


class _Repairs(logging.Handler):
    """pypdf's warnings, kept for the read they belong to -- and never logged: their
    messages can quote the file."""

    def emit(self, record: logging.LogRecord) -> None:
        repairs = _REPAIRS.get()
        if repairs is not None:
            repairs.append(record)


_PYPDF = logging.getLogger("pypdf")
_PYPDF.addHandler(_Repairs(logging.WARNING))
_PYPDF.propagate = False

# pypdf's words for damage that may have cost text, as against repairs that cost
# nothing (a wrong xref offset, a /Prev chain that loops): any trouble decoding a
# stream, and these. Pinned to pypdf 6.19 by tests/test_malformed_pdfs.py.
_LOSS = re.compile(
    r"output will be incomplete|may be missing|might not be read|object \d+ \d+ not defined|object not found"
    r"|cannot be read|can not find reference|unable to decode|check if output is ok",
    re.I,
)


def _loses_text(record: logging.LogRecord) -> bool:
    return record.name == "pypdf.filters" or _LOSS.search(record.getMessage()) is not None


def read_pdf(file_bytes: bytes) -> PdfText:
    """The text of a text-based PDF (spec TC-003 scope: no OCR, no support for
    scanned/image-only PDFs), and whether damage may have left some out. The file
    is untrusted: pypdf stops a stream that would decompress past its limits, and
    anything a malformed file makes it throw is a refusal, never a crash."""
    repairs: list[logging.LogRecord] = []
    token = _REPAIRS.set(repairs)
    try:
        text = _read(file_bytes)
    finally:
        _REPAIRS.reset(token)
    lost = [record for record in repairs if _loses_text(record)]
    if repairs:  # what kind, never what they say
        logger.info("A PDF needed %d repairs, %d of them losing text (%s)", len(repairs), len(lost), ", ".join(sorted({r.name for r in repairs})))
    if not text.strip():
        raise PdfParseError(DAMAGED if lost else NO_TEXT)
    return PdfText(text=text, damaged=bool(lost))


def _open(file_bytes: bytes) -> PdfReader:
    reader = PdfReader(io.BytesIO(file_bytes))
    if reader.is_encrypted:
        raise PdfParseError(PASSWORD)
    if len(reader.pages) > MAX_PDF_PAGES:
        raise PdfParseError(f"This PDF has more than {MAX_PDF_PAGES} pages, more than can be imported at once.")
    return reader


def _refusing(read: Callable[[], T]) -> T:
    """Whatever a malformed file makes pypdf throw is a refusal, never a 500 (SEC-011)."""
    try:
        return read()
    except PdfParseError:
        raise
    except LimitReachedError as exc:
        raise PdfParseError(TOO_MUCH) from exc
    except Exception as exc:  # noqa: BLE001
        logger.info("Unreadable PDF: %s at %s", type(exc).__name__, where(exc))
        raise PdfParseError(INVALID) from exc


def pdf_page_count(file_bytes: bytes) -> int:
    """How many pages an import of this PDF reads (what the plan's PDF pages count,
    PLAN-001), before any is read; refused exactly as read_pdf would refuse it."""
    return _refusing(lambda: len(_open(file_bytes).pages))


def _read(file_bytes: bytes) -> str:
    def read() -> str:
        reader = _open(file_bytes)
        deadline = time.monotonic() + MAX_PDF_SECONDS
        texts = []
        for page in reader.pages:
            if time.monotonic() > deadline:
                raise PdfParseError(TOO_SLOW)
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > MAX_PDF_PAGE_CONTENT:
                raise PdfParseError(TOO_DENSE)
            texts.append(page.extract_text() or "")
        return "\n\n".join(texts)

    return _refusing(read)


def extract_pdf_text(file_bytes: bytes) -> str:
    """All of a PDF's text, or a refusal: for an instructions file, which has no
    report to say part of it is missing."""
    read = read_pdf(file_bytes)
    if read.damaged:
        raise PdfParseError(PARTLY_DAMAGED)
    return read.text
