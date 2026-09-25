"""The plans a workspace can be on and what each allows (plans.json), validated
when the backend starts so a typo stops startup instead of a request."""

import json
from pathlib import Path

from pydantic import Field

from app.models.base import ApiModel

FREE = "free"


class Entitlements(ApiModel):
    """What a plan allows (корекции.docx §35). None = unlimited."""

    canExportDocx: bool
    canExportPdf: bool
    maxDocuments: int | None = Field(ge=0)
    maxDocumentSizeMb: int = Field(ge=1)
    # Per calendar month.
    maxAiOperations: int | None = Field(ge=0)
    maxTemplates: int | None = Field(ge=0)
    maxStorageMb: int | None = Field(ge=0)
    priorityProcessing: bool


class Plan(ApiModel):
    key: str
    name: str
    # What the pricing page says, e.g. "€9 / month"; None until prices are set.
    priceLabel: str | None
    entitlements: Entitlements


def _load() -> dict[str, Plan]:
    raw = json.loads((Path(__file__).parent / "plans.json").read_text(encoding="utf-8"))["plans"]
    plans = {key: Plan(key=key, **value) for key, value in raw.items()}
    if FREE not in plans:
        raise ValueError("plans.json needs a 'free' plan: every workspace without a subscription is on it")
    return plans


PLANS: dict[str, Plan] = _load()
