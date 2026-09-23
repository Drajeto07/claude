import base64
import binascii
import io
import xml.sax.saxutils as saxutils

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import Image as PdfImage
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

from app.models.document import Document, DocumentSettings, Element, ElementType, InlineRun, MarkType

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

# reportlab ships only Helvetica/Times-Roman/Courier (+ Bold/Oblique
# variants) without registering external .ttf files, disproportionate to
# embed for an MVP -- PDF font *rendering* won't be pixel-identical to the
# live preview or the DOCX export even though the document structure and
# content are, a real, deliberately-flagged fidelity gap.
_FONT_FAMILY_MAP = {
    "arial": "Helvetica",
    "calibri": "Helvetica",
    "times new roman": "Times-Roman",
    "georgia": "Times-Roman",
    "courier new": "Courier",
}


def build_pdf(
    document: Document,
    *,
    include_headers: bool = True,
    include_page_numbers: bool = True,
    include_page_breaks: bool = True,
) -> bytes:
    """Independent of docx_export.py's python-docx-based builder --
    LibreOffice isn't available on this machine to convert one into the
    other (see the Phase 6 plan). Both read the same document.resolvedStyles,
    so there is nothing to keep in sync beyond that shared source of truth.

    The three include_* flags are export-time-only overrides (spec's export
    options screen) -- see build_docx's docstring; same contract here."""
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
        story.extend(_build_flowables(element, document))
    if not story:
        # An entirely empty story makes reportlab emit a zero-page PDF --
        # technically valid but a degenerate, likely-unopenable file for a
        # real "export my document" feature. One blank paragraph guarantees
        # at least one page exists.
        story.append(Paragraph("", ParagraphStyle("empty")))

    def decorate_page(canvas_obj, doc_obj) -> None:
        canvas_obj.saveState()
        page_width = doc_obj.pagesize[0]
        if include_headers and settings.header:
            canvas_obj.setFont("Helvetica", 9)
            canvas_obj.drawCentredString(page_width / 2, doc_obj.pagesize[1] - 20, settings.header)
        footer_text = settings.footer if include_headers else None
        page_number_text = _page_number_text(settings, canvas_obj) if include_page_numbers else None
        footer_parts = [part for part in (footer_text, page_number_text) if part]
        if footer_parts:
            canvas_obj.setFont("Helvetica", 9)
            canvas_obj.drawCentredString(page_width / 2, 20, " · ".join(footer_parts))
        canvas_obj.restoreState()

    doc_template.build(story, onFirstPage=decorate_page, onLaterPages=decorate_page)
    return buffer.getvalue()


def _page_number_text(settings: DocumentSettings, canvas_obj) -> str | None:
    return f"Page {canvas_obj.getPageNumber()}" if settings.showPageNumbers else None


def _page_dimensions_mm(settings: DocumentSettings) -> tuple[float, float]:
    width_mm, height_mm = _PAGE_DIMENSIONS_MM.get(settings.pageSize, _PAGE_DIMENSIONS_MM["A4"])
    if settings.orientation == "landscape":
        return height_mm, width_mm
    return width_mm, height_mm


def _content_width_pt(document: Document) -> float:
    width_mm, _ = _page_dimensions_mm(document.settings)
    content_width_mm = width_mm - (document.settings.marginLeftCm + document.settings.marginRightCm) * 10
    return content_width_mm * mm


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
    if value in _NAMED_COLORS:
        return colors.HexColor(f"#{_NAMED_COLORS[value]}")
    return None


def _base_font(css: dict[str, str]) -> str:
    family = css.get("font-family", "").strip('"').lower()
    base = _FONT_FAMILY_MAP.get(family, "Helvetica")
    bold = css.get("font-weight") == "bold"
    italic = css.get("font-style") == "italic"
    variants = {
        "Helvetica": {(False, False): "Helvetica", (True, False): "Helvetica-Bold", (False, True): "Helvetica-Oblique", (True, True): "Helvetica-BoldOblique"},
        "Times-Roman": {(False, False): "Times-Roman", (True, False): "Times-Bold", (False, True): "Times-Italic", (True, True): "Times-BoldItalic"},
        "Courier": {(False, False): "Courier", (True, False): "Courier-Bold", (False, True): "Courier-Oblique", (True, True): "Courier-BoldOblique"},
    }
    return variants[base][(bold, italic)]


