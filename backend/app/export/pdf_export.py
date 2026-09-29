import io
import xml.sax.saxutils as saxutils
from collections.abc import Mapping
from contextvars import ContextVar
from functools import partial
from itertools import groupby

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Indenter,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Table,
    TableStyle,
    XPreformatted,
)
from reportlab.platypus.doctemplate import ActionFlowable
from reportlab.platypus import Image as PdfImage

from app.export.fonts import PdfFont, font_for, pdf_font
from app.export.images import resolve_image_bytes
from app.fidelity.exports import collecting, note, pdf_document_notes
from app.fidelity.report import FidelityPolicy, ReportBuilder
from app.formatting.colors import NAMED_COLORS
from app.formatting.render_spec import page_size_mm
from app.formatting.list_numbering import item_label, list_counters, list_levels
from app.models.document import (
    Document,
    DocumentSettings,
    Element,
    ElementType,
    InlineRun,
    MarkType,
    SectionSettings,
    TableContent,
    target_for_element,
)
from app.parsers.docx_styles import format_number

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
    report: ReportBuilder | None = None,
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
    ({PAGE}, {NUMPAGES}) is left out too.

    `report` collects what this export approximates or leaves out (app/fidelity)."""
    with collecting(report):
        pdf_document_notes(document)
        return _build_pdf(document, assets or {}, include_headers, include_page_numbers, include_page_breaks)


def _build_pdf(
    document: Document, assets: Mapping[str, bytes], include_headers: bool, include_page_numbers: bool, include_page_breaks: bool
) -> bytes:
    settings = document.settings
    buffer = io.BytesIO()
    # Each section's own settings; the last section's are Document.lastSection's (DOCX-015).
    sections = [section if section is not None else document.lastSection for section in _section_settings(document)]
    pages = [_SectionPage.of(section, settings) for section in sections]
    doc_template = BaseDocTemplate(
        buffer,
        pagesize=(pages[0].width, pages[0].height),
        pageTemplates=[page.template(index) for index, page in enumerate(pages)],
        title=document.metadata.title,
        author=(document.metadata.sourceProperties.author if document.metadata.sourceProperties else None) or "",
        subject=(document.metadata.sourceProperties.subject if document.metadata.sourceProperties else None) or "",
    )
    numbering = _Numbering()

    story: list = [_SectionStart(numbering, 0, None, sections[0])]
    section = 0
    token = _SECTION_AREA.set(pages[0].area)
    previous: tuple[Element, list] | None = None
    try:
        for element in document.elements:
            if element.type == ElementType.PAGE_BREAK and not include_page_breaks:
                continue
            if element.type == ElementType.SECTION_BREAK:  # the next section, on its own pages (DOCX-015)
                section = min(section + 1, len(pages) - 1)
                start = element.sectionBreak.start if element.sectionBreak and include_page_breaks else "continuous"
                story.append(NextPageTemplate(f"section-{section}"))
                if start != "continuous":
                    story.append(PageBreak())
                story.append(_SectionStart(numbering, section, start, sections[section]))
                _SECTION_AREA.set(pages[section].area)
                previous = None
                continue
            placed, flowables = _story_flowables(element, document, assets, previous, pages[section])
            story.extend(placed)
            previous = (element, flowables)
    finally:
        _SECTION_AREA.reset(token)
    return _finish(document, doc_template, story, pages, numbering, buffer, include_headers, include_page_numbers)


def _story_flowables(
    element: Element, document: Document, assets: Mapping[str, bytes], previous: tuple[Element, list] | None, page: "_SectionPage"
) -> tuple[list, list]:
    """An element's flowables at its section's column width: as they go into the
    story (kept together, with border lines), and as they are."""
    flowables = _build_flowables(element, document, assets, width=page.column_width)
    css = _resolved_css(element, document)
    if previous is not None and _contextual(css) and _contextual(_resolved_css(previous[0], document)):
        if target_for_element(previous[0]) == target_for_element(element):
            _close_up(previous[1], flowables)  # no space between paragraphs of the same kind (DOCX-014)
    above, below = _border_lines(css)
    placed = [*above, *flowables, *below] if above or below else flowables
    if css.get("break-inside") == "avoid" and placed:
        return [KeepTogether(placed)], flowables  # its lines kept together on one page
    return placed, flowables


def _finish(document, doc_template, story: list, pages: list, numbering, buffer, include_headers: bool, include_page_numbers: bool) -> bytes:
    settings = document.settings
    if not any(not isinstance(flowable, ActionFlowable) for flowable in story):
        # An entirely empty story makes reportlab emit a zero-page PDF --
        # technically valid but a degenerate, likely-unopenable file for a
        # real "export my document" feature. One blank paragraph guarantees
        # at least one page exists.
        story.append(Paragraph("", ParagraphStyle("empty")))

    page_numbers = include_page_numbers and settings.showPageNumbers
    font = pdf_font(document.resolvedStyles.get("Paragraph", {}).get("font-family"))
    texts = _HeaderTexts(document)

    def decorate(canvas_obj: Canvas, page: int, total: int) -> None:
        page_width, page_height = canvas_obj._pagesize
        section = numbering.section_of(page)
        area = pages[section]  # the page's own section: its margins, numbering, headers and footers (DOCX-015)
        label = numbering.label(page)
        header_key, footer_key = texts.keys(section, first=numbering.first_page(section) == page, even=numbering.number(page) % 2 == 0)
        header = _page_text(texts.text(section, header_key), include_headers, include_page_numbers)
        footer = _page_text(texts.text(section, footer_key), include_headers, include_page_numbers)
        canvas_obj.saveState()
        canvas_obj.setFont(font.regular, 9)
        # At the section's header and footer distances from the page's edges, as Word places them.
        if header:
            canvas_obj.drawCentredString(page_width / 2, page_height - min(area.header_distance, page_height / 3) - 9, _fill(header, label, total))
        footer_parts = [part for part in (_fill(footer, label, total) if footer else None, f"Page {label}" if page_numbers else None) if part]
        if footer_parts:
            canvas_obj.drawCentredString(page_width / 2, min(area.footer_distance, page_height / 3) + 2, " · ".join(footer_parts))
        canvas_obj.restoreState()

    doc_template.build(story, canvasmaker=partial(_DecoratedCanvas, decorate=decorate))
    return buffer.getvalue()


def _border(value: str | None) -> tuple[float, object, str] | None:
    """A border rule's width, colour and style, or None for none."""
    if not value or value == "none":
        return None
    style, width, color = value.split(" ")
    parsed = _parse_color(color)
    return _parse_pt(width, default=0.5), parsed if parsed is not None else colors.black, style


