"""The geometry read (tracker PDF-010) and the page classifier (PDF-011) on the PDF
fixtures (tests/fixtures/pdf/, scripts/make_pdf_fixtures.py, P2E-008): what each page
holds, where, and what kind of page it is with the evidence -- and the read's limits,
each met on a small file with the limit lowered: past a file-level one it refuses like
the text read, past one met on a page it stops and says where, never running unbounded."""

import logging
import zlib
from pathlib import Path

import pytest

from app.fidelity.pdf_inspection import inspect_pdf
from app.parsers import pdf as text_read
from app.parsers import pdf_geometry
from app.parsers.pdf import INVALID, NO_TEXT, PASSWORD, TOO_MUCH, PdfParseError, read_pdf
from app.parsers.pdf_classify import EMPTY, HYBRID, SCANNED, TEXT, classify_page, coverage, document_kind, font_name
from app.parsers.pdf_geometry import (
    DAMAGED_PAGE,
    STOPPED_DATA,
    STOPPED_DEEP,
    STOPPED_DENSE,
    STOPPED_SLOW,
    PdfGeometry,
    read_pdf_geometry,
)
from scripts.make_pdf_fixtures import SCAN_LINES
from tests.malformed_pdf import variants

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"
_security = pytest.mark.security  # the limits and the malformed corpus: part of the security regression suite (TEST-030)
_CORPUS = variants()
A4 = (595.28, 841.89)


def _read(name: str) -> PdfGeometry:
    geometry = read_pdf_geometry((FIXTURES / name).read_bytes())
    assert geometry.complete, (geometry.stopped, geometry.unread, geometry.structure_problem)
    return geometry


def _text(page) -> str:
    return "".join(char.text for char in page.chars)


def _raw_pdf(content: bytes, xobjects: dict[str, bytes] | None = None) -> bytes:
    """A one-page PDF drawing `content`, with form XObjects by name (each may draw the
    others: every form gets every other form among its resources)."""
    names = list(xobjects or {})
    references = "".join(f"/{name} {5 + index} 0 R" for index, name in enumerate(names))
    resources = f"<</Font<</F1 4 0 R>>/XObject<<{references}>>>>".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources " + resources + b"/Contents " + str(5 + len(names)).encode() + b" 0 R>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    for name in names:
        body = (xobjects or {})[name]
        objects.append(b"<</Type/XObject/Subtype/Form/BBox[0 0 612 792]/Resources " + resources + b"/Length %d>>\nstream\n" % len(body) + body + b"\nendstream")
    objects.append(b"<</Length %d>>\nstream\n" % len(content) + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref)
    return bytes(out)


# --- what each page holds (PDF-010) ---------------------------------------------------------

# name: per page (kind, characters, lines, rectangles, curves, pictures, rotation)
_PAGES = {
    "text.pdf": [(TEXT, 230, 0, 0, 0, 0, 0), (TEXT, 69, 0, 0, 0, 0, 0)],
    "columns.pdf": [(TEXT, 1153, 0, 0, 0, 0, 0)],
    "table.pdf": [(TEXT, 56, 10, 1, 0, 0, 0)],
    "pictures.pdf": [(TEXT, 67, 0, 0, 0, 2, 0)],
    "scanned.pdf": [(SCANNED, 0, 0, 0, 0, 1, 0)],
    "hybrid.pdf": [(HYBRID, 82, 0, 0, 0, 1, 0), (TEXT, 45, 0, 0, 0, 0, 0), (SCANNED, 0, 0, 0, 0, 1, 0)],
    "rotated.pdf": [(TEXT, 30, 0, 0, 0, 0, 0), (TEXT, 31, 0, 0, 0, 0, 90), (TEXT, 32, 0, 0, 0, 0, 270), (TEXT, 17, 0, 0, 0, 0, 0), (TEXT, 44, 0, 0, 0, 0, 0)],
    "multilingual.pdf": [(TEXT, 94, 0, 0, 0, 0, 0)],
    "form.pdf": [(TEXT, 36, 0, 3, 0, 0, 0)],
}


@pytest.mark.parametrize("name", list(_PAGES))
def test_each_fixture_page_by_page(name):
    geometry = _read(name)
    found = [
        (classify_page(page).kind, len(page.chars), len(page.lines), len(page.rects), len(page.curves), len(page.images), page.rotation)
        for page in geometry.pages
    ]
    assert found == _PAGES[name]
    assert geometry.page_count == geometry.read_pages == len(_PAGES[name])
    assert geometry.version == ("1.4" if name == "form.pdf" else "1.3")


