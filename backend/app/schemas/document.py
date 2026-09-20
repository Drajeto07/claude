from pydantic import BaseModel, Field, field_validator


class CreateDocumentRequest(BaseModel):
    text: str = Field(..., min_length=1)
    title: str | None = None

    @field_validator("text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v