def _box(css: dict[str, str]) -> tuple[float, object] | None:
    sides = [css.get(f"border-{side}") for side in ("top", "bottom", "left", "right")]
    if all(side and side != "none" for side in sides) and len(set(sides)) == 1:
        width, color, _ = _border(sides[0])
        return width, color
    return None


def _border_lines(css: dict[str, str]) -> tuple[list, list]:
    """A border above or below a paragraph without a box, as a line before or after it."""
    if _box(css):
        return [], []
    lines = []
    for side in ("top", "bottom"):
        border = _border(css.get(f"border-{side}"))
        if border is None:
            lines.append([])
            continue
        width, color, style = border
        dash = {"dotted": [1, 2], "dashed": [4, 2]}.get(style)
        lines.append([HRFlowable(width="100%", thickness=width, color=color, dash=dash, spaceBefore=2, spaceAfter=2)])
    return lines[0], lines[1]


def _contextual(css: dict[str, str]) -> bool:
    return css.get("--contextual-spacing") == "true"


def _close_up(before: list, after: list) -> None:
    """No space between two paragraphs, as Word's contextual spacing sets them."""
    last = next((flowable for flowable in reversed(before) if isinstance(flowable, Paragraph)), None)
    first = next((flowable for flowable in after if isinstance(flowable, Paragraph)), None)
    if last is not None and first is not None:
        last.style = last.style.clone(f"{last.style.name}-close", spaceAfter=0)
        first.style = first.style.clone(f"{first.style.name}-close", spaceBefore=0)


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


def _fill(text: str, page: int | str, total: int) -> str:
    return text.replace(PAGE_TOKEN, str(page)).replace(NUMPAGES_TOKEN, str(total))


# -- sections (DOCX-015) ------------------------------------------------------------------

# The content area (width, height) of the section being laid out: pictures fit it.
_SECTION_AREA: ContextVar[tuple[float, float] | None] = ContextVar("section_area", default=None)


def _section_settings(document: Document) -> list[SectionSettings | None]:
    """Each section's own settings, in order: a section break holds the one it ends;
    the last section's are the document's (None)."""
    breaks = [element.sectionBreak or SectionSettings() for element in document.elements if element.type == ElementType.SECTION_BREAK]
    return [*breaks, None]


_HEADER_DISTANCE_CM = 1.27  # Word's default header and footer distance


