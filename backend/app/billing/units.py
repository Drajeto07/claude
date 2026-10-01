"""The usage units (корекции.docx §63, tracker PLAN-001): every kind of use a plan
can limit, in one place. GET /api/v1/usage and the billing page list them from
here, the plan checks find a unit's limit through here, and each unit's limit is
an entitlement in billing/plans.json -- so a new unit is one entry below plus its
entitlement in every plan (tests/test_usage_units.py checks both).

A unit is either counted as it happens, one usage_records row per use (`metric`),
and summed over the calendar month (UTC), or measured as it is now (documents,
templates, storage). Some are named before the feature that uses them exists:
`counted` is False until it does, and nothing counts them yet."""

from dataclasses import dataclass
from typing import Literal

# usage_records metrics: one row per use, its quantity the amount.
DOCUMENTS_CREATED = "documents_created"
PROCESSING_JOBS = "processing_jobs"
EXPORTS = "exports"
AI_OPERATIONS = "ai_operations"
PDF_PAGES = "pdf_pages"
OCR_PAGES = "ocr_pages"
TRANSLATION_CHARACTERS = "translation_characters"
BATCH_JOBS = "batch_jobs"

MB = 1024 * 1024


@dataclass(frozen=True)
class UsageUnit:
    # Its name in the API (GET /usage, GET /billing).
    key: str
    # For people, e.g. "AI operations".
    label: str
    # The plan's limit for it: an entitlement in billing/plans.json (None there = unlimited).
    entitlement: str
    # Counted per calendar month from usage_records rows of this metric; None = measured as it is now.
    metric: str | None
    # How the amount reads: a count, or bytes.
    measure: Literal["count", "bytes"] = "count"
    # The entitlement's number times this is the limit in the unit's own measure (MB -> bytes).
    scale: int = 1
    # False: named now, counted once the feature that uses it exists (none counts it yet).
    counted: bool = True

    @property
    def per_month(self) -> bool:
        return self.metric is not None

    def limit(self, entitlements) -> int | None:
        value = getattr(entitlements, self.entitlement)
        return None if value is None else value * self.scale


DOCUMENTS = UsageUnit("documents", "Documents", "maxDocuments", None)
TEMPLATES = UsageUnit("templates", "Templates of your own", "maxTemplates", None)
STORAGE = UsageUnit("storageBytes", "Storage", "maxStorageMb", None, measure="bytes", scale=MB)
AI = UsageUnit("aiOperations", "AI operations", "maxAiOperations", AI_OPERATIONS)
EXPORT = UsageUnit("exports", "Exports", "maxExports", EXPORTS)
# Counted when a PDF is imported: every page of it, whatever it holds.
PDF = UsageUnit("pdfPages", "PDF pages", "maxPdfPages", PDF_PAGES)
OCR = UsageUnit("ocrPages", "OCR pages", "maxOcrPages", OCR_PAGES, counted=False)
TRANSLATION = UsageUnit("translationCharacters", "Translation characters", "maxTranslationCharacters", TRANSLATION_CHARACTERS, counted=False)
BATCH = UsageUnit("batchJobs", "Batch jobs", "maxBatchJobs", BATCH_JOBS, counted=False)

# In the order the billing page shows them.
UNITS: tuple[UsageUnit, ...] = (DOCUMENTS, EXPORT, PDF, OCR, TRANSLATION, BATCH, AI, STORAGE, TEMPLATES)
BY_METRIC: dict[str, UsageUnit] = {unit.metric: unit for unit in UNITS if unit.metric is not None}
