from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import Field, computed_field, field_validator, model_validator

from app.fidelity.report import FidelityReport
from app.formatting.colors import is_renderable_color, is_safe_font_name
from app.models.base import ApiModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ElementType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"
    QUOTE = "quote"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    CODE_BLOCK = "code_block"
    PAGE_BREAK = "page_break"
    # The end of a Word section: how the next one starts, and the page setup of the
    # pages above it (Element.sectionBreak, DOCX-015).
    SECTION_BREAK = "section_break"
    HORIZONTAL_RULE = "horizontal_rule"
    OTHER = "other"


class MarkType(str, Enum):
    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    STRIKE = "strike"
    CODE = "code"
    LINK = "link"
    SUPERSCRIPT = "superscript"
    SUBSCRIPT = "subscript"
    # Character formatting on part of a paragraph: the Mark's fontFamily /
    # fontSizePt / color / backgroundColor (a highlight is a background colour).
    TEXT_STYLE = "textStyle"
    # Word's hidden text (w:vanish): kept, and kept hidden -- the editor shows it
    # on request, a Word export hides it again, a PDF leaves it out (DOCX-025).
    HIDDEN = "hidden"


# How an underline is drawn (None: one plain line); a strikethrough is single or "double".
LineStyle = Literal["double", "thick", "dotted", "dashed", "wavy"]