class _SectionPage:
    """A section's page: size, margins, columns, and where its header and footer
    sit (their distance from the page's edge), in points."""

    def __init__(self, width: float, height: float, margins: tuple[float, float, float, float], columns: int, gap: float, section: SectionSettings | None) -> None:
        self.width, self.height = width, height
        self.top, self.bottom, self.left, self.right = margins
        usable = width - self.left - self.right
        column_width = (usable - gap * (columns - 1)) / columns if columns > 1 else usable
        if columns > 1 and column_width < 3 * cm:  # too narrow to set text in: one column
            columns, column_width = 1, usable
        self.columns, self.gap, self.column_width = columns, gap, column_width
        self.section = section
        self.area = (column_width, height - self.top - self.bottom)
        header, footer = (section.headerDistanceCm, section.footerDistanceCm) if section is not None else (None, None)
        self.header_distance = (header if header is not None else _HEADER_DISTANCE_CM) * cm
        self.footer_distance = (footer if footer is not None else _HEADER_DISTANCE_CM) * cm

    @classmethod
    def of(cls, section: SectionSettings | None, settings: DocumentSettings) -> "_SectionPage":
        width_mm, height_mm = page_size_mm(settings.pageSize, settings.orientation)
        if section is not None and section.pageWidthMm and section.pageHeightMm:
            width_mm, height_mm = section.pageWidthMm, section.pageHeightMm
        elif section is not None and section.orientation and (section.orientation == "landscape") != (width_mm > height_mm):
            width_mm, height_mm = height_mm, width_mm

        def margin(name: str) -> float:
            own = getattr(section, f"margin{name}Cm") if section is not None else None
            return (own if own is not None else getattr(settings, f"margin{name}Cm")) * cm

        columns = section.columns if section is not None and section.columns else 1
        gap = (section.columnSpacingCm if section is not None and section.columnSpacingCm is not None else 1.25) * cm
        return cls(width_mm * mm, height_mm * mm, (margin("Top"), margin("Bottom"), margin("Left"), margin("Right")), columns, gap, section)

    def template(self, index: int) -> PageTemplate:
        frames = [
            Frame(self.left + column * (self.column_width + self.gap), self.bottom, self.column_width, self.height - self.top - self.bottom, id=f"section-{index}-{column}")
            for column in range(self.columns)
        ]
        return PageTemplate(id=f"section-{index}", frames=frames, pagesize=(self.width, self.height))


class _Numbering:
    """Which section each page is in, and the number it shows (DOCX-015)."""

    def __init__(self) -> None:
        self.starts: list[tuple[int, int, str, int]] = []  # (first page, its number, format, section)

    def _start(self, page: int) -> tuple[int, int, str, int] | None:
        found = None
        for start in self.starts:
            if start[0] > page:
                break
            found = start
        return found

    def number(self, page: int) -> int:
        start = self._start(page)
        return start[1] + (page - start[0]) if start else page

    def label(self, page: int) -> str:
        start = self._start(page)
        return format_number(self.number(page), start[2] if start else "decimal")

    def section_of(self, page: int) -> int:
        start = self._start(page)
        return start[3] if start else 0

    def first_page(self, section: int) -> int | None:
        return next((start[0] for start in self.starts if start[3] == section), None)


class _HeaderTexts:
    """Each section's headers and footers, as Word shows them (DOCX-015): its own, or
    the previous section's where it has none of that kind (linked to previous)."""

    def __init__(self, document: Document) -> None:
        self.document = document
        self.sections = _section_settings(document)

    def _own(self, index: int, key: str) -> str | None:
        section = self.sections[index]
        if section is not None:
            return getattr(section, key)
        last = self.document.lastSection
        if key in ("header", "footer"):  # the last section's main ones are the document's; "" in lastSection an own empty one
            own = getattr(self.document.settings, key)
            return own if own is not None else getattr(last, key) if last is not None else None
        return getattr(last, key) if last is not None else None

    def text(self, index: int, key: str) -> str | None:
        while index >= 0:
            own = self._own(index, key)
            if own is not None:
                return own
            index -= 1
        return None

    def keys(self, index: int, *, first: bool, even: bool) -> tuple[str, str]:
        """Which header and footer a page takes: its section's first-page ones on its
        first page, when it has them; the even-page ones on even pages, when the
        document has them; the main ones otherwise."""
        section = self.sections[index]
        different_first = section.differentFirstPage if section is not None else (
            self.document.lastSection.differentFirstPage if self.document.lastSection is not None else None
        )
        if first and different_first:
            return "firstHeader", "firstFooter"
        if even and self.document.evenAndOddHeaders:
            return "evenHeader", "evenFooter"
        return "header", "footer"


