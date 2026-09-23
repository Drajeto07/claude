from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AIBlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    QUOTE = "quote"
    CODE_BLOCK = "code_block"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    OTHER = "other"
    # Deliberately no IMAGE: plain prose/PDF-extracted text never carries a
    # real image reference for the AI to legitimately report -- only the
    # deterministic DOCX/Markdown parsers ever produce IMAGE elements.


class AIListItem(BaseModel):
    text: str
    level: int = 0
    checked: Optional[bool] = None


class AITableRow(BaseModel):
    cells: list[str]


class AIBlock(BaseModel):
    type: AIBlockType
    text: str = ""
    level: Optional[int] = None
    ordered: Optional[bool] = None
    items: Optional[list[AIListItem]] = None
    rows: Optional[list[AITableRow]] = None
    has_header_row: Optional[bool] = None
    language: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)


class AIStructureResponse(BaseModel):
    document_type: str
    document_type_confidence: float = Field(ge=0.0, le=1.0)
    blocks: list[AIBlock]


class AIFormattingRule(BaseModel):
    target: str
    property: str
    value: str
    unit: Optional[str] = None


class AIDocumentOperation(BaseModel):
    """One structural or targeted-style edit the instruction implies, beyond
    a coarse-type style rule. A flat, all-fields-optional shape (mirroring
    AIFormattingRule's style) rather than a discriminated union, since not
    every field applies to every `op` -- unused fields for a given op are
    just left null. `element_id`/`after_element_id` must name an element
    that already exists in the document the AI was shown; an op can never
    reference an element another op in the same batch is about to create."""

    op: str  # "set_style" | "delete_element" | "insert_element" | "move_element" | "add_page_break"
    element_id: Optional[str] = None
    after_element_id: Optional[str] = None
    element_type: Optional[str] = None  # insert_element: "paragraph" | "heading"
    text: Optional[str] = None  # insert_element
    property: Optional[str] = None  # set_style
    value: Optional[str] = None  # set_style
    unit: Optional[str] = None  # set_style


class AIInstructionExtractionResponse(BaseModel):
    rules: list[AIFormattingRule] = Field(default_factory=list)
    operations: list[AIDocumentOperation] = Field(default_factory=list)


class AIStyleFlag(BaseModel):
    element_id: str
    reason: str


class AIStyleAnalysisResponse(BaseModel):
    consistency_score: float = Field(ge=0.0, le=1.0)
    tone: str
    summary: str
    flagged: list[AIStyleFlag] = Field(default_factory=list)
