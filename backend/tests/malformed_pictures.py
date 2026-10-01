"""Pictures that must never be decoded (tracker SEC-012, TEST-030): a few bytes each that
claim a size no server should allocate, pictures past the byte limit, formats outside
the allowlist, pictures whose bytes aren't the type they claim, and cut-short ones --
beside a small real picture of each allowed format."""

import io
import struct
import zlib

from PIL import Image as PILImage

from app.security.files import MAX_PICTURE_BYTES


def real(format_name: str, size: tuple[int, int] = (6, 4)) -> bytes:
    """A small real picture, as Pillow writes it."""
    buffer = io.BytesIO()
    PILImage.new("RGB", size, (200, 30, 30)).save(buffer, format=format_name)
    return buffer.getvalue()


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_claiming(width: int, height: int) -> bytes:
    """A PNG whose header claims `width` x `height`, with a few bytes of image data."""
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + _chunk(b"IEND", b"")


def jpeg_claiming(width: int, height: int) -> bytes:
    """A small JPEG whose frame header claims `width` x `height` (at most 65535 each)."""
    data = bytearray(real("JPEG", (8, 8)))
    start = data.index(b"\xff\xc0")
    data[start + 5 : start + 9] = struct.pack(">HH", height, width)
    return bytes(data)


def gif_claiming(width: int, height: int) -> bytes:
    """A small GIF whose logical screen claims `width` x `height`."""
    data = bytearray(real("GIF"))
    data[6:10] = struct.pack("<HH", width, height)
    return bytes(data)


def bmp_claiming(width: int, height: int) -> bytes:
    data = bytearray(real("BMP"))
    data[18:26] = struct.pack("<ii", width, height)
    return bytes(data)


EPS = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n%%EndComments\nshowpage\n"

# name -> (bytes, the content type it claims, what it is: "ok", "too_large" or "unreadable")
PICTURES: dict[str, tuple[bytes, str, str]] = {
    "a small PNG": (real("PNG"), "image/png", "ok"),
    "a small JPEG": (real("JPEG"), "image/jpeg", "ok"),
    "a small GIF": (real("GIF"), "image/gif", "ok"),
    "a small BMP": (real("BMP"), "image/bmp", "ok"),
    "a small WebP": (real("WEBP"), "image/webp", "ok"),
    "a PNG just under the pixel limit": (png_claiming(7_000, 7_000), "image/png", "ok"),
    "a PNG claiming 100000 x 100000": (png_claiming(100_000, 100_000), "image/png", "too_large"),
    "a PNG just over the pixel limit": (png_claiming(8_000, 7_000), "image/png", "too_large"),
    "a strip 30000 pixels long": (png_claiming(30_000, 1), "image/png", "too_large"),
    "a JPEG claiming 60000 x 60000": (jpeg_claiming(60_000, 60_000), "image/jpeg", "too_large"),
    "a GIF claiming 60000 x 60000": (gif_claiming(60_000, 60_000), "image/gif", "too_large"),
    "a BMP claiming 30000 x 30000": (bmp_claiming(30_000, 30_000), "image/bmp", "too_large"),
    "a PNG past the byte limit": (real("PNG") + b"\x00" * MAX_PICTURE_BYTES, "image/png", "too_large"),
    "a PNG cut short": (real("PNG")[:20], "image/png", "unreadable"),
    "a TIFF said to be a PNG": (real("TIFF"), "image/png", "unreadable"),
    "a GIF said to be a PNG": (real("GIF"), "image/png", "unreadable"),  # both allowed: stored, it'd be served as what it isn't
    "an EPS said to be a PNG": (EPS, "image/png", "unreadable"),
    "garbage said to be a JPEG": (b"\xff\xd8\xff" + bytes(range(256)) * 4, "image/jpeg", "unreadable"),
}
