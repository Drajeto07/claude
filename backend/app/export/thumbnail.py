"""A project's thumbnail (SmartDoc 2.0, UI review 2026-10-14): the real first page, as the PDF
export draws it, made into a small picture -- never invented content.

Only the first blocks are laid out (a first page holds no more than these), so a long document
costs no more than a short one; pdfium draws just that page. The result is cached in storage by
the document's revision (services/document_service.py), so a document is drawn once per change,
not on every dashboard visit."""

import io
import threading
from collections.abc import Mapping

import pypdfium2
from PIL import Image

from app.export.pdf_export import build_pdf
from app.models.document import Document

# Enough for the densest first page (short lines, no pictures); more only slows the layout.
FIRST_PAGE_BLOCKS = 60
# Twice a card's width on a wide screen, so it stays sharp on high-density displays.
WIDTH_PX = 480
# The card shows the top of the page: width 4, height 3.
ASPECT = 3 / 4

# PDFium is not thread-safe (pypdfium2's own documentation): two threads inside it at once crash the
# whole process (B-028). Thumbnails are drawn in worker threads (asyncio.to_thread), so every PDFium
# call below holds this one lock. One per process is enough: each process loads its own PDFium.
_PDFIUM_LOCK = threading.Lock()


def first_page_document(document: Document) -> Document:
    return document.model_copy(update={"elements": document.elements[:FIRST_PAGE_BLOCKS]})


def _first_page_image(pdf_bytes: bytes) -> Image.Image:
    """Page 1 drawn WIDTH_PX wide, as an RGB image of its own. Everything PDFium made for it -- bitmap,
    page, document, closed in that order, on errors too -- is gone before the lock is let go."""
    with _PDFIUM_LOCK:
        pdf = pypdfium2.PdfDocument(pdf_bytes)
        try:
            page = pdf[0]
            try:
                bitmap = page.render(scale=WIDTH_PX / page.get_width())
                try:
                    # to_pil() may share the bitmap's memory; convert() always returns a copy of the pixels.
                    return bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            pdf.close()


def render_thumbnail(document: Document, assets: Mapping[str, bytes] | None = None) -> bytes:
    """The top of the document's first page as a PNG, WIDTH_PX wide."""
    pdf_bytes = build_pdf(first_page_document(document), assets=assets or {}, include_page_numbers=False)
    image = _first_page_image(pdf_bytes)
    top = image.crop((0, 0, image.width, min(image.height, round(image.width * ASPECT))))
    out = io.BytesIO()
    # A palette keeps text crisp and the file small (a few tens of kB).
    top.quantize(colors=128, method=Image.Quantize.MEDIANCUT).save(out, format="PNG", optimize=True)
    return out.getvalue()