class _SectionStart(ActionFlowable):
    """Where a section starts: its first page and the number it shows. A section to an
    even or odd page ends a blank page first when the one it would start on is the
    other kind, as Word does. A continuous one begins on the page the section before
    ends on, which stays that section's: its own pages -- their header, footer and
    number -- are the ones after, as in Word."""

    def __init__(self, numbering: _Numbering, index: int, start: str | None, section: SectionSettings | None) -> None:
        super().__init__()
        self.numbering, self.index, self.start = numbering, index, start
        self.restart = section.pageNumberStart if section is not None else None
        self.format = (section.pageNumberFormat if section is not None else None) or "decimal"

    def apply(self, doc) -> None:
        page = doc.page
        if not self.numbering.starts:  # the first section, from the first page
            number = self.restart if self.restart is not None else page
        else:
            if self.start == "continuous":
                page += 1
            number = self.restart if self.restart is not None else self.numbering.number(page - 1) + 1
        if self.start in ("evenPage", "oddPage") and (number % 2 == 0) != (self.start == "evenPage"):
            doc.handle_pageBreak()  # a blank page ends the section before
            page += 1
            number = self.restart if self.restart is not None else number + 1
        self.numbering.starts.append((page, number, self.format, self.index))


def _page_dimensions_mm(settings: DocumentSettings) -> tuple[float, float]:
    return page_size_mm(settings.pageSize, settings.orientation)


def _content_width_pt(document: Document) -> float:
    if (area := _SECTION_AREA.get()) is not None:
        return area[0]
    width_mm, _ = _page_dimensions_mm(document.settings)
    content_width_mm = width_mm - (document.settings.marginLeftCm + document.settings.marginRightCm) * 10
    return content_width_mm * mm


def _content_height_pt(document: Document) -> float:
    if (area := _SECTION_AREA.get()) is not None:
        return area[1]
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
        # DOCX-014: the right indent and Word's pagination controls.
        "rightIndent": _parse_cm(css.get("margin-right", "")) * cm if css.get("margin-right", "").endswith("cm") else 0,
        "keepWithNext": 1 if css.get("break-after") == "avoid" else 0,
    }
    if css.get("widows") in ("1", "2"):  # widow and orphan control on (2) or off (1)
        kwargs["allowWidows"] = kwargs["allowOrphans"] = 1 if css["widows"] == "1" else 0
    if (background := _parse_color(css.get("background-color"))) is not None:
        kwargs["backColor"] = background
    if css.get("direction") == "rtl" and "text-align" not in css:
        kwargs["alignment"] = TA_RIGHT  # a right-to-left paragraph starts on the right
    if box := _box(css):  # a border on all four sides, the same: reportlab's box
        width, color = box
        kwargs.update(borderWidth=width, borderColor=color, borderPadding=3)
    text_color = _parse_color(css.get("color"))
    if text_color is not None:
        kwargs["textColor"] = text_color
    return ParagraphStyle(name, **kwargs)


def _escaped(text: str) -> str:
    return saxutils.escape(text).replace("\n", "<br/>").replace("\t", "&nbsp;" * 4)


def _small_caps(text: str, size: float) -> str:
    """Small capitals: the lower-case letters as capitals a size smaller (reportlab has none)."""
    parts = []
    for lower, group in groupby(text, key=str.islower):
        piece = "".join(group)
        parts.append(f'<font size="{size * 0.8:g}">{_escaped(piece.upper())}</font>' if lower else _escaped(piece))
    return "".join(parts)


def _inline_to_markup(inline_runs: list[InlineRun], base_size: float | None = None) -> str:
    parts = []
    for run in inline_runs:
        if any(mark.type == MarkType.HIDDEN for mark in run.marks):
            continue  # hidden text isn't printed (DOCX-025), as in Word
        by_type = {mark.type: mark for mark in run.marks}
        marks = set(by_type)
        text_style = by_type.get(MarkType.TEXT_STYLE)
        size = (text_style.fontSizePt if text_style else None) or base_size or 11.0
        if text_style is not None and text_style.caps:
            text = _escaped(run.text.upper())
        elif text_style is not None and text_style.smallCaps:
            text = _small_caps(run.text, size)
        else:
            text = _escaped(run.text)
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
        elif text_style is not None and text_style.baselineShiftPt:  # raised or lowered, at its own size
            tag = "super" if text_style.baselineShiftPt > 0 else "sub"
            text = f'<{tag} size="{size:g}" rise="{abs(text_style.baselineShiftPt):g}">{text}</{tag}>'
        if MarkType.BOLD in marks:
            text = f"<b>{text}</b>"
        if MarkType.ITALIC in marks:
            text = f"<i>{text}</i>"
        if MarkType.UNDERLINE in marks:  # dotted, dashed and wavy lines are plain ones (the export report says so)
            line = by_type[MarkType.UNDERLINE].lineStyle
            attributes = ' kind="double"' if line == "double" else ' width="1.5"' if line == "thick" else ""
            text = f"<u{attributes}>{text}</u>"
        if MarkType.STRIKE in marks:
            attributes = ' kind="double"' if by_type[MarkType.STRIKE].lineStyle == "double" else ""
            text = f"<strike{attributes}>{text}</strike>"
        link = next((m for m in run.marks if m.type == MarkType.LINK and m.href), None)
        if link:
            escaped_href = saxutils.escape(link.href, {'"': "&quot;"})
            text = f'<a href="{escaped_href}" color="blue">{text}</a>'
        parts.append(text)
    return "".join(parts) or "&nbsp;"