class Mark(ApiModel):
    type: MarkType
    href: Optional[str] = None
    # A link's title: its tooltip in Word, the title attribute in the editor.
    title: Optional[str] = Field(default=None, max_length=500)
    # underline and strike only (DOCX-013).
    lineStyle: Optional[LineStyle] = None
    # textStyle only; None means "not set on this run". Validated because the
    # values end up in style attributes and in exported files.
    fontFamily: Optional[str] = Field(default=None, max_length=100)
    fontSizePt: Optional[float] = Field(default=None, gt=0, le=400)
    color: Optional[str] = None
    backgroundColor: Optional[str] = None
    # All capitals, small capitals, the space added between characters (points;
    # negative condenses) and a raised (positive) or lowered baseline, in points (DOCX-013).
    caps: Optional[bool] = None
    smallCaps: Optional[bool] = None
    letterSpacingPt: Optional[float] = Field(default=None, ge=-100, le=100)
    baselineShiftPt: Optional[float] = Field(default=None, ge=-100, le=100)
    # The language the text is in (a BCP 47 tag, "bg-BG"), where it isn't the
    # document's own: Word checks its spelling in it (DOCX-013).
    lang: Optional[str] = Field(default=None, max_length=35, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")

    @field_validator("caps", "smallCaps")
    @classmethod
    def _set_or_unset(cls, value: Optional[bool]) -> Optional[bool]:
        return True if value else None  # "not in capitals" and "unset" are the same

    @field_validator("letterSpacingPt", "baselineShiftPt")
    @classmethod
    def _nonzero(cls, value: Optional[float]) -> Optional[float]:
        return round(value, 2) or None if value is not None else None

    @model_validator(mode="after")
    def _line_style_fits_the_mark(self) -> "Mark":
        if self.lineStyle is not None and not (
            self.type == MarkType.UNDERLINE or (self.type == MarkType.STRIKE and self.lineStyle == "double")
        ):
            raise ValueError("lineStyle is an underline's style, or a double strikethrough")
        return self

    @field_validator("fontFamily")
    @classmethod
    def _safe_font(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not is_safe_font_name(value):
            raise ValueError("must be one font name (letters, digits, spaces, '.' and '-')")
        return value

    @field_validator("color", "backgroundColor")
    @classmethod
    def _renderable(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not is_renderable_color(value):
            raise ValueError("must be #rgb, #rrggbb or a basic colour name")
        return value


_MARK_ORDER = {mark_type: index for index, mark_type in enumerate(MarkType)}


class InlineRun(ApiModel):
    text: str
    marks: list[Mark] = Field(default_factory=list)

    @field_validator("marks")
    @classmethod
    def _canonical_order(cls, marks: list[Mark]) -> list[Mark]:
        """Marks in one order, MarkType's, whoever wrote them: the editor lists them
        its own way, and a different order must not look like a change (EDIT-007)."""
        return sorted(marks, key=lambda mark: _MARK_ORDER[mark.type])


def plain_text_from_inline(runs: Optional[list[InlineRun]]) -> str:
    """Deterministic plain-text projection used to keep `Element.content`
    always populated, regardless of which parser produced the rich fields."""
    if not runs:
        return ""
    return "".join(run.text for run in runs)


# How deep blocks may nest inside table cells, list items and quotes (a table inside a
# cell of a table is 2). Real documents stay far below it; the cap stops a crafted
# document from building a structure every reader then has to recurse through.
MAX_BLOCK_DEPTH = 8

NumberFormat = Literal["decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman"]
# How a list level counts (DOCX-016): NumberFormat's, 01 02 03 (Word's decimalZero),
# and Cyrillic letters а б в (Word's russianLower/russianUpper).
ListFormat = Literal["decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman", "decimalZero", "russianLower", "russianUpper"]
# A level's: a number in one of those, a bullet, or no label at all.
LevelFormat = Literal[
    "decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman", "decimalZero", "russianLower", "russianUpper", "bullet", "none"
]


SectionStart = Literal["nextPage", "continuous", "evenPage", "oddPage"]


class SectionSettings(ApiModel):
    """A Word section's own settings (DOCX-015). A section break holds those of the
    section it ends -- the pages above it -- and how the section after it starts;
    Document.lastSection holds the last section's, beside DocumentSettings.

    Page setup: None is the document's own (DocumentSettings). Headers and footers:
    None is the previous section's (Word's "link to previous"); the first section
    has nothing to link to, so None there is none. The first-page ones show on a
    section's first page when differentFirstPage is set, the even ones on even pages
    when the document has evenAndOddHeaders."""

    start: SectionStart = "nextPage"
    orientation: Optional[Literal["portrait", "landscape"]] = None
    pageWidthMm: Optional[float] = Field(default=None, ge=50, le=1600)
    pageHeightMm: Optional[float] = Field(default=None, ge=50, le=1600)
    marginTopCm: Optional[float] = Field(default=None, ge=0, le=20)
    marginBottomCm: Optional[float] = Field(default=None, ge=0, le=20)
    marginLeftCm: Optional[float] = Field(default=None, ge=0, le=20)
    marginRightCm: Optional[float] = Field(default=None, ge=0, le=20)
    headerDistanceCm: Optional[float] = Field(default=None, ge=0, le=20)
    footerDistanceCm: Optional[float] = Field(default=None, ge=0, le=20)
    columns: Optional[int] = Field(default=None, ge=1, le=10)
    columnSpacingCm: Optional[float] = Field(default=None, ge=0, le=20)
    pageNumberStart: Optional[int] = Field(default=None, ge=0, le=99_999)
    pageNumberFormat: Optional["NumberFormat"] = None
    header: Optional[str] = Field(default=None, max_length=500)
    footer: Optional[str] = Field(default=None, max_length=500)
    firstHeader: Optional[str] = Field(default=None, max_length=500)
    firstFooter: Optional[str] = Field(default=None, max_length=500)
    evenHeader: Optional[str] = Field(default=None, max_length=500)
    evenFooter: Optional[str] = Field(default=None, max_length=500)
    differentFirstPage: Optional[bool] = None


class ListLevel(ApiModel):
    """One level of a list, as Word's w:lvl defines it (DOCX-016): how it counts, the
    label around its number, where it starts, where its text sits and how far its
    label hangs out to the left of it."""

    format: LevelFormat = "decimal"
    # The label: %1..%9 stand for the numbers of the list's levels 1..9 -- "%1.",
    # "Чл. %1.", "(%2)", "%1.%2." -- and a bullet level's is its bullet. None: "%n." at level n.
    text: Optional[str] = Field(default=None, max_length=50)
    start: int = Field(default=1, ge=0, le=999_999)
    # From the text column's left edge, cm: where the level's text starts, and how far
    # its label hangs out to the left of that (negative: a first line indented instead).
    indentCm: Optional[float] = Field(default=None, ge=-50, le=50)
    hangingCm: Optional[float] = Field(default=None, ge=-50, le=50)
    # Word's legal numbering (isLgl): the numbers of the levels above shown as 1, 2, 3.
    legal: bool = False
    # Word's lvlRestart: None restarts after an item of any level above; 0 never; n after
    # one of level n (1-based).
    restartAfter: Optional[int] = Field(default=None, ge=0, le=9)
    # What separates the label from the text.
    suffix: Literal["tab", "space", "nothing"] = "tab"

    @field_validator("text")
    @classmethod
    def _printable(cls, value: str | None) -> str | None:
        if value is not None and any(ord(character) < 32 for character in value):
            raise ValueError("a label can't hold control characters")
        return value


class ListNumbering(ApiModel):
    """How a list counts: the number its first item gets and its top level's format
    ("a.", "iv."). From a Word file each of its levels comes too (DOCX-016): the
    labels ("Чл. 1.", "1.1", "(а)"), bullets, starts and indents. Without them, deeper
    levels count 1., a., i. in turn and bullets go •, ◦, ▪."""

    start: int = Field(default=1, ge=0, le=999_999)
    format: ListFormat = "decimal"
    # The list's own levels, its top one first; None for the usual ones.
    levels: Optional[list[ListLevel]] = Field(default=None, max_length=9)


class ListItem(ApiModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    # The item's first paragraph.
    inline: list[InlineRun]
    level: int = 0
    checked: Optional[bool] = None
    # Whatever follows the first paragraph inside the item, in order: more
    # paragraphs, code, pictures, a table, or a sub-list that can't be expressed as
    # deeper `level`s (another kind of list, one with its own start). None for the
    # usual one-paragraph item.
    blocks: Optional[list["Element"]] = None


def _border(value: Optional[str]) -> Optional[str]:
    """A border side as border rules write them: "<style> <width>pt <colour>" or "none"."""
    if value is None:
        return None
    from app.formatting.values import InvalidRuleValue, border_value

    try:
        return border_value(value)
    except InvalidRuleValue as error:
        raise ValueError(str(error)) from None


class CellBorders(ApiModel):
    """A cell's own borders, side by side (DOCX-017); None is the table's."""

    top: Optional[str] = None
    bottom: Optional[str] = None
    left: Optional[str] = None
    right: Optional[str] = None

    _sides = field_validator("top", "bottom", "left", "right")(classmethod(lambda cls, value: _border(value)))


class TableBorders(CellBorders):
    """A table's borders: its four sides, and the lines between its rows (insideH) and
    its columns (insideV) (DOCX-017)."""

    insideH: Optional[str] = None
    insideV: Optional[str] = None

    _inside = field_validator("insideH", "insideV")(classmethod(lambda cls, value: _border(value)))


class CellMargins(ApiModel):
    """Space between a cell's edges and its text, cm (DOCX-017); None is Word's own."""

    topCm: Optional[float] = Field(default=None, ge=0, le=10)
    bottomCm: Optional[float] = Field(default=None, ge=0, le=10)
    leftCm: Optional[float] = Field(default=None, ge=0, le=10)
    rightCm: Optional[float] = Field(default=None, ge=0, le=10)


CellAlignment = Literal["left", "center", "right", "justify"]


class TableCell(ApiModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    # The cell's text. When `blocks` is set it holds their plain text (lines joined
    # by "\n") for anything that only needs the words; `blocks` is the content.
    inline: list[InlineRun]
    header: bool = False
    colspan: int = 1
    rowspan: int = 1
    # Cell shading, e.g. a header row's fill.
    background: Optional[str] = None
    # The cell's content when it is more than one paragraph: several paragraphs,
    # lists, pictures, code, quotes, a nested table.
    blocks: Optional[list["Element"]] = None
    # Its own look (DOCX-017): where its text sits up and down, and across when its
    # column's (TableContent.alignments) isn't the same for every cell; its own
    # borders and margins over the table's.
    verticalAlign: Optional[Literal["top", "center", "bottom"]] = None
    align: Optional[CellAlignment] = None
    borders: Optional[CellBorders] = None
    margins: Optional[CellMargins] = None

    @field_validator("background")
    @classmethod
    def _renderable(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not is_renderable_color(value):
            raise ValueError("must be #rgb, #rrggbb or a basic colour name")
        return value


class TableRow(ApiModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    cells: list[TableCell]
    # Its height, cm, and whether that is its least or its only one (DOCX-017).
    heightCm: Optional[float] = Field(default=None, gt=0, le=100)
    heightRule: Literal["atLeast", "exact"] = "atLeast"
    # A header row, repeated at the top of every page the table runs onto (Word's tblHeader).
    repeatHeader: bool = False
    # Kept whole on one page (Word's cantSplit).
    cantSplit: bool = False


class TableFloat(ApiModel):
    """Where a table floats with text around it (Word's tblpPr, DOCX-017): what its
    position is measured from, the position itself (cm, or Word's named places),
    and how far the text keeps from it (cm)."""

    horizontalAnchor: Literal["text", "margin", "page"] = "text"
    verticalAnchor: Literal["text", "margin", "page"] = "text"
    xCm: Optional[float] = Field(default=None, ge=-100, le=100)
    yCm: Optional[float] = Field(default=None, ge=-100, le=100)
    xAlign: Optional[Literal["left", "center", "right", "inside", "outside"]] = None
    yAlign: Optional[Literal["inline", "top", "center", "bottom", "inside", "outside"]] = None
    leftFromTextCm: Optional[float] = Field(default=None, ge=0, le=50)
    rightFromTextCm: Optional[float] = Field(default=None, ge=0, le=50)
    topFromTextCm: Optional[float] = Field(default=None, ge=0, le=50)
    bottomFromTextCm: Optional[float] = Field(default=None, ge=0, le=50)


class TableLook(ApiModel):
    """Which parts of a Word table style a table shows (w:tblLook)."""

    firstRow: bool = True
    lastRow: bool = False
    firstColumn: bool = True
    lastColumn: bool = False
    bandedRows: bool = True
    bandedColumns: bool = False


class TableContent(ApiModel):
    rows: list[TableRow]
    hasHeaderRow: bool = False
    alignments: Optional[list[Optional[str]]] = None
    # The table's geometry and look (DOCX-017): each grid column's width, the table's
    # width (cm, or % of the text column), where it sits across the page and how far
    # it's indented, its borders and cell margins -- a Word table style's resolved
    # where the table has none of its own -- and that style's name and look, which a
    # Word export gives back where the style exists.
    columnWidthsCm: Optional[list[float]] = Field(default=None, max_length=64)
    widthCm: Optional[float] = Field(default=None, gt=0, le=200)
    widthPercent: Optional[float] = Field(default=None, gt=0, le=100)
    align: Optional[Literal["left", "center", "right"]] = None
    indentCm: Optional[float] = Field(default=None, ge=-50, le=50)
    borders: Optional[TableBorders] = None
    cellMargins: Optional[CellMargins] = None
    style: Optional[str] = Field(default=None, max_length=100)
    look: Optional[TableLook] = None
    # A table text flows around, where it floats: kept for a Word export; the pages here
    # and a PDF put it in line with the text.
    floating: Optional[TableFloat] = None
    # Whether header cells are drawn bold whatever their text says: a table made here.
    # One from Word is drawn as its text and style say (False).
    headerBold: bool = True

    @field_validator("columnWidthsCm")
    @classmethod
    def _widths(cls, value: Optional[list[float]]) -> Optional[list[float]]:
        if value is not None and any(not 0 <= width <= 200 for width in value):
            raise ValueError("a column is 0 to 200 cm wide")
        return value


# Formats the editor, both exporters and every browser can actually render. Anything
# else (EMF/WMF/SVG/TIFF...) is reported via Document.unsupportedFeatures instead.
WEB_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"})


class ImageContent(ApiModel):
    # A stored asset (services/asset_service.py) when assetId is set -- src is then
    # empty. Otherwise src is an external URL or a legacy inline data: URI.
    src: str
    assetId: Optional[str] = None
    alt: Optional[str] = None
    title: Optional[str] = None


class Element(ApiModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: ElementType
    content: str
    inline: Optional[list[InlineRun]] = None
    listItems: Optional[list[ListItem]] = None
    ordered: bool = False
    table: Optional[TableContent] = None
    image: Optional[ImageContent] = None
    language: Optional[str] = None
    parentId: Optional[str] = None
    order: int
    level: Optional[int] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    styleRef: Optional[str] = None
    # Preservation layer (корекции.docx §9/§11): source data the editor can't show
    # but an export can put back. The DOCX importer stores "ooxml": equations,
    # fields, bookmarks, links to bookmarks and comments, each with where its
    # text sits (parsers/docx.py); the DOCX export re-inserts them. The editor and
    # the formatting engine never read it; it round-trips through saves untouched.
    preservedAttributes: Optional[dict[str, Any]] = None
    # A quote's content when it is more than one paragraph (paragraphs, a list,
    # code...); `inline`/`content` then hold its plain text.
    children: Optional[list["Element"]] = None
    # Ordered lists that don't count 1, 2, 3 from one: another start or format.
    numbering: Optional[ListNumbering] = None
    # Where a top-level element came from in its Word file: the indices of the
    # body's children it was read from, and its fingerprint as imported (when the
    # file is kept). Unchanged, a Word export copies those children as they are
    # (app/export/provenance.py, DOCX-028).
    # A section break's own settings (DOCX-015); None for every other element.
    sectionBreak: Optional[SectionSettings] = None
    sourceBlocks: Optional[list[int]] = Field(default=None, max_length=10_000)
    sourceHash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _limit_nesting(self) -> "Element":
        if block_depth(self, MAX_BLOCK_DEPTH + 1) > MAX_BLOCK_DEPTH:
            raise ValueError(f"blocks may nest at most {MAX_BLOCK_DEPTH} levels deep")
        return self

    @model_validator(mode="after")
    def _section_break_settings(self) -> "Element":
        if self.type == ElementType.SECTION_BREAK and self.sectionBreak is None:
            self.sectionBreak = SectionSettings()
        elif self.type != ElementType.SECTION_BREAK and self.sectionBreak is not None:
            raise ValueError("only a section break has sectionBreak settings")
        return self


def child_blocks(element: Element) -> Iterator[Element]:
    """The blocks directly inside `element`: a quote's children, every table cell's
    blocks and every list item's blocks, in reading order."""
    if element.children:
        yield from element.children
    if element.listItems:
        for item in element.listItems:
            if item.blocks:
                yield from item.blocks
    if element.table:
        for row in element.table.rows:
            for cell in row.cells:
                if cell.blocks:
                    yield from cell.blocks


def block_depth(element: Element, limit: int) -> int:
    """How many levels of blocks sit inside `element` (0 = none), counting no further than `limit`."""
    if limit <= 0:
        return 0
    return max((1 + block_depth(child, limit - 1) for child in child_blocks(element)), default=0)


def walk_elements(elements: Iterable[Element]) -> Iterator[Element]:
    """Every element, depth first, the blocks nested inside cells, list items and
    quotes included -- what anything that must see all of a document's content
    (pictures, their assets, text) iterates instead of `document.elements`."""
    for element in elements:
        yield element
        yield from walk_elements(child_blocks(element))


def inline_runs(element: Element) -> Iterator[InlineRun]:
    """Every run of text in `element`: its own, its list items' and table cells',
    and those of every block nested in it. A cell's `inline` is skipped when it
    has blocks -- it is only their plain text then."""
    yield from element.inline or []
    for item in element.listItems or []:
        yield from item.inline
    if element.table:
        for row in element.table.rows:
            for cell in row.cells:
                if not cell.blocks:
                    yield from cell.inline
    for child in child_blocks(element):
        yield from inline_runs(child)


ListItem.model_rebuild()
TableCell.model_rebuild()
TableRow.model_rebuild()
TableContent.model_rebuild()
Element.model_rebuild()


class FormattingProperty(str, Enum):
    # Per-element properties -- resolved into Document.resolvedStyles[target].
    FONT_FAMILY = "fontFamily"
    FONT_SIZE = "fontSize"
    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    COLOR = "color"
    ALIGNMENT = "alignment"
    LINE_SPACING = "lineSpacing"
    PARAGRAPH_SPACING = "paragraphSpacing"  # space after
    SPACE_BEFORE = "spaceBefore"
    FIRST_LINE_INDENT = "firstLineIndent"
    INDENT_LEFT = "indentLeft"
    # Paragraph formatting beyond spacing and indents (DOCX-014).
    INDENT_RIGHT = "indentRight"
    SHADING = "shading"  # the paragraph's background colour
    KEEP_WITH_NEXT = "keepWithNext"
    KEEP_LINES_TOGETHER = "keepLinesTogether"
    WIDOW_CONTROL = "widowControl"
    CONTEXTUAL_SPACING = "contextualSpacing"  # no space between paragraphs of the same kind
    DIRECTION = "direction"  # ltr or rtl
    # A border on one side: "solid 0.5pt #000000" (solid, double, dotted or dashed), or "none".
    BORDER_TOP = "borderTop"
    BORDER_BOTTOM = "borderBottom"
    BORDER_LEFT = "borderLeft"
    BORDER_RIGHT = "borderRight"
    # Tab stops, kept for Word (the editor and a PDF can't place them): "right 16cm dot; left 2cm".
    TAB_STOPS = "tabStops"
    IMAGE_WIDTH = "imageWidth"
    IMAGE_ALIGNMENT = "imageAlignment"
    # Page-level properties -- no single element owns these, so the engine
    # resolves them into Document.settings instead of resolvedStyles.
    PAGE_SIZE = "pageSize"
    ORIENTATION = "orientation"
    MARGIN_TOP = "marginTop"
    MARGIN_BOTTOM = "marginBottom"
    MARGIN_LEFT = "marginLeft"
    MARGIN_RIGHT = "marginRight"
    HEADER = "header"
    FOOTER = "footer"
    SHOW_PAGE_NUMBERS = "showPageNumbers"


class FormattingRule(ApiModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    target: str
    property: FormattingProperty
    value: str
    unit: Optional[str] = None
    priority: int = 0
    source: str = "system"


class SourceProperties(ApiModel):
    """A Word file's own document properties, kept so that an export to Word
    carries them again -- not the export template's."""

    author: Optional[str] = Field(default=None, max_length=255)
    lastModifiedBy: Optional[str] = Field(default=None, max_length=255)
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    subject: Optional[str] = Field(default=None, max_length=255)
    keywords: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    category: Optional[str] = Field(default=None, max_length=255)


DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class SourcePackage(ApiModel):
    """The Word file a document was imported from, kept as it was (an asset,
    never changed): a Word export writes the document's content into it, so what
    the document model doesn't hold -- styles, headers and footers of every kind,
    properties, the theme -- is kept (brief §20, tracker DOCX-010/011). Checked by
    its SHA-256 before it is used."""

    assetId: str = Field(max_length=100)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    format: Literal["docx"] = "docx"


class DocumentMetadata(ApiModel):
    title: str = "Untitled Document"
    createdAt: datetime = Field(default_factory=_now)
    updatedAt: datetime = Field(default_factory=_now)
    sourceType: str = "pasted_text"
    originalFilename: Optional[str] = None
    sourceProperties: Optional[SourceProperties] = None


class DocumentSettings(ApiModel):
    pageSize: str = "A4"
    orientation: str = "portrait"
    marginTopCm: float = 2.0
    marginBottomCm: float = 2.0
    marginLeftCm: float = 2.0
    marginRightCm: float = 2.0
    header: Optional[str] = None
    footer: Optional[str] = None
    showPageNumbers: bool = False

    # The page's real size, from the render specification (formatting/render_spec.py),
    # so the editor draws pages without a size table of its own.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def pageWidthMm(self) -> float:
        from app.formatting.render_spec import page_size_mm  # render_spec imports this module

        return page_size_mm(self.pageSize, self.orientation)[0]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pageHeightMm(self) -> float:
        from app.formatting.render_spec import page_size_mm

        return page_size_mm(self.pageSize, self.orientation)[1]


class Section(ApiModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: Optional[str] = None
    order: int = 0


class Revision(ApiModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    createdAt: datetime = Field(default_factory=_now)
    description: str


class ChangeCategory(str, Enum):
    """What a change touches (brief §19, tracker REV-001)."""

    FORMAT = "format"
    STRUCTURE = "structure"
    CONTENT = "content"
    METADATA = "metadata"
    PRESERVATION = "preservation"
    TRANSLATION = "translation"


class ProposedChange(ApiModel):
    """A change the user didn't make themselves -- an AI instruction's -- that
    alters the document's content, so it waits for their review: PLAN ->
    VALIDATE -> PREVIEW -> ACCEPT -> APPLY (brief §19, tracker AI-006). Nothing
    in it is applied until the user accepts it; a rejected one is gone."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: Literal["insert_element", "delete_element", "move_element"]
    category: ChangeCategory = ChangeCategory.CONTENT
    # The element it deletes or moves.
    elementId: Optional[str] = Field(default=None, max_length=100)
    # Where an insert or a move goes: after this element; None = at the very start.
    afterElementId: Optional[str] = Field(default=None, max_length=100)
    # An insert's kind of block.
    elementType: Optional[ElementType] = None
    property: Optional[str] = Field(default=None, max_length=50)
    # The element's text when the change was proposed (a delete or a move), for the record.
    before: Optional[str] = Field(default=None, max_length=2000)
    # An insert's text.
    after: Optional[str] = Field(default=None, max_length=10_000)
    # Why: the instruction that asked for it.
    reason: str = Field(default="", max_length=500)
    source: Literal["instruction"] = "instruction"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    createdAt: datetime = Field(default_factory=_now)


CURRENT_SCHEMA_VERSION = 1


class Document(ApiModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    schemaVersion: int = CURRENT_SCHEMA_VERSION
    # The database row's optimistic-concurrency token, filled in on every read;
    # clients send it back as If-Match. Never persisted inside the JSON itself.
    revision: int = 1
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    documentType: str = "general"
    templateId: Optional[str] = None
    settings: DocumentSettings = Field(default_factory=DocumentSettings)
    sections: list[Section] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)
    formattingRules: list[FormattingRule] = Field(default_factory=list)
    revisions: list[Revision] = Field(default_factory=list)
    resolvedStyles: dict[str, dict[str, str]] = Field(default_factory=dict)
    # Spec §9's strategy C ("explicitly unsupported, flagged before/at
    # processing" -- never silent deletion): human-readable notes about
    # something a parser detected but could not fully preserve. Currently
    # populated only by parsers/docx.py for merged table cells; more
    # detections are added as later phases' parsing work finds them, not
    # invented ahead of a real producer.
    unsupportedFeatures: list[str] = Field(default_factory=list)
    # What the import changed, approximated or left out, item by item, and whether
    # the document's words were checked against the source's (app/fidelity).
    importReport: Optional[FidelityReport] = None
    # Changes to the content waiting for the user's review (app/formatting/proposals.py).
    proposals: list[ProposedChange] = Field(default_factory=list, max_length=200)
    # The Word file this document came from, kept for exports (SourcePackage).
    sourcePackage: Optional[SourcePackage] = None
    # The last section's settings beyond DocumentSettings (which holds its page setup
    # and main header and footer): its first-page and even-page headers and footers,
    # page numbering, columns (DOCX-015). Its header or footer here is "" only for a
    # main one of its own left empty -- rules can't hold an empty text -- where None
    # in DocumentSettings would otherwise show the previous section's. And whether
    # even pages have headers and footers of their own, a document-wide setting in Word.
    lastSection: Optional[SectionSettings] = None
    evenAndOddHeaders: bool = False


_ELEMENT_TYPE_TO_TARGET = {
    ElementType.LIST: "List",
    ElementType.TABLE: "Table",
    ElementType.QUOTE: "Quote",
    ElementType.CAPTION: "Caption",
    ElementType.FOOTNOTE: "Footnote",
    ElementType.CODE_BLOCK: "CodeBlock",
    ElementType.IMAGE: "Image",
    ElementType.PAGE_BREAK: "PageBreak",
    ElementType.SECTION_BREAK: "SectionBreak",
    ElementType.HORIZONTAL_RULE: "HorizontalRule",
}


def target_for_element(el: Element) -> str:
    """Canonical formatting-rule target label for an element -- the join key
    between Element.styleRef and Document.resolvedStyles. A pure function of
    type/level (not an enum: "Heading 1".."Heading 6" don't enumerate cleanly),
    so both the engine and the frontend's mirrored helper stay in lockstep."""
    if el.type == ElementType.HEADING:
        return f"Heading {el.level or 1}"
    return _ELEMENT_TYPE_TO_TARGET.get(el.type, "Paragraph")


# Every string target_for_element() can ever produce, plus "Document" (the
# page-level pseudo-target) -- i.e. every *coarse* (type-level) target. Used
# to tell a coarse rule apart from a per-element override rule (whose target
# is one specific element's own id) regardless of the rule's priority/source,
# since a dangling override can be left behind by anything that deletes an
# element, not just the live-override UI path.
COARSE_TARGETS = frozenset(
    {"Document", "Paragraph", *_ELEMENT_TYPE_TO_TARGET.values(), *(f"Heading {level}" for level in range(1, 7))}
)
