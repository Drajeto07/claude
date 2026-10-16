"""The pictures of a PDF, as files a document can hold (tracker P2E-003): each one the
structure reconstruction places (parsers/pdf_structure.py) is found by its name among its
page's pictures and decoded -- a JPEG kept as it is, anything else drawn into a PNG -- then
judged like any picture taken in (security/files.py picture_problem, SEC-012).

The file is untrusted, and a picture can claim any size in a few bytes: one is decoded
only when the size the geometry read found for it is within MAX_PDF_PICTURE_PIXELS, all of
an import's together within MAX_PDF_PICTURES_PIXELS, no more than MAX_PDF_PICTURES of them,
for MAX_PDF_PICTURES_SECONDS at most. pypdf decodes (with its own limits on what a stream
inflates to); Pillow, with its own backstop, writes the PNG. Every picture not decoded has
its reason, for the import report: none is dropped silently."""

import io
import logging
import time
from dataclasses import dataclass

from PIL import Image as PILImage
from pypdf import PdfReader

from app.parsers.trace import where
from app.security.files import picture_problem

logger = logging.getLogger(__name__)

MAX_PDF_PICTURES = 300
MAX_PDF_PICTURE_PIXELS = 25_000_000
MAX_PDF_PICTURES_PIXELS = 150_000_000
MAX_PDF_PICTURES_SECONDS = 30.0

# Why a picture wasn't imported (each a phrase after "N pictures were ...").
TOO_MANY = "past the most an import takes"
TOO_LARGE = "too large to decode safely"
UNREADABLE = "in a form that couldn't be read"
MISSING = "not found where the page says they are"
TOO_SLOW = "not read in the time a PDF's pictures have"


@dataclass(frozen=True, slots=True)
class PictureRef:
    page: int  # from 1
    index: int  # among the page's pictures, as the geometry read lists them
    name: str | None  # its XObject's name
    pixels: tuple[int, int] | None  # its own width and height, as the file says


@dataclass(frozen=True, slots=True)
class Picture:
    mime: str
    data: bytes


def _png(image: PILImage.Image) -> bytes:
    if image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.mode else "RGB")  # CMYK, YCbCr, I;16...
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _decode(images, ref: PictureRef) -> Picture | str:
    keys = list(images.keys())
    key = next((k for k in keys if k == f"/{ref.name}"), None) or next((k for k in keys if str(k).rsplit("/", 1)[-1] == ref.name), None)
    if key is None:
        return MISSING
    found = images[key]
    if found.name.lower().endswith((".jpg", ".jpeg")):
        picture = Picture("image/jpeg", found.data)
    else:
        if found.image is None:
            return UNREADABLE
        picture = Picture("image/png", _png(found.image))
    problem = picture_problem(picture.data, picture.mime)
    if problem is not None:
        return TOO_LARGE if problem.kind == "too_large" else UNREADABLE
    return picture


def decode_pictures(file_bytes: bytes, wanted: list[PictureRef]) -> dict[tuple[int, int], Picture | str]:
    """Each wanted picture decoded, or why not, by (page, index). Never raises."""
    results: dict[tuple[int, int], Picture | str] = {}
    pending = []
    pixels_left = MAX_PDF_PICTURES_PIXELS
    for ref in wanted:
        key = (ref.page, ref.index)
        if ref.name is None:
            results[key] = MISSING
        elif ref.pixels is None or ref.pixels[0] * ref.pixels[1] > MAX_PDF_PICTURE_PIXELS:
            results[key] = TOO_LARGE  # a size it won't say is no size to trust
        elif len(pending) >= MAX_PDF_PICTURES or ref.pixels[0] * ref.pixels[1] > pixels_left:
            results[key] = TOO_MANY
        else:
            pixels_left -= ref.pixels[0] * ref.pixels[1]
            pending.append(ref)
    if not pending:
        return results
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001 -- the text read opened it; whatever fails now costs the pictures only
        logger.info("A PDF's pictures couldn't be opened: %s at %s", type(exc).__name__, where(exc))
        return results | {(ref.page, ref.index): UNREADABLE for ref in pending}
    deadline = time.monotonic() + MAX_PDF_PICTURES_SECONDS
    for ref in pending:
        key = (ref.page, ref.index)
        if time.monotonic() > deadline:
            results[key] = TOO_SLOW
            continue
        try:
            results[key] = _decode(reader.pages[ref.page - 1].images, ref)
        except Exception as exc:  # noqa: BLE001 -- one picture's damage costs that picture
            logger.info("A PDF picture couldn't be decoded: %s at %s", type(exc).__name__, where(exc))
            results[key] = UNREADABLE
    return results