def _build_paragraph(element: Element, document: Document, *, css: dict[str, str] | None = None, indent: float = 0.0) -> Paragraph:
    css = _resolved_css(element, document) if css is None else css
    inline_runs = element.inline or ([InlineRun(text=element.content)] if element.content else [])
    style = _paragraph_style(f"el-{element.id}", css)
    if indent:
        style.leftIndent += indent
    return Paragraph(_inline_to_markup(inline_runs, style.fontSize), style)


def _build_code_block(element: Element, document: Document, *, indent: float = 0.0) -> XPreformatted:
    """Preformatted, so indentation and line breaks survive."""
    css = _resolved_css(element, document)
    font = pdf_font(css.get("font-family") or "Courier New")
    base = _paragraph_style(f"code-{element.id}", css, font=font)
    # The grey box's padding sits outside the text, so the spacing makes room for it.
    style = base.clone(
        f"code-{element.id}-box",
        fontName=font.regular,
        backColor=colors.HexColor("#F0F0F0"),
        borderPadding=6,
        spaceBefore=base.spaceBefore + 6,
        spaceAfter=base.spaceAfter + 6,
        leftIndent=base.leftIndent + indent,
    )
    return XPreformatted(saxutils.escape(element.content), style)


# The numbering sequence by level, as the Word export writes it (docx_export.py).


def _build_list_flowables(
    element: Element,
    document: Document,
    assets: Mapping[str, bytes],
    *,
    width: float,
    indent: float = 0.0,
    base_level: int = 0,
    in_cell: bool = False,
) -> list:
    """`base_level`: how deep the list sits (a list inside a list item), for its
    indent and its numbering. Each item is numbered from the list's levels as Word
    numbers it (DOCX-016): its label -- "Чл. 1.", "1.2.", "а)", a bullet -- hangs at its
    level's indent, or leads its text with a space or nothing, as the level says."""
    css = _resolved_css(element, document)
    base_style = _paragraph_style(f"list-{element.id}", css)
    base_indent = base_style.leftIndent + indent
    checklist = any(item.checked is not None for item in element.listItems or [])
    kind = "none" if checklist else "number" if element.ordered else "bullet"
    levels = list_levels(kind, element.numbering, base_level)
    counters = list_counters(levels, element.numbering, kind, base_level)
    flowables = []
    for item in element.listItems or []:
        level = min(item.level + base_level, len(levels) - 1)
        spec = levels[level]
        label = item_label(levels, counters, level)
        text_indent = base_indent + spec.left / 20
        item_style = base_style.clone(f"list-{element.id}-{item.id}", leftIndent=text_indent, spaceBefore=0, spaceAfter=0)
        markup = _inline_to_markup(item.inline, item_style.fontSize)
        if item.checked is not None:
            flowables.append(Paragraph(f"{_CHECKBOX[item.checked]} " + markup, item_style))
        elif spec.suffix == "tab" and label:
            item_style.bulletIndent = max(text_indent - spec.hanging / 20, 0)
            item_style.bulletFontName = font_for(label[0], item_style.fontName) if spec.fmt == "bullet" else item_style.fontName
            item_style.bulletFontSize = item_style.fontSize
            flowables.append(Paragraph(markup, item_style, bulletText=_escaped(label)))
        else:
            item_style.firstLineIndent = -spec.hanging / 20
            lead = f"{_escaped(label)} " if spec.suffix == "space" and label else _escaped(label)
            if spec.fmt == "bullet" and label and font_for(label[0], item_style.fontName) != item_style.fontName:
                lead = f'<font name="{font_for(label[0], item_style.fontName)}">{lead}</font>'
            flowables.append(Paragraph(lead + markup, item_style))
        # What the item holds after its first paragraph sits under its text; a list
        # there nests one level deeper and counts on its own.
        for block in item.blocks or []:
            if block.type == ElementType.LIST:
                flowables += _build_list_flowables(block, document, assets, width=width, indent=indent, base_level=level + 1, in_cell=in_cell)
            else:
                flowables += _build_flowables(block, document, assets, width=width, indent=text_indent, in_cell=in_cell)
    if flowables and isinstance(flowables[-1], Paragraph):
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


