import io
import re
from collections.abc import Mapping

from docx import Document as DocxDocument
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor
from docx.text.run import Run

from app.export.images import resolve_image_bytes
from app.formatting.colors import NAMED_COLORS
from app.models.document import Document, DocumentSettings, Element, ElementType, InlineRun, Mark, MarkType, TableContent

# Mirrors frontend/editor/pageGeometry.ts's PAGE_DIMENSIONS_MM exactly,
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

# Background colours Word can show as a real highlight; any other becomes run shading.
_WORD_HIGHLIGHTS = {
    "FFFF00": "yellow",
    "00FF00": "green",
    "00FFFF": "cyan",
    "FF00FF": "magenta",
    "0000FF": "blue",
    "FF0000": "red",
    "000080": "darkBlue",
    "008080": "darkCyan",
    "008000": "darkGreen",
    "800080": "darkMagenta",
    "800000": "darkRed",
    "808000": "darkYellow",
    "808080": "darkGray",
    "C0C0C0": "lightGray",
    "000000": "black",
}

_PAGE_FIELD = re.compile(r"(\{PAGE\}|\{NUMPAGES\})")


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
    existed. With page numbers left out, header/footer text built around a
    page-number field ({PAGE}, {NUMPAGES}) is left out too."""
    docx_document = DocxDocument()
    zoom = docx_document.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")  # required by the schema; python-docx's template leaves it out
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

    header = _page_text(settings.header, include_headers, include_page_numbers)
    footer = _page_text(settings.footer, include_headers, include_page_numbers)
    if header:
        _write_page_text(section.header.paragraphs[0], header)
    if footer:
        _write_page_text(section.footer.paragraphs[0], footer)
    if include_page_numbers and settings.showPageNumbers:
        page_number_paragraph = section.footer.add_paragraph() if footer else section.footer.paragraphs[0]
        page_number_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _append_field(page_number_paragraph, "PAGE")


def _page_text(text: str | None, include_headers: bool, include_page_numbers: bool) -> str | None:
    if not include_headers or not text:
        return None
    if not include_page_numbers and _PAGE_FIELD.search(text):
        return None
    return text


def _write_page_text(paragraph, text: str) -> None:
    """Header/footer text, with {PAGE}/{NUMPAGES} written as the Word fields."""
    for part in _PAGE_FIELD.split(text):
        if part == "{PAGE}":
            _append_field(paragraph, "PAGE")
        elif part == "{NUMPAGES}":
            _append_field(paragraph, "NUMPAGES")
        elif part:
            paragraph.add_run(part)


def _append_field(paragraph, instruction: str) -> None:
    """python-docx has no high-level API for field codes -- raw XML, as for
    hyperlinks below."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
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


def _hex6(value: str | None) -> str | None:
    """#rgb/#rrggbb/named colour as RRGGBB, or None."""
    if not value:
        return None
    value = value.strip().lower()
    if value.startswith("#"):
        hex_value = value.lstrip("#")
        if len(hex_value) == 3:
            hex_value = "".join(ch * 2 for ch in hex_value)
        return hex_value.upper() if re.fullmatch(r"[0-9a-f]{6}", hex_value) else None
    return NAMED_COLORS.get(value)


def _parse_color(value: str) -> RGBColor | None:
    hex_value = _hex6(value)
    return RGBColor.from_string(hex_value) if hex_value else None


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


def _apply_text_style(run, mark: Mark) -> None:
    """A textStyle mark on this run: its values win over the element's CSS."""
    if mark.fontFamily:
        run.font.name = mark.fontFamily
    if mark.fontSizePt:
        run.font.size = Pt(mark.fontSizePt)
    if (rgb := _parse_color(mark.color or "")) is not None:
        run.font.color.rgb = rgb
    background = _hex6(mark.backgroundColor)
    if background:
        r_pr = run._r.get_or_add_rPr()
        if background in _WORD_HIGHLIGHTS:
            highlight = OxmlElement("w:highlight")
            highlight.set(qn("w:val"), _WORD_HIGHLIGHTS[background])
            r_pr.append(highlight)
        else:
            shading = OxmlElement("w:shd")
            shading.set(qn("w:val"), "clear")
            shading.set(qn("w:color"), "auto")
            shading.set(qn("w:fill"), background)
            r_pr.append(shading)


