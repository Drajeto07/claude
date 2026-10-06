"""The PDF inspection (tracker PDF-012): what the geometry read (parsers/pdf_geometry.py)
found in an imported PDF, page by page -- each page's kind with its evidence (PDF-011),
its size, rotation and boxes, its fonts and text colours, how many lines, rectangles,
curves, pictures, links and annotations it has -- and the file's outline, form fields
and metadata. Kept with the document it was imported into (Document.pdfInspection).

Only what the file says about itself, and none of what it holds that could be personal:
metadata by its names alone, form fields without their values, web links counted, not
listed. Lists are capped (and their full counts given), so a long file stays a small
report."""

from typing import Literal, Optional

from pydantic import Field

from app.models.base import ApiModel

PdfKind = Literal["text", "scanned", "hybrid", "empty"]


class PdfPageEvidence(ApiModel):
    """What a page's kind was decided from (parsers/pdf_classify.py)."""

    # The share of the page under visible characters, and under pictures (0..1).
    textCoverage: float = Field(ge=0.0, le=1.0)
    imageCoverage: float = Field(ge=0.0, le=1.0)
    # Characters other than spaces, drawn visibly and invisibly (text render mode 3 or 7).
    visibleCharacters: int = Field(ge=0)
    invisibleCharacters: int = Field(ge=0)
    fonts: list[str] = Field(default_factory=list, max_length=50)


class PdfFontUse(ApiModel):
    name: str = Field(max_length=100)  # without a subset's prefix
    sizes: list[float] = Field(default_factory=list, max_length=10)  # the sizes it is drawn in, smallest first
    characters: int = Field(ge=0)


class PdfImageBox(ApiModel):
    # Points on the page as shown, from its top left: x0, top, x1, bottom.
    box: list[float] = Field(min_length=4, max_length=4)
    pixelWidth: Optional[int] = None
    pixelHeight: Optional[int] = None


class PdfLinkCounts(ApiModel):
    web: int = 0  # to an address a document may open (security/links.py)
    internal: int = 0  # to a place in the file
    unsafe: int = 0  # to any other address: javascript:, file:, a relative one...
    other: int = 0  # an action: launch a program, run a script, open another file...


class PdfPageInspection(ApiModel):
    number: int = Field(ge=1)
    kind: PdfKind
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=500)
    evidence: PdfPageEvidence
    # In points, as shown (turned by `rotation`).
    width: float
    height: float
    rotation: int
    # The boxes the file sets, in its own coordinates (x0, y0, x1, y1): media and crop
    # always, bleed, trim and art when it sets them.
    boxes: dict[str, list[float]] = Field(default_factory=dict)
    characters: int = Field(ge=0)
    fonts: list[PdfFontUse] = Field(default_factory=list, max_length=20)  # most used first
    textColours: list[str] = Field(default_factory=list, max_length=20)  # "#rrggbb", most used first
    lines: int = Field(ge=0)
    rectangles: int = Field(ge=0)
    curves: int = Field(ge=0)
    imageCount: int = Field(ge=0)
    images: list[PdfImageBox] = Field(default_factory=list, max_length=50)
    links: PdfLinkCounts = Field(default_factory=PdfLinkCounts)
    # Annotations by kind ("Link", "Widget" -- a form field --, "Text" -- a note --, "Highlight"...).
    annotations: dict[str, int] = Field(default_factory=dict)


class PdfPageNotRead(ApiModel):
    number: int = Field(ge=1)
    reason: str = Field(max_length=500)


class PdfOutlineItem(ApiModel):
    title: str = Field(max_length=200)
    level: int = Field(ge=0)  # 0: top level
    page: Optional[int] = None  # None: it goes nowhere in the file


class PdfFormField(ApiModel):
    name: str = Field(max_length=200)
    kind: Literal["text", "button", "choice", "signature", "other"]


class PdfInspection(ApiModel):
    # The file's kind from its pages' (one kind throughout, or hybrid); None when no page was read.
    kind: Optional[PdfKind] = None
    pageCount: int = Field(ge=0)
    version: Optional[str] = Field(default=None, max_length=10)
    pages: list[PdfPageInspection] = Field(default_factory=list)
    notRead: list[PdfPageNotRead] = Field(default_factory=list)
    # Every page and the file's structure were read.
    complete: bool
    # Why the inspection ended before the last page, or couldn't start; None when it didn't.
    stopped: Optional[str] = Field(default=None, max_length=500)
    # Why the outline, form fields and metadata couldn't be read; None when they were.
    structureProblem: Optional[str] = Field(default=None, max_length=500)
    outline: list[PdfOutlineItem] = Field(default_factory=list, max_length=1000)
    outlineCount: int = Field(default=0, ge=0)
    formFields: list[PdfFormField] = Field(default_factory=list, max_length=1000)
    formFieldCount: int = Field(default=0, ge=0)
    # The names of the document information entries it has (Title, Author, Producer...), not their values.
    metadata: list[str] = Field(default_factory=list, max_length=50)
    xmp: bool = False  # it has XMP metadata too
