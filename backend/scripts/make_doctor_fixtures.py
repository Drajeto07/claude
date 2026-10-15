"""The labelled defect corpus for Document Doctor v0 (tests/fixtures/doctor/): small Word files, each with planted
defects of a known kind and count -- the ground truth is written here, by construction, not read back from what
the detector finds -- and controls: a clean file (nothing may be proposed), and files Doctor must refuse.

    python -m scripts.make_doctor_fixtures

Writes the .docx files and manifest.json. Deterministic: the same files every time (fixed core properties).
"""

import datetime
import io
import json
import pathlib
import zipfile

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from PIL import Image

OUT = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "doctor"
FIXED = datetime.datetime(2026, 10, 15, 9, 0, 0)

LOREM = [
    "The committee met on Monday and reviewed the quarterly figures in detail.",
    "Revenue rose in every region, and costs stayed within the agreed budget.",
    "The new reporting process will start next month after a short pilot.",
    "Each team lead will send a summary of open questions by Friday.",
    "The next meeting is planned for the first week of the following month.",
]


def new_document() -> Document:
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)
    properties = document.core_properties
    properties.author = "SmartDoc fixtures"
    properties.created = properties.modified = FIXED
    properties.last_modified_by = "SmartDoc fixtures"
    properties.revision = 1
    return document


def text_paragraphs(document: Document, count: int, start: int = 0) -> None:
    for index in range(count):
        document.add_paragraph(LOREM[(start + index) % len(LOREM)])


def save(document: Document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def png(width: int, height: int) -> io.BytesIO:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def with_part(data: bytes, name: str, content: bytes) -> bytes:
    """The package with one more part (a signature, macros): written whole, the other parts as they were."""
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        target.writestr(zipfile.ZipInfo(name, date_time=(2026, 10, 15, 9, 0, 0)), content)
    return buffer.getvalue()


def bookmark(paragraph, name: str, number: int) -> None:
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(number))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(number))
    paragraph._p.append(start)
    paragraph._p.append(end)


def page_field(paragraph, font: str) -> None:
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), " PAGE ")
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), font)
    fonts.set(qn("w:hAnsi"), font)
    properties.append(fonts)
    run.append(properties)
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    field.append(run)
    paragraph._p.append(field)


def wide_table(document: Document, width_cm: float) -> None:
    table = document.add_table(rows=2, cols=3)
    table.autofit = False
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            cell.width = Cm(width_cm / 3)
            cell.text = f"Cell {index + 1}"
    properties = table._tbl.tblPr
    for existing in properties.findall(qn("w:tblW")):
        properties.remove(existing)
    width = OxmlElement("w:tblW")
    width.set(qn("w:w"), str(int(width_cm / 2.54 * 1440)))
    width.set(qn("w:type"), "dxa")
    style = properties.find(qn("w:tblStyle"))
    (style.addnext(width) if style is not None else properties.insert(0, width))
    for column in table._tbl.tblGrid.findall(qn("w:gridCol")):
        column.set(qn("w:w"), str(int(width_cm / 3 / 2.54 * 1440)))


def tracked_insertion(paragraph, words: str) -> None:
    insertion = OxmlElement("w:ins")
    insertion.set(qn("w:id"), "1")
    insertion.set(qn("w:author"), "Reviewer")
    insertion.set(qn("w:date"), "2026-10-15T09:00:00Z")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.set(qn("xml:space"), "preserve")
    text.text = words
    run.append(text)
    insertion.append(run)
    paragraph._p.append(insertion)