def test_characters_carry_their_font_size_colour_and_place():
    page = _read("text.pdf").pages[0]
    heading = [char for char in page.chars if char.font == "Helvetica-Bold"]
    assert "".join(char.text for char in heading) == "Quarterly report"
    assert {(char.size, char.colour, char.upright, char.invisible) for char in heading} == {(20.0, "#1a3399", True, False)}
    # Drawn from y = 770 up: its top is 841.89 - 770 - the font's ascent, from the top of the page.
    first = heading[0]
    assert first.box[0] == 72.0 and 50 < first.box[1] < first.box[3] < 80
    warning = [char for char in page.chars if char.font == "Courier"]
    assert {(char.size, char.colour) for char in warning} == {(10.0, "#cc0000")}
    assert {char.font for char in page.chars} == {"Helvetica-Bold", "Helvetica", "Times-Roman", "Courier"}


def test_two_columns_are_two_runs_of_characters_side_by_side():
    page = _read("columns.pdf").pages[0]
    body = [char for char in page.chars if char.size == 10.0]
    left = [char for char in body if char.box[0] < A4[0] / 2]
    right = [char for char in body if char.box[0] >= A4[0] / 2]
    assert "".join(char.text for char in left).startswith("Left column line 1 of the text.")
    assert "".join(char.text for char in right).startswith("Right column line 1 here.")
    assert min(char.box[0] for char in right) == pytest.approx(A4[0] / 2 + 18, abs=0.01)
    assert max(char.box[2] for char in left) < min(char.box[0] for char in right)


def test_a_ruled_table_is_its_lines_and_its_shaded_header():
    page = _read("table.pdf").pages[0]
    horizontal = sorted(line.box for line in page.lines if line.box[1] == line.box[3])
    vertical = sorted(line.box for line in page.lines if line.box[0] == line.box[2])
    assert len(horizontal) == len(vertical) == 5
    assert [box[1] for box in horizontal] == [round(A4[1] - 740 + row * 24, 2) for row in range(5)]
    assert [box[0] for box in vertical] == [72 + column * 112 for column in range(5)]
    assert {(line.width, line.stroke) for line in page.lines} == {(0.8, "#000000")}
    (header,) = page.rects
    assert (header.box, header.fill, header.stroke) == ((72.0, round(A4[1] - 740, 2), 520.0, round(A4[1] - 716, 2)), "#d9d9d9", None)
    assert "Desk" in _text(page) and "120.00" in _text(page)


def test_pictures_have_their_boxes_and_pixel_sizes():
    images = _read("pictures.pdf").pages[0].images
    assert [(image.box, image.pixels) for image in images] == [
        ((72.0, round(A4[1] - 680, 2), 272.0, round(A4[1] - 560, 2)), (200, 120)),
        ((320.0, round(A4[1] - 680, 2), 440.0, round(A4[1] - 560, 2)), (120, 120)),
    ]


def test_turned_pages_are_read_as_shown():
    pages = _read("rotated.pdf").pages
    assert [(page.rotation, page.width, page.height) for page in pages] == [
        (0, *A4), (90, *A4), (270, *A4), (0, A4[1], A4[0]), (0, *A4)
    ]
    # Turned with its page, the text runs down the page: not upright, still its own size.
    assert {(char.upright, char.size) for char in pages[1].chars} == {(False, 11.0)}
    assert _text(pages[1]) == "This page is turned 90 degrees."
    for page in pages:  # every character on the page as shown
        assert all(0 <= char.box[0] <= char.box[2] <= page.width and 0 <= char.box[1] <= char.box[3] <= page.height for char in page.chars)
    assert pages[1].boxes["media"] == (0.0, 0.0, A4[1], A4[0])
    assert pages[4].boxes == {
        "media": (0.0, 0.0, *A4),
        "crop": (20.0, 20.0, round(A4[0] - 20, 2), round(A4[1] - 20, 2)),
        "bleed": (10.0, 10.0, round(A4[0] - 10, 2), round(A4[1] - 10, 2)),
        "trim": (30.0, 30.0, round(A4[0] - 30, 2), round(A4[1] - 30, 2)),
        "art": (50.0, 50.0, round(A4[0] - 50, 2), round(A4[1] - 50, 2)),
    }
    assert set(pages[0].boxes) == {"media", "crop"}


