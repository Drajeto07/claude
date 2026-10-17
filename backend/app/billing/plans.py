"""The plans a workspace can be on and what each allows (plans.json), validated
when the backend starts so a typo stops startup instead of a request. Every limit
and default a plan has lives in plans.json (PLAN-002); the code reads them from
here, never a plan's name."""

import json
from pathlib import Path

from pydantic import ConfigDict, Field

from app.models.base import ApiModel


class Entitlements(ApiModel):
    """What a plan allows (корекции.docx §35). None = unlimited. Each usage unit
    (billing/units.py) has its limit here."""

    # An entitlement plans.json doesn't know is a typo, not something to ignore.
    model_config = ConfigDict(extra="forbid")

    canExportDocx: bool
    canExportPdf: bool
    maxDocuments: int | None = Field(ge=0)
    maxDocumentSizeMb: int = Field(ge=1)
    # Per calendar month (UTC), each.
    maxExports: int | None = Field(ge=0)
    maxPdfPages: int | None = Field(ge=0)
    maxOcrPages: int | None = Field(ge=0)
    maxTranslationCharacters: int | None = Field(ge=0)
    maxBatchJobs: int | None = Field(ge=0)
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


def _load() -> tuple[dict[str, Plan], str]:
    raw = json.loads((Path(__file__).parent / "plans.json").read_text(encoding="utf-8"))
    plans = {key: Plan(key=key, **value) for key, value in raw["plans"].items()}
    default = raw["defaultPlan"]
    if default not in plans:
        raise ValueError(f"plans.json's defaultPlan {default!r} isn't one of its plans: every workspace without a subscription is on it")
    return plans, default


PLANS: dict[str, Plan]
PLANS, DEFAULT_PLAN = _load()
# The default plan's key: what a workspace without a subscription in good standing
# is on (plans.json's defaultPlan, "free" today). FREE is the name the code had for it.
FREE = DEFAULT_PLAN
