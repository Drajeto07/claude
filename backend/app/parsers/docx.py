import base64
import io
import zipfile

from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.table import _Cell as DocxCell
from docx.text.hyperlink import Hyperlink as DocxHyperlink
from docx.text.paragraph import Paragraph as DocxParagraph
from docx.text.run import Run as DocxRun

from app.models.document import (
    WEB_IMAGE_TYPES,
    Document,
    DocumentMetadata,
    Element,
    ElementType,
    ImageContent,
    InlineRun,
    ListItem,
    Mark,
    MarkType,
    Section,
    TableCell,
    TableContent,
    TableRow,
    plain_text_from_inline,
)

_CONTENT_TYPE_ALIASES = {"image/jpg": "image/jpeg"}


class DocxParseError(Exception):
    """Raised when the uploaded bytes aren't a readable .docx file."""


def parse_docx(file_bytes: bytes, filename: str, title: str | None = None) -> Document:
    """Deterministic DOCX structure extraction from real Word paragraph
    styles/lists/tables -- strictly more accurate than re-inferring structure
    via AI from a flattened text dump, and free. confidence=1.0 throughout:
    this reads ground truth the author (or Word) already recorded, no AI runs.

    Known simplifications (acceptable per this phase's scope, not silent
    gaps): table cell merges don't reconstruct real colspan/rowspan; DOCX
    footnotes are unsupported; a document with no real styles applied (every
    paragraph "Normal") never falls back to AI -- re-paste the extracted text
    through the paste flow instead if AI analysis is wanted for such a file.
    A picture sharing a paragraph with text becomes its own image element right
    after that paragraph (InlineRun is text-only). Pictures inside table cells
    or list items, and non-web formats (EMF/WMF/SVG...), are reported in
    unsupportedFeatures rather than imported.
    """
    try:
        docx_document = DocxDocument(io.BytesIO(file_bytes))
    except (PackageNotFoundError, zipfile.BadZipFile) as exc:
        raise DocxParseError(f"{filename!r} is not a valid .docx file") from exc

    section = Section(order=0)
    elements: list[Element] = []
    order = 0
    pending_list: list[tuple[DocxParagraph, int]] = []
    # Spec §9's three-strategy rule for a feature the model can't fully
    # represent yet: fully supported / preserved-but-not-editable / or here,
    # explicitly flagged rather than silently dropped. Populated by whichever
    # helper below actually detects something (currently just merged table
    # cells -- more detections are added as later phases need them, not
    # invented speculatively now).
    unsupported_features: list[str] = []

    def flush_list() -> None:
        nonlocal order
        if not pending_list:
            return
        first_style = pending_list[0][0].style.name if pending_list[0][0].style else ""
        ordered = "number" in (first_style or "").lower()
        items = [
            ListItem(inline=_paragraph_inline(paragraph), level=_list_level(paragraph), checked=None)
            for paragraph, _ in pending_list
        ]
        content = "\n".join(plain_text_from_inline(item.inline) for item in items)
        elements.append(
            Element(
                type=ElementType.LIST,
                content=content,
                listItems=items,
                ordered=ordered,
                parentId=section.id,
                order=order,
                confidence=1.0,
            )
        )
        order += 1
        pending_list.clear()

    for block in docx_document.iter_inner_content():
        if isinstance(block, DocxParagraph):
            num_id = _numbering_id(block)
            if num_id is not None:
                if _has_drawing(block):
                    unsupported_features.append("Images inside list items were not imported.")
                if pending_list and pending_list[-1][1] != num_id:
                    flush_list()
                pending_list.append((block, num_id))
                continue
            flush_list()
            element = _paragraph_to_element(block, section.id, order)
            if element is not None:
                elements.append(element)
                order += 1
            images, problems = _paragraph_images(block)
            unsupported_features.extend(problems)
            for image in images:
                elements.append(
                    Element(
                        type=ElementType.IMAGE,
                        content="",
                        image=image,
                        parentId=section.id,
                        order=order,
                        confidence=1.0,
                    )
                )
                order += 1
        elif isinstance(block, DocxTable):
            flush_list()
            table = _table_to_content(block, unsupported_features)
            content = "\n".join(
                " | ".join(plain_text_from_inline(cell.inline) for cell in row.cells) for row in table.rows
            )
            elements.append(
                Element(
                    type=ElementType.TABLE,
                    content=content,
                    table=table,
                    parentId=section.id,
                    order=order,
                    confidence=1.0,
                )
            )
            order += 1
    flush_list()

    derived_title = (
        elements[0].content if elements and elements[0].type == ElementType.HEADING else filename
    )
    return Document(
        metadata=DocumentMetadata(
            title=title or derived_title, sourceType="uploaded_docx", originalFilename=filename
        ),
        sections=[section],
        elements=elements,
        # dict.fromkeys dedupes (e.g. two merged tables) while keeping order,
        # cheaper than a set for the tiny lists this ever produces.
        unsupportedFeatures=list(dict.fromkeys(unsupported_features)),
    )