def test_cyrillic_and_greek_are_read_as_their_letters():
    page = _read("multilingual.pdf").pages[0]
    text = _text(page)
    assert "Добър ден, свят!" in text and "Това е български текст на кирилица." in text
    assert "Καλημέρα κόσμε!" in text and "Αυτό είναι ελληνικό κείμενο." in text
    assert {font_name(char.font) for char in page.chars} == {"DejaVuSans"}  # embedded as a subset: "ABCDEF+DejaVuSans"


def test_links_annotations_outline_and_metadata():
    geometry = _read("text.pdf")
    first = geometry.pages[0]
    assert [(link.link, link.target) for link in first.links] == [("web", "https://example.com/report"), ("unsafe", None), ("internal", 2)]
    assert [annotation.kind for annotation in first.annotations] == ["Link", "Link", "Link", "Text"]
    assert first.annotations[0].box == (72.0, round(A4[1] - 610, 2), 200.0, round(A4[1] - 597, 2))
    assert [(entry.title, entry.level, entry.page) for entry in geometry.outline] == [("Introduction", 0, 1), ("Details", 0, 2), ("Figures", 1, 2)]
    assert geometry.outline_count == 3
    assert geometry.metadata["Title"] == "Text fixture" and geometry.metadata["Author"] == "SmartDoc PDF fixtures"
    assert {"Subject", "Creator", "Producer", "CreationDate"} <= set(geometry.metadata)
    assert not geometry.xmp and geometry.fields == [] and geometry.field_count == 0


def test_form_fields_are_found_with_their_kinds():
    geometry = _read("form.pdf")
    assert [(field.name, field.kind) for field in geometry.fields] == [("applicant", "text"), ("subscribe", "button"), ("size", "choice")]
    assert geometry.field_count == 3
    assert [annotation.kind for annotation in geometry.pages[0].annotations] == ["Widget"] * 3


# --- what kind of page (PDF-011) ------------------------------------------------------------


def test_scanned_and_hybrid_pages_with_their_evidence():
    scan, typed, bare_scan = (classify_page(page) for page in _read("hybrid.pdf").pages)
    layer = sum(len(line.replace(" ", "")) for line in SCAN_LINES)
    assert (scan.kind, scan.confidence) == (HYBRID, 0.95)
    assert (scan.evidence.invisible_chars, scan.evidence.visible_chars, scan.evidence.image_coverage) == (layer, 0, 1.0)
    assert scan.evidence.fonts == ("Helvetica",) and "Invisible text" in scan.reason
    assert (typed.kind, typed.evidence.image_coverage, typed.evidence.invisible_chars) == (TEXT, 0.0, 0)
    assert typed.evidence.text_coverage > 0
    assert (bare_scan.kind, bare_scan.confidence, bare_scan.evidence.visible_chars, bare_scan.evidence.image_coverage) == (SCANNED, 0.9, 0, 1.0)
    assert bare_scan.evidence.fonts == ()
    only = classify_page(_read("scanned.pdf").pages[0])
    assert (only.kind, only.evidence.images, only.evidence.text_coverage) == (SCANNED, 1, 0.0)


def test_a_text_page_with_pictures_stays_a_text_page():
    kind = classify_page(_read("pictures.pdf").pages[0])
    assert kind.kind == TEXT and kind.confidence == 1.0
    # Two pictures of 200 x 120 and 120 x 120 points on an A4 page.
    assert kind.evidence.image_coverage == pytest.approx((200 * 120 + 120 * 120) / (A4[0] * A4[1]), abs=0.01)
    assert kind.evidence.images == 2 and kind.evidence.paths == 0


def test_text_over_a_page_sized_picture_or_alone(monkeypatch):
    page = _read("hybrid.pdf").pages[0]
    shown = [char.__class__(char.text, char.font, char.size, char.colour, char.box, False, char.upright) for char in page.chars]
    page.chars = shown  # the same layer drawn visibly: text on a background picture, or a scan with text added
    assert (classify_page(page).kind, classify_page(page).confidence) == (HYBRID, 0.6)
    page.images = []
    assert classify_page(page).kind == TEXT
    page.chars = []
    assert (classify_page(page).kind, classify_page(page).reason) == (EMPTY, "No text and no pictures on this page.")


def test_coverage_counts_overlaps_once():
    assert coverage([(0, 0, 50, 100)], 100, 100) == 0.5
    assert coverage([(0, 0, 50, 100), (0, 0, 50, 100), (25, 0, 75, 100)], 100, 100) == 0.75
    assert coverage([(-10, -10, 1000, 1000)], 100, 100) == 1.0
    assert coverage([], 100, 100) == 0.0 and coverage([(0, 0, 1, 1)], 0, 0) == 0.0