def _apply_paragraph_css(paragraph, css: dict[str, str]) -> None:
    alignment = _ALIGNMENT_MAP.get(css.get("text-align", ""))
    if alignment is not None:
        paragraph.alignment = alignment
    line_height = css.get("line-height")
    if line_height:
        try:
            # "12pt" is an exact line height; a plain number is a multiple.
            paragraph.paragraph_format.line_spacing = Pt(_parse_pt(line_height)) if line_height.endswith("pt") else float(line_height)
        except ValueError:
            pass
    margin_top = css.get("margin-top")
    if margin_top:
        paragraph.paragraph_format.space_before = Pt(_parse_pt(margin_top))
    margin_bottom = css.get("margin-bottom")
    if margin_bottom:
        paragraph.paragraph_format.space_after = Pt(_parse_pt(margin_bottom))
    margin_left = css.get("margin-left")
    if margin_left and margin_left.endswith("cm"):
        paragraph.paragraph_format.left_indent = Cm(_parse_cm(margin_left))
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
        marks = {mark.type: mark for mark in inline_run.marks}
        link = marks.get(MarkType.LINK) if marks.get(MarkType.LINK) and marks[MarkType.LINK].href else None
        # run.text turns "\n" into a line break and "\t" into a tab.
        run = _add_hyperlink_run(paragraph, inline_run.text, link.href) if link else paragraph.add_run(inline_run.text)
        _apply_run_css(run, css)
        if MarkType.BOLD in marks:
            run.font.bold = True
        if MarkType.ITALIC in marks:
            run.font.italic = True
        if MarkType.UNDERLINE in marks:
            run.font.underline = True
        if MarkType.STRIKE in marks:
            run.font.strike = True
        if MarkType.SUPERSCRIPT in marks:
            run.font.superscript = True
        elif MarkType.SUBSCRIPT in marks:
            run.font.subscript = True
        if MarkType.CODE in marks:
            run.font.name = "Courier New"
        if MarkType.TEXT_STYLE in marks:
            _apply_text_style(run, marks[MarkType.TEXT_STYLE])


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


def _add_checkbox(paragraph, checked: bool) -> None:
    """A real Word checkbox (a content control): clickable in Word 2010 and
    later, a ☒/☐ character anywhere else -- and imported back as a checklist."""
    glyph = "☒" if checked else "☐"
    paragraph._p.append(
        parse_xml(
            f"<w:sdt {nsdecls('w', 'w14')}><w:sdtPr><w14:checkbox>"
            f'<w14:checked w14:val="{1 if checked else 0}"/>'
            '<w14:checkedState w14:val="2612" w14:font="MS Gothic"/>'
            '<w14:uncheckedState w14:val="2610" w14:font="MS Gothic"/>'
            "</w14:checkbox></w:sdtPr><w:sdtContent><w:r><w:rPr>"
            '<w:rFonts w:ascii="MS Gothic" w:eastAsia="MS Gothic" w:hAnsi="MS Gothic" w:hint="eastAsia"/>'
            f"</w:rPr><w:t>{glyph}</w:t></w:r></w:sdtContent></w:sdt>"
        )
    )
    paragraph.add_run(" ")


_LIST_LEVELS = 9  # Word's maximum
_LEVEL_INDENT_TWIPS = 357  # 0.63 cm per level
_BULLETS = ("•", "◦", "▪")
_NUMBER_FORMATS = ("decimal", "lowerLetter", "lowerRoman")