_CELL_PADDING = 12  # LEFTPADDING + RIGHTPADDING below


_V_ALIGN = {"top": "TOP", "center": "MIDDLE", "bottom": "BOTTOM"}
_H_ALIGN = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}
_WORD_CELL_MARGIN = 0.19 * cm  # Word's left and right cell margin


def _column_widths(table_content: TableContent, columns: int, width: float) -> list[float]:
    """Each column's width, pt: the grid's, as wide as the table says (cm, or a share of
    the room) and never wider than the room; equal columns without a grid."""
    grid = table_content.columnWidthsCm
    if not grid or len(grid) != columns or sum(grid) <= 0:
        total = min(width, table_content.widthCm * cm) if table_content.widthCm else width
        return [total / columns] * columns
    widths = [value * cm for value in grid]
    total = sum(widths)
    if table_content.widthPercent:
        target = width * table_content.widthPercent / 100
    elif table_content.widthCm:
        target = table_content.widthCm * cm
    else:
        target = total
    scale = min(target, width) / total
    return [value * scale for value in widths]


def _line(value: str | None):
    """A border value as (width, colour, dash, count) for a table line, or None for no line."""
    if not value or value == "none":
        return None
    style, width, color = value.split(" ")
    parsed = _parse_color(color)
    dash = {"dashed": (3, 2), "dotted": (1, 1.5)}.get(style)
    return _parse_pt(width, default=0.5), parsed if parsed is not None else colors.black, dash, 2 if style == "double" else 1


def _border_commands(table_content: TableContent, grid, rows: int, columns: int) -> list[tuple]:
    """Every cell edge's line, as Word draws it: the cell's own border on that side, else
    its neighbour's across the edge, else the table's (its outer sides, or the lines
    between rows and columns). A table with no borders anywhere, made here, is a grid."""
    table_borders = table_content.borders
    if table_borders is None and not any(cell.borders for row in table_content.rows for cell in row.cells):
        return [("GRID", (0, 0), (-1, -1), 0.5, colors.grey)] if table_content.headerBold else []
    owner: dict[tuple[int, int], tuple[int, int, object]] = {}
    for row in grid:
        for slot in row:
            if slot is not None:
                row_index, column, cell = slot
                for dr in range(cell.rowspan):
                    for dc in range(cell.colspan):
                        owner[(row_index + dr, column + dc)] = slot

    def own(cell, side: str) -> str | None:
        return getattr(cell.borders, side) if cell.borders is not None else None

    def table_side(side: str) -> str | None:
        return getattr(table_borders, side) if table_borders is not None else None

    commands: list[tuple] = []

    def draw(op: str, start: tuple[int, int], stop: tuple[int, int], value: str | None) -> None:
        line = _line(value)
        if line is None:
            return
        weight, color, dash, count = line
        commands.append((op, start, stop, weight, color, 1, dash, 1, count, 1))

    for (row_index, column), slot in owner.items():
        if (row_index, column) != slot[:2]:
            continue
        _, _, cell = slot
        last_row, last_column = min(row_index + cell.rowspan - 1, rows - 1), min(column + cell.colspan - 1, columns - 1)
        above = owner.get((row_index - 1, column))
        left = owner.get((row_index, column - 1))
        top = own(cell, "top") or (own(above[2], "bottom") if above else None) or table_side("top" if row_index == 0 else "insideH")
        before = own(cell, "left") or (own(left[2], "right") if left else None) or table_side("left" if column == 0 else "insideV")
        draw("LINEABOVE", (column, row_index), (last_column, row_index), top)
        draw("LINEBEFORE", (column, row_index), (column, last_row), before)
        if last_row == rows - 1:
            draw("LINEBELOW", (column, last_row), (last_column, last_row), own(cell, "bottom") or table_side("bottom"))
        if last_column == columns - 1:
            draw("LINEAFTER", (last_column, row_index), (last_column, last_row), own(cell, "right") or table_side("right"))
    return commands


