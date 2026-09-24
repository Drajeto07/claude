import io
from collections.abc import Mapping

from docx import Document as DocxDocument
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.text.run import Run

from app.export.images import resolve_image_bytes
from app.models.document import Document, DocumentSettings, Element, ElementType, InlineRun, MarkType

# Mirrors frontend/components/DocumentEditor.tsx's PAGE_DIMENSIONS_MM exactly,
# so the exported page size matches what the live preview approximated.
_PAGE_DIMENSIONS_MM: dict[str, tuple[float, float]] = {
    "A4": (210, 297),
    "Letter": (216, 279),
    "Legal": (216, 356),
}

_ALIGNMENT_MAP = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}

_STYLE_FOR_TYPE = {
    ElementType.QUOTE: "Quote",
    ElementType.CAPTION: "Caption",
}

_NAMED_COLORS = {
    "red": "FF0000",
    "blue": "0000FF",
    "green": "008000",
    "black": "000000",
    "white": "FFFFFF",
    "gray": "808080",
    "grey": "808080",
    "yellow": "FFFF00",
    "orange": "FFA500",
    "purple": "800080",
}


def build_docx(
    document: Document,
    *,
    assets: Mapping[str, bytes] | None = None,
    include_headers: bool = True,
    include_page_numbers: bool = True,
    include_page_breaks: bool = True,
) -> bytes:
    """Real, editable .docx (spec §7.17) built from the same resolved styles
    the editor already renders -- no separate style computation. Independent
    of pdf_export.py's reportlab-based builder (LibreOffice isn't available
    on this machine to convert one into the other -- see the Phase 6 plan);
    both read the same document.resolvedStyles, so there's nothing to keep
    in sync beyond that shared source of truth.

    The three include_* flags are export-time-only overrides (spec's export
    options screen) -- they never touch the persisted document.settings, so
    exporting once without page numbers doesn't turn them off for next time.
    All default True, matching this function's behavior before these flags
    existed."""
    docx_document = DocxDocument()
    _apply_page_setup(docx_document, document, include_headers=include_headers, include_page_numbers=include_page_numbers)
    for element in document.elements:
        if element.type == ElementType.PAGE_BREAK and not include_page_breaks:
            continue
        _add_element(docx_document, element, document, assets or {})

    buffer = io.BytesIO()
    docx_document.save(buffer)
    return buffer.getvalue()


def _page_dimensions_mm(settings: DocumentSettings) -> tuple[float, float]:
    width_mm, height_mm = _PAGE_DIMENSIONS_MM.get(settings.pageSize, _PAGE_DIMENSIONS_MM["A4"])
    if settings.orientation == "landscape":
        return height_mm, width_mm
    return width_mm, height_mm


def _apply_page_setup(docx_document: DocxDocument, document: Document, *, include_headers: bool, include_page_numbers: bool) -> None:
    settings = document.settings
    section = docx_document.sections[0]
    width_mm, height_mm = _page_dimensions_mm(settings)
    section.orientation = WD_ORIENT.LANDSCAPE if settings.orientation == "landscape" else WD_ORIENT.PORTRAIT
    section.page_width = Cm(width_mm / 10)
    section.page_height = Cm(height_mm / 10)
    section.top_margin = Cm(settings.marginTopCm)
    section.bottom_margin = Cm(settings.marginBottomCm)
    section.left_margin = Cm(settings.marginLeftCm)
    section.right_margin = Cm(settings.marginRightCm)

    footer_has_text = include_headers and bool(settings.footer)
    if include_headers and settings.header:
        section.header.paragraphs[0].text = settings.header
    if footer_has_text:
        section.footer.paragraphs[0].text = settings.footer
    if include_page_numbers and settings.showPageNumbers:
        page_number_paragraph = section.footer.add_paragraph() if footer_has_text else section.footer.paragraphs[0]
        page_number_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _append_page_number_field(page_number_paragraph)


