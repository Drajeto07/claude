from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, field_validator

from app.formatting.colors import is_renderable_color, is_safe_font_name


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


class Mark(BaseModel):
    type: MarkType
    href: Optional[str] = None
    # textStyle only; None means "not set on this run". Validated because the
    # values end up in style attributes and in exported files.
    fontFamily: Optional[str] = Field(default=None, max_length=100)
    fontSizePt: Optional[float] = Field(default=None, gt=0, le=400)
    color: Optional[str] = None
    backgroundColor: Optional[str] = None

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


class InlineRun(BaseModel):
    text: str
    marks: list[Mark] = Field(default_factory=list)


def plain_text_from_inline(runs: Optional[list[InlineRun]]) -> str:
    """Deterministic plain-text projection used to keep `Element.content`
    always populated, regardless of which parser produced the rich fields."""
    if not runs:
        return ""
    return "".join(run.text for run in runs)


class ListItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    inline: list[InlineRun]
    level: int = 0
    checked: Optional[bool] = None


class TableCell(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    inline: list[InlineRun]
    header: bool = False
    colspan: int = 1
    rowspan: int = 1
    # Cell shading, e.g. a header row's fill.
    background: Optional[str] = None

    @field_validator("background")
    @classmethod
    def _renderable(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not is_renderable_color(value):
            raise ValueError("must be #rgb, #rrggbb or a basic colour name")
        return value


class TableRow(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    cells: list[TableCell]


class TableContent(BaseModel):
    rows: list[TableRow]
    hasHeaderRow: bool = False
    alignments: Optional[list[Optional[str]]] = None


# Formats the editor, both exporters and every browser can actually render. Anything
# else (EMF/WMF/SVG/TIFF...) is reported via Document.unsupportedFeatures instead.
WEB_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"})


class ImageContent(BaseModel):
    # A stored asset (services/asset_service.py) when assetId is set -- src is then
    # empty. Otherwise src is an external URL or a legacy inline data: URI.
    src: str
    assetId: Optional[str] = None
    alt: Optional[str] = None
    title: Optional[str] = None


class Element(BaseModel):
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


class FormattingRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    target: str
    property: FormattingProperty
    value: str
    unit: Optional[str] = None
    priority: int = 0
    source: str = "system"


class DocumentMetadata(BaseModel):
    title: str = "Untitled Document"
    createdAt: datetime = Field(default_factory=_now)
    updatedAt: datetime = Field(default_factory=_now)
    sourceType: str = "pasted_text"
    originalFilename: Optional[str] = None


class DocumentSettings(BaseModel):
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


class Section(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: Optional[str] = None
    order: int = 0


class Revision(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    createdAt: datetime = Field(default_factory=_now)
    description: str


CURRENT_SCHEMA_VERSION = 1


class Document(BaseModel):
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


_ELEMENT_TYPE_TO_TARGET = {
    ElementType.LIST: "List",
    ElementType.TABLE: "Table",
    ElementType.QUOTE: "Quote",
    ElementType.CAPTION: "Caption",
    ElementType.FOOTNOTE: "Footnote",
    ElementType.CODE_BLOCK: "CodeBlock",
    ElementType.IMAGE: "Image",
    ElementType.PAGE_BREAK: "PageBreak",
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
