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
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX, WD_UNDERLINE
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
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
    second = doc.add_paragraph("A second, ordinary paragraph.")
    second.add_run(" A note only its author sees.").font.hidden = True  # Word's hidden text (DOCX-025)
    third = doc.add_paragraph("Also ")  # character formatting beyond plain lines (DOCX-013)
    third.add_run("double underlined").font.underline = WD_UNDERLINE.DOUBLE
    third.add_run(", ")
    third.add_run("wavy").font.underline = WD_UNDERLINE.WAVY
    third.add_run(", ")
    third.add_run("struck twice").font.double_strike = True
    third.add_run(", ")
    third.add_run("in capitals").font.all_caps = True
    third.add_run(", ")
    third.add_run("Small Capitals").font.small_caps = True
    third.add_run(", ")
    third.add_run("spaced")._r.get_or_add_rPr().append(parse_xml(f'<w:spacing {_NS} w:val="40"/>'))
    third.add_run(" and ")
    third.add_run("raised")._r.get_or_add_rPr().append(parse_xml(f'<w:position {_NS} w:val="6"/>'))
    third.add_run(", ")
    third.add_run("на български")._r.get_or_add_rPr().append(parse_xml(f'<w:lang {_NS} w:val="bg-BG"/>'))
    third.add_run(".")
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


def kept_blocks() -> DocxDocument:
    """What the app doesn't hold, in blocks a Word export writes as they are while
    they're unchanged (DOCX-028): a field's code, a content control, a double
    underline, a bookmark, a landscape section before a portrait one."""
    doc = _new()
    first = doc.sections[0]
    first.orientation, first.page_width, first.page_height = WD_ORIENT.LANDSCAPE, first.page_height, first.page_width
    doc.add_heading("Kept as written", level=1)
    author = doc.add_paragraph("Written by ")
    for run in (
        '<w:fldChar w:fldCharType="begin"/>',
        '<w:instrText xml:space="preserve"> AUTHOR </w:instrText>',
        '<w:fldChar w:fldCharType="separate"/>',
        "<w:t>SmartDoc golden fixtures</w:t>",
        '<w:fldChar w:fldCharType="end"/>',
    ):
        author._p.append(parse_xml(f"<w:r {_NS}>{run}</w:r>"))
    _append_xml(
        doc,
        f'<w:sdt {_NS}><w:sdtPr><w:alias w:val="Status"/><w:tag w:val="status"/></w:sdtPr>'
        "<w:sdtContent><w:p><w:r><w:t>Draft for review</w:t></w:r></w:p></w:sdtContent></w:sdt>",
    )
    marked = doc.add_paragraph("Underlined ")
    marked._p.append(parse_xml(f'<w:r {_NS}><w:rPr><w:u w:val="double"/></w:rPr><w:t>twice</w:t></w:r>'))
    target = doc.add_paragraph()
    target._p.append(parse_xml(f'<w:bookmarkStart {_NS} w:id="7" w:name="Results"/>'))
    target._p.append(parse_xml(f"<w:r {_NS}><w:t>The results section.</w:t></w:r>"))
    target._p.append(parse_xml(f'<w:bookmarkEnd {_NS} w:id="7"/>'))
    last = doc.add_section(WD_SECTION.NEW_PAGE)  # the landscape section ends here
    last.orientation, last.page_width, last.page_height = WD_ORIENT.PORTRAIT, last.page_height, last.page_width
    doc.add_paragraph("Edit this line.")
    return doc


def _page_number(paragraph) -> None:
    """ "Page {PAGE}": the page's number, as a simple field."""
    paragraph.add_run("Page ")
    paragraph._p.append(parse_xml(f'<w:fldSimple {_NS} w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'))


def _number_pages(section, fmt: str | None, start: int | None) -> None:
    """A section's page numbering: its style and the number it restarts at (neither: it runs on)."""
    sect_pr = section._sectPr
    for old in sect_pr.findall(qn("w:pgNumType")):
        sect_pr.remove(old)
    if fmt or start:
        attrs = (f' w:fmt="{fmt}"' if fmt else "") + (f' w:start="{start}"' if start else "")
        sect_pr.find(qn("w:cols")).addprevious(parse_xml(f"<w:pgNumType {_NS}{attrs}/>"))


