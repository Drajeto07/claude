"""The PDF -> editable conversion's confidence and what it doesn't keep (tracker P2E-005,
brief §41 and §88): how sure the conversion is of each thing it had to work out -- the
text, paragraphs, headings, lists, captions, tables, columns, pictures, reading order --
and in all (models/pdf_inspection.py PdfConversion, kept as Document.pdfConversion); and
the import report's items for what the PDF holds that the document doesn't: notes and
highlights, a form's fields, the outline, links it can't keep. Nothing a conversion
leaves behind goes unsaid."""

from collections import Counter

from app.fidelity.report import FidelityItem, FidelityPolicy
from app.models.document import Document, ElementType
from app.models.pdf_inspection import PdfAspectConfidence, PdfConversion, PdfInspection
from app.parsers.pdf_structure import GUESS, LIKELY, SURE, PdfStructure

# Under this a block is worth a look (the Structure panel's mark, too).
LOW = 0.6
# The text read straight from the PDF's drawn text, every word checked.
TEXT_READ = 0.95
# While tables or pictures aren't rebuilt, a document holding them is no better than this in all.
NOT_ALL_REBUILT = 0.6
# The text alone, no structure rebuilt: its order is the text read's, its blocks a guess.
TEXT_ONLY = 0.5
# Annotations that are part of something else: a link (counted as links), a form field, a note's pop-up.
_NOT_NOTES = {"Link", "Widget", "Popup"}
# The annotations' kinds (their subtypes) in words.
_NOTE_NAMES = {
    "Text": "note", "FreeText": "text box", "Highlight": "highlight", "Underline": "underline", "StrikeOut": "strike-out",
    "Squiggly": "squiggle", "Ink": "drawing", "Stamp": "stamp", "FileAttachment": "attached file", "Square": "box",
    "Circle": "circle", "Line": "line", "Polygon": "shape", "PolyLine": "shape", "Caret": "insertion mark", "Sound": "sound",
}


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}{'es' if word.endswith(('s', 'x')) else 's'}"


def _text(document: Document, inspection: PdfInspection, rebuilt: bool) -> PdfAspectConfidence:
    report = document.importReport
    features = {item.feature for item in report.items} if report else set()
    confidence, notes = TEXT_READ, []
    if report is None or report.content is None or not report.content.verified:
        confidence, notes = TEXT_ONLY, ["its words don't all match what was read"]
    if "pdf.text_reads_differ" in features:
        confidence = min(confidence, LIKELY)
        notes.append("a few words were found by one read only")
    if any(element.layout is not None and element.layout.source == "pdf-text-layer" for element in document.elements) or (
        not rebuilt and any(page.kind == "hybrid" for page in inspection.pages)
    ):
        confidence = min(confidence, LOW)
        notes.append("some is the text layer over a scan, with whatever mistakes read the scan")
    if "pdf.unreadable_characters" in features:
        confidence = min(confidence, LOW)
        notes.append("some characters had no text in the file")
    scanned = sum(1 for page in inspection.pages if page.kind == "scanned")
    if scanned:
        confidence = min(confidence, 0.5)
        notes.append(f"{_plural(scanned, 'scanned page')} had no text to read")
    note = "Read from the PDF's text, every word checked." if not notes else "Read from the PDF's text; " + "; ".join(notes) + "."
    return PdfAspectConfidence(aspect="text", confidence=confidence, count=len(document.elements), note=note[:300])


def _blocks(document: Document) -> list[PdfAspectConfidence]:
    aspects = []
    for aspect, kind, what in (
        ("paragraphs", ElementType.PARAGRAPH, "paragraph"),
        ("headings", ElementType.HEADING, "heading"),
        ("lists", ElementType.LIST, "list"),
        ("captions", ElementType.CAPTION, "caption"),
    ):
        scored = [element.confidence for element in document.elements if element.type == kind and element.confidence is not None]
        if scored:
            low = sum(1 for value in scored if value < LOW)
            note = f"{_plural(len(scored), what)}" + (f", {low} of them a guess worth a look" if low else "")
            aspects.append(PdfAspectConfidence(aspect=aspect, confidence=round(sum(scored) / len(scored), 2), count=len(scored), note=note))
    return aspects


