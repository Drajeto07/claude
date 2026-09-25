"""Builds the golden Word documents in tests/fixtures/documents/ (корекции.docx
§44): one per feature the importer and the exporter must carry through, and
one with everything together. tests/test_golden_documents.py imports each,
formats it, exports it, imports the export again and compares.

Built with python-docx, plus raw XML where it has no API (links, fields,
shading, footnotes, checkboxes). Document properties are fixed, so a rebuild
changes nothing but the ZIP's timestamps.

    python -m scripts.make_golden_documents
"""

import io
from datetime import datetime, timezone
from pathlib import Path

from docx import Document as DocxDocument
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Cm, Inches, Pt, RGBColor
from PIL import Image as PILImage

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "documents"
_NS = nsdecls("w", "r")
_FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _png(color: str, size: tuple[int, int] = (120, 60)) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _new() -> DocxDocument:
    doc = DocxDocument()
    core = doc.core_properties
    core.author = core.last_modified_by = "SmartDoc golden fixtures"
    core.created = core.modified = _FIXED
    core.revision = 1
    return doc


def _append_xml(doc: DocxDocument, xml: str) -> None:
    body = doc.element.body
    body.insert(len(body) - 1, parse_xml(xml))  # before the final sectPr


def _link(doc: DocxDocument, paragraph, text: str, url: str) -> None:
    rel = doc.part.relate_to(url, RT.HYPERLINK, is_external=True)
    paragraph._p.append(parse_xml(f'<w:hyperlink {_NS} r:id="{rel}"><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:hyperlink>'))


def _shade(cell, fill: str) -> None:
    cell._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {_NS} w:val="clear" w:color="auto" w:fill="{fill}"/>'))


def _page_fields(paragraph) -> None:
    """ "Page {PAGE} of {NUMPAGES}": one simple field and one complex field, as Word writes both."""
    paragraph.add_run("Page ")
    paragraph._p.append(parse_xml(f'<w:fldSimple {_NS} w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'))
    paragraph.add_run(" of ")
    for xml in (
        f'<w:r {_NS}><w:fldChar w:fldCharType="begin"/></w:r>',
        f'<w:r {_NS}><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r>',
        f'<w:r {_NS}><w:fldChar w:fldCharType="separate"/></w:r>',
        f"<w:r {_NS}><w:t>3</w:t></w:r>",
        f'<w:r {_NS}><w:fldChar w:fldCharType="end"/></w:r>',
    ):
        paragraph._p.append(parse_xml(xml))


def _footnote(doc: DocxDocument, paragraph, text: str) -> None:
    notes = (
        f'<w:footnotes {_NS}><w:footnote w:type="separator" w:id="-1"><w:p/></w:footnote>'
        f'<w:footnote w:id="1"><w:p><w:r><w:footnoteRef/></w:r><w:r><w:t xml:space="preserve"> {text}</w:t></w:r></w:p></w:footnote></w:footnotes>'
    )
    part = Part(
        PackURI("/word/footnotes.xml"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
        notes.encode(),
        doc.part.package,
    )
    doc.part.relate_to(part, RT.FOOTNOTES)
    paragraph._p.append(parse_xml(f'<w:r {_NS}><w:footnoteReference w:id="1"/></w:r>'))


def _prices_table(doc: DocxDocument) -> None:
    """3 x 3: a shaded header row, a cell spanning two columns, one spanning two rows."""
    table = doc.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, ("Item", "Quarter", "Price")):
        cell.text = text
        _shade(cell, "D9EAF7")
    table.cell(1, 0).text = "Paper"
    table.cell(1, 1).text = "Q1"
    table.cell(1, 2).merge(table.cell(2, 2)).text = "12.50"
    table.cell(2, 0).merge(table.cell(2, 1)).text = "Ink, all quarters"
    for row in table.rows:
        row.cells[0].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER


def simple() -> DocxDocument:
    doc = _new()
    doc.add_heading("Annual Report", level=1)
    doc.add_paragraph("This report summarises the year.")
    doc.add_paragraph("Revenue grew in every quarter.")
    doc.add_paragraph("Отчетът обобщава годината и резултатите от нея.")
    return doc


def rich_text() -> DocxDocument:
    doc = _new()
    paragraph = doc.add_paragraph("Plain, ")
    paragraph.add_run("bold").bold = True
    paragraph.add_run(", ")
    paragraph.add_run("italic").italic = True
    paragraph.add_run(", ")
    paragraph.add_run("underlined").underline = True
    paragraph.add_run(", ")
    paragraph.add_run("struck").font.strike = True
    paragraph.add_run(", E=mc")
    paragraph.add_run("2").font.superscript = True
    paragraph.add_run(", H")
    paragraph.add_run("2").font.subscript = True
    paragraph.add_run("O, ")
    red = paragraph.add_run("red")
    red.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    paragraph.add_run(", ")
    paragraph.add_run("highlighted").font.highlight_color = WD_COLOR_INDEX.YELLOW
    paragraph.add_run(", ")
    serif = paragraph.add_run("Georgia")
    serif.font.name = "Georgia"
    paragraph.add_run(" and ")
    paragraph.add_run("large").font.size = Pt(18)
    paragraph.add_run(".")
    doc.add_paragraph("A second, ordinary paragraph.")
    return doc


def tables() -> DocxDocument:
    doc = _new()
    doc.add_heading("Prices", level=2)
    _prices_table(doc)
    doc.add_paragraph("Prices include tax.")
    return doc


def images() -> DocxDocument:
    doc = _new()
    doc.add_paragraph("Before the pictures.")
    doc.add_picture(io.BytesIO(_png("blue")), width=Cm(8))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("Between the pictures.")
    doc.add_picture(io.BytesIO(_png("green", (60, 60))), width=Inches(1))
    doc.add_paragraph("After the pictures.")
    return doc


