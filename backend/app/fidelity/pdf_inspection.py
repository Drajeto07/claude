"""The PDF inspection of an import (tracker PDF-012; the model is models/pdf_inspection.py):
the geometry read page by page, each page summed up as it is read and classified, so a
long file's characters are never all held at once. And what it means for the import
report: pages whose words the text import couldn't have (scanned), and pages whose
words came from a text layer over a scan (hybrid)."""

import logging
from collections import Counter
from collections.abc import Callable

from app.fidelity.report import FidelityItem, FidelityPolicy
from app.models.pdf_inspection import (
    PdfFontUse,
    PdfFormField,
    PdfImageBox,
    PdfInspection,
    PdfLinkCounts,
    PdfOutlineItem,
    PdfPageEvidence,
    PdfPageInspection,
    PdfPageNotRead,
)
from app.parsers.pdf import PdfParseError
from app.parsers.pdf_classify import HYBRID, SCANNED, classify_page, document_kind, font_name
from app.parsers.pdf_geometry import PdfPage, read_pdf_geometry
from app.parsers.trace import where

logger = logging.getLogger(__name__)

# The most of each list a page's summary keeps.
_FONTS, _COLOURS, _IMAGES, _SIZES = 20, 20, 50, 10
FAILED = "This PDF couldn't be inspected."


def _page(page: PdfPage) -> PdfPageInspection:
    kind = classify_page(page)
    evidence = kind.evidence
    fonts: Counter[str] = Counter()
    sizes: dict[str, set[float]] = {}
    colours: Counter[str] = Counter()
    for char in page.chars:
        if not char.text.strip():
            continue
        name = font_name(char.font)
        fonts[name] += 1
        sizes.setdefault(name, set()).add(char.size)
        if char.colour is not None and not char.invisible:
            colours[char.colour] += 1
    links = Counter(link.link for link in page.links)
    return PdfPageInspection(
        number=page.number,
        kind=kind.kind,
        confidence=kind.confidence,
        reason=kind.reason,
        evidence=PdfPageEvidence(
            textCoverage=evidence.text_coverage,
            imageCoverage=evidence.image_coverage,
            visibleCharacters=evidence.visible_chars,
            invisibleCharacters=evidence.invisible_chars,
            fonts=list(evidence.fonts)[:50],
        ),
        width=page.width,
        height=page.height,
        rotation=page.rotation,
        boxes={name: list(box) for name, box in page.boxes.items()},
        characters=len(page.chars),
        fonts=[PdfFontUse(name=name[:100], sizes=sorted(sizes[name])[:_SIZES], characters=count) for name, count in fonts.most_common(_FONTS)],
        textColours=[colour for colour, _ in colours.most_common(_COLOURS)],
        lines=len(page.lines),
        rectangles=len(page.rects),
        curves=len(page.curves),
        imageCount=len(page.images),
        images=[
            PdfImageBox(box=list(image.box), pixelWidth=image.pixels[0] if image.pixels else None, pixelHeight=image.pixels[1] if image.pixels else None)
            for image in page.images[:_IMAGES]
        ],
        links=PdfLinkCounts(web=links["web"], internal=links["internal"], unsafe=links["unsafe"], other=links["other"]),
        annotations=dict(Counter(annotation.kind for annotation in page.annotations)),
    )


def inspect_pdf(file_bytes: bytes, on_page: Callable[[PdfPage, str], None] | None = None) -> PdfInspection:
    """What is on each page of a PDF the text read has already accepted. Never raises: a
    file the geometry read refuses, or a failure here, is an inspection that says so --
    the import doesn't depend on it. Each page read goes to `on_page` too, with its kind,
    when given (the structure reconstruction, P2E-002: one read of the file for both);
    `on_page` must not raise."""
    pages: list[PdfPageInspection] = []

    def read(page: PdfPage) -> None:
        pages.append(_page(page))
        if on_page is not None:
            on_page(page, pages[-1].kind)

    try:
        geometry = read_pdf_geometry(file_bytes, on_page=read)
    except PdfParseError as refused:
        return PdfInspection(pageCount=0, complete=False, stopped=str(refused))
    except Exception as exc:  # noqa: BLE001 -- the inspection is extra: it never costs the import
        logger.warning("PDF inspection failed: %s at %s", type(exc).__name__, where(exc))
        return PdfInspection(pageCount=0, complete=False, stopped=FAILED)
    return PdfInspection(
        kind=document_kind([page.kind for page in pages]),
        pageCount=geometry.page_count,
        version=geometry.version,
        pages=pages,
        notRead=[PdfPageNotRead(number=number, reason=reason) for number, reason in sorted(geometry.unread.items())],
        complete=geometry.complete,
        stopped=geometry.stopped,
        structureProblem=geometry.structure_problem,
        outline=[PdfOutlineItem(title=entry.title, level=entry.level, page=entry.page) for entry in geometry.outline],
        outlineCount=geometry.outline_count,
        formFields=[PdfFormField(name=field.name, kind=field.kind) for field in geometry.fields],  # type: ignore[arg-type]
        formFieldCount=geometry.field_count,
        metadata=sorted(geometry.metadata)[:50],
        xmp=geometry.xmp,
    )


def _pages(numbers: list[int]) -> str:
    shown = ", ".join(str(number) for number in numbers[:10])
    more = f" and {len(numbers) - 10} more" if len(numbers) > 10 else ""
    return f"Page {shown}" if len(numbers) == 1 else f"Pages {shown}{more}"


def page_kind_items(inspection: PdfInspection, read_by_ocr: frozenset[int] = frozenset()) -> list[FidelityItem]:
    """The import report's items for the pages the text import can't fully stand behind --
    a scanned page OCR read (P2E-006) is said to be so by the import instead."""
    items: list[FidelityItem] = []
    scanned = [page.number for page in inspection.pages if page.kind == SCANNED and page.number not in read_by_ocr]
    hybrid = [page for page in inspection.pages if page.kind == HYBRID]
    if scanned:
        items.append(
            FidelityItem(
                feature="pdf.scanned_pages",
                policy=FidelityPolicy.UNSUPPORTED,
                reason=f"{_pages(scanned)} {'is a scan' if len(scanned) == 1 else 'are scans'} with no text: any words in "
                f"{'it' if len(scanned) == 1 else 'them'} weren't imported (reading pictures of text isn't available yet).",
                count=len(scanned),
                confidence=min(page.confidence for page in inspection.pages if page.kind == SCANNED),
                contentChanged=True,
            )
        )
    if hybrid:
        numbers = [page.number for page in hybrid]
        items.append(
            FidelityItem(
                feature="pdf.hybrid_pages",
                policy=FidelityPolicy.LOSSY,
                reason=f"{_pages(numbers)} {'has' if len(numbers) == 1 else 'have'} text over a page-sized picture, as a scan with a "
                "text layer has: the text was imported as it is, and a scan's text layer can hold the mistakes of whatever read "
                "the scan -- check it against the original.",
                count=len(numbers),
                confidence=min(page.confidence for page in hybrid),
            )
        )
    return items