def test_a_files_kind_is_its_pages_kind_or_hybrid():
    assert document_kind([TEXT, EMPTY, TEXT]) == TEXT
    assert document_kind([SCANNED, SCANNED]) == SCANNED
    assert document_kind([TEXT, SCANNED]) == HYBRID
    assert document_kind([EMPTY]) == EMPTY and document_kind([]) is None
    assert font_name("ABCDEF+DejaVuSans") == "DejaVuSans" and font_name("Helvetica+Bold") == "Helvetica+Bold"


# --- limits: refused like the text read, or stopped where the limit was met ------------------


@_security
def test_too_many_pages_is_refused_with_the_text_reads_message(monkeypatch):
    data = (FIXTURES / "rotated.pdf").read_bytes()
    monkeypatch.setattr(text_read, "MAX_PDF_PAGES", 4)  # one setting for both reads
    with pytest.raises(PdfParseError) as text_refusal:
        read_pdf(data)
    with pytest.raises(PdfParseError) as geometry_refusal:
        read_pdf_geometry(data)
    assert str(geometry_refusal.value) == str(text_refusal.value) == "This PDF has more than 4 pages, more than can be imported at once."
    monkeypatch.setattr(text_read, "MAX_PDF_PAGES", 5)
    assert read_pdf_geometry(data).read_pages == 5


@_security
def test_too_many_objects_is_refused(monkeypatch):
    data = (FIXTURES / "text.pdf").read_bytes()
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_OBJECTS", 10)
    with pytest.raises(PdfParseError, match=TOO_MUCH):
        read_pdf_geometry(data)
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_OBJECTS", 100)
    assert read_pdf_geometry(data).complete


@_security
def test_a_page_with_too_much_content_stops_the_read_there(monkeypatch):
    data = (FIXTURES / "text.pdf").read_bytes()  # its pages' content: 692 and 258 bytes
    monkeypatch.setattr(text_read, "MAX_PDF_PAGE_CONTENT", 500)
    geometry = read_pdf_geometry(data)
    assert (geometry.stopped, geometry.read_pages, geometry.pages, geometry.complete) == (STOPPED_DENSE.format(page=1), 0, [], False)
    monkeypatch.setattr(text_read, "MAX_PDF_PAGE_CONTENT", 700)
    assert read_pdf_geometry(data).complete


@_security
def test_a_form_drawn_again_and_again_counts_each_time(monkeypatch):
    # 1,000 draws of a form 4 KB long: 4 MB drawn from a file of a few kilobytes.
    monkeypatch.setattr(text_read, "MAX_PDF_PAGE_CONTENT", 100_000)
    geometry = read_pdf_geometry(_raw_pdf(b"/X1 Do", {"X1": b"/X2 Do\n" * 1000, "X2": b"q Q\n" * 1000}))
    assert geometry.stopped == STOPPED_DENSE.format(page=1) and geometry.read_pages == 0
    assert read_pdf_geometry(_raw_pdf(b"/X1 Do", {"X1": b"/X2 Do\n" * 20, "X2": b"q Q\n" * 1000})).complete  # 80 KB


@_security
def test_too_many_things_on_a_page_stops_the_read(monkeypatch):
    data = (FIXTURES / "columns.pdf").read_bytes()  # 1,153 characters
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_PAGE_ITEMS", 1000)
    assert read_pdf_geometry(data).stopped == STOPPED_DENSE.format(page=1)
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_PAGE_ITEMS", 1200)
    assert read_pdf_geometry(data).complete


@_security
def test_the_time_budget_stops_the_read(monkeypatch):
    data = (FIXTURES / "text.pdf").read_bytes()
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_GEOMETRY_SECONDS", 0.0)
    geometry = read_pdf_geometry(data)
    assert (geometry.stopped, geometry.read_pages) == (STOPPED_SLOW.format(page=1), 0)