def _abstract_numbering(numbering, kind: str) -> str:
    """The id of this document's multi-level list definition for `kind`
    ("bullet", "number", or "none" for checklists), added the first time it's
    needed. python-docx's template only has single-level lists."""
    name = f"SmartDoc {kind}"
    for abstract in numbering.findall(qn("w:abstractNum")):
        name_element = abstract.find(qn("w:name"))
        if name_element is not None and name_element.get(qn("w:val")) == name:
            return abstract.get(qn("w:abstractNumId"))
    abstract_id = str(1 + max((int(a.get(qn("w:abstractNumId"))) for a in numbering.findall(qn("w:abstractNum"))), default=-1))
    levels = []
    for ilvl in range(_LIST_LEVELS):
        left = _LEVEL_INDENT_TWIPS * (ilvl + 1)
        if kind == "none":  # just the indent; the checkbox leads the text
            number = '<w:numFmt w:val="none"/><w:suff w:val="nothing"/><w:lvlText w:val=""/>'
            indent = f'<w:ind w:left="{left}" w:hanging="0"/>'
        else:
            fmt, text = ("bullet", _BULLETS[ilvl % 3]) if kind == "bullet" else (_NUMBER_FORMATS[ilvl % 3], f"%{ilvl + 1}.")
            number = f'<w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>'
            indent = f'<w:ind w:left="{left}" w:hanging="{_LEVEL_INDENT_TWIPS}"/>'
        levels.append(
            f'<w:lvl w:ilvl="{ilvl}"><w:start w:val="1"/>{number}<w:lvlJc w:val="left"/><w:pPr>{indent}</w:pPr></w:lvl>'
        )
    abstract = parse_xml(
        f'<w:abstractNum {nsdecls("w")} w:abstractNumId="{abstract_id}">'
        f'<w:multiLevelType w:val="hybridMultilevel"/><w:name w:val="{name}"/>{"".join(levels)}</w:abstractNum>'
    )
    first_num = numbering.find(qn("w:num"))  # the schema puts every abstractNum before the nums
    if first_num is not None:
        first_num.addprevious(abstract)
    else:
        numbering.append(abstract)
    return abstract_id


def _new_list_numbering(docx_document: DocxDocument, kind: str) -> int:
    """A numbering instance of its own for one list: levels nest for real (Tab
    and Shift+Tab work in Word, and a re-import keeps them), and a numbered
    list starts again at 1 instead of continuing the previous one."""
    numbering = docx_document.part.numbering_part.element
    abstract_id = _abstract_numbering(numbering, kind)
    num_id = 1 + max((int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))), default=0)
    restarts = "".join(
        f'<w:lvlOverride w:ilvl="{ilvl}"><w:startOverride w:val="1"/></w:lvlOverride>' for ilvl in range(_LIST_LEVELS)
    )
    numbering.append(
        parse_xml(f'<w:num {nsdecls("w")} w:numId="{num_id}"><w:abstractNumId w:val="{abstract_id}"/>{restarts}</w:num>')
    )
    return num_id


def _set_numbering(paragraph, num_id: int, level: int) -> None:
    num_pr = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    num_pr.get_or_add_ilvl().val = min(max(level, 0), _LIST_LEVELS - 1)
    num_pr.get_or_add_numId().val = num_id


def _add_list(docx_document: DocxDocument, element: Element, document: Document) -> None:
    css = _resolved_css(element, document)
    checklist = any(item.checked is not None for item in element.listItems or [])
    style_name = "List Paragraph" if checklist else "List Number" if element.ordered else "List Bullet"
    num_id = _new_list_numbering(docx_document, "none" if checklist else "number" if element.ordered else "bullet")
    base_indent = _parse_cm(css.get("margin-left", "")) if css.get("margin-left", "").endswith("cm") else 0.0
    for item in element.listItems or []:
        paragraph = docx_document.add_paragraph(style=style_name)
        _set_numbering(paragraph, num_id, item.level)
        if base_indent:  # otherwise the list level sets the indent
            paragraph.paragraph_format.left_indent = Cm(base_indent + 0.63 * (item.level + 1))
        if item.checked is not None:
            _add_checkbox(paragraph, item.checked)
        _add_inline_runs(paragraph, item.inline, css)
        line_height = css.get("line-height")
        if line_height and not line_height.endswith("pt"):
            try:
                paragraph.paragraph_format.line_spacing = float(line_height)
            except ValueError:
                pass


