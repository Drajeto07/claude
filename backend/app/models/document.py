from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


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
    OTHER = "other"


class MarkType(str, Enum):
    BOLD = "bold"
    ITALIC = "italic"
    STRIKE = "strike"
    CODE = "code"
    LINK = "link"


class Mark(BaseModel):
    type: MarkType
    href: Optional[str] = None


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


class TableRow(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    cells: list[TableCell]


class TableContent(BaseModel):
    rows: list[TableRow]
    hasHeaderRow: bool = False
    alignments: Optional[list[Optional[str]]] = None


class ImageContent(BaseModel):
    src: str
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
    PARAGRAPH_SPACING = "paragraphSpacing"
    FIRST_LINE_INDENT = "firstLineIndent"
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


class Section(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: Optional[str] = None
    order: int = 0


class Revision(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    createdAt: datetime = Field(default_factory=_now)
    description: str


class Document(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    documentType: str = "general"
    templateId: Optional[str] = None
    settings: DocumentSettings = Field(default_factory=DocumentSettings)
    sections: list[Section] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)
    formattingRules: list[FormattingRule] = Field(default_factory=list)
    revisions: list[Revision] = Field(default_factory=list)
    resolvedStyles: dict[str, dict[str, str]] = Field(default_factory=dict)


_ELEMENT_TYPE_TO_TARGET = {
    ElementType.LIST: "List",
    ElementType.TABLE: "Table",
    ElementType.QUOTE: "Quote",
    ElementType.CAPTION: "Caption",
    ElementType.FOOTNOTE: "Footnote",
    ElementType.CODE_BLOCK: "CodeBlock",
    ElementType.IMAGE: "Image",
    ElementType.PAGE_BREAK: "PageBreak",
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
