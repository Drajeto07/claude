from typing import Literal

from pydantic import Field, model_validator

from app.formatting.values import clean_rule_value
from app.models.base import ApiModel
from app.models.document import FormattingProperty


class RuleValue(ApiModel):
    """A property and its value as a person or the editor sets it; refused
    (422) unless every renderer can use the value as it is (formatting/values.py)."""

    property: FormattingProperty
    value: str = Field(..., min_length=1, max_length=500)
    unit: str | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _clean(self) -> "RuleValue":
        self.value, self.unit = clean_rule_value(self.property, self.value, self.unit)
        return self


class SetElementStyleRequest(RuleValue):
    pass


class ConflictResolutionInput(ApiModel):
    elementId: str
    property: FormattingProperty
    resolution: Literal["apply_recommended", "keep_current"]
