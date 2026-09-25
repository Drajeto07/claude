from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.db.models import TemplateVisibility
from app.formatting.reference_style import ReferenceStyle
from app.formatting.style_system import StyleSystem
from app.models.base import ApiModel
from app.models.document import DocumentSettings
from app.services.template_service import TemplateVersionView, TemplateView, preview_styles


def _not_blank(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("must not be blank")
    return value


class TemplateOut(ApiModel):
    id: str
    name: str
    category: str
    description: str
    styleSystem: StyleSystem
    builtin: bool
    # Whether this user may edit/rename/delete it (built-ins never).
    editable: bool
    isDefault: bool
    visibility: TemplateVisibility | None
    version: int | None
    sourceDocumentId: str | None
    updatedAt: datetime | None
    # What each element type resolves to under this template (CSS, keyed like
    # Document.resolvedStyles), computed by the engine itself for previews.
    previewStyles: dict[str, dict[str, str]]

    @classmethod
    def of(cls, view: TemplateView) -> "TemplateOut":
        styles, _ = preview_styles(view.style_system)
        return cls(
            id=view.id,
            name=view.name,
            category=view.category,
            description=view.description,
            styleSystem=view.style_system,
            builtin=view.builtin,
            editable=view.editable,
            isDefault=view.is_default,
            visibility=view.visibility,
            version=view.version,
            sourceDocumentId=view.source_document_id,
            updatedAt=view.updated_at,
            previewStyles=styles,
        )


class CreatedTemplateOut(TemplateOut):
    # Anything a source document had that the template couldn't carry over.
    notes: list[str] = Field(default_factory=list)


class CreateTemplateRequest(ApiModel):
    """A new template from a style system, from a document's current look
    (`sourceDocumentId`), or empty (neither) to fill in afterwards."""

    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(default="general", min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    visibility: TemplateVisibility = TemplateVisibility.WORKSPACE
    styleSystem: StyleSystem | None = None
    sourceDocumentId: str | None = None

    _names = field_validator("name", "category")(_not_blank)

    @model_validator(mode="after")
    def _one_source(self) -> "CreateTemplateRequest":
        if self.styleSystem is not None and self.sourceDocumentId is not None:
            raise ValueError("give either styleSystem or sourceDocumentId, not both")
        return self


class UpdateTemplateRequest(ApiModel):
    """Only the fields present change. Send If-Match with the version you loaded."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    visibility: TemplateVisibility | None = None
    styleSystem: StyleSystem | None = None

    _names = field_validator("name", "category")(_not_blank)


class DuplicateTemplateRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)

    _names = field_validator("name")(_not_blank)


class DefaultTemplateRequest(ApiModel):
    templateId: str | None


class DefaultTemplateOut(ApiModel):
    templateId: str | None


class TemplateVersionOut(ApiModel):
    number: int
    name: str
    createdAt: datetime
    author: str | None
    current: bool

    @classmethod
    def of(cls, view: TemplateVersionView) -> "TemplateVersionOut":
        return cls(
            number=view.number, name=view.name, createdAt=view.created_at, author=view.author, current=view.current
        )


class StylePreviewOut(ApiModel):
    resolvedStyles: dict[str, dict[str, str]]
    settings: DocumentSettings


class ReferenceStyleOut(ApiModel):
    """Format by Example: the style a reference document uses, not saved yet.
    Save it with POST /api/templates, then format with that template."""

    suggestedName: str
    styleSystem: StyleSystem
    # What couldn't be taken over, and how headings were found.
    notes: list[str]
    headingsFrom: Literal["styles", "look", "ai", "none"]
    # Heading level ("1".."6") -> how many headings of it the reference has.
    headingCounts: dict[str, int]
    # paragraphs, lists, tables, images, captions
    counts: dict[str, int]
    previewStyles: dict[str, dict[str, str]]
    settings: DocumentSettings

    @classmethod
    def of(cls, reference: ReferenceStyle, suggested_name: str) -> "ReferenceStyleOut":
        resolved, settings = preview_styles(reference.style_system)
        return cls(
            suggestedName=suggested_name,
            styleSystem=reference.style_system,
            notes=reference.notes,
            headingsFrom=reference.headings_from,
            headingCounts={str(level): count for level, count in reference.heading_counts.items()},
            counts=reference.counts,
            previewStyles=resolved,
            settings=settings,
        )