def _build_table(element: Element, document: Document, assets: Mapping[str, bytes], *, width: float):
    """A table as the model has it (DOCX-017): its grid's widths, borders edge by edge,
    cell margins, each cell's alignment across and up and down, rows' heights, header
    rows repeated on each page."""
    table_content = element.table
    if table_content is None or not table_content.rows:
        return None
    css = _resolved_css(element, document)
    font = _css_font(css)
    cell_style = _paragraph_style(f"cell-{element.id}", {**css, "margin-bottom": "0", "margin-top": "0"}, font=font)
    alignments = table_content.alignments or []

    grid, columns = _grid(table_content)
    if columns == 0:
        return None
    column_widths = _column_widths(table_content, columns, width)
    margins = table_content.cellMargins
    default_side = 6 if table_content.headerBold else _WORD_CELL_MARGIN  # made here, or Word's own

    def padding(value: float | None, fallback: float) -> float:
        return value * cm if value is not None else fallback

    commands: list[tuple] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), padding(margins.leftCm if margins else None, default_side)),
        ("RIGHTPADDING", (0, 0), (-1, -1), padding(margins.rightCm if margins else None, default_side)),
    ]
    if margins is not None:
        commands += [
            ("TOPPADDING", (0, 0), (-1, -1), padding(margins.topCm, 3)),
            ("BOTTOMPADDING", (0, 0), (-1, -1), padding(margins.bottomCm, 3)),
        ]
    commands += _border_commands(table_content, grid, len(grid), columns)
    data: list[list[object]] = []
    for row_index, row in enumerate(grid):
        cells: list[object] = []
        for column, slot in enumerate(row):
            if slot is None:
                cells.append("")
                continue
            _, _, cell = slot
            alignment = cell.align or (alignments[column] if column < len(alignments) else None)
            room = max(sum(column_widths[column : column + cell.colspan]) - 2 * default_side, 12)
            if cell.blocks:
                # A cell holding more than one paragraph: its blocks, as wide as the cell.
                content: list = []
                for block in cell.blocks:
                    content += _build_flowables(block, document, assets, width=room, in_cell=True)
                cells.append(content or "")
            else:
                style = cell_style.clone(
                    f"cell-{element.id}-{row_index}-{column}",
                    fontName=font.variant((cell.header and table_content.headerBold) or css.get("font-weight") == "bold", css.get("font-style") == "italic"),
                    alignment=_ALIGNMENT_MAP.get(alignment or "", cell_style.alignment),
                )
                cells.append(Paragraph(_inline_to_markup(cell.inline, style.fontSize), style))
            span = (column, row_index), (column + cell.colspan - 1, row_index + cell.rowspan - 1)
            if cell.colspan > 1 or cell.rowspan > 1:
                commands.append(("SPAN", *span))
            if (background := _parse_color(cell.background)) is not None:
                commands.append(("BACKGROUND", *span, background))
            if cell.verticalAlign is not None:
                commands.append(("VALIGN", *span, _V_ALIGN[cell.verticalAlign]))
            if cell.margins is not None:
                for side, name in (("left", "LEFTPADDING"), ("right", "RIGHTPADDING"), ("top", "TOPPADDING"), ("bottom", "BOTTOMPADDING")):
                    value = getattr(cell.margins, f"{side}Cm")
                    if value is not None:
                        commands.append((name, *span, value * cm))
        data.append(cells)
    heights = _row_heights(table_content, data, column_widths)
    repeat = 0
    while repeat < len(table_content.rows) and table_content.rows[repeat].repeatHeader:
        repeat += 1
    if repeat == 0 and table_content.headerBold and table_content.hasHeaderRow:
        repeat = 1  # a table made here repeats its header row, as before
    plain = table_content.style is None and table_content.borders is None and table_content.columnWidthsCm is None
    table = Table(data, colWidths=column_widths, rowHeights=heights, repeatRows=repeat, hAlign=_H_ALIGN.get(table_content.align or ("center" if plain else "left")))
    table.setStyle(TableStyle(commands))
    table.spaceAfter = _parse_pt(css.get("margin-bottom", ""), default=6) or 6
    return table


def _row_heights(table_content: TableContent, data: list[list[object]], column_widths: list[float]) -> list[float | None]:
    """Each row's height, pt: an exact one as it is, a least one as tall as its text needs
    but never less; None lets the row be as tall as its text."""
    heights: list[float | None] = []
    for row, cells in zip(table_content.rows, data):
        if row.heightCm is None:
            heights.append(None)
            continue
        wanted = row.heightCm * cm
        if row.heightRule == "exact":
            heights.append(wanted)
            continue
        needed = 0.0
        for index, content in enumerate(cells):
            flowables = content if isinstance(content, list) else [content] if hasattr(content, "wrap") else []
            room = column_widths[index] if index < len(column_widths) else column_widths[-1]
            needed = max(needed, sum(flowable.wrap(room, 10_000)[1] for flowable in flowables) + 6)
        heights.append(max(wanted, needed))
    return heights if any(height is not None for height in heights) else None