def _append_page_number_field(paragraph) -> None:
    """python-docx has no high-level API for field codes -- same "drop into
    raw XML" pattern already used by parsers/docx.py for list numbering."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def _content_width_cm(document: Document) -> float:
    width_mm, _ = _page_dimensions_mm(document.settings)
    return width_mm / 10 - document.settings.marginLeftCm - document.settings.marginRightCm


def _resolved_css(element: Element, document: Document) -> dict[str, str]:
    if not element.styleRef:
        return {}
    return document.resolvedStyles.get(element.styleRef, {})


def _parse_pt(value: str) -> float:
    try:
        return float(value.replace("pt", "").strip())
    except ValueError:
        return 0.0


def _parse_cm(value: str) -> float:
    try:
        return float(value.replace("cm", "").strip())
    except ValueError:
        return 0.0


def _parse_color(value: str) -> RGBColor | None:
    value = value.strip().lower()
    if value.startswith("#"):
        hex_value = value.lstrip("#")
        if len(hex_value) == 3:
            hex_value = "".join(ch * 2 for ch in hex_value)
        if len(hex_value) == 6:
            try:
                return RGBColor.from_string(hex_value)
            except ValueError:
                return None
        return None
    if value in _NAMED_COLORS:
        return RGBColor.from_string(_NAMED_COLORS[value])
    return None


def _apply_run_css(run, css: dict[str, str]) -> None:
    font_family = css.get("font-family")
    if font_family:
        run.font.name = font_family.strip('"')
    font_size = css.get("font-size")
    if font_size:
        run.font.size = Pt(_parse_pt(font_size))
    color = css.get("color")
    if color:
        rgb = _parse_color(color)
        if rgb is not None:
            run.font.color.rgb = rgb
    if css.get("font-weight") == "bold":
        run.font.bold = True
    if css.get("font-style") == "italic":
        run.font.italic = True
    if css.get("text-decoration") == "underline":
        run.font.underline = True


def _apply_paragraph_css(paragraph, css: dict[str, str]) -> None:
    alignment = _ALIGNMENT_MAP.get(css.get("text-align", ""))
    if alignment is not None:
        paragraph.alignment = alignment
    line_height = css.get("line-height")
    if line_height:
        try:
            paragraph.paragraph_format.line_spacing = float(line_height)
        except ValueError:
            pass
    margin_bottom = css.get("margin-bottom")
    if margin_bottom:
        paragraph.paragraph_format.space_after = Pt(_parse_pt(margin_bottom))
    text_indent = css.get("text-indent")
    if text_indent:
        paragraph.paragraph_format.first_line_indent = Cm(_parse_cm(text_indent))


def _add_hyperlink_run(paragraph, text: str, url: str) -> Run:
    """python-docx has no high-level hyperlink API -- same raw-XML pattern
    already used elsewhere in this file for numbering and the page-number
    field. Returns a real Run wrapper around the new <w:r> inside the
    hyperlink, so the caller applies bold/italic/underline/etc. through the
    normal .font API exactly as for any other run."""
    r_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    run_element = OxmlElement("w:r")
    run_properties = OxmlElement("w:rPr")
    style = OxmlElement("w:rStyle")
    style.set(qn("w:val"), "Hyperlink")
    run_properties.append(style)
    run_element.append(run_properties)
    hyperlink.append(run_element)
    paragraph._p.append(hyperlink)

    run = Run(run_element, paragraph)
    run.text = text
    return run


def _add_inline_runs(paragraph, inline_runs: list[InlineRun], css: dict[str, str]) -> None:
    for inline_run in inline_runs:
        marks = {mark.type for mark in inline_run.marks}
        link = next((m for m in inline_run.marks if m.type == MarkType.LINK and m.href), None)
        run = _add_hyperlink_run(paragraph, inline_run.text, link.href) if link else paragraph.add_run(inline_run.text)
        if MarkType.BOLD in marks:
            run.font.bold = True
        if MarkType.ITALIC in marks:
            run.font.italic = True
        if MarkType.UNDERLINE in marks:
            run.font.underline = True
        if MarkType.STRIKE in marks:
            run.font.strike = True
        if MarkType.CODE in marks:
            run.font.name = "Courier New"
        _apply_run_css(run, css)


def _add_runs(paragraph, element: Element, document: Document) -> None:
    css = _resolved_css(element, document)
    inline_runs = element.inline or ([InlineRun(text=element.content)] if element.content else [])
    _add_inline_runs(paragraph, inline_runs, css)
    _apply_paragraph_css(paragraph, css)


def _add_heading(docx_document: DocxDocument, element: Element, document: Document) -> None:
    heading = docx_document.add_heading(level=min(max(element.level or 1, 1), 9))
    _add_runs(heading, element, document)


def _add_paragraph(docx_document: DocxDocument, element: Element, document: Document) -> None:
    paragraph = docx_document.add_paragraph(style=_STYLE_FOR_TYPE.get(element.type))
    _add_runs(paragraph, element, document)


def _add_list(docx_document: DocxDocument, element: Element, document: Document) -> None:
    css = _resolved_css(element, document)
    style_name = "List Number" if element.ordered else "List Bullet"
    for item in element.listItems or []:
        paragraph = docx_document.add_paragraph(style=style_name)
        paragraph.paragraph_format.left_indent = Cm(0.63 * (item.level + 1))
        if item.checked is True:
            paragraph.add_run("☑ ")
        elif item.checked is False:
            paragraph.add_run("☐ ")
        _add_inline_runs(paragraph, item.inline, css)


def _add_table(docx_document: DocxDocument, element: Element, document: Document) -> None:
    table_content = element.table
    if table_content is None or not table_content.rows:
        return
    css = _resolved_css(element, document)
    num_cols = max(len(row.cells) for row in table_content.rows)
    table = docx_document.add_table(rows=len(table_content.rows), cols=num_cols)
    table.style = "Table Grid"
    for row_index, row in enumerate(table_content.rows):
        for cell_index, cell in enumerate(row.cells):
            paragraph = table.cell(row_index, cell_index).paragraphs[0]
            _add_inline_runs(paragraph, cell.inline, css)
            if cell.header:
                for run in paragraph.runs:
                    run.font.bold = True


def _add_image(
    docx_document: DocxDocument, element: Element, document: Document, assets: Mapping[str, bytes]
) -> None:
    image_bytes = resolve_image_bytes(element.image, assets) if element.image else None
    if image_bytes is None:
        return

    width = None
    image_width_css = _resolved_css(element, document).get("width", "")
    if image_width_css.endswith("%"):
        try:
            percent = float(image_width_css.rstrip("%"))
            width = Cm(_content_width_cm(document) * percent / 100)
        except ValueError:
            width = None

    try:
        if width is not None:
            docx_document.add_picture(io.BytesIO(image_bytes), width=width)
        else:
            docx_document.add_picture(io.BytesIO(image_bytes))
    except Exception:
        pass  # best-effort, same philosophy as the parser's own image handling


def _shade_paragraph(paragraph, hex_color: str) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    p_pr.append(shd)


def _add_code_block(docx_document: DocxDocument, element: Element, document: Document) -> None:
    paragraph = docx_document.add_paragraph()
    run = paragraph.add_run(element.content)
    run.font.name = "Courier New"
    run.font.size = Pt(10)
    _shade_paragraph(paragraph, "F0F0F0")


def _add_page_break(docx_document: DocxDocument) -> None:
    # python-docx has a real, first-class page break -- a run-level WD_BREAK,
    # not a styled paragraph standing in for one.
    docx_document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _add_element(
    docx_document: DocxDocument, element: Element, document: Document, assets: Mapping[str, bytes]
) -> None:
    if element.type == ElementType.HEADING:
        _add_heading(docx_document, element, document)
    elif element.type == ElementType.LIST:
        _add_list(docx_document, element, document)
    elif element.type == ElementType.TABLE:
        _add_table(docx_document, element, document)
    elif element.type == ElementType.IMAGE:
        _add_image(docx_document, element, document, assets)
    elif element.type == ElementType.CODE_BLOCK:
        _add_code_block(docx_document, element, document)
    elif element.type == ElementType.PAGE_BREAK:
        _add_page_break(docx_document)
    else:
        _add_paragraph(docx_document, element, document)