def build() -> dict[str, dict]:
    files: dict[str, bytes] = {}
    truth: dict[str, dict] = {}

    # d01: empty paragraphs used as spacing -- 2 + 3 + 1 empties.
    document = new_document()
    text_paragraphs(document, 1)
    for _ in range(2):
        document.add_paragraph("")
    text_paragraphs(document, 1, 1)
    for _ in range(3):
        document.add_paragraph("")
    text_paragraphs(document, 1, 2)
    document.add_paragraph("")
    text_paragraphs(document, 1, 3)
    files["d01-empty-spacing.docx"] = save(document)
    truth["d01-empty-spacing.docx"] = {"repairs": {"empty_paragraphs": 6}, "v0": {"empty_paragraphs": 6}, "refusals": [], "about": "6 empty paragraphs used as spacing"}

    # d02: two paragraphs set in another font than the body's.
    document = new_document()
    text_paragraphs(document, 2)
    for index in range(2):
        document.add_paragraph().add_run(LOREM[2 + index]).font.name = "Comic Sans MS"
    text_paragraphs(document, 2, 4)
    files["d02-mixed-fonts.docx"] = save(document)
    truth["d02-mixed-fonts.docx"] = {"repairs": {"fonts": 2}, "v0": {}, "gaps": {"fonts": "a font set on a whole paragraph is imported as a paragraph rule, which the font fix doesn't clear"}, "refusals": [], "about": "2 paragraphs in Comic Sans MS in an Arial body"}

    # d03: text that repeats its style's font and size (Arial 11) as direct formatting.
    document = new_document()
    text_paragraphs(document, 2)
    for index in range(3):
        run = document.add_paragraph().add_run(LOREM[index])
        run.font.name = "Arial"
        run.font.size = Pt(11)
    files["d03-repeated-formatting.docx"] = save(document)
    truth["d03-repeated-formatting.docx"] = {"repairs": {"duplicated_formatting": 3}, "v0": {}, "gaps": {"duplicated_formatting": "the importer folds formatting equal to the style away, so the editor's model never sees it; the Word file keeps it"}, "refusals": [], "about": "3 paragraphs repeating Arial 11 set by the style"}

    # d04: a table 20 cm wide on a page with 16.51 cm of text width (Letter, 1-inch margins).
    document = new_document()
    text_paragraphs(document, 1)
    wide_table(document, 20)
    text_paragraphs(document, 1, 1)
    files["d04-wide-table.docx"] = save(document)
    truth["d04-wide-table.docx"] = {"repairs": {"wide_table": 1}, "v0": {"wide_table": 1}, "refusals": [], "about": "1 table wider than the text area"}

    # d05: a picture 20 cm wide.
    document = new_document()
    text_paragraphs(document, 1)
    document.add_picture(png(400, 200), width=Cm(20))
    text_paragraphs(document, 1, 1)
    files["d05-wide-picture.docx"] = save(document)
    truth["d05-wide-picture.docx"] = {"repairs": {"wide_picture": 1}, "v0": {"wide_picture": 1}, "refusals": [], "about": "1 picture wider than the text area"}

    # d06: two page breaks in a row (an empty page) and one after all the content.
    document = new_document()
    text_paragraphs(document, 1)
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    text_paragraphs(document, 1, 1)
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    files["d06-page-breaks.docx"] = save(document)
    truth["d06-page-breaks.docx"] = {"repairs": {"page_breaks": 2}, "v0": {"page_breaks": 2}, "refusals": [], "about": "a doubled page break and one after the content"}

    # d07: two empty paragraphs to remove, and one empty paragraph holding a bookmark that must stay.
    document = new_document()
    text_paragraphs(document, 1)
    document.add_paragraph("")
    bookmark(document.add_paragraph(""), "keep_me", 7)
    text_paragraphs(document, 1, 1)
    document.add_paragraph("")
    text_paragraphs(document, 1, 2)
    files["d07-bookmark-in-empty.docx"] = save(document)
    truth["d07-bookmark-in-empty.docx"] = {"repairs": {"empty_paragraphs": 2}, "v0": {"empty_paragraphs": 2}, "refusals": [], "keep": ["bookmark keep_me"], "about": "2 empties to remove; the bookmarked empty paragraph must stay"}

    # d08: one Comic Sans paragraph to repair, one holding a PAGE field in Comic Sans that must be left alone.
    document = new_document()
    text_paragraphs(document, 3)
    document.add_paragraph().add_run(LOREM[3]).font.name = "Comic Sans MS"
    paragraph = document.add_paragraph()
    paragraph.add_run("Page ").font.name = "Comic Sans MS"
    page_field(paragraph, "Comic Sans MS")
    files["d08-field-in-mixed-font.docx"] = save(document)
    truth["d08-field-in-mixed-font.docx"] = {"repairs": {"fonts": 1}, "v0": {}, "gaps": {"fonts": "as d02"}, "refusals": [], "keep": ["field PAGE"], "about": "1 font repair; the paragraph with a field is left for a person"}

    # d09: clean -- nothing to repair (false-positive control).
    document = new_document()
    document.add_heading("Clean report", level=1)
    text_paragraphs(document, 3)
    document.add_heading("Details", level=2)
    text_paragraphs(document, 2, 3)
    files["d09-clean.docx"] = save(document)
    truth["d09-clean.docx"] = {"repairs": {}, "v0": {}, "refusals": [], "about": "no defects: nothing may be proposed"}

    # d10: a signed package (a signature part) -- must be refused.
    document = new_document()
    text_paragraphs(document, 2)
    document.add_paragraph("")
    files["d10-signed.docx"] = with_part(save(document), "_xmlsignatures/sig1.xml", b"<Signature xmlns='http://www.w3.org/2000/09/xmldsig#'/>")
    truth["d10-signed.docx"] = {"repairs": {}, "v0": {}, "refusals": ["signed"], "about": "digitally signed: any change breaks the signature"}

    # d11: macros -- must be refused.
    document = new_document()
    text_paragraphs(document, 2)
    document.add_paragraph("")
    files["d11-macros.docx"] = with_part(save(document), "word/vbaProject.bin", b"\x00" * 64)
    truth["d11-macros.docx"] = {"repairs": {}, "v0": {}, "refusals": ["macros"], "about": "contains macros"}

    # d12: a tracked insertion waiting for a decision -- must be refused.
    document = new_document()
    text_paragraphs(document, 1)
    tracked_insertion(document.add_paragraph("Agreed: "), "the budget is approved.")
    document.add_paragraph("")
    files["d12-tracked-changes.docx"] = save(document)
    truth["d12-tracked-changes.docx"] = {"repairs": {}, "v0": {}, "refusals": ["tracked_changes"], "about": "tracked changes still to be decided"}

    # d13: a realistic mix -- a heading, spacing by empties, one off-font paragraph, a wide table.
    document = new_document()
    document.add_heading("Quarterly summary", level=1)
    text_paragraphs(document, 1)
    document.add_paragraph("")
    document.add_paragraph("")
    document.add_paragraph().add_run(LOREM[1]).font.name = "Times New Roman"
    text_paragraphs(document, 1, 2)
    wide_table(document, 19)
    document.add_paragraph("")
    text_paragraphs(document, 1, 3)
    files["d13-mixed-report.docx"] = save(document)
    truth["d13-mixed-report.docx"] = {"repairs": {"empty_paragraphs": 3, "fonts": 1, "wide_table": 1}, "v0": {"empty_paragraphs": 2, "wide_table": 1}, "gaps": {"empty_paragraphs": "the one next to the table is left on purpose (Word needs it)", "fonts": "as d02"}, "refusals": [], "about": "3 empties, 1 off-font paragraph, 1 wide table"}

    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (OUT / name).write_bytes(data)
    (OUT / "manifest.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return truth


if __name__ == "__main__":
    for name, entry in build().items():
        print(f"{name}: {entry['about']}")
