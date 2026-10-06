"""The OCR provider interface (tracker P2E-006, brief §43). A provider reads one picture of a
page and says, for each word it found, its text, how sure it is, and where it is on the
picture; with the page it came from and the language or script it took it for. Engines --
a local one, a cloud service -- sit behind it and can be swapped; which one is used is a
setting (OCR_PROVIDER). What a provider gives back is untrusted (app/ocr/results.py)."""

from dataclasses import dataclass, field
from typing import Protocol


class OcrUnavailable(Exception):
    """No OCR provider is configured, or the one configured can't be reached."""


@dataclass(frozen=True, slots=True)
class OcrWord:
    text: str
    confidence: float  # 0..1
    box: tuple[float, float, float, float]  # x0, top, x1, bottom in the picture's pixels, from its top left


@dataclass(frozen=True, slots=True)
class OcrPage:
    page: int  # the PDF page the picture is of, from 1
    words: list[OcrWord] = field(default_factory=list)
    language: str | None = None  # a BCP 47 tag ("bg", "en"), when the provider says
    script: str | None = None  # an ISO 15924 code ("Cyrl", "Latn"), when the provider says


class OcrProvider(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    def recognize(self, picture: bytes, mime: str, *, page: int, languages: list[str]) -> OcrPage:
        """The words on one picture (PNG or JPEG). `languages`: BCP 47 tags to expect, most
        likely first. OcrUnavailable when it can't be read here at all."""
        ...


class NoOcr:
    """The default: no OCR. A page that is only a picture of text stays a picture, and the
    import says its words weren't read."""

    name = "none"

    @property
    def available(self) -> bool:
        return False

    def recognize(self, picture: bytes, mime: str, *, page: int, languages: list[str]) -> OcrPage:
        raise OcrUnavailable("No OCR provider is configured.")