def conversion_summary(document: Document, structure: PdfStructure | None, inspection: PdfInspection) -> PdfConversion:
    """How sure the conversion of `document` from its PDF is (see the module's docstring).
    `structure`: what the reconstruction saw, or None when the text alone was used."""
    rebuilt = structure is not None
    text = _text(document, inspection, rebuilt)
    aspects = [text]
    pictures = sum(page.imageCount for page in inspection.pages)
    if not rebuilt:
        order = PdfAspectConfidence(
            aspect="readingOrder", confidence=TEXT_ONLY, note="The text read's order: the structure wasn't rebuilt from the layout."
        )
        aspects.append(order)
        if pictures:
            aspects.append(PdfAspectConfidence(aspect="pictures", confidence=0.0, count=pictures, note="Not imported yet (P2E-003)."))
        scored = [element.confidence for element in document.elements if element.confidence is not None]
        return PdfConversion(
            rebuilt=False,
            confidence=min(text.confidence, TEXT_ONLY),
            aspects=aspects,
            blocks=len(document.elements),
            lowConfidenceBlocks=sum(1 for value in scored if value < LOW),
        )
    aspects.extend(_blocks(document))
    pictures, placed = structure.pictures, structure.pictures_placed
    if structure.tables or structure.table_rows:
        notes = []
        if structure.tables:
            notes.append(f"{_plural(structure.tables, 'ruled table')} rebuilt, cell by cell")
        if structure.table_rows:
            notes.append(f"{_plural(structure.table_rows, 'row')} set apart by space alone came in a paragraph a row")
        confidence = structure.table_confidence if structure.tables and not structure.table_rows else (
            min(structure.table_confidence, 0.3) if structure.tables else 0.3
        )
        aspects.append(
            PdfAspectConfidence(
                aspect="tables", confidence=confidence, count=structure.tables + structure.table_rows, note=("; ".join(notes) + ".")[:300]
            )
        )
    if structure.column_pages:
        aspects.append(
            PdfAspectConfidence(
                aspect="columns", confidence=LIKELY, count=structure.column_pages,
                note=f"Columns on {_plural(structure.column_pages, 'page')}, read one after the other.",
            )
        )
    if pictures:
        note = f"{placed} of {pictures} placed in the text where they stood" + ("." if placed == pictures else "; the rest are in the report.")
        aspects.append(PdfAspectConfidence(aspect="pictures", confidence=round(LIKELY * placed / pictures, 2), count=pictures, note=note))
    order, why = SURE, []
    if structure.column_pages or structure.run_on:
        order = LIKELY
        if structure.run_on:
            why.append(f"{_plural(structure.run_on, 'paragraph')} run on into another column or page")
        if structure.column_pages:
            why.append("columns")
    if structure.turned_lines:
        order = GUESS
        why.append(f"{_plural(structure.turned_lines, 'line')} of turned text")
    aspects.append(
        PdfAspectConfidence(
            aspect="readingOrder", confidence=order,
            note=("Top to bottom, " + ", ".join(why) + "." if why else "Top to bottom, one block after another.")[:300],
        )
    )
    weights = [(max(len(element.content), 1), element.confidence if element.confidence is not None else GUESS) for element in document.elements]
    blocks = sum(weight * value for weight, value in weights) / sum(weight for weight, _ in weights) if weights else 0.0
    confidence = min(blocks, text.confidence, order)
    if structure.table_rows or placed < pictures:
        confidence = min(confidence, NOT_ALL_REBUILT)
    return PdfConversion(
        rebuilt=True,
        confidence=round(confidence, 2),
        aspects=aspects,
        blocks=len(document.elements),
        lowConfidenceBlocks=sum(1 for _, value in weights if value < LOW),
    )


def conversion_items(inspection: PdfInspection, *, rebuilt: bool) -> list[FidelityItem]:
    """The import report's items for what the PDF holds that the document doesn't keep."""
    items: list[FidelityItem] = []
    notes: Counter[str] = Counter()
    for page in inspection.pages:
        for kind, count in page.annotations.items():
            if kind not in _NOT_NOTES:
                notes[kind] += count
    if notes:
        total = sum(notes.values())
        kinds = ", ".join(_plural(count, _NOTE_NAMES.get(kind, "other mark")) for kind, count in notes.most_common(5))
        items.append(
            FidelityItem(
                feature="pdf.annotations",
                policy=FidelityPolicy.UNSUPPORTED,
                reason=f"What was marked on the PDF's pages -- {kinds} -- {'wasn' if total == 1 else 'weren'}'t imported.",
                count=total,
                contentChanged=True,
            )
        )
    if inspection.formFieldCount:
        items.append(
            FidelityItem(
                feature="pdf.form_fields",
                policy=FidelityPolicy.UNSUPPORTED,
                reason=f"The PDF's form has {_plural(inspection.formFieldCount, 'field')}: the words beside them came in as text, "
                "the fields and anything filled in them didn't.",
                count=inspection.formFieldCount,
                contentChanged=True,
            )
        )
    if inspection.outlineCount:
        items.append(
            FidelityItem(
                feature="pdf.outline",
                policy=FidelityPolicy.LOSSY,
                reason=f"The PDF's outline ({inspection.outlineCount} {'entry' if inspection.outlineCount == 1 else 'entries'}) isn't kept as it was: "
                "the document's headings make its outline now.",
                count=inspection.outlineCount,
            )
        )
    links: Counter[str] = Counter()
    for page in inspection.pages:
        links["web"] += page.links.web
        links["kept out"] += page.links.internal + page.links.unsafe + page.links.other
    lost = links["kept out"] + (0 if rebuilt else links["web"])
    if lost:
        what = "to places in the file, or to addresses a document may not open" if rebuilt else "of every kind"
        items.append(
            FidelityItem(
                feature="pdf.links",
                policy=FidelityPolicy.LOSSY,
                reason=f"{_plural(lost, 'link')} ({what}) came in as {'their' if lost != 1 else 'its'} text, not as links.",
                count=lost,
            )
        )
    return items
