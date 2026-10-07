from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from app.models.base import ApiModel, XmlText
from app.models.document import ChangeCategory, Document, DocumentSettings, Element, FormattingProperty, GlossaryTerm, LanguageTag
from app.schemas.formatting import RuleValue

# What the editor can set on a block itself: alignment (a shortcut, or pasted
# text) and a picture's size.
_DIRECT_PROPERTIES = frozenset({FormattingProperty.ALIGNMENT, FormattingProperty.IMAGE_WIDTH})


class CreateDocumentRequest(ApiModel):
    text: str = Field(..., min_length=1, max_length=2_000_000)
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
    # Formatting the editor holds on top-level blocks themselves, kept as each
    # element's own style (DirectStyle).
    styles: list["DirectStyle"] = Field(default_factory=list, max_length=10_000)


class AddedElement(ApiModel):
    """A top-level block the editor added, and the id of the one just before it in
    the document (null: it comes first)."""

    after: str | None = Field(..., max_length=200)
    element: Element


class ContentPatchRequest(ApiModel):
    """What changed since the revision named in If-Match (PERF-003), in place of
    PUT /content's whole list: top-level elements changed (whole), added (in the
    document's order) and removed. The server builds the whole list from its own
    copy and saves it as PUT /content saves one, with every check that has."""

    changed: list[Element] = Field(default_factory=list)
    added: list[AddedElement] = Field(default_factory=list)
    removed: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list)
    styles: list["DirectStyle"] = Field(default_factory=list, max_length=10_000)


class ContentSaved(ApiModel):
    """A patch's answer: how the stored document now differs from the revision the
    patch was based on. The top-level elements changed or added, as stored; their
    ids in order only when that isn't the order the patch made (null: it is); and
    every other part of the document that changed, whole, by name."""

    revision: int
    changed: list[Element]
    order: list[str] | None
    fields: dict[str, Any]


class DirectStyle(RuleValue):
    """Formatting the editor holds on one block itself -- alignment typed with a
    shortcut or pasted, a picture's width -- kept as that element's own style,
    the tier the toolbar sets (editor/tiptapToDocument.ts). The value is
    checked like any other (RuleValue)."""

    elementId: str = Field(..., min_length=1, max_length=100)

    @model_validator(mode="after")
    def _set_by_the_editor(self) -> "DirectStyle":
        if self.property not in _DIRECT_PROPERTIES:
            raise ValueError(f"the editor doesn't set {self.property.value} on a block")
        return self


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


class TrackedChangesRequest(ApiModel):
    """What a Word export does with the file's tracked changes (DOCX-022): keeps them in
    the blocks not changed here, or they are all accepted -- or all rejected (DOCX-022A),
    which reads the document again from the file: `discardEdits` says the changes made here
    since the upload may go (else 409 `edits_would_be_lost` when there are any)."""

    choice: Literal["kept", "accepted", "rejected"]
    discardEdits: bool = False


class RenameDocumentRequest(ApiModel):
    title: str = Field(..., min_length=1)

    @field_validator("title")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()


class SetDocumentSettingRequest(RuleValue):
    """Page-level settings (size/margins/header/footer/page numbers) as a
    direct user edit -- the UI-overhaul right sidebar's Page section. Same
    priority tier as a per-element live override (spec §7.9 tier 1): wins
    over template/instructions and survives a reformat, via the exact same
    FormattingRule + priority mechanism, just targeting the "Document"
    pseudo-target instead of one element's id."""


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
    # Changes to the content the instructions asked for, waiting for review (document.proposals).
    proposalCount: int = 0


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


class TranslateSelection(ApiModel):
    """Part of one block's text: characters `start` to `end` of it."""

    start: int = Field(ge=0)
    end: int = Field(ge=1)


class TranslateRequest(ApiModel):
    """Blocks to translate as proposals (TRAN-005): their ids, or one block and part of its
    text. The target language is always said; the source is detected when not said."""

    elementIds: list[str] = Field(min_length=1, max_length=500)
    targetLanguage: LanguageTag
    sourceLanguage: LanguageTag | None = None
    selection: TranslateSelection | None = None

    @model_validator(mode="after")
    def _one_block_for_a_selection(self) -> "TranslateRequest":
        if self.selection is not None and len(self.elementIds) != 1:
            raise ValueError("a selection is part of one block")
        if self.selection is not None and self.selection.end <= self.selection.start:
            raise ValueError("a selection ends after it starts")
        return self


class NotTranslated(ApiModel):
    elementId: str
    reasons: list[str]


class SectionTextRequest(ApiModel):
    """One header or footer of a section, edited here as that section's own (DOCX-015C). `sectionId`:
    the section break ending the section; none -- the last section (whose main header and footer are
    the page settings'). `text`: the text ({PAGE} and {NUMPAGES} for page numbers); "" -- its own,
    empty; null -- none of its own: the previous section's shows (Word's "link to previous")."""

    sectionId: str | None = Field(default=None, max_length=100)
    kind: Literal["header", "footer", "firstHeader", "firstFooter", "evenHeader", "evenFooter"]
    text: XmlText | None = Field(default=None, max_length=500)


class AcceptProposalsRequest(ApiModel):
    """Every waiting change of one category, accepted at once (never the content's: REV-003)."""

    category: ChangeCategory


class AcceptProposalsResponse(ApiModel):
    document: Document
    accepted: int
    # Left waiting: they change the words (accepted one by one) or no longer fit the document.
    skipped: int


class HealthFixesRequest(ApiModel):
    """The checks whose fixes to propose (HLTH-002); none named: every check's."""

    checkIds: list[str] | None = Field(default=None, max_length=50)


class HealthFixesResponse(ApiModel):
    document: Document
    proposalCount: int


class TranslateResponse(ApiModel):
    document: Document
    proposalCount: int
    sourceLanguage: str | None
    characters: int
    notTranslated: list[NotTranslated] = Field(default_factory=list)
    # Shown wherever a translation is (brief §48).
    label: str


class GlossaryRequest(ApiModel):
    terms: list[GlossaryTerm] = Field(max_length=500)


class LanguageRequest(ApiModel):
    language: LanguageTag | None = None


class LanguageOut(ApiModel):
    """The document's language: as set, as detected, and the one translations start from."""

    set: str | None
    detected: str | None
    script: str | None
    direction: Literal["ltr", "rtl"]
    confidence: float
    name: str


class StylePreviewRequest(ApiModel):
    """A look to try on the document (FMT-003): a template's StyleSystem, e.g. one read from a reference document."""

    styleSystem: "StyleSystemModel"


class DocumentStylePreviewOut(ApiModel):
    """The document now and with the look, as the engine resolves both; what changes, in words. Nothing is saved."""

    before: dict[str, dict[str, str]]
    after: dict[str, dict[str, str]]
    settingsBefore: DocumentSettings
    settingsAfter: DocumentSettings
    changes: list[str]
    tables: int
    lists: int


from app.formatting.style_system import StyleSystem as StyleSystemModel  # noqa: E402 -- style_system imports this module's models

StylePreviewRequest.model_rebuild()
