import io
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import LimitReachedError

from app.parsers.trace import where

logger = logging.getLogger(__name__)

# More pages than a document here plausibly has; a file past it is refused
# before its text is read (each page's extraction costs time and memory).
MAX_PDF_PAGES = 1000

INVALID = "This file isn't a valid PDF."
PASSWORD = "This PDF is password-protected and can't be read."
TOO_MUCH = "This PDF holds more data than can be read safely."
NO_TEXT = "No extractable text found in this PDF -- scanned/image-based PDFs aren't supported yet."
DAMAGED = "This PDF is damaged and its text can't be read."
PARTLY_DAMAGED = "This PDF is damaged: part of its text can't be read."


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


def _read(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            raise PdfParseError(PASSWORD)
        if len(reader.pages) > MAX_PDF_PAGES:
            raise PdfParseError(f"This PDF has more than {MAX_PDF_PAGES} pages, more than can be imported at once.")
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfParseError:
        raise
    except LimitReachedError as exc:
        raise PdfParseError(TOO_MUCH) from exc
    except Exception as exc:  # noqa: BLE001 -- whatever a malformed file makes pypdf throw: a refusal, never a 500 (SEC-011)
        logger.info("Unreadable PDF: %s at %s", type(exc).__name__, where(exc))
        raise PdfParseError(INVALID) from exc


def extract_pdf_text(file_bytes: bytes) -> str:
    """All of a PDF's text, or a refusal: for an instructions file, which has no
    report to say part of it is missing."""
    read = read_pdf(file_bytes)
    if read.damaged:
        raise PdfParseError(PARTLY_DAMAGED)
    return read.text
