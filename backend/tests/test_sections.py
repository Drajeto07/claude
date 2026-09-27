"""Word sections as the model has them (tracker DOCX-015, part 1): a section break
is an element of its own -- how the next section starts, and the page setup of
the section it ends (size, orientation, margins, header and footer distances,
columns, page numbering). The importer makes one per section's end, a Word export
writes each back as its sectPr in the schema's order, and a PDF breaks the page
where the next section starts on a new one, naming the page setup it can't use."""

import io
import zipfile

import pytest
from docx import Document as DocxDocument
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.export.docx_export import build_docx
from app.export.package_check import package_problems
from app.export.pdf_export import build_pdf
from app.fidelity.report import ReportBuilder
from app.main import app
from app.models.document import Element, ElementType
from app.parsers.docx import parse_docx

client = TestClient(app, base_url="https://testserver")
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_W = nsdecls("w")
# CT_SectPr's children, in the schema's order.
_SECT_PR_ORDER = (
    "headerReference footerReference footnotePr endnotePr type pgSz pgMar paperSrc pgBorders lnNumType pgNumType cols "
    "formProt vAlign noEndnote titlePg textDirection bidi rtlGutter docGrid printerSettings"
).split()


def _word_file() -> bytes:
    word = DocxDocument()
    first = word.sections[0]
    first.orientation, first.page_width, first.page_height = WD_ORIENT.LANDSCAPE, first.page_height, first.page_width
    first._sectPr.append(parse_xml(f'<w:pgNumType {_W} w:fmt="lowerRoman" w:start="1"/>'))
    columns = first._sectPr.find(qn("w:cols"))
    columns.set(qn("w:num"), "2")
    word.add_paragraph("A wide section in two columns.")
    last = word.add_section(WD_SECTION.ODD_PAGE)
    last.orientation, last.page_width, last.page_height = WD_ORIENT.PORTRAIT, last.page_height, last.page_width
    for extra in last._sectPr.findall(qn("w:pgNumType")):
        last._sectPr.remove(extra)
    last._sectPr.find(qn("w:cols")).set(qn("w:num"), "1")
    word.add_paragraph("A narrow one, on an odd page.")
    buffer = io.BytesIO()
    word.save(buffer)
    return buffer.getvalue()


def _breaks(document) -> list[Element]:
    return [element for element in document.elements if element.type == ElementType.SECTION_BREAK]


def test_a_section_break_holds_how_the_next_section_starts_and_the_setup_of_the_one_it_ends():
    document = parse_docx(_word_file(), "sections.docx")

    [section] = _breaks(document)
    settings = section.sectionBreak
    assert [element.type for element in document.elements] == [ElementType.PARAGRAPH, ElementType.SECTION_BREAK, ElementType.PARAGRAPH]
    assert settings.start == "oddPage"
    assert (settings.orientation, round(settings.pageWidthMm), round(settings.pageHeightMm)) == ("landscape", 279, 216)
    assert (settings.columns, settings.pageNumberStart, settings.pageNumberFormat) == (2, 1, "lowerRoman")
    assert settings.marginTopCm == 2.54 and settings.headerDistanceCm == 1.27


def test_a_word_export_writes_each_section_back_in_the_schemas_order():
    document = parse_docx(_word_file(), "sections.docx")

    exported = build_docx(document)

    assert package_problems(exported) == []
    with zipfile.ZipFile(io.BytesIO(exported)) as package:
        body = parse_xml(package.read("word/document.xml"))
    sections = list(body.iter(qn("w:sectPr")))
    assert len(sections) == 2
    for sect_pr in sections:
        tags = [child.tag.split("}")[1] for child in sect_pr]
        assert tags == sorted(tags, key=_SECT_PR_ORDER.index), tags
    last = sections[-1].find(qn("w:type"))
    assert last is not None and last.get(qn("w:val")) == "oddPage"  # how the last section starts
    again = parse_docx(exported, "again.docx")
    assert [element.sectionBreak for element in _breaks(again)] == [element.sectionBreak for element in _breaks(document)]


def test_without_page_breaks_sections_run_on():
    document = parse_docx(_word_file(), "sections.docx")

    exported = build_docx(document, include_page_breaks=False)

    with zipfile.ZipFile(io.BytesIO(exported)) as package:
        body = parse_xml(package.read("word/document.xml"))
    starts = [(sect_pr.find(qn("w:type")).get(qn("w:val")) if sect_pr.find(qn("w:type")) is not None else "nextPage") for sect_pr in body.iter(qn("w:sectPr"))]
    assert starts[-1] == "continuous"


