"""Builds the PDF fixtures in tests/fixtures/pdf/ (tracker P2E-008): one per kind of
page the PDF inspection (parsers/pdf_geometry.py, PDF-010..012) and the PDF -> editable
phase must tell apart -- text, two columns, a ruled table, pictures, a scanned page, a
scanned page under an invisible text layer, turned pages, Cyrillic and Greek, a form,
and the headings, lists, running header and captions the structure reconstruction finds.
Synthetic text only.

Built with reportlab and Pillow in reportlab's invariant mode (fixed dates and document
ids), so a rebuild writes the same bytes: tests/test_pdf_fixtures.py checks the
committed files against this script. The Cyrillic and Greek one embeds DejaVu Sans,
found where the PDF export finds fonts (CI installs fonts-dejavu-core).

    python -m scripts.make_pdf_fixtures
"""

import io
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "pdf"
WIDTH, HEIGHT = A4
# The words a "scanned" page shows in its picture (and, on the hybrid page, in its text layer).
SCAN_LINES = ("Scanned letter", "This page is a picture of", "printed text, with no text", "layer of its own.")
# DejaVu Sans as fonts-dejavu-core 2.37 ships it: the bytes of multilingual.pdf depend on it.
DEJAVU_SHA256 = "ae7b7855e115a5966d8b1b3f80f254ccc117ec86f9965e202ee2940453837280"


def _canvas(buffer: io.BytesIO, title: str, pagesize: tuple[float, float] = A4) -> Canvas:
    canvas = Canvas(buffer, pagesize=pagesize, invariant=1, pageCompression=1)
    canvas.setTitle(title)
    canvas.setAuthor("SmartDoc PDF fixtures")
    canvas.setSubject("Synthetic test document")
    canvas.setCreator("scripts/make_pdf_fixtures.py")
    return canvas


def _lines(canvas: Canvas, x: float, y: float, lines: list[str], font: str = "Helvetica", size: float = 11, leading: float = 15) -> float:
    canvas.setFont(font, size)
    for line in lines:
        canvas.drawString(x, y, line)
        y -= leading
    return y


def _png(size: tuple[int, int], colour: tuple[int, int, int], stripe: tuple[int, int, int]) -> ImageReader:
    picture = Image.new("RGB", size, colour)
    draw = ImageDraw.Draw(picture)
    for x in range(0, size[0], 20):
        draw.rectangle((x, 0, x + 9, size[1]), fill=stripe)
    return ImageReader(picture)


def _scan() -> ImageReader:
    """A page-sized greyscale "scan" of printed text: a picture, nothing to select."""
    picture = Image.new("L", (850, 1100), 250)
    draw = ImageDraw.Draw(picture)
    font = ImageFont.load_default(size=40)
    for index, line in enumerate(SCAN_LINES):
        draw.text((90, 110 + index * 70), line, fill=20, font=font)
    draw.rectangle((60, 60, 790, 1040), outline=120, width=3)
    return ImageReader(picture)


