import io
import xml.sax.saxutils as saxutils
from collections.abc import Mapping
from functools import partial

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle, XPreformatted
from reportlab.platypus import Image as PdfImage

from app.export.fonts import PdfFont, pdf_font
from app.export.images import resolve_image_bytes
from app.formatting.colors import NAMED_COLORS
from app.models.document import Document, DocumentSettings, Element, ElementType, InlineRun, MarkType, TableContent

# Kept in lockstep with docx_export.py's own copy and the frontend's
# PAGE_DIMENSIONS_MM -- all three must agree on what "A4" etc. means.
_PAGE_DIMENSIONS_MM: dict[str, tuple[float, float]] = {
    "A4": (210, 297),
    "Letter": (216, 279),
    "Legal": (216, 356),
}

_ALIGNMENT_MAP = {
    "left": TA_LEFT,
    "center": TA_CENTER,
    "right": TA_RIGHT,
    "justify": TA_JUSTIFY,
}

PAGE_TOKEN = "{PAGE}"
NUMPAGES_TOKEN = "{NUMPAGES}"
# Checkboxes from the always-available ZapfDingbats font: ❑ empty, ✔ ticked.
_CHECKBOX = {False: '<font face="ZapfDingbats">q</font>', True: '<font face="ZapfDingbats">4</font>'}


def build_pdf(
    document: Document,
    *,
    assets: Mapping[str, bytes] | None = None,
    include_headers: bool = True,
    include_page_numbers: bool = True,
    include_page_breaks: bool = True,
) -> bytes:
    """Independent of docx_export.py's python-docx-based builder --
    LibreOffice isn't available on this machine to convert one into the
    other (see the Phase 6 plan). Both read the same document.resolvedStyles,
    so there is nothing to keep in sync beyond that shared source of truth.
    Text is set in real TrueType fonts embedded in the file (export/fonts.py),
    so Cyrillic and other non-Latin text comes out right.

    The three include_* flags are export-time-only overrides (spec's export
    options screen) -- see build_docx's docstring; same contract here. With
    page numbers left out, header/footer text built around a page-number field
    ({PAGE}, {NUMPAGES}) is left out too."""
    settings = document.settings
    width_mm, height_mm = _page_dimensions_mm(settings)
    buffer = io.BytesIO()
    doc_template = SimpleDocTemplate(
        buffer,
        pagesize=(width_mm * mm, height_mm * mm),
        leftMargin=settings.marginLeftCm * cm,
        rightMargin=settings.marginRightCm * cm,
        topMargin=settings.marginTopCm * cm,
        bottomMargin=settings.marginBottomCm * cm,
        title=document.metadata.title,
    )

    story: list = []
    for element in document.elements:
        if element.type == ElementType.PAGE_BREAK and not include_page_breaks:
            continue
        story.extend(_build_flowables(element, document, assets or {}))
    if not story:
        # An entirely empty story makes reportlab emit a zero-page PDF --
        # technically valid but a degenerate, likely-unopenable file for a
        # real "export my document" feature. One blank paragraph guarantees
        # at least one page exists.
        story.append(Paragraph("", ParagraphStyle("empty")))

    header = _page_text(settings.header, include_headers, include_page_numbers)
    footer = _page_text(settings.footer, include_headers, include_page_numbers)
    page_numbers = include_page_numbers and settings.showPageNumbers
    font = pdf_font(document.resolvedStyles.get("Paragraph", {}).get("font-family"))

    def decorate(canvas_obj: Canvas, page: int, total: int) -> None:
        page_width, page_height = canvas_obj._pagesize
        canvas_obj.saveState()
        canvas_obj.setFont(font.regular, 9)
        if header:
            canvas_obj.drawCentredString(page_width / 2, page_height - max(settings.marginTopCm * cm / 2, 14), _fill(header, page, total))
        footer_parts = [part for part in (_fill(footer, page, total) if footer else None, f"Page {page}" if page_numbers else None) if part]
        if footer_parts:
            canvas_obj.drawCentredString(page_width / 2, max(settings.marginBottomCm * cm / 2, 14), " · ".join(footer_parts))
        canvas_obj.restoreState()

    doc_template.build(story, canvasmaker=partial(_DecoratedCanvas, decorate=decorate))
    return buffer.getvalue()