@_security
@pytest.mark.parametrize("content", [b"0 0 1 1 re f\n" * 20_000, b"q Q " * 50_000], ids=["drawing", "nothing drawn"])
def test_the_time_budget_is_checked_within_a_page(monkeypatch, content):
    # A clock that moves a second each time it is read: the page is stopped within the budget,
    # whether it draws (each path checked) or only saves and restores states.
    data = _raw_pdf(content)
    clock = iter(range(10**6))
    monkeypatch.setattr(pdf_geometry.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_GEOMETRY_SECONDS", 1000)
    geometry = read_pdf_geometry(data)
    assert geometry.stopped == STOPPED_SLOW.format(page=1) and next(clock) < 1010


@_security
def test_nesting_past_the_limit_stops_the_read(monkeypatch):
    assert read_pdf_geometry(_raw_pdf(b"q " * 100 + b"Q " * 100)).stopped == STOPPED_DEEP.format(page=1)
    assert read_pdf_geometry(_raw_pdf(b"q " * 60 + b"Q " * 60)).complete
    chain = {f"X{level}": f"/X{level + 1} Do".encode() for level in range(1, 6)} | {"X6": b"0 0 1 1 re f"}
    assert read_pdf_geometry(_raw_pdf(b"/X1 Do", chain)).complete
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_NESTING", 5)
    assert read_pdf_geometry(_raw_pdf(b"/X1 Do", chain)).stopped == STOPPED_DEEP.format(page=1)


@_security
def test_what_a_stream_decodes_to_is_bounded(monkeypatch):
    data = (FIXTURES / "text.pdf").read_bytes()
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_STREAM_DECODED", 600)  # the first page's content is 692 bytes
    assert read_pdf_geometry(data).stopped == STOPPED_DATA.format(page=1)
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_STREAM_DECODED", 700)
    assert read_pdf_geometry(data).complete


@_security
def test_what_a_read_decodes_in_all_is_bounded(monkeypatch):
    data = (FIXTURES / "text.pdf").read_bytes()
    monkeypatch.setattr(pdf_geometry, "MAX_PDF_DECODED", 800)  # 692 + 258 bytes of content
    geometry = read_pdf_geometry(data)
    assert (geometry.stopped, geometry.read_pages) == (STOPPED_DATA.format(page=2), 1)


@_security
def test_a_decompression_bomb_is_never_inflated_whole():
    geometry = read_pdf_geometry(_CORPUS["a decompression bomb"][0])  # a stream of 200 MB
    assert geometry.stopped == STOPPED_DATA.format(page=1)
    with pytest.raises(pdf_geometry._TooMuchData):
        pdf_geometry.pdftypes.zlib.decompress(zlib.compress(b" " * (pdf_geometry.MAX_PDF_STREAM_DECODED + 1)))


@_security
def test_a_damaged_stream_gives_what_decoded_before_the_damage():
    whole = zlib.compress(b"words " * 1000)
    assert pdf_geometry.pdftypes.zlib.decompress(whole) == b"words " * 1000
    assert (b"words " * 1000).startswith(pdf_geometry.pdftypes.zlib.decompress(whole[:200]))
    assert pdf_geometry.pdftypes.rldecode(b"\x02abc\xfdz\x80") == b"abczzzz"
    assert pdf_geometry.pdftypes.lzwdecode(b"\x80\x0b\x60\x50\x22\x0c\x0c\x85\x01") == b"-----A---B"


@_security
@pytest.mark.parametrize("name", list(_CORPUS))
def test_a_malformed_pdf_is_read_refused_or_stopped_never_a_crash(name):
    data, expected = _CORPUS[name]
    try:
        geometry = read_pdf_geometry(data)
    except PdfParseError as refused:
        assert str(refused) in (INVALID, PASSWORD, TOO_MUCH), name
        assert (str(refused) == PASSWORD) == (expected == "password"), name  # in the text read's words
        return
    assert expected != "password"
    assert set(geometry.unread.values()) <= {DAMAGED_PAGE}
    assert inspect_pdf(data).pageCount == geometry.page_count


@_security
def test_a_scanned_pdf_is_still_refused_by_the_text_read():
    with pytest.raises(PdfParseError, match=NO_TEXT):
        read_pdf((FIXTURES / "scanned.pdf").read_bytes())


class _Root(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@_security
def test_nothing_pdfminer_says_about_a_file_reaches_the_log():
    root = _Root()
    logging.getLogger().addHandler(root)
    try:
        for data, _ in _CORPUS.values():
            try:
                read_pdf_geometry(data)
            except PdfParseError:
                pass
        logging.getLogger("pdfminer.pdfparser").error("Page 1 begins: what pdfminer could quote")  # at any level
    finally:
        logging.getLogger().removeHandler(root)
    assert [record.name for record in root.records if record.name.startswith(("pdfminer", "pypdf"))] == []
    ours = [record.getMessage() for record in root.records if record.name == "app.parsers.pdf_geometry"]
    assert ours and all(" at " in message for message in ours)
    assert not [message for message in ours if "begins" in message or "Page 1" in message]