def text() -> bytes:
    """Two pages of plain text in three fonts, sizes and colours, with an outline, links
    (a web address, a javascript: one, one to page 2) and a note."""
    buffer = io.BytesIO()
    canvas = _canvas(buffer, "Text fixture")
    canvas.bookmarkPage("intro")
    canvas.addOutlineEntry("Introduction", "intro", level=0)
    canvas.setFillColorRGB(0.1, 0.2, 0.6)
    _lines(canvas, 72, 770, ["Quarterly report"], font="Helvetica-Bold", size=20)
    canvas.setFillColorRGB(0, 0, 0)
    y = _lines(canvas, 72, 730, ["The first paragraph has plain words in Helvetica.", "It runs over two lines of text."])
    y = _lines(canvas, 72, y - 10, ["A second paragraph is set in Times Roman."], font="Times-Roman", size=12)
    canvas.setFillColorRGB(0.8, 0, 0)
    _lines(canvas, 72, y - 10, ["A warning in red, in Courier."], font="Courier", size=10)
    canvas.setFillColorRGB(0, 0, 0)
    _lines(canvas, 72, 600, ["Visit the example site.", "Do not run this script.", "Go to the details."])
    canvas.linkURL("https://example.com/report", (72, 597, 200, 610), relative=0)
    canvas.linkURL("javascript:alert(1)", (72, 582, 200, 595), relative=0)
    canvas.linkAbsolute("details", "details", (72, 567, 200, 580))
    canvas.textAnnotation("A reviewer's note.", Rect=(400, 700, 420, 720), relative=0)
    canvas.showPage()
    canvas.bookmarkPage("details")
    canvas.addOutlineEntry("Details", "details", level=0)
    canvas.bookmarkPage("figures")
    canvas.addOutlineEntry("Figures", "figures", level=1)
    _lines(canvas, 72, 770, ["Details"], font="Helvetica-Bold", size=16)
    _lines(canvas, 72, 740, ["The second page holds the details.", "Its words are plain as well."])
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def columns() -> bytes:
    """One page set in two columns."""
    buffer = io.BytesIO()
    canvas = _canvas(buffer, "Columns fixture")
    _lines(canvas, 72, 780, ["Two columns"], font="Helvetica-Bold", size=18)
    left = [f"Left column line {number} of the text." for number in range(1, 21)]
    right = [f"Right column line {number} here." for number in range(1, 21)]
    _lines(canvas, 72, 740, left, size=10, leading=14)
    _lines(canvas, WIDTH / 2 + 18, 740, right, size=10, leading=14)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def table() -> bytes:
    """A ruled table: a shaded header row and a grid of 4 x 4 cells drawn as lines."""
    buffer = io.BytesIO()
    canvas = _canvas(buffer, "Table fixture")
    _lines(canvas, 72, 780, ["Prices"], font="Helvetica-Bold", size=16)
    left, top, width, height = 72, 740, 112, 24
    canvas.setFillColorRGB(0.85, 0.85, 0.85)
    canvas.rect(left, top - height, width * 4, height, stroke=0, fill=1)
    canvas.setFillColorRGB(0, 0, 0)
    canvas.setLineWidth(0.8)
    for row in range(5):
        canvas.line(left, top - row * height, left + 4 * width, top - row * height)
    for column in range(5):
        canvas.line(left + column * width, top, left + column * width, top - 4 * height)
    cells = [["Item", "Size", "Count", "Price"], ["Pen", "S", "10", "1.20"], ["Book", "M", "2", "9.50"], ["Desk", "L", "1", "120.00"]]
    for row, values in enumerate(cells):
        canvas.setFont("Helvetica-Bold" if row == 0 else "Helvetica", 10)
        for column, value in enumerate(values):
            canvas.drawString(left + column * width + 6, top - row * height - 16, value)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def pictures() -> bytes:
    """Text with two pictures beside and under it."""
    buffer = io.BytesIO()
    canvas = _canvas(buffer, "Pictures fixture")
    _lines(canvas, 72, 780, ["Pictures", "Two pictures follow this line."])
    canvas.drawImage(_png((200, 120), (40, 90, 160), (230, 230, 240)), 72, 560, width=200, height=120)
    canvas.drawImage(_png((120, 120), (180, 60, 40), (250, 220, 120)), 320, 560, width=120, height=120)
    _lines(canvas, 72, 530, ["A caption under the pictures."])
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def scanned() -> bytes:
    """One page that is only a picture of text: nothing to read without OCR."""
    buffer = io.BytesIO()
    canvas = _canvas(buffer, "Scanned fixture")
    canvas.drawImage(_scan(), 0, 0, width=WIDTH, height=HEIGHT)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def hybrid() -> bytes:
    """A scanned page under an invisible text layer (what OCR software writes), a page of
    ordinary text, and a scanned page with no text layer."""
    buffer = io.BytesIO()
    canvas = _canvas(buffer, "Hybrid fixture")
    canvas.drawImage(_scan(), 0, 0, width=WIDTH, height=HEIGHT)
    layer = canvas.beginText()
    layer.setTextRenderMode(3)  # invisible: there to be found and copied, the picture shows the words
    layer.setFont("Helvetica", 19)
    for index, line in enumerate(SCAN_LINES):
        layer.setTextOrigin(WIDTH * 90 / 850, HEIGHT - HEIGHT * (140 + index * 70) / 1100)
        layer.textOut(line)
    canvas.drawText(layer)
    canvas.showPage()
    _lines(canvas, 72, 780, ["An ordinary page", "Typed text between the scans."])
    canvas.showPage()
    canvas.drawImage(_scan(), 0, 0, width=WIDTH, height=HEIGHT)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def rotated() -> bytes:
    """Pages turned 0, 90 and 270 degrees, a landscape one, and one with every page box."""
    buffer = io.BytesIO()
    canvas = _canvas(buffer, "Rotated fixture")
    for turn in (0, 90, 270):
        canvas.setPageRotation(turn)
        _lines(canvas, 72, 500, [f"This page is turned {turn} degrees."])  # inside the page either way round
        canvas.showPage()
    canvas.setPageRotation(0)
    canvas.setPageSize(landscape(A4))
    _lines(canvas, 72, 520, ["A landscape page."])
    canvas.showPage()
    canvas.setPageSize(A4)
    canvas.setCropBox((20, 20, WIDTH - 20, HEIGHT - 20))
    canvas.setBleedBox((10, 10, WIDTH - 10, HEIGHT - 10))
    canvas.setTrimBox((30, 30, WIDTH - 30, HEIGHT - 30))
    canvas.setArtBox((50, 50, WIDTH - 50, HEIGHT - 50))
    _lines(canvas, 72, 760, ["A page with crop, bleed, trim and art boxes."])
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def dejavu() -> Path:
    from app.export.fonts import _font_files  # where the PDF export looks for fonts

    path = _font_files().get("dejavusans.ttf")
    if path is None:
        raise FileNotFoundError("DejaVu Sans isn't installed (apt-get install fonts-dejavu-core)")
    return path