def links() -> DocxDocument:
    doc = _new()
    paragraph = doc.add_paragraph("Read ")
    _link(doc, paragraph, "the documentation", "https://example.com/docs")
    paragraph.add_run(" or ")
    _link(doc, paragraph, "write to us", "mailto:team@example.org")
    paragraph.add_run(".")
    doc.add_paragraph("Plain addresses become links too: www.example.net.")
    _append_xml(doc, f'<w:p {_NS}><w:bookmarkStart w:id="0" w:name="Results"/><w:r><w:t>Results</w:t></w:r><w:bookmarkEnd w:id="0"/></w:p>')
    _append_xml(doc, f'<w:p {_NS}><w:r><w:t xml:space="preserve">Jump to </w:t></w:r><w:hyperlink w:anchor="Results"><w:r><w:t>the results</w:t></w:r></w:hyperlink></w:p>')
    return doc


def lists() -> DocxDocument:
    doc = _new()
    doc.add_paragraph("Shopping", style="Heading 2")
    for text, style in (("Fruit", "List Bullet"), ("Apples", "List Bullet 2"), ("Green apples", "List Bullet 3"), ("Bread", "List Bullet")):
        doc.add_paragraph(text, style=style)
    doc.add_paragraph("Steps", style="Heading 2")
    for text, style in (("Preheat the oven", "List Number"), ("Mix", "List Number"), ("Flour first", "List Number 2"), ("Bake", "List Number")):
        doc.add_paragraph(text, style=style)
    doc.add_paragraph("To do", style="Heading 2")
    for text in ("☐ Write the report", "☑ Book the room"):
        doc.add_paragraph(text, style="List Bullet")
    return doc


def headings() -> DocxDocument:
    doc = _new()
    for level in range(1, 7):
        doc.add_heading(f"Heading level {level}", level=level)
        doc.add_paragraph(f"Text under heading {level}.")
    return doc


def captions() -> DocxDocument:
    doc = _new()
    doc.add_picture(io.BytesIO(_png("blue")), width=Cm(6))
    doc.add_paragraph("Figure 1: The blue box.", style="Caption")
    doc.add_paragraph("Table 1. Quarterly prices")
    _prices_table(doc)
    doc.add_paragraph("Figure 2 is discussed later, but this is ordinary text.")
    return doc


def sections() -> DocxDocument:
    doc = _new()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Inches(11), Inches(8.5)  # US Letter, turned
    section.left_margin, section.right_margin = Cm(2), Cm(2)
    section.top_margin, section.bottom_margin = Cm(2.5), Cm(2.5)
    doc.add_heading("A wide page", level=1)
    doc.add_paragraph("This document is set on US Letter paper, in landscape, with its own margins.")
    return doc


def header_footer() -> DocxDocument:
    doc = _new()
    section = doc.sections[0]
    section.header.paragraphs[0].text = "Quarterly report"
    _page_fields(section.footer.paragraphs[0])
    doc.add_paragraph("The body of the report.")
    return doc


def page_breaks() -> DocxDocument:
    doc = _new()
    doc.add_paragraph("Page one.")
    doc.add_page_break()
    doc.add_paragraph("Page two.")
    doc.add_paragraph("Page three starts here.").paragraph_format.page_break_before = True
    _append_xml(doc, f'<w:p {_NS}><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="auto"/></w:pBdr></w:pPr></w:p>')
    doc.add_paragraph("After the rule.")
    return doc


def complex_document() -> DocxDocument:
    doc = _new()
    doc.styles["Normal"].font.name = "Calibri"
    section = doc.sections[0]
    section.header.paragraphs[0].text = "SmartDoc — golden document"
    _page_fields(section.footer.paragraphs[0])
    doc.add_heading("Проектен отчет", level=1)
    intro = doc.add_paragraph("A report with ")
    intro.add_run("bold").bold = True
    intro.add_run(" and ")
    intro.add_run("italic").italic = True
    intro.add_run(" words, a ")
    _link(doc, intro, "link", "https://example.com/report")
    intro.add_run(" and a note")
    _footnote(doc, intro, "Sources are listed at the end.")
    intro.add_run(".")
    doc.add_heading("Plan", level=2)
    for text, style in (("Research", "List Number"), ("Interviews", "List Number 2"), ("Write-up", "List Number")):
        doc.add_paragraph(text, style=style)
    doc.add_paragraph("Quality is never an accident.", style="Quote")
    code = doc.add_paragraph().add_run("total = sum(prices)")
    code.font.name = "Courier New"
    doc.add_paragraph("Table 1. Prices")
    _prices_table(doc)
    doc.add_picture(io.BytesIO(_png("purple")), width=Cm(5))
    doc.add_paragraph("Figure 1: A purple square.", style="Caption")
    doc.add_page_break()
    doc.add_heading("Резултати", level=2)
    doc.add_paragraph("Всички цели са изпълнени навреме.")
    return doc


BUILDERS = {
    "01-simple.docx": simple,
    "02-rich-text.docx": rich_text,
    "03-tables.docx": tables,
    "04-images.docx": images,
    "05-links.docx": links,
    "06-lists.docx": lists,
    "07-headings.docx": headings,
    "08-caption.docx": captions,
    "09-sections.docx": sections,
    "10-header-footer.docx": header_footer,
    "11-page-breaks.docx": page_breaks,
    "12-complex.docx": complex_document,
}


def build(name: str) -> bytes:
    buffer = io.BytesIO()
    BUILDERS[name]().save(buffer)
    return buffer.getvalue()


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name in BUILDERS:
        (FIXTURES / name).write_bytes(build(name))
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