def _grid_positions(table_content: TableContent) -> tuple[list[tuple[int, int, object]], int]:
    """(row, column, cell) for every cell, with spans taken into account."""
    occupied: set[tuple[int, int]] = set()
    placed: list[tuple[int, int, object]] = []
    width = 0
    for row_index, row in enumerate(table_content.rows):
        column = 0
        for cell in row.cells:
            while (row_index, column) in occupied:
                column += 1
            placed.append((row_index, column, cell))
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    occupied.add((row_index + dr, column + dc))
            column += cell.colspan
            width = max(width, column)
    return placed, width


def _add_table(docx_document: DocxDocument, element: Element, document: Document) -> None:
    table_content = element.table
    if table_content is None or not table_content.rows:
        return
    css = _resolved_css(element, document)
    placed, width = _grid_positions(table_content)
    if width == 0:
        return
    height = len(table_content.rows)
    table = docx_document.add_table(rows=height, cols=width)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    alignments = table_content.alignments or []
    for row_index, column, cell in placed:
        last_row = min(row_index + cell.rowspan - 1, height - 1)
        last_column = min(column + cell.colspan - 1, width - 1)
        target = table.cell(row_index, column)
        if (last_row, last_column) != (row_index, column):
            target = target.merge(table.cell(last_row, last_column))
        paragraph = target.paragraphs[0]
        _add_inline_runs(paragraph, cell.inline, {key: value for key, value in css.items() if not key.startswith("margin")})
        if cell.header:
            for run in paragraph.runs:
                run.font.bold = True
        alignment = _ALIGNMENT_MAP.get((alignments[column] if column < len(alignments) else None) or "")
        if alignment is not None:
            paragraph.alignment = alignment
        background = _hex6(cell.background)
        if background:
            shading = OxmlElement("w:shd")
            shading.set(qn("w:val"), "clear")
            shading.set(qn("w:color"), "auto")
            shading.set(qn("w:fill"), background)
            target._tc.get_or_add_tcPr().append(shading)


def _image_alignment(css: dict[str, str]):
    left, right = css.get("margin-left"), css.get("margin-right")
    if left == "auto" and right == "auto":
        return WD_ALIGN_PARAGRAPH.CENTER
    if left == "auto":
        return WD_ALIGN_PARAGRAPH.RIGHT
    return None


def _add_image(
    docx_document: DocxDocument, element: Element, document: Document, assets: Mapping[str, bytes]
) -> None:
    image_bytes = resolve_image_bytes(element.image, assets) if element.image else None
    if image_bytes is None:
        return

    css = _resolved_css(element, document)
    width = None
    image_width_css = css.get("width", "")
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
        return  # best-effort, same philosophy as the parser's own image handling
    alignment = _image_alignment(css)
    if alignment is not None:
        docx_document.paragraphs[-1].alignment = alignment


def _shade_paragraph(paragraph, hex_color: str) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    p_pr.append(shd)


def _add_code_block(docx_document: DocxDocument, element: Element, document: Document) -> None:
    css = _resolved_css(element, document)
    paragraph = docx_document.add_paragraph()
    run = paragraph.add_run(element.content)
    run.font.name = css.get("font-family", "Courier New").strip('"')
    run.font.size = Pt(_parse_pt(css["font-size"])) if css.get("font-size") else Pt(10)
    _shade_paragraph(paragraph, "F0F0F0")
    if css.get("margin-bottom"):
        paragraph.paragraph_format.space_after = Pt(_parse_pt(css["margin-bottom"]))


def _add_horizontal_rule(docx_document: DocxDocument) -> None:
    paragraph = docx_document.add_paragraph()
    paragraph._p.get_or_add_pPr().append(
        parse_xml(f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" w:sz="6" w:space="1" w:color="9CA3AF"/></w:pBdr>')
    )


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
    elif element.type == ElementType.HORIZONTAL_RULE:
        _add_horizontal_rule(docx_document)
    else:
        _add_paragraph(docx_document, element, document)