def _image_alignment(css: dict[str, str]) -> str:
    left, right = css.get("margin-left"), css.get("margin-right")
    if left == "auto" and right == "auto":
        return "CENTER"
    if left == "auto":
        return "RIGHT"
    return "LEFT"


def _build_image(element: Element, document: Document, assets: Mapping[str, bytes], *, width: float) -> PdfImage | None:
    image_bytes = resolve_image_bytes(element.image, assets) if element.image else None
    if image_bytes is None:
        note("export.image.missing", FidelityPolicy.UNSUPPORTED, "A picture couldn't be found for the export and was left out.", content_changed=True)
        return None
    try:
        native_width, native_height = PILImage.open(io.BytesIO(image_bytes)).size
    except OSError:
        note("export.pdf.image_unreadable", FidelityPolicy.UNSUPPORTED, "A picture that couldn't be read was left out of the PDF.", content_changed=True)
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
    target_width = min(target_width, width)  # never wider than the room it sits in
    target_height = target_width * (native_height / native_width)
    max_height = _content_height_pt(document) * 0.95
    if target_height > max_height:  # a picture taller than the page would stop the export
        target_width, target_height = target_width * max_height / target_height, max_height
    image = PdfImage(io.BytesIO(image_bytes), width=target_width, height=target_height)
    image.hAlign = _image_alignment(css)
    return image


def _indented(flowables: list, indent: float, in_cell: bool) -> list:
    """Flowables with no indent of their own (tables, pictures, rules) moved in by
    `indent` -- in the page's flow; a table cell is too narrow to indent in."""
    if not indent or in_cell or not flowables:
        return flowables
    return [Indenter(left=indent), *flowables, Indenter(left=-indent)]


def _build_quote(element: Element, document: Document, assets: Mapping[str, bytes], *, width: float, indent: float, in_cell: bool) -> list:
    """A quote of one paragraph is one paragraph; a quote holding more writes its
    paragraphs with the quote's look and the rest indented like them."""
    css = _resolved_css(element, document)
    if not element.children:
        return [_build_paragraph(element, document, css=css, indent=indent)]
    quote_indent = _parse_cm(css.get("margin-left", "")) * cm or 24
    flowables: list = []
    for child in element.children:
        if child.type == ElementType.PARAGRAPH:
            flowables.append(_build_paragraph(child, document, css=css, indent=indent))
        else:
            flowables += _build_flowables(child, document, assets, width=width, indent=indent + quote_indent, in_cell=in_cell)
    return flowables


def _build_flowables(
    element: Element,
    document: Document,
    assets: Mapping[str, bytes],
    *,
    width: float | None = None,
    indent: float = 0.0,
    in_cell: bool = False,
) -> list:
    """`width`: the room there is (a table cell's, or the page's content width);
    `indent`: how far in the block starts (under a list item's text, in a quote)."""
    width = _content_width_pt(document) if width is None else width
    if element.type == ElementType.SECTION_BREAK:  # the pages of a section are the document's own here (DOCX-015)
        start = element.sectionBreak.start if element.sectionBreak else "nextPage"
        return [] if in_cell or start == "continuous" else [PageBreak()]
    if element.type == ElementType.PAGE_BREAK:
        # A page break can't split a table cell; in the page's flow it is one.
        if in_cell:
            note("export.pdf.page_break_in_table", FidelityPolicy.LOSSY, "A page break inside a table can't be kept in a PDF.")
            return []
        return [PageBreak()]
    if element.type == ElementType.HORIZONTAL_RULE:
        rule = HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#9CA3AF"), spaceBefore=6, spaceAfter=6)
        return _indented([rule], indent, in_cell)
    if element.type == ElementType.LIST:
        return _build_list_flowables(element, document, assets, width=width, indent=indent, in_cell=in_cell)
    if element.type == ElementType.TABLE:
        table = _build_table(element, document, assets, width=width - (0 if in_cell else indent))
        return _indented([table], indent, in_cell) if table is not None else []
    if element.type == ElementType.IMAGE:
        image = _build_image(element, document, assets, width=width - (0 if in_cell else indent))
        return _indented([image], indent, in_cell) if image is not None else []
    if element.type == ElementType.CODE_BLOCK:
        return [_build_code_block(element, document, indent=indent)]
    if element.type == ElementType.QUOTE:
        return _build_quote(element, document, assets, width=width, indent=indent, in_cell=in_cell)
    return [_build_paragraph(element, document, indent=indent)]
