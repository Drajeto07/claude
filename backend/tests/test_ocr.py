"""OCR (tracker P2E-006, brief §43): the provider interface, with a fake engine standing in
for a real one. A scanned page's picture is read through it, its words laid where the
picture shows them and rebuilt into paragraphs like any page's, each block as sure as the
engine was and marked as read by OCR; what the engine gives back is untrusted and made safe
first; an engine that fails costs that page's words, said, never the import. With none
configured (the default) a PDF of scans is refused as before."""

import asyncio
import math
from pathlib import Path

import pytest

from app.ai.base import AIStructuredOutputError
from app.config import get_settings
from app.ocr import factory
from app.ocr.base import NoOcr, OcrPage, OcrUnavailable, OcrWord
from app.ocr.results import MAX_OCR_WORD, MAX_OCR_WORDS, clean, page_chars
from app.parsers.pdf import NO_TEXT, PdfParseError
from app.services import ingestion_service
from app.services.ingestion_service import build_document_from_upload
from scripts.make_pdf_fixtures import SCAN_LINES
from tests.fakes import FakeAIProvider

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"


def _ai() -> FakeAIProvider:
    return FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)


class FakeOcr:
    """Reads the fixtures' scan (scripts/make_pdf_fixtures.py _scan: 850 x 1100 pixels, each
    line at (90, 110 + 70 * n), 40 pixels high), each letter 20 pixels wide."""

    name = "fake"

    def __init__(self, confidence: float = 0.8, fail: bool = False) -> None:
        self.confidence, self.fail, self.calls = confidence, fail, []

    @property
    def available(self) -> bool:
        return True

    def recognize(self, picture: bytes, mime: str, *, page: int, languages: list[str]) -> OcrPage:
        self.calls.append((page, mime, len(picture)))
        if self.fail:
            raise OcrUnavailable("the engine is down")
        words = []
        for row, line in enumerate(SCAN_LINES):
            x = 90
            for word in line.split():
                words.append(OcrWord(word, self.confidence, (x, 110 + 70 * row, x + 20 * len(word), 150 + 70 * row)))
                x += 20 * len(word) + 12
        return OcrPage(page=page, words=words, language="en", script="Latn")


def _upload(name: str, ocr):
    original = ingestion_service.get_ocr_provider
    ingestion_service.get_ocr_provider = lambda: ocr
    try:
        return asyncio.run(build_document_from_upload((FIXTURES / name).read_bytes(), name, None, _ai()))
    finally:
        ingestion_service.get_ocr_provider = original


def _features(document) -> dict:
    return {item.feature: item for item in document.importReport.items}


def test_none_is_configured_by_default_and_a_scan_is_refused_as_before():
    assert get_settings().ocr_provider == "none" and isinstance(factory.get_ocr_provider(), NoOcr)
    assert not NoOcr().available
    with pytest.raises(OcrUnavailable):
        NoOcr().recognize(b"", "image/png", page=1, languages=[])
    with pytest.raises(PdfParseError, match=NO_TEXT):
        _upload("scanned.pdf", NoOcr())


def test_with_no_engine_a_scan_is_refused_before_its_pages_are_read(monkeypatch):
    def not_now(*_, **__):
        raise AssertionError("the layout read ran for a file that is refused anyway")

    monkeypatch.setattr(ingestion_service, "_read_pdf_layout", not_now)
    with pytest.raises(PdfParseError, match=NO_TEXT):
        _upload("scanned.pdf", NoOcr())


def test_an_unknown_provider_is_refused(monkeypatch):
    monkeypatch.setattr(factory, "get_settings", lambda: type("S", (), {"ocr_provider": "magic"})())
    factory.get_ocr_provider.cache_clear()
    try:
        with pytest.raises(ValueError, match="Unknown OCR_PROVIDER"):
            factory.get_ocr_provider()
    finally:
        factory.get_ocr_provider.cache_clear()


