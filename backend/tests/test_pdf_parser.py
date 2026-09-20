from pathlib import Path

import pytest

from app.parsers.pdf import PdfParseError, extract_pdf_text

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_extracts_text_from_a_real_pdf():
    file_bytes = (FIXTURES_DIR / "sample.pdf").read_bytes()

    text = extract_pdf_text(file_bytes)

    assert "Hello World Sample PDF Text" in text


def test_invalid_pdf_bytes_raise_pdf_parse_error():
    with pytest.raises(PdfParseError):
        extract_pdf_text(b"not actually a pdf file")


def test_blank_pdf_raises_pdf_parse_error():
    # A structurally valid PDF with a page that has no text content at all --
    # extract_pdf_text must reject it clearly rather than return "".
    with pytest.raises(PdfParseError):
        extract_pdf_text(_build_minimal_pdf(page_has_content=False))


def _build_minimal_pdf(*, page_has_content: bool) -> bytes:
    """Hand-built minimal single-page PDF with a correct xref table (mirrors
    tests/fixtures/sample.pdf's generator) -- used here to construct a
    variant with no text content, without depending on a second fixture file.
    """
    if page_has_content:
        objects = [
            b"<</Type/Catalog/Pages 2 0 R>>",
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>",
            b"<</Length 4>>\nstream\n\n\nendstream",
        ]
    else:
        objects = [
            b"<</Type/Catalog/Pages 2 0 R>>",
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>",
        ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj".encode() + b"\n" + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref_offset}\n%%EOF".encode()
    return bytes(out)