def section_headers() -> DocxDocument:
    """Headers, footers and page numbers by section (DOCX-015): front matter numbered
    i, ii.. whose cover has an empty header of its own, a chapter with its own header
    numbered from 1, and a last section linked to the one before for both. Each
    section is set up before the next is added: python-docx's add_section hands the
    old sectPr on to the new last section (without its header references)."""
    doc = _new()
    front = doc.sections[0]
    front.different_first_page_header_footer = True
    front.first_page_header.is_linked_to_previous = False  # the cover's own header, empty
    front.header.paragraphs[0].text = "Front matter"
    _page_number(front.footer.paragraphs[0])
    _number_pages(front, "lowerRoman", 1)
    doc.add_paragraph("The cover.")
    doc.add_page_break()
    doc.add_paragraph("The contents.")

    chapter = doc.add_section(WD_SECTION.NEW_PAGE)
    chapter.different_first_page_header_footer = False
    chapter.header.is_linked_to_previous = False
    chapter.header.paragraphs[0].text = "Chapter one"
    _number_pages(chapter, None, 1)
    doc.add_paragraph("Chapter one begins.")

    last = doc.add_section(WD_SECTION.NEW_PAGE)
    _number_pages(last, None, None)
    doc.add_paragraph("It goes on in a section of its own, under the same header.")
    return doc


def _list_definition(doc: DocxDocument, abstract_id: int, levels: list[tuple[str, str]], *, step: int = 720) -> None:
    """A multi-level list definition: (numFmt, lvlText) per level, each indented `step` more."""
    xml = "".join(
        f'<w:lvl w:ilvl="{ilvl}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>'
        f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{step * (ilvl + 1)}" w:hanging="360"/></w:pPr></w:lvl>'
        for ilvl, (fmt, text) in enumerate(levels)
    )
    numbering = doc.part.numbering_part.element
    abstract = parse_xml(f'<w:abstractNum {_NS} w:abstractNumId="{abstract_id}"><w:multiLevelType w:val="multilevel"/>{xml}</w:abstractNum>')
    numbering.find(qn("w:num")).addprevious(abstract)


def _list_instance(doc: DocxDocument, num_id: int, abstract_id: int, *, restart: bool = False) -> None:
    override = '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride>' if restart else ""
    doc.part.numbering_part.element.append(parse_xml(f'<w:num {_NS} w:numId="{num_id}"><w:abstractNumId w:val="{abstract_id}"/>{override}</w:num>'))


def _numbered(doc: DocxDocument, text: str, num_id: int, level: int = 0) -> None:
    paragraph = doc.add_paragraph(text, style="List Paragraph")
    paragraph._p.get_or_add_pPr().append(parse_xml(f'<w:numPr {_NS}><w:ilvl w:val="{level}"/><w:numId w:val="{num_id}"/></w:numPr>'))


def numbering() -> DocxDocument:
    """Lists as Word numbers them (DOCX-016, brief §25): one, two, three and five levels
    deep, labels of their own ("Чл. 1.", "а)"), a list Word restarts, and one that goes on
    across a section break. Each list has a definition of its own but the restarted one,
    which shares the list before it and starts again at 1."""
    doc = _new()
    _list_definition(doc, 300, [("decimal", "%1)")])
    _list_definition(doc, 301, [("upperLetter", "%1."), ("decimal", "%2.")])
    _list_definition(doc, 302, [("decimal", "%1."), ("decimal", "%1.%2."), ("decimal", "%1.%2.%3.")])
    _list_definition(doc, 303, [("decimal", "%1."), ("decimal", "%1.%2."), ("decimal", "%1.%2.%3."), ("decimal", "%1.%2.%3.%4."), ("decimal", "%1.%2.%3.%4.%5.")], step=360)
    _list_definition(doc, 304, [("decimal", "Чл. %1."), ("russianLower", "%2)")])
    _list_definition(doc, 305, [("decimal", "%1)")])
    _list_definition(doc, 306, [("decimalZero", "%1.")])
    for num_id, abstract_id in ((300, 300), (301, 301), (302, 302), (303, 303), (304, 304), (305, 305), (306, 306)):
        _list_instance(doc, num_id, abstract_id)
    _list_instance(doc, 307, 305, restart=True)

    doc.add_paragraph("One level:")
    for text in ("Apples", "Pears"):
        _numbered(doc, text, 300)
    doc.add_paragraph("Two levels:")
    for text, level in (("Fruit", 0), ("Apples", 1), ("Vegetables", 0), ("Leeks", 1)):
        _numbered(doc, text, 301, level)
    doc.add_paragraph("Three levels:")
    for text, level in (("Scope", 0), ("Terms", 1), ("Defined terms", 2), ("Other terms", 1)):
        _numbered(doc, text, 302, level)
    doc.add_paragraph("Five levels:")
    for level in range(5):
        _numbered(doc, f"Level {level + 1}", 303, level)
    doc.add_paragraph("Labels of their own:")
    for text, level in (("Предмет", 0), ("първа точка", 1), ("втора точка", 1), ("Срок", 0)):
        _numbered(doc, text, 304, level)
    doc.add_paragraph("A list and one Word restarts:")
    for text in ("First", "Second"):
        _numbered(doc, text, 305)
    doc.add_paragraph("Numbered again from one:")
    for text in ("First again", "Second again"):
        _numbered(doc, text, 307)
    doc.add_paragraph("Across a section break:")
    for text in ("Before the break", "Still before it"):
        _numbered(doc, text, 306)
    doc.add_section(WD_SECTION.NEW_PAGE)
    for text in ("After the break", "Still after it"):
        _numbered(doc, text, 306)
    return doc


