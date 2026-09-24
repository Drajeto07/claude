from typing import Literal

from pydantic import BaseModel, Field

from app.models.document import FormattingProperty


class SetElementStyleRequest(BaseModel):
    property: FormattingProperty
    value: str = Field(..., min_length=1)
    unit: str | None = None


class ConflictResolutionInput(BaseModel):
    elementId: str
    property: FormattingProperty
    resolution: Literal["apply_recommended", "keep_current"]
