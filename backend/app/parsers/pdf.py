import io
import logging

from pypdf import PdfReader
from pypdf.errors import LimitReachedError, PyPdfError

logger = logging.getLogger(__name__)

# More pages than a document here plausibly has; a file past it is refused
# before its text is read (each page's extraction costs time and memory).
MAX_PDF_PAGES = 1000


class PdfParseError(Exception):
    """Raised when the uploaded bytes aren't a readable, text-based PDF."""


def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract plain text from a text-based PDF (spec TC-003 scope: no OCR,
    no support for scanned/image-only PDFs). The file is untrusted: pypdf
    stops a stream that would decompress past its limits, and anything a
    malformed file makes it throw is a refusal, never a crash."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            raise PdfParseError("This PDF is password-protected and can't be read.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise PdfParseError(f"This PDF has more than {MAX_PDF_PAGES} pages, more than can be imported at once.")
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except LimitReachedError as exc:
        raise PdfParseError("This PDF holds more data than can be read safely.") from exc
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as exc:
        logger.info("Unreadable PDF (%s)", type(exc).__name__)
        raise PdfParseError("This file isn't a valid PDF.") from exc

    if not text.strip():
        raise PdfParseError(
            "No extractable text found in this PDF -- scanned/image-based PDFs aren't supported yet."
        )
    return text
