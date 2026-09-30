"""Which addresses a link may have (SEC-014): one policy for every way a link reaches a
document -- the Word and Markdown importers, the editor, the AI -- and for every export
that writes one. A Word file or a PDF opens its links outside the app, so a link may only
be an absolute address of a kind that opens a page, a mail, a call or a chat: never
javascript:, data:, vbscript: or file:, a UNC path, or a relative address, which a Word
file resolves against the folder it sits in."""

from urllib.parse import urlsplit

from app.models.base import xml_text

# The editor's own (Tiptap's), but cid: -- a part of an e-mail, nothing in a document.
SAFE_SCHEMES = frozenset({"http", "https", "ftp", "ftps", "mailto", "tel", "callto", "sms", "xmpp"})
# Longer than any address a person follows; past it, it isn't kept as a link.
MAX_HREF = 2048
# What browsers (WHATWG) and urlsplit remove from inside an address before reading it.
_INSIDE = str.maketrans("", "", "\t\n\r")


def safe_href(value: str | None) -> str | None:
    """`value` as a link may keep it, or None. A bare "www." address gets https://."""
    if not value:
        return None
    # Control codes go, as XML can't hold them -- and browsers drop the leading ones,
    # so "\\x01javascript:" is javascript: to them.
    value = xml_text(value).translate(_INSIDE).strip()
    if not value or len(value) > MAX_HREF:
        return None
    if value.lower().startswith("www."):
        value = f"https://{value}"
    try:
        scheme = urlsplit(value).scheme.lower()
    except ValueError:  # an address urlsplit can't read (an unbalanced IPv6 bracket)
        return None
    return value if scheme in SAFE_SCHEMES else None
