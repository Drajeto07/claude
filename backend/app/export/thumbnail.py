"""A project's thumbnail (SmartDoc 2.0, UI review 2026-10-14): the real first page, as the PDF
export draws it, made into a small picture -- never invented content.

Only the first blocks are laid out (a first page holds no more than these), so a long document
costs no more than a short one; pdfium draws just that page. The result is cached in storage by
the document's revision (services/document_service.py), so a document is drawn once per change,
not on every dashboard visit."""

import io
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


def first_page_document(document: Document) -> Document:
    return document.model_copy(update={"elements": document.elements[:FIRST_PAGE_BLOCKS]})


def render_thumbnail(document: Document, assets: Mapping[str, bytes] | None = None) -> bytes:
    """The top of the document's first page as a PNG, WIDTH_PX wide."""
    pdf_bytes = build_pdf(first_page_document(document), assets=assets or {}, include_page_numbers=False)
    pdf = pypdfium2.PdfDocument(pdf_bytes)
    try:
        page = pdf[0]
        try:
            scale = WIDTH_PX / page.get_width()
            image: Image.Image = page.render(scale=scale).to_pil()
        finally:
            page.close()
    finally:
        pdf.close()
    image = image.convert("RGB")
    top = image.crop((0, 0, image.width, min(image.height, round(image.width * ASPECT))))
    out = io.BytesIO()
    # A palette keeps text crisp and the file small (a few tens of kB).
    top.quantize(colors=128, method=Image.Quantize.MEDIANCUT).save(out, format="PNG", optimize=True)
    return out.getvalue()