def table_engine() -> DocxDocument:
    """Tables as Word lays them out (DOCX-017, brief §26): a styled table whose style
    draws its first row, with its own column widths, an exact row height and a cell
    centred up and down with a border of its own; a table whose header row repeats on
    each page; and a cell holding paragraphs, a list and a table of its own."""
    doc = _new()
    doc.add_heading("Prices", level=2)
    styled = doc.add_table(rows=3, cols=3)
    styled.style = doc.styles["Light List Accent 1"]
    for column, twips in zip(styled._tbl.tblGrid.findall(qn("w:gridCol")), (2835, 1701, 1701)):  # 5, 3 and 3 cm
        column.set(qn("w:w"), str(twips))
    for (row, column), text in {
        (0, 0): "Item", (0, 1): "Quarter", (0, 2): "Price",
        (1, 0): "Paper", (1, 1): "Q1", (1, 2): "12.50",
        (2, 0): "Ink", (2, 1): "Q2", (2, 2): "3.20",
    }.items():
        styled.cell(row, column).text = text
    styled.rows[1]._tr.get_or_add_trPr().append(parse_xml(f'<w:trHeight {_NS} w:val="567" w:hRule="exact"/>'))
    tc_pr = styled.cell(1, 2)._tc.get_or_add_tcPr()
    tc_pr.append(parse_xml(f'<w:tcBorders {_NS}><w:bottom w:val="double" w:sz="12" w:color="C00000"/></w:tcBorders>'))
    tc_pr.append(parse_xml(f'<w:vAlign {_NS} w:val="center"/>'))
    styled.cell(1, 2).paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

    doc.add_paragraph("A table whose header row repeats:")
    repeated = doc.add_table(rows=3, cols=2)
    repeated.style = doc.styles["Table Grid"]
    repeated.rows[0]._tr.get_or_add_trPr().append(parse_xml(f"<w:tblHeader {_NS}/>"))
    for (row, column), text in {(0, 0): "Name", (0, 1): "Role", (1, 0): "Ana", (1, 1): "Editor", (2, 0): "Boris", (2, 1): "Author"}.items():
        repeated.cell(row, column).text = text

    doc.add_paragraph("A cell holding more:")
    busy = doc.add_table(rows=1, cols=2)
    busy.style = doc.styles["Table Grid"]
    cell = busy.cell(0, 0)
    cell.paragraphs[0].text = "Two paragraphs,"
    cell.add_paragraph("a list:")
    for text in ("apples", "pears"):
        cell.add_paragraph(text, style="List Bullet")
    inner = cell.add_table(rows=1, cols=2)
    inner.cell(0, 0).text, inner.cell(0, 1).text = "and a table", "of its own"
    busy.cell(0, 1).text = "One line."
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
    "13-kept-blocks.docx": kept_blocks,
    "14-section-headers.docx": section_headers,
    "15-numbering.docx": numbering,
    "16-table-engine.docx": table_engine,
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
