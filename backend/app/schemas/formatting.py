from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.formatting.templates import Template
from app.models.document import FormattingProperty


class FormattingRuleInput(BaseModel):
    target: str = Field(..., min_length=1)
    property: FormattingProperty
    value: str
    unit: str | None = None


class SetElementStyleRequest(BaseModel):
    property: FormattingProperty
    value: str = Field(..., min_length=1)
    unit: str | None = None


class ConflictResolutionInput(BaseModel):
    elementId: str
    property: FormattingProperty
    resolution: Literal["apply_recommended", "keep_current"]


class CreateTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    description: str = ""
    rules: list[FormattingRuleInput] = Field(default_factory=list)

    @field_validator("name", "category")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


class TemplatePreview(BaseModel):
    """A handful of the template's own Paragraph-level rule values, so a
    gallery card can render real sample text in the template's actual look
    instead of a hand-guessed stand-in that could drift from templates.py."""

    fontFamily: str | None = None
    alignment: str | None = None
    lineSpacing: str | None = None


class TemplateSummary(BaseModel):
    id: str
    name: str
    category: str
    description: str
    preview: TemplatePreview

    @classmethod
    def from_template(cls, template: Template) -> "TemplateSummary":
        paragraph_rules = {rule.property: rule.value for rule in template.rules if rule.target == "Paragraph"}
        return cls(
            id=template.id,
            name=template.name,
            category=template.category,
            description=template.description,
            preview=TemplatePreview(
                fontFamily=paragraph_rules.get(FormattingProperty.FONT_FAMILY),
                alignment=paragraph_rules.get(FormattingProperty.ALIGNMENT),
                lineSpacing=paragraph_rules.get(FormattingProperty.LINE_SPACING),
            ),
        )
