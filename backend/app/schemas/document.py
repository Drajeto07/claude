from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.models.base import ApiModel
from app.models.document import Document, Element, FormattingProperty


class CreateDocumentRequest(ApiModel):
    text: str = Field(..., min_length=1)
    title: str | None = None

    @field_validator("text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v


class UpdateContentRequest(ApiModel):
    """Stage 0: the frontend has already reconciled Tiptap's live JSON
    against the stored document (matching existing elements by id, adding
    new top-level blocks, dropping removed ones) -- this just carries that
    result across the wire."""

    elements: list[Element]


class AddPageRequest(ApiModel):
    afterElementId: str | None = None


class InsertElementRequest(ApiModel):
    """The editor's own Add-element UI (Stage 10) -- a direct, non-AI insert.
    Deliberately a narrower set than every ElementType: paragraph/heading/
    list/table have a sensible empty-but-real default shape to insert;
    image needs a file picked first (a different UX entirely, not a same-
    shape variant of this), and page_break already has its own dedicated
    add-page endpoint."""

    elementType: Literal["paragraph", "heading", "list", "table"]
    afterElementId: str | None = None
    text: str = ""


class RenameDocumentRequest(ApiModel):
    title: str = Field(..., min_length=1)

    @field_validator("title")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()


class SetDocumentSettingRequest(ApiModel):
    """Page-level settings (size/margins/header/footer/page numbers) as a
    direct user edit -- the UI-overhaul right sidebar's Page section. Same
    priority tier as a per-element live override (spec §7.9 tier 1): wins
    over template/instructions and survives a reformat, via the exact same
    FormattingRule + priority mechanism, just targeting the "Document"
    pseudo-target instead of one element's id."""

    property: FormattingProperty
    value: str = Field(..., min_length=1)
    unit: str | None = None


class FormatResponse(ApiModel):
    """`/format`'s success shape: the updated document, whether the AI
    instruction call itself failed (vs. legitimately finding nothing to
    change), and how many rules/operations the instructions text actually
    produced -- together these let the frontend avoid a fake-looking
    success when an instruction silently did nothing (AC-INSTRUCTION-11):
    aiUnavailable=True means the call failed outright; aiUnavailable=False
    with instructionEditCount=0 (and non-blank instructions text) means the
    AI ran fine but found nothing it could turn into a real edit."""

    document: Document
    aiUnavailable: bool = False
    instructionEditCount: int = 0


class StyleFlag(ApiModel):
    elementId: str
    reason: str


class StyleAnalysisResponse(ApiModel):
    """Read-only writing-style assessment (tone/consistency of the prose
    itself, a different axis entirely from the deterministic formatting
    engine's CSS-level work) -- never rewrites anything, only ever points at
    elements for the user to look at themselves. `status` distinguishes
    three honest outcomes so the frontend never has to fake one: "ok" (a
    real analysis), "empty_document" (no real text to analyze yet), and
    "ai_unavailable" (the AI call itself failed after retries)."""

    status: Literal["ok", "empty_document", "ai_unavailable"]
    consistencyScore: float | None = None
    tone: str | None = None
    summary: str | None = None
    flagged: list[StyleFlag] = Field(default_factory=list)


class DocumentSummaryOut(ApiModel):
    """A document in the list and on the dashboard: what it is, not what it holds.
    `status` is "formatted" once a template or instructions were applied."""

    id: str
    title: str
    createdAt: datetime
    updatedAt: datetime
    formattedAt: datetime | None
    status: Literal["draft", "formatted"]
    sourceType: str
    originalFilename: str | None
    templateId: str | None
    # None when the template is gone (the document keeps its look) or not visible to this user.
    templateName: str | None


class DocumentListOut(ApiModel):
    items: list[DocumentSummaryOut]
    total: int


class DocumentVersionOut(ApiModel):
    """One kept version: the document's state after one change. `current` is the
    one it shows now (undo moves it back, redo forward)."""

    number: int
    kind: Literal["created", "content", "change"]
    description: str
    createdAt: datetime
    author: str | None
    current: bool
