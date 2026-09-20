import io

import pytest
from docx import Document as DocxDocument
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.models.document import ElementType, MarkType
from app.parsers.docx import DocxParseError, parse_docx


def _add_num_pr(paragraph, num_id: int, ilvl: int = 0) -> None:
    """python-docx's `style="List Bullet"` alone does not add the per-paragraph
    `w:numPr` real Word writes when a user actually applies bullets/numbering
    (the built-in style only carries numbering via the style definition) --
    inject it directly so the fixture matches what a real .docx contains."""
    p_pr = paragraph._p.get_or_add_pPr()
    num_pr = OxmlElement("w:numPr")
    ilvl_el = OxmlElement("w:ilvl")
    ilvl_el.set(qn("w:val"), str(ilvl))
    num_id_el = OxmlElement("w:numId")
    num_id_el.set(qn("w:val"), str(num_id))
    num_pr.append(ilvl_el)
    num_pr.append(num_id_el)
    p_pr.append(num_pr)


def _save_bytes(doc: DocxDocument) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_heading_styles_map_to_heading_levels():
    doc = DocxDocument()
    doc.add_heading("Main Title", level=1)
    doc.add_heading("Subsection", level=2)

    document = parse_docx(_save_bytes(doc), "test.docx")

    headings = [e for e in document.elements if e.type == ElementType.HEADING]
    assert [(h.content, h.level) for h in headings] == [("Main Title", 1), ("Subsection", 2)]
    assert document.metadata.title == "Main Title"


def test_bold_italic_strike_marks_are_captured():
    doc = DocxDocument()
    paragraph = doc.add_paragraph()
    bold_run = paragraph.add_run("bold")
    bold_run.bold = True
    paragraph.add_run(" plain ")
    italic_run = paragraph.add_run("italic")
    italic_run.italic = True

    document = parse_docx(_save_bytes(doc), "test.docx")

    paragraph_element = document.elements[0]
    marks_by_text = {run.text: {m.type for m in run.marks} for run in paragraph_element.inline}
    assert MarkType.BOLD in marks_by_text["bold"]
    assert marks_by_text[" plain "] == set()
    assert MarkType.ITALIC in marks_by_text["italic"]


def test_consecutive_bulleted_paragraphs_group_into_one_list():
    doc = DocxDocument()
    for text in ("First", "Second", "Third"):
        p = doc.add_paragraph(text, style="List Bullet")
        _add_num_pr(p, num_id=1)

    document = parse_docx(_save_bytes(doc), "test.docx")

    lists = [e for e in document.elements if e.type == ElementType.LIST]
    assert len(lists) == 1
    assert lists[0].ordered is False
    assert [item.inline[0].text for item in lists[0].listItems] == ["First", "Second", "Third"]


def test_numbered_list_is_marked_ordered():
    doc = DocxDocument()
    for text in ("Step one", "Step two"):
        p = doc.add_paragraph(text, style="List Number")
        _add_num_pr(p, num_id=2)

    document = parse_docx(_save_bytes(doc), "test.docx")

    lists = [e for e in document.elements if e.type == ElementType.LIST]
    assert lists[0].ordered is True


def test_different_num_ids_produce_separate_lists():
    doc = DocxDocument()
    p1 = doc.add_paragraph("List A item", style="List Bullet")
    _add_num_pr(p1, num_id=1)
    p2 = doc.add_paragraph("List B item", style="List Bullet")
    _add_num_pr(p2, num_id=2)

    document = parse_docx(_save_bytes(doc), "test.docx")

    lists = [e for e in document.elements if e.type == ElementType.LIST]
    assert len(lists) == 2


def test_nested_list_level_from_ilvl():
    doc = DocxDocument()
    p1 = doc.add_paragraph("Top level", style="List Bullet")
    _add_num_pr(p1, num_id=1, ilvl=0)
    p2 = doc.add_paragraph("Nested", style="List Bullet")
    _add_num_pr(p2, num_id=1, ilvl=1)

    document = parse_docx(_save_bytes(doc), "test.docx")

    lists = [e for e in document.elements if e.type == ElementType.LIST]
    assert [item.level for item in lists[0].listItems] == [0, 1]


def test_table_rows_and_cells_are_extracted():
    doc = DocxDocument()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Name"
    table.cell(0, 1).text = "Price"
    table.cell(1, 0).text = "Widget"
    table.cell(1, 1).text = "9.99"

    document = parse_docx(_save_bytes(doc), "test.docx")

    tables = [e for e in document.elements if e.type == ElementType.TABLE]
    assert len(tables) == 1
    rows = tables[0].table.rows
    assert [c.inline[0].text if c.inline else "" for c in rows[0].cells] == ["Name", "Price"]
    assert [c.inline[0].text if c.inline else "" for c in rows[1].cells] == ["Widget", "9.99"]
    assert rows[0].cells[0].header is True
    assert rows[1].cells[0].header is False


def test_invalid_docx_bytes_raise_docx_parse_error():
    with pytest.raises(DocxParseError):
        parse_docx(b"not actually a docx file", "bad.docx")


def test_all_elements_have_full_confidence():
    doc = DocxDocument()
    doc.add_heading("Title", level=1)
    doc.add_paragraph("Some text.")

    document = parse_docx(_save_bytes(doc), "test.docx")

    assert all(e.confidence == 1.0 for e in document.elements)