def _paragraph_to_element(paragraph: DocxParagraph, section_id: str, order: int) -> Element | None:
    inline = _paragraph_inline(paragraph)
    content = plain_text_from_inline(inline)
    if not content.strip():
        return None  # skip empty paragraphs used purely for spacing

    style_name = (paragraph.style.name if paragraph.style else "") or ""

    heading_level = _heading_level(style_name)
    if heading_level is not None:
        return Element(
            type=ElementType.HEADING,
            content=content,
            inline=inline,
            parentId=section_id,
            order=order,
            level=heading_level,
            confidence=1.0,
        )
    if style_name == "Caption":
        return Element(
            type=ElementType.CAPTION, content=content, inline=inline, parentId=section_id, order=order, confidence=1.0
        )
    if style_name in ("Quote", "Intense Quote"):
        return Element(
            type=ElementType.QUOTE, content=content, inline=inline, parentId=section_id, order=order, confidence=1.0
        )
    return Element(
        type=ElementType.PARAGRAPH, content=content, inline=inline, parentId=section_id, order=order, confidence=1.0
    )


def _heading_level(style_name: str) -> int | None:
    if style_name == "Title":
        return 1
    if style_name.startswith("Heading "):
        suffix = style_name[len("Heading ") :].strip()
        if suffix.isdigit():
            return min(int(suffix), 6)
    return None


def _paragraph_inline(paragraph: DocxParagraph) -> list[InlineRun]:
    runs: list[InlineRun] = []
    for item in paragraph.iter_inner_content():
        if isinstance(item, DocxHyperlink):
            if item.text:
                runs.append(InlineRun(text=item.text, marks=[Mark(type=MarkType.LINK, href=item.address)]))
        elif isinstance(item, DocxRun) and item.text:
            # run.text excludes drawings; pictures are collected by _paragraph_images.
            runs.append(InlineRun(text=item.text, marks=_run_marks(item)))
    return runs


def _run_marks(run: DocxRun) -> list[Mark]:
    marks: list[Mark] = []
    if run.bold:
        marks.append(Mark(type=MarkType.BOLD))
    if run.italic:
        marks.append(Mark(type=MarkType.ITALIC))
    if run.underline:
        marks.append(Mark(type=MarkType.UNDERLINE))
    if run.font.strike:
        marks.append(Mark(type=MarkType.STRIKE))
    return marks


def _has_drawing(paragraph: DocxParagraph) -> bool:
    return next(paragraph._p.iter(qn("w:drawing")), None) is not None


