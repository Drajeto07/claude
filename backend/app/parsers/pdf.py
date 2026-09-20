import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfParseError(Exception):
    """Raised when the uploaded bytes aren't a readable, text-based PDF."""


def extract_pdf_text(file_bytes: bytes) -> str:
    """Extract plain text from a text-based PDF (spec TC-003 scope: no OCR,
    no support for scanned/image-only PDFs)."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            raise PdfParseError("This PDF is password-protected and can't be read.")
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as exc:
        raise PdfParseError("This file isn't a valid PDF.") from exc

    if not text.strip():
        raise PdfParseError(
            "No extractable text found in this PDF -- scanned/image-based PDFs aren't supported yet."
        )
    return text
