"""Export file names: safe on every file system, and a Content-Disposition
header that carries a Cyrillic title (used by the export endpoints and jobs)."""

import re
from urllib.parse import quote

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def safe_filename(title: str) -> str:
    return _UNSAFE_FILENAME_CHARS.sub("_", title).strip() or "document"


def content_disposition(filename: str) -> str:
    """Content-Disposition headers are Latin-1 only (RFC 7230), so a
    Cyrillic (or any non-ASCII) title needs the RFC 6266 filename* form --
    percent-encoded UTF-8, alongside a plain ASCII fallback for clients that
    don't understand filename*."""
    ascii_fallback = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
