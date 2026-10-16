"""What an OCR provider gives back, made safe to use (tracker P2E-006): it is untrusted --
an engine can be wrong, a service can be compromised, a picture can be made to read as
anything. Its words are only ever text: control codes and anything XML can't hold go, each
word is capped in length and the page in words, confidence is held to 0..1 and a box to
the picture, and words without text are dropped. Then each word becomes characters laid
across its box on the page (`page_chars`), for the structure reconstruction to read like
any other text, marked as read by OCR."""

import math
import statistics

from app.models.base import xml_text
from app.ocr.base import OcrPage, OcrWord
from app.parsers.pdf_geometry import Box, PdfChar

MAX_OCR_WORDS = 20_000  # on one page: more than a page of small print holds
MAX_OCR_WORD = 100  # characters in one word
OCR_FONT = "OCR"


def _finite(value: float, low: float, high: float) -> float:
    return min(max(value, low), high) if isinstance(value, (int, float)) and math.isfinite(value) else low


def clean(page: OcrPage, width: float, height: float) -> list[OcrWord]:
    """The provider's words on a picture `width` x `height` pixels, made safe (see the module's docstring)."""
    words = []
    for word in page.words[:MAX_OCR_WORDS]:
        text = xml_text(str(word.text or "")).replace("\n", " ").replace("\t", " ").strip()[:MAX_OCR_WORD]
        if not text:
            continue
        x0, top, x1, bottom = (_finite(v, 0.0, limit) for v, limit in zip(word.box, (width, height, width, height), strict=True))
        if x1 <= x0 or bottom <= top:
            continue
        words.append(OcrWord(text=text, confidence=_finite(word.confidence, 0.0, 1.0), box=(x0, top, x1, bottom)))
    return words


def page_chars(words: list[OcrWord], picture: Box, pixels: tuple[int, int]) -> list[PdfChar]:
    """Each word's characters laid evenly across its box, the box moved from the picture's
    pixels onto the page (where the picture is drawn), with a space after each word."""
    x0, top, x1, bottom = picture
    sx, sy = (x1 - x0) / pixels[0], (bottom - top) / pixels[1]
    chars: list[PdfChar] = []
    # A word's box is as tall as its letters (with or without descenders): every word up to a
    # third taller than the page's usual one is that size, so lines of one size stay one size.
    usual = statistics.median((word.box[3] - word.box[1]) * sy for word in words) if words else 1.0
    for word in words:
        left, upper, right, lower = x0 + word.box[0] * sx, top + word.box[1] * sy, x0 + word.box[2] * sx, top + word.box[3] * sy
        step = (right - left) / len(word.text)
        height = lower - upper
        size = round(max(usual if height <= 1.3 * usual else height, 1.0), 2)
        for index, character in enumerate(word.text):
            box = (round(left + index * step, 2), round(upper, 2), round(left + (index + 1) * step, 2), round(lower, 2))
            chars.append(PdfChar(character, OCR_FONT, size, None, box, False, True))
        end = round(right, 2)
        chars.append(PdfChar(" ", OCR_FONT, size, None, (end, round(upper, 2), end + step / 2, round(lower, 2)), False, True))
    return chars


def mean_confidence(words: list[OcrWord]) -> float:
    weights = [(len(word.text), word.confidence) for word in words]
    total = sum(weight for weight, _ in weights)
    return round(sum(weight * value for weight, value in weights) / total, 2) if total else 0.0
