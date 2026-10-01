"""Malformed PDFs (tracker SEC-011, TEST-030): a deterministic corpus made from small
valid PDFs, one way of breaking them each -- cut short, garbage, a broken xref, a stream
that doesn't decode, an object that isn't there, loops, a decompression bomb, nesting
past the parser's limit, a password. Each must come back as its text (all of it, or what
could be read with the damage said) or as invalid_file: never a 500."""

import io
import re
import zlib

from reportlab.pdfgen import canvas

PAGES = 3


def pdf(pages: int = PAGES, *, compress: bool = True, encrypt: str | None = None) -> bytes:
    """`pages` pages of two lines each, the same bytes every time (invariant)."""
    buffer = io.BytesIO()
    document = canvas.Canvas(buffer, invariant=1, pageCompression=1 if compress else 0, encrypt=encrypt)
    for number in range(1, pages + 1):
        document.drawString(72, 720, f"Page {number} begins here with words")
        document.drawString(72, 700, f"and page {number} ends here")
        document.showPage()
    document.save()
    return buffer.getvalue()


def words(pages: int = PAGES) -> list[str]:
    """The words of `pdf(pages)`."""
    return [word for number in range(1, pages + 1) for word in f"Page {number} begins here with words and page {number} ends here".split()]


def _once(data: bytes, old: bytes, new: bytes) -> bytes:
    assert data.count(old) >= 1, old
    return data.replace(old, new, 1)


def _streams(data: bytes) -> list[re.Match[bytes]]:
    """Each stream's dictionary, in the file's order (a page's content streams among them)."""
    return [match for match in re.finditer(rb"<<([^<>]*)>>\s*stream\r?\n", data) if b"/Length" in match.group(1)]


def _corrupt_first_stream(data: bytes) -> bytes:
    start = _streams(data)[0].end()
    return data[:start] + b"\x00" * 20 + data[start + 20 :]


def _without_object(data: bytes, number: int) -> bytes:
    """`data` with object `number` taken out, as if it had never been written."""
    match = re.search(rb"(?<![0-9])" + str(number).encode() + rb" 0 obj.*?endobj\r?\n", data, re.S)
    assert match is not None
    return data[: match.start()] + data[match.end() :]


def _second_page_contents(data: bytes) -> int:
    """The object number of the second page's content stream."""
    references = re.findall(rb"/Contents (\d+) 0 R", data)
    assert len(references) >= 2
    return int(references[1])


def _looping_kids(data: bytes) -> bytes:
    pages = re.search(rb"(\d+) 0 obj\s*<<[^>]*/Type /Pages", data) or re.search(rb"(\d+) 0 obj\s*<<\s*/Count", data)
    assert pages is not None
    return _once(data, b"/Kids [", b"/Kids [ " + pages.group(1) + b" 0 R ")


def _looping_prev(data: bytes) -> bytes:
    startxref = int(re.findall(rb"startxref\s+(\d+)", data)[-1])
    return re.sub(rb"trailer(\r?\n)<<", lambda match: b"trailer" + match.group(1) + f"<< /Prev {startxref}".encode(), data, count=1)


def _bomb(data: bytes) -> bytes:
    """The first flate stream replaced by one that inflates to 200 MB."""
    payload = zlib.compress(b" " * 200_000_000, 9)
    for match in _streams(data):
        if b"/FlateDecode" in match.group(1):
            length = int(re.search(rb"/Length (\d+)", match.group(1)).group(1))
            return data[: match.start()] + f"<< /Filter /FlateDecode /Length {len(payload)} >>\nstream\n".encode() + payload + data[match.end() + length :]
    raise AssertionError("no flate stream")


def _wrong_length(data: bytes) -> bytes:
    """The first stream says it is shorter than it is."""
    match = _streams(data)[0]
    length = int(re.search(rb"/Length (\d+)", match.group(1)).group(1))
    return data[: match.start()] + match.group(0).replace(f"/Length {length}".encode(), f"/Length {length // 2}".encode()) + data[match.end() :]


# What each variant is: its text read whole, read with the damage said, or refused.
READ = "read"
DAMAGED = "damaged"


def variants() -> dict[str, tuple[bytes, str]]:
    """Each way of breaking a valid PDF, by name: (bytes, READ / DAMAGED / the refusal's kind)."""
    base, plain = pdf(), pdf(compress=False)
    return {
        "truncated in the middle": (base[: len(base) // 2], "invalid"),
        "truncated at 90%": (base[: len(base) * 9 // 10], "invalid"),
        "no %%EOF": (base[: base.rindex(b"%%EOF")], "invalid"),
        "only the header": (b"%PDF-1.4\n", "invalid"),
        "garbage after the header": (b"%PDF-1.4\n" + bytes(range(256)) * 16, "invalid"),
        "kids that loop": (_looping_kids(plain), "invalid"),
        "an array nested 5000 deep": (_once(plain, b"/Type /Catalog", b"/Deep " + b"[" * 5000 + b"]" * 5000 + b" /Type /Catalog"), "invalid"),
        "a decompression bomb": (_bomb(base), "too much"),
        "no pages": (re.sub(rb"/Kids \[[^\]]*\]", b"/Kids [ ]", plain, count=1), "no text"),
        "a password": (pdf(encrypt="secret"), "password"),
        "the only page damaged": (_corrupt_first_stream(pdf(1)), "damaged, no text"),
        # Read whole: repairs that lose nothing.
        "offsets shifted": (_once(base, b"\n", b"\n" + b" " * 100), READ),
        "no xref table": (re.sub(rb"xref.*?trailer", b"trailer", base, count=1, flags=re.S), READ),
        "a /Prev that loops": (_looping_prev(plain), READ),
        "a page count that isn't": (_once(plain, b"/Count 3", b"/Count 99999999999999999999999999"), READ),
        "a page far larger than paper": (re.sub(rb"/MediaBox \[[^\]]*\]", b"/MediaBox [ 0 0 99999999 99999999 ]", plain), READ),
        "a stream that says it is shorter": (_wrong_length(plain), READ),
        # Read with the damage said.
        "a stream that doesn't decode": (_corrupt_first_stream(base), DAMAGED),
        "a page's text object missing": (_without_object(plain, _second_page_contents(plain)), DAMAGED),
    }


def with_control_code() -> bytes:
    """A PDF whose first line holds a backspace (a PDF string's \\b), as a broken font's text can."""
    return _once(pdf(compress=False), b"(Page 1 begins", b"(Page 1 \\bbegins")
