import io

from docx import Document as DocxDocument

from app.export.docx_export import build_docx
from app.formatting.engine import apply_formatting
from app.formatting.templates import BUILTIN_TEMPLATES
from app.models.document import (
    Document,
    DocumentMetadata,
    DocumentSettings,
    Element,
    ElementType,
    ImageContent,
    InlineRun,
    ListItem,
    Mark,
    MarkType,
    TableCell,
    TableContent,
    TableRow,
)

# A well-known minimal valid 1x1 transparent PNG, base64-encoded.
_MINIMAL_PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="


def sample_document() -> Document:
    """One of every element type, then a real template applied -- exercises
    the same document.resolvedStyles path build_docx() reads from."""
    elements = [
        Element(type=ElementType.HEADING, content="Export Test", inline=[InlineRun(text="Export Test")], level=1, order=0),
        Element(
            type=ElementType.PARAGRAPH,
            content="Bold and italic text.",
            inline=[
                InlineRun(text="Bold", marks=[Mark(type=MarkType.BOLD)]),
                InlineRun(text=" and italic", marks=[Mark(type=MarkType.ITALIC)]),
                InlineRun(text=" text."),
            ],
            order=1,
        ),
        Element(
            type=ElementType.LIST,
            content="First item\nSecond item",
            listItems=[
                ListItem(inline=[InlineRun(text="First item")], level=0),
                ListItem(inline=[InlineRun(text="Second item")], level=0),
            ],
            ordered=False,
            order=2,
        ),
        Element(
            type=ElementType.TABLE,
            content="Header\nCell",
            table=TableContent(
                rows=[
                    TableRow(cells=[TableCell(inline=[InlineRun(text="Header")], header=True)]),
                    TableRow(cells=[TableCell(inline=[InlineRun(text="Cell")], header=False)]),
                ],
                hasHeaderRow=True,
            ),
            order=3,
        ),
        Element(
            type=ElementType.IMAGE,
            content="",
            image=ImageContent(src=f"data:image/png;base64,{_MINIMAL_PNG_BASE64}"),
            order=4,
        ),
        Element(type=ElementType.CODE_BLOCK, content="print('hi')", language="python", order=5),
    ]
    document = Document(metadata=DocumentMetadata(title="Export Test Doc"), elements=elements)
    template = BUILTIN_TEMPLATES["academic-default"]
    apply_formatting(document, template_id=template.id, template_rules=template.rules, instruction_rules=[])
    return document


def test_build_docx_round_trip():
    document = sample_document()

    readback = DocxDocument(io.BytesIO(build_docx(document)))

    paragraphs = [p for p in readback.paragraphs if p.text.strip()]
    assert paragraphs[0].text == "Export Test"
    assert paragraphs[0].style.name == "Heading 1"

    bold_paragraph = next(p for p in paragraphs if "Bold" in p.text)
    assert any(run.bold for run in bold_paragraph.runs if run.text.strip() == "Bold")

    list_paragraphs = [p for p in paragraphs if p.style and p.style.name == "List Bullet"]
    assert [p.text for p in list_paragraphs] == ["First item", "Second item"]

    assert len(readback.tables) == 1
    table = readback.tables[0]
    assert table.cell(0, 0).text == "Header"
    assert table.cell(1, 0).text == "Cell"

    assert len(readback.inline_shapes) == 1

    code_paragraph = next(p for p in paragraphs if "print" in p.text)
    assert code_paragraph.runs[0].font.name == "Courier New"

    # academic-default sets margins 2/2/3/2 cm (see formatting/templates.py).
    section = readback.sections[0]
    assert round(section.left_margin.cm, 1) == 3.0
    assert round(section.top_margin.cm, 1) == 2.0


def test_build_docx_handles_empty_document():
    document = Document(metadata=DocumentMetadata(title="Empty"), elements=[])

    readback = DocxDocument(io.BytesIO(build_docx(document)))

    assert readback.paragraphs == [] or all(not p.text.strip() for p in readback.paragraphs)


def test_build_docx_page_break_is_a_real_break_not_an_empty_paragraph():
    document = Document(
        metadata=DocumentMetadata(title="Page Break Test"),
        elements=[
            Element(type=ElementType.PARAGRAPH, content="Before", inline=[InlineRun(text="Before")], order=0),
            Element(type=ElementType.PAGE_BREAK, content="", order=1),
            Element(type=ElementType.PARAGRAPH, content="After", inline=[InlineRun(text="After")], order=2),
        ],
    )

    readback = DocxDocument(io.BytesIO(build_docx(document)))

    xml = readback.element.xml
    assert 'w:type="page"' in xml


def _document_with_header_footer_and_page_numbers() -> Document:
    return Document(
        metadata=DocumentMetadata(title="Options Test"),
        settings=DocumentSettings(header="My Header", footer="My Footer", showPageNumbers=True),
        elements=[
            Element(type=ElementType.PARAGRAPH, content="Before", inline=[InlineRun(text="Before")], order=0),
            Element(type=ElementType.PAGE_BREAK, content="", order=1),
            Element(type=ElementType.PARAGRAPH, content="After", inline=[InlineRun(text="After")], order=2),
        ],
    )


def test_build_docx_defaults_include_everything():
    document = _document_with_header_footer_and_page_numbers()

    readback = DocxDocument(io.BytesIO(build_docx(document)))

    assert readback.sections[0].header.paragraphs[0].text == "My Header"
    assert readback.sections[0].footer.paragraphs[0].text == "My Footer"
    assert 'w:type="page"' in readback.element.xml
    assert "PAGE" in readback.sections[0].footer._element.xml  # the page-number field code


def test_build_docx_can_omit_page_breaks():
    document = _document_with_header_footer_and_page_numbers()

    readback = DocxDocument(io.BytesIO(build_docx(document, include_page_breaks=False)))

    assert 'w:type="page"' not in readback.element.xml


def test_build_docx_can_omit_headers_and_footer():
    document = _document_with_header_footer_and_page_numbers()

    readback = DocxDocument(io.BytesIO(build_docx(document, include_headers=False)))

    assert readback.sections[0].header.paragraphs[0].text == ""
    assert readback.sections[0].footer.paragraphs[0].text == ""


def test_build_docx_can_omit_page_numbers_while_keeping_footer_text():
    document = _document_with_header_footer_and_page_numbers()

    readback = DocxDocument(io.BytesIO(build_docx(document, include_page_numbers=False)))

    assert readback.sections[0].footer.paragraphs[0].text == "My Footer"
    assert "PAGE" not in readback.sections[0].footer._element.xml