def multilingual() -> bytes:
    """Bulgarian (Cyrillic) and Greek text in an embedded DejaVu Sans."""
    if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(dejavu())))
    buffer = io.BytesIO()
    canvas = _canvas(buffer, "Multilingual fixture")
    _lines(canvas, 72, 780, ["Добър ден, свят!", "Това е български текст на кирилица."], font="DejaVuSans", size=14, leading=20)
    _lines(canvas, 72, 700, ["Καλημέρα κόσμε!", "Αυτό είναι ελληνικό κείμενο."], font="DejaVuSans", size=14, leading=20)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def form() -> bytes:
    """A form: a text field, a check box and a choice."""
    buffer = io.BytesIO()
    canvas = _canvas(buffer, "Form fixture")
    _lines(canvas, 72, 780, ["Application form"], font="Helvetica-Bold", size=16)
    _lines(canvas, 72, 740, ["Name:", "", "Subscribe:", "", "Size:"])
    form = canvas.acroForm
    black = Color(0, 0, 0)
    form.textfield(name="applicant", tooltip="Name", x=150, y=730, width=200, height=20, borderColor=black, forceBorder=True)
    form.checkbox(name="subscribe", tooltip="Subscribe", x=150, y=700, size=16, borderColor=black, forceBorder=True)
    form.choice(name="size", tooltip="Size", value="M", options=["S", "M", "L"], x=150, y=670, width=80, height=20, borderColor=black, forceBorder=True)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def structure() -> bytes:
    """Three pages with what the PDF -> editable reconstruction rebuilds (P2E-002): a
    running header and page numbers on every page; headings at two sizes and a bold one
    at body size; paragraphs told apart by a gap and by a first-line indent; a bulleted
    list with a nested level and an item over two lines; a numbered list, and one that
    counts on from 3 after a break; a paragraph running on to the next page; a picture
    with a "Figure 1" caption under it."""
    buffer = io.BytesIO()
    canvas = _canvas(buffer, "Structure fixture")

    def furniture(number: int) -> None:
        canvas.setFillColorRGB(0, 0, 0)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(72, HEIGHT - 40, "Annual review - Synthetic Ltd")
        canvas.drawRightString(WIDTH - 72, 30, f"Page {number} of 3")

    def item(x: float, y: float, marker: str, text: str) -> None:
        canvas.setFont("Helvetica", 11)
        canvas.drawString(x, y, marker)
        canvas.drawString(x + 14, y, text)

    furniture(1)
    _lines(canvas, 72, 770, ["Annual review"], font="Helvetica-Bold", size=22)
    _lines(canvas, 72, 735, ["Overview"], font="Helvetica-Bold", size=16)
    y = _lines(canvas, 72, 710, ["The year brought steady work across every team, and this", "review sums it up in a few short sections."])
    y = _lines(canvas, 90, y, ["A second paragraph starts with an indent instead of a gap,"])
    y = _lines(canvas, 72, y, ["as books set them, and carries on at the margin."])
    _lines(canvas, 72, y - 12, ["Key points"], font="Helvetica-Bold", size=11)
    y -= 12 + 15 + 6
    item(72, y, "•", "Sales grew in every region.")
    item(72, y - 15, "•", "Costs stayed close to plan, with two")
    _lines(canvas, 86, y - 30, ["exceptions noted below."])
    item(90, y - 45, "–", "Travel ran over.")
    item(90, y - 60, "–", "Training ran under.")
    item(72, y - 75, "•", "Hiring finished early.")
    y = _lines(canvas, 72, y - 100, ["The steps taken were these:"])
    for number, text in enumerate(["Reviewed every budget line.", "Agreed the targets.", "Set the next dates."], start=1):
        item(72, y - 6, f"{number}.", text)
        y -= 15
    canvas.showPage()

    furniture(2)
    _lines(canvas, 72, 770, ["Results"], font="Helvetica-Bold", size=16)
    _lines(canvas, 72, 745, ["Output rose in each quarter, as the figure shows."])
    canvas.drawImage(_png((300, 140), (60, 120, 90), (220, 240, 225)), 72, 580, width=300, height=140)
    _lines(canvas, 72, 562, ["Figure 1. Output by quarter."], size=9)
    _lines(canvas, 72, 120, ["The last quarter closed with more orders than any before it, and the"])
    _lines(canvas, 72, 105, ["team carried them into the new year without a pause in the"])
    canvas.showPage()

    furniture(3)
    _lines(canvas, 72, 770, ["work, which the next review will follow."])
    _lines(canvas, 72, 740, ["Next steps"], font="Helvetica-Bold", size=16)
    y = _lines(canvas, 72, 715, ["The plan resumes at step three:"])
    for number, text in enumerate(["Hire two more people.", "Open the second office."], start=3):
        item(72, y - 6, f"{number}.", text)
        y -= 15
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


BUILDERS: dict[str, Callable[[], bytes]] = {
    "text.pdf": text,
    "columns.pdf": columns,
    "table.pdf": table,
    "pictures.pdf": pictures,
    "scanned.pdf": scanned,
    "hybrid.pdf": hybrid,
    "rotated.pdf": rotated,
    "multilingual.pdf": multilingual,
    "form.pdf": form,
    "structure.pdf": structure,
}


def build(name: str) -> bytes:
    return BUILDERS[name]()


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name in BUILDERS:
        (FIXTURES / name).write_bytes(build(name))
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