def test_a_scan_is_read_by_ocr_into_paragraphs():
    ocr = FakeOcr(confidence=0.8)
    document = _upload("scanned.pdf", ocr)
    assert ocr.calls == [(1, "image/png", ocr.calls[0][2])]
    # Its lines evenly spaced, all one size: one paragraph.
    assert [element.content for element in document.elements] == ["Scanned letter This page is a picture of printed text, with no text layer of its own."]
    assert all(element.layout.source == "pdf-ocr" and element.confidence == 0.75 for element in document.elements)
    features = _features(document)
    assert features["pdf.ocr"].reason.startswith("Page 1, scanned, was read by OCR (fake), 80% sure")
    assert "pdf.scanned_pages" not in features and "pdf.images" not in features  # the scan is its words now
    text = next(aspect for aspect in document.pdfConversion.aspects if aspect.aspect == "text")
    assert text.confidence == 0.75 and "1 scanned page read by OCR" in text.note
    # Unsure words make unsure blocks.
    unsure = _upload("scanned.pdf", FakeOcr(confidence=0.4))
    assert {element.confidence for element in unsure.elements} == {0.4}


def test_in_a_hybrid_file_only_the_scan_without_text_is_read():
    ocr = FakeOcr()
    document = _upload("hybrid.pdf", ocr)
    assert [page for page, _, _ in ocr.calls] == [3]  # page 1 has a text layer, page 2 is text
    assert [element.layout.source for element in document.elements] == ["pdf-text-layer"] * 3 + ["pdf-text", "pdf-ocr"]
    assert "pdf.scanned_pages" not in _features(document)


def test_an_engine_that_fails_costs_that_page_and_says_so():
    document = _upload("hybrid.pdf", FakeOcr(fail=True))
    item = _features(document)["pdf.ocr_failed"]
    assert (item.count, item.contentChanged) == (1, True) and "page 3" in item.reason
    assert document.elements[-1].layout.source == "pdf-picture"  # the scan stays, as a picture
    with pytest.raises(PdfParseError, match=NO_TEXT):  # nothing read at all: refused as a scan always was
        _upload("scanned.pdf", FakeOcr(fail=True))


def test_what_an_engine_gives_back_is_made_safe():
    words = [
        OcrWord("plain", 0.9, (10, 10, 60, 30)),
        OcrWord("bell\x07and\x00null", 0.9, (70, 10, 120, 30)),
        OcrWord("<script>alert(1)</script>", 0.9, (130, 10, 300, 30)),  # only ever text
        OcrWord("x" * 500, 0.9, (10, 40, 60, 60)),
        OcrWord("   ", 0.9, (10, 70, 60, 90)),
        OcrWord("nan", math.nan, (10, 100, 60, 120)),
        OcrWord("huge", 7.0, (-50, -50, 5000, 5000)),
        OcrWord("flat", 0.5, (10, 130, 10, 150)),
        OcrWord("line\nbreak", 0.5, (10, 160, 60, 180)),
    ]
    cleaned = clean(OcrPage(page=1, words=words), 400, 400)
    assert [word.text for word in cleaned] == ["plain", "bellandnull", "<script>alert(1)</script>", "x" * MAX_OCR_WORD, "nan", "huge", "line break"]
    assert cleaned[4].confidence == 0.0 and cleaned[5].confidence == 1.0 and cleaned[5].box == (0.0, 0.0, 400, 400)
    many = OcrPage(page=1, words=[OcrWord("w", 0.5, (0, 0, 1, 1))] * (MAX_OCR_WORDS + 10))
    assert len(clean(many, 10, 10)) == MAX_OCR_WORDS


def test_words_are_laid_where_the_picture_shows_them():
    chars = page_chars([OcrWord("ab", 0.9, (0, 0, 100, 50))], picture=(100, 200, 300, 300), pixels=(200, 100))
    assert [(char.text, char.box) for char in chars] == [
        ("a", (100.0, 200.0, 150.0, 250.0)),
        ("b", (150.0, 200.0, 200.0, 250.0)),
        (" ", (200.0, 200.0, 225.0, 250.0)),
    ]
    assert all(char.font == "OCR" and not char.invisible for char in chars)
