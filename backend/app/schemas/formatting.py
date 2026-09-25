from typing import Literal

from pydantic import Field

from app.models.base import ApiModel
from app.models.document import FormattingProperty


class SetElementStyleRequest(ApiModel):
    property: FormattingProperty
    value: str = Field(..., min_length=1)
    unit: str | None = None


class ConflictResolutionInput(ApiModel):
    elementId: str
    property: FormattingProperty
    resolution: Literal["apply_recommended", "keep_current"]