class _DecoratedCanvas(Canvas):
    """Holds every page back until the document is finished, then draws the
    headers and footers: only then is the page count ({NUMPAGES}) known."""

    def __init__(self, *args, decorate, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._decorate = decorate
        self._pages: list[dict] = []

    def showPage(self) -> None:  # noqa: N802 -- reportlab's name
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._decorate(self, self.getPageNumber(), total)
            super().showPage()
        super().save()


def _page_text(text: str | None, include_headers: bool, include_page_numbers: bool) -> str | None:
    if not include_headers or not text:
        return None
    if not include_page_numbers and (PAGE_TOKEN in text or NUMPAGES_TOKEN in text):
        return None
    return text


def _fill(text: str, page: int, total: int) -> str:
    return text.replace(PAGE_TOKEN, str(page)).replace(NUMPAGES_TOKEN, str(total))


def _page_dimensions_mm(settings: DocumentSettings) -> tuple[float, float]:
    width_mm, height_mm = _PAGE_DIMENSIONS_MM.get(settings.pageSize, _PAGE_DIMENSIONS_MM["A4"])
    if settings.orientation == "landscape":
        return height_mm, width_mm
    return width_mm, height_mm


def _content_width_pt(document: Document) -> float:
    width_mm, _ = _page_dimensions_mm(document.settings)
    content_width_mm = width_mm - (document.settings.marginLeftCm + document.settings.marginRightCm) * 10
    return content_width_mm * mm


def _content_height_pt(document: Document) -> float:
    _, height_mm = _page_dimensions_mm(document.settings)
    return height_mm * mm - (document.settings.marginTopCm + document.settings.marginBottomCm) * cm


def _resolved_css(element: Element, document: Document) -> dict[str, str]:
    if not element.styleRef:
        return {}
    return document.resolvedStyles.get(element.styleRef, {})


def _parse_pt(value: str, default: float = 0.0) -> float:
    try:
        return float(value.replace("pt", "").strip())
    except (ValueError, AttributeError):
        return default


def _parse_cm(value: str) -> float:
    try:
        return float(value.replace("cm", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def _parse_float(value: str, default: float = 1.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _parse_color(value: str | None) -> colors.Color | None:
    if not value:
        return None
    value = value.strip().lower()
    if value.startswith("#"):
        hex_value = value.lstrip("#")
        if len(hex_value) == 3:
            hex_value = "".join(ch * 2 for ch in hex_value)
        if len(hex_value) == 6:
            try:
                return colors.HexColor(f"#{hex_value}")
            except ValueError:
                return None
        return None
    if value in NAMED_COLORS:
        return colors.HexColor(f"#{NAMED_COLORS[value]}")
    return None


def _hex(value: str | None) -> str | None:
    color = _parse_color(value)
    return color.hexval().replace("0x", "#") if color is not None else None


def _css_font(css: dict[str, str]) -> PdfFont:
    return pdf_font(css.get("font-family"))


def _paragraph_style(name: str, css: dict[str, str], *, font: PdfFont | None = None) -> ParagraphStyle:
    font = font or _css_font(css)
    font_size = _parse_pt(css.get("font-size", ""), default=11)
    line_height = css.get("line-height", "")
    leading = _parse_pt(line_height) if line_height.endswith("pt") else font_size * max(_parse_float(line_height, default=1.0), 1.0)
    kwargs: dict[str, object] = {
        "fontName": font.variant(css.get("font-weight") == "bold", css.get("font-style") == "italic"),
        "fontSize": font_size,
        "leading": max(leading, font_size),
        # A bigger word inside the line (a textStyle mark) gets room instead of overlapping.
        "autoLeading": "max",
        "alignment": _ALIGNMENT_MAP.get(css.get("text-align", "left"), TA_LEFT),
        "spaceBefore": _parse_pt(css.get("margin-top", "")),
        "spaceAfter": _parse_pt(css.get("margin-bottom", "")),
        "leftIndent": _parse_cm(css.get("margin-left", "")) * cm,
        "firstLineIndent": _parse_cm(css.get("text-indent", "")) * cm,
    }
    text_color = _parse_color(css.get("color"))
    if text_color is not None:
        kwargs["textColor"] = text_color
    return ParagraphStyle(name, **kwargs)


def _inline_to_markup(inline_runs: list[InlineRun]) -> str:
    parts = []
    for run in inline_runs:
        text = saxutils.escape(run.text).replace("\n", "<br/>").replace("\t", "&nbsp;" * 4)
        marks = {mark.type for mark in run.marks}
        text_style = next((mark for mark in run.marks if mark.type == MarkType.TEXT_STYLE), None)
        if MarkType.CODE in marks:
            text = f'<font face="{pdf_font("Courier New").regular}">{text}</font>'
        if text_style is not None:
            attributes = []
            if text_style.fontFamily:
                attributes.append(f'face="{pdf_font(text_style.fontFamily).regular}"')
            if text_style.fontSizePt:
                attributes.append(f'size="{text_style.fontSizePt:g}"')
            if (color := _hex(text_style.color)) is not None:
                attributes.append(f'color="{color}"')
            if (background := _hex(text_style.backgroundColor)) is not None:
                attributes.append(f'backColor="{background}"')
            if attributes:
                text = f"<font {' '.join(attributes)}>{text}</font>"
        if MarkType.SUPERSCRIPT in marks:
            text = f"<super>{text}</super>"
        elif MarkType.SUBSCRIPT in marks:
            text = f"<sub>{text}</sub>"
        if MarkType.BOLD in marks:
            text = f"<b>{text}</b>"
        if MarkType.ITALIC in marks:
            text = f"<i>{text}</i>"
        if MarkType.UNDERLINE in marks:
            text = f"<u>{text}</u>"
        if MarkType.STRIKE in marks:
            text = f"<strike>{text}</strike>"
        link = next((m for m in run.marks if m.type == MarkType.LINK and m.href), None)
        if link:
            escaped_href = saxutils.escape(link.href, {'"': "&quot;"})
            text = f'<a href="{escaped_href}" color="blue">{text}</a>'
        parts.append(text)
    return "".join(parts) or "&nbsp;"


def _build_paragraph(element: Element, document: Document) -> Paragraph:
    css = _resolved_css(element, document)
    inline_runs = element.inline or ([InlineRun(text=element.content)] if element.content else [])
    return Paragraph(_inline_to_markup(inline_runs), _paragraph_style(f"el-{element.id}", css))


def _build_code_block(element: Element, document: Document) -> XPreformatted:
    """Preformatted, so indentation and line breaks survive."""
    css = _resolved_css(element, document)
    font = pdf_font(css.get("font-family") if "font-family" in css else "Courier New")
    size = _parse_pt(css.get("font-size", ""), default=9)
    style = ParagraphStyle(
        f"code-{element.id}",
        fontName=font.regular,
        fontSize=size,
        leading=size * 1.25,
        backColor=colors.HexColor("#F0F0F0"),
        borderPadding=6,
        spaceBefore=6,
        spaceAfter=_parse_pt(css.get("margin-bottom", ""), default=6) + 6,
    )
    return XPreformatted(saxutils.escape(element.content), style)


def _build_list_flowables(element: Element, document: Document) -> list:
    css = _resolved_css(element, document)
    base_style = _paragraph_style(f"list-{element.id}", css)
    flowables = []
    counters: dict[int, int] = {}
    for item in element.listItems or []:
        counters[item.level] = counters.get(item.level, 0) + 1
        for deeper in [lvl for lvl in counters if lvl > item.level]:
            counters[deeper] = 0

        if item.checked is not None:
            prefix = f"{_CHECKBOX[item.checked]} "
        elif element.ordered:
            prefix = f"{counters[item.level]}. "
        else:
            prefix = "• "

        item_style = base_style.clone(
            f"list-{element.id}-{item.id}", leftIndent=base_style.leftIndent + 14 * (item.level + 1), spaceBefore=0, spaceAfter=2
        )
        flowables.append(Paragraph(prefix + _inline_to_markup(item.inline), item_style))
    if flowables:
        flowables[-1].style = flowables[-1].style.clone(f"list-{element.id}-last", spaceAfter=base_style.spaceAfter)
    return flowables


def _grid(table_content: TableContent) -> tuple[list[list[tuple[int, int, object] | None]], int]:
    """Where each cell sits once spans are taken into account: grid[row][col]
    is (row, col, cell) at a cell's top-left corner and None where a span covers."""
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
    height = len(table_content.rows)
    grid: list[list[tuple[int, int, object] | None]] = [[None] * width for _ in range(height)]
    for row_index, column, cell in placed:
        if row_index < height:
            grid[row_index][column] = (row_index, column, cell)
    return grid, width


def _build_table(element: Element, document: Document):
    table_content = element.table
    if table_content is None or not table_content.rows:
        return None
    css = _resolved_css(element, document)
    font = _css_font(css)
    cell_style = _paragraph_style(f"cell-{element.id}", {**css, "margin-bottom": "0", "margin-top": "0"}, font=font)
    alignments = table_content.alignments or []

    grid, width = _grid(table_content)
    if width == 0:
        return None
    commands: list[tuple] = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    data: list[list[object]] = []
    for row_index, row in enumerate(grid):
        cells: list[object] = []
        for column, slot in enumerate(row):
            if slot is None:
                cells.append("")
                continue
            _, _, cell = slot
            alignment = alignments[column] if column < len(alignments) else None
            style = cell_style.clone(
                f"cell-{element.id}-{row_index}-{column}",
                fontName=font.variant(cell.header or css.get("font-weight") == "bold", css.get("font-style") == "italic"),
                alignment=_ALIGNMENT_MAP.get(alignment or "", cell_style.alignment),
            )
            cells.append(Paragraph(_inline_to_markup(cell.inline), style))
            if cell.colspan > 1 or cell.rowspan > 1:
                commands.append(("SPAN", (column, row_index), (column + cell.colspan - 1, row_index + cell.rowspan - 1)))
            if (background := _parse_color(cell.background)) is not None:
                commands.append(("BACKGROUND", (column, row_index), (column + cell.colspan - 1, row_index + cell.rowspan - 1), background))
        data.append(cells)
    table = Table(data, colWidths=[_content_width_pt(document) / width] * width, repeatRows=1 if table_content.hasHeaderRow else 0)
    table.setStyle(TableStyle(commands))
    table.spaceAfter = _parse_pt(css.get("margin-bottom", ""), default=6) or 6
    return table


def _image_alignment(css: dict[str, str]) -> str:
    left, right = css.get("margin-left"), css.get("margin-right")
    if left == "auto" and right == "auto":
        return "CENTER"
    if left == "auto":
        return "RIGHT"
    return "LEFT"


def _build_image(element: Element, document: Document, assets: Mapping[str, bytes]) -> PdfImage | None:
    image_bytes = resolve_image_bytes(element.image, assets) if element.image else None
    if image_bytes is None:
        return None
    try:
        native_width, native_height = PILImage.open(io.BytesIO(image_bytes)).size
    except OSError:
        return None
    if not native_width or not native_height:
        return None

    css = _resolved_css(element, document)
    width_css = css.get("width", "")
    content_width = _content_width_pt(document)
    if width_css.endswith("%"):
        try:
            target_width = content_width * float(width_css.rstrip("%")) / 100
        except ValueError:
            target_width = content_width
    else:
        target_width = content_width
    target_height = target_width * (native_height / native_width)
    max_height = _content_height_pt(document) * 0.95
    if target_height > max_height:  # a picture taller than the page would stop the export
        target_width, target_height = target_width * max_height / target_height, max_height
    image = PdfImage(io.BytesIO(image_bytes), width=target_width, height=target_height)
    image.hAlign = _image_alignment(css)
    return image


def _build_flowables(element: Element, document: Document, assets: Mapping[str, bytes]) -> list:
    if element.type == ElementType.PAGE_BREAK:
        return [PageBreak()]
    if element.type == ElementType.HORIZONTAL_RULE:
        return [HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#9CA3AF"), spaceBefore=6, spaceAfter=6)]
    if element.type == ElementType.LIST:
        return _build_list_flowables(element, document)
    if element.type == ElementType.TABLE:
        table = _build_table(element, document)
        return [table] if table is not None else []
    if element.type == ElementType.IMAGE:
        image = _build_image(element, document, assets)
        return [image] if image is not None else []
    if element.type == ElementType.CODE_BLOCK:
        return [_build_code_block(element, document)]
    return [_build_paragraph(element, document)]