def _paragraph_images(paragraph: DocxParagraph) -> tuple[list[ImageContent], list[str]]:
    """Every embedded picture in the paragraph, in document order, as an inline
    data: URI (services/image_assets.py moves the bytes into asset storage before
    the document is saved), plus a note for each picture that couldn't be imported."""
    images: list[ImageContent] = []
    problems: list[str] = []
    for drawing in paragraph._p.iter(qn("w:drawing")):
        try:
            blip = next(drawing.iter(qn("a:blip")), None)
            r_id = blip.get(qn("r:embed")) if blip is not None else None
            if not r_id:
                problems.append("A linked (not embedded) image was not imported.")
                continue
            part = paragraph.part.related_parts[r_id]
            content_type = (part.content_type or "").lower()
            content_type = _CONTENT_TYPE_ALIASES.get(content_type, content_type)
            if content_type not in WEB_IMAGE_TYPES:
                problems.append(f"An image in an unsupported format ({content_type or 'unknown'}) was not imported.")
                continue
            doc_pr = next(drawing.iter(qn("wp:docPr")), None)
            alt = (doc_pr.get("descr") or doc_pr.get("title")) if doc_pr is not None else None
            encoded = base64.b64encode(part.blob).decode("ascii")
            images.append(ImageContent(src=f"data:{content_type};base64,{encoded}", alt=alt or None))
        except Exception:  # noqa: BLE001 -- untrusted file; one broken picture must not abort the import
            problems.append("An image could not be read and was not imported.")
    return images, problems


def _numbering_id(paragraph: DocxParagraph) -> int | None:
    num_pr = _find_num_pr(paragraph)
    if num_pr is None:
        return None
    num_id_el = num_pr.find(qn("w:numId"))
    if num_id_el is None:
        return None
    value = num_id_el.get(qn("w:val"))
    return int(value) if value is not None else None


def _list_level(paragraph: DocxParagraph) -> int:
    num_pr = _find_num_pr(paragraph)
    if num_pr is None:
        return 0
    ilvl_el = num_pr.find(qn("w:ilvl"))
    if ilvl_el is None:
        return 0
    value = ilvl_el.get(qn("w:val"))
    return int(value) if value is not None else 0


def _find_num_pr(paragraph: DocxParagraph):
    p_pr = paragraph._p.find(qn("w:pPr"))
    if p_pr is None:
        return None
    return p_pr.find(qn("w:numPr"))


def _cell_is_merged(cell: DocxCell) -> bool:
    """Detects (not reconstructs) a horizontal (gridSpan > 1) or vertical
    (vMerge, with or without a val -- restart and continuation cells both
    carry the element) cell merge. colspan/rowspan on TableCell stay at
    their default of 1 either way -- this only feeds the explicit
    unsupported-feature warning (spec §9 strategy C), it does not model the
    merge. Real reconstruction is Phase 9 scope."""
    tc_pr = cell._tc.find(qn("w:tcPr"))
    if tc_pr is None:
        return False
    grid_span = tc_pr.find(qn("w:gridSpan"))
    if grid_span is not None and int(grid_span.get(qn("w:val"), "1")) > 1:
        return True
    return tc_pr.find(qn("w:vMerge")) is not None


def _table_to_content(table: DocxTable, unsupported_features: list[str]) -> TableContent:
    rows: list[TableRow] = []
    has_merge = False
    has_image = False
    for row_index, row in enumerate(table.rows):
        is_header_row = row_index == 0
        cells: list[TableCell] = []
        for cell in row.cells:
            if _cell_is_merged(cell):
                has_merge = True
            inline: list[InlineRun] = []
            for paragraph_index, paragraph in enumerate(cell.paragraphs):
                if paragraph_index > 0:
                    inline.append(InlineRun(text="\n"))
                inline.extend(_paragraph_inline(paragraph))
                has_image = has_image or _has_drawing(paragraph)
            cells.append(TableCell(inline=inline, header=is_header_row))
        rows.append(TableRow(cells=cells))
    if has_merge:
        unsupported_features.append("Merged table cells were flattened -- original colspan/rowspan not preserved.")
    if has_image:
        unsupported_features.append("Images inside table cells were not imported.")
    # Word has no universal "this is the header row" flag exposed at this
    # level -- treating row 0 as the header is a reasonable common-case
    # default, not a guaranteed-correct read (flagged simplification).
    return TableContent(rows=rows, hasHeaderRow=bool(rows), alignments=None)