def _paragraph_style(name: str, css: dict[str, str]) -> ParagraphStyle:
    font_size = _parse_pt(css.get("font-size", ""), default=11)
    line_height = _parse_float(css.get("line-height", ""), default=1.0)
    kwargs: dict[str, object] = {
        "fontName": _base_font(css),
        "fontSize": font_size,
        "leading": font_size * max(line_height, 1.0),
        "alignment": _ALIGNMENT_MAP.get(css.get("text-align", "left"), TA_LEFT),
        "spaceAfter": _parse_pt(css.get("margin-bottom", "")),
        "firstLineIndent": _parse_cm(css.get("text-indent", "")) * cm,
    }
    text_color = _parse_color(css.get("color"))
    if text_color is not None:
        kwargs["textColor"] = text_color
    return ParagraphStyle(name, **kwargs)


def _inline_to_markup(inline_runs: list[InlineRun]) -> str:
    parts = []
    for run in inline_runs:
        text = saxutils.escape(run.text)
        marks = {mark.type for mark in run.marks}
        if MarkType.CODE in marks:
            text = f'<font face="Courier">{text}</font>'
        if MarkType.BOLD in marks:
            text = f"<b>{text}</b>"
        if MarkType.ITALIC in marks:
            text = f"<i>{text}</i>"
        if MarkType.STRIKE in marks:
            text = f"<strike>{text}</strike>"
        parts.append(text)
    return "".join(parts) or "&nbsp;"


def _build_paragraph(element: Element, document: Document) -> Paragraph:
    css = _resolved_css(element, document)
    inline_runs = element.inline or ([InlineRun(text=element.content)] if element.content else [])
    return Paragraph(_inline_to_markup(inline_runs), _paragraph_style(f"el-{element.id}", css))


def _build_code_block(element: Element, document: Document) -> Paragraph:
    style = ParagraphStyle(
        f"code-{element.id}",
        fontName="Courier",
        fontSize=9,
        leading=11,
        backColor=colors.HexColor("#F0F0F0"),
        borderPadding=6,
    )
    text = saxutils.escape(element.content).replace("\n", "<br/>")
    return Paragraph(text, style)


def _build_list_flowables(element: Element, document: Document) -> list:
    css = _resolved_css(element, document)
    base_style = _paragraph_style(f"list-{element.id}", css)
    flowables = []
    counters: dict[int, int] = {}
    for item in element.listItems or []:
        counters[item.level] = counters.get(item.level, 0) + 1
        for deeper in [lvl for lvl in counters if lvl > item.level]:
            counters[deeper] = 0

        if item.checked is True:
            prefix = "☑ "
        elif item.checked is False:
            prefix = "☐ "
        elif element.ordered:
            prefix = f"{counters[item.level]}. "
        else:
            prefix = "• "

        item_style = base_style.clone(f"list-{element.id}-{item.id}", leftIndent=base_style.leftIndent + 14 * (item.level + 1))
        flowables.append(Paragraph(prefix + _inline_to_markup(item.inline), item_style))
    return flowables


def _build_table(element: Element, document: Document):
    from reportlab.platypus import Table, TableStyle

    table_content = element.table
    if table_content is None or not table_content.rows:
        return None
    css = _resolved_css(element, document)
    cell_style = _paragraph_style(f"cell-{element.id}", css)
    header_style = cell_style.clone(f"cell-{element.id}-header", fontName=_base_font({**css, "font-weight": "bold"}))

    data = [
        [Paragraph(_inline_to_markup(cell.inline), header_style if cell.header else cell_style) for cell in row.cells]
        for row in table_content.rows
    ]
    table = Table(data)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _build_image(element: Element, document: Document) -> PdfImage | None:
    image = element.image
    if image is None:
        return None
    try:
        _header, encoded = image.src.split(",", 1)
        image_bytes = base64.b64decode(encoded)
        native_width, native_height = PILImage.open(io.BytesIO(image_bytes)).size
    except (ValueError, binascii.Error, OSError):
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
    return PdfImage(io.BytesIO(image_bytes), width=target_width, height=target_height)


def _build_flowables(element: Element, document: Document) -> list:
    if element.type == ElementType.PAGE_BREAK:
        return [PageBreak()]
    if element.type == ElementType.LIST:
        return _build_list_flowables(element, document)
    if element.type == ElementType.TABLE:
        table = _build_table(element, document)
        return [table] if table is not None else []
    if element.type == ElementType.IMAGE:
        image = _build_image(element, document)
        return [image] if image is not None else []
    if element.type == ElementType.CODE_BLOCK:
        return [_build_code_block(element, document)]
    return [_build_paragraph(element, document)]
