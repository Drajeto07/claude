"""The OCR provider the settings choose (OCR_PROVIDER). Only "none" exists so far: which engine
to run -- a local one such as Tesseract, or a cloud service -- is the owner's choice, and
its implementation goes here behind app/ocr/base.py's OcrProvider (P2E-006)."""

from functools import lru_cache

from app.config import get_settings
from app.ocr.base import NoOcr, OcrProvider


@lru_cache
def get_ocr_provider() -> OcrProvider:
    choice = get_settings().ocr_provider
    if choice == "none":
        return NoOcr()
    raise ValueError(f"Unknown OCR_PROVIDER: {choice}")