def test_a_pdf_gives_each_section_its_own_pages_and_numbers():
    from pypdf import PdfReader

    document = parse_docx(_word_file(), "sections.docx")
    document.settings.showPageNumbers = True
    report = ReportBuilder()

    pages = PdfReader(io.BytesIO(build_pdf(document, report=report))).pages

    sizes = [(float(page.mediabox.width), float(page.mediabox.height)) for page in pages]
    assert len(pages) == 3  # the wide section, a blank page, the narrow one on an odd page
    assert sizes[0][0] > sizes[0][1] and sizes[2][0] < sizes[2][1]
    texts = [page.extract_text() for page in pages]
    assert "A wide section" in texts[0] and "Page i" in texts[0]  # lower-case roman numbering, from 1
    assert "A narrow one" in texts[2] and "Page 3" in texts[2]
    assert "export.pdf.sections" not in {item.feature for item in report.items()}


def test_only_a_section_break_has_section_settings():
    with pytest.raises(ValidationError):
        Element.model_validate({"type": "paragraph", "content": "x", "order": 0, "sectionBreak": {"start": "continuous"}})
    assert Element.model_validate({"type": "section_break", "content": "", "order": 0}).sectionBreak.start == "nextPage"
    with pytest.raises(ValidationError):
        Element.model_validate({"type": "section_break", "content": "", "order": 0, "sectionBreak": {"start": "sideways"}})


def test_a_section_written_anew_names_what_its_original_had(api_db):
    word = DocxDocument()
    word.sections[0].header.paragraphs[0].text = "Chapter one"
    ending = word.add_paragraph("The end of chapter one.")
    word.add_section(WD_SECTION.NEW_PAGE)
    holder = next(p for p in word.element.body.iterchildren(qn("w:p")) if p.find(f"{qn('w:pPr')}/{qn('w:sectPr')}") is not None)
    ending._p.get_or_add_pPr().append(holder.find(f"{qn('w:pPr')}/{qn('w:sectPr')}"))  # the section ends in the text
    word.element.body.remove(holder)
    later = word.sections[-1]
    later.header.is_linked_to_previous = False
    later.header.paragraphs[0].text = "Chapter two"
    word.add_paragraph("Chapter two.")
    buffer = io.BytesIO()
    word.save(buffer)
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "sections@example.com", "password": "long enough password"}).status_code == 201
    document = client.post("/api/v1/documents/upload", files={"file": ("chapters.docx", buffer.getvalue(), _DOCX)}).json()
    elements = document["elements"]
    edited = next(element for element in elements if element["content"] == "The end of chapter one.")
    edited["content"], edited["inline"] = "The end of chapter one, revised.", [{"text": "The end of chapter one, revised.", "marks": []}]
    assert client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements}).status_code == 200

    job = client.post("/api/v1/jobs/export", json={"documentId": document["id"], "format": "docx"}).json()
    items = {item["feature"]: item for item in client.get(f"/api/v1/jobs/{job['id']}").json()["result"]["fidelity"]["items"]}
    client.cookies.clear()

    assert "export.docx.section_lost" not in items  # the section is still there, from its section break
    assert "sections' own headers and footers" in items["export.docx.rewritten_blocks"]["reason"]


def test_a_picture_fits_its_sections_column_and_page_in_a_pdf():
    from PIL import Image as PILImage

    image = io.BytesIO()
    PILImage.new("RGB", (400, 1200), "navy").save(image, format="PNG")  # tall: the page's full width would be too high
    word = DocxDocument()
    first = word.sections[0]
    first.orientation, first.page_width, first.page_height = WD_ORIENT.LANDSCAPE, first.page_height, first.page_width
    first._sectPr.find(qn("w:cols")).set(qn("w:num"), "2")
    word.add_picture(io.BytesIO(image.getvalue()), width=first.page_width - first.left_margin - first.right_margin)
    word.add_section(WD_SECTION.NEW_PAGE)
    word.add_paragraph("After.")
    buffer = io.BytesIO()
    word.save(buffer)

    pdf = build_pdf(parse_docx(buffer.getvalue(), "tall.docx"))  # reportlab refuses a picture bigger than its frame

    assert pdf.startswith(b"%PDF")
