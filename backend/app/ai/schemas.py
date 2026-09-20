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


class AIInstructionExtractionResponse(BaseModel):
    rules: list[AIFormattingRule]
