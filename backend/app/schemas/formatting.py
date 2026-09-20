from pydantic import BaseModel, Field, field_validator

from app.formatting.templates import Template
from app.models.document import FormattingProperty


class FormattingRuleInput(BaseModel):
    target: str = Field(..., min_length=1)
    property: FormattingProperty
    value: str
    unit: str | None = None


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


class TemplateSummary(BaseModel):
    id: str
    name: str
    category: str
    description: str

    @classmethod
    def from_template(cls, template: Template) -> "TemplateSummary":
        return cls(id=template.id, name=template.name, category=template.category, description=template.description)
