import io

from pypdf import PdfReader

from app.export.pdf_export import build_pdf
from app.formatting.engine import apply_formatting
from app.formatting.templates import BUILTIN_TEMPLATES
from app.models.document import (
    Document,
    DocumentMetadata,
    DocumentSettings,
    Element,
    ElementType,
    InlineRun,
    ListItem,
    Mark,
    MarkType,
    TableCell,
    TableContent,
    TableRow,
)


def sample_document() -> Document:
    elements = [
        Element(type=ElementType.HEADING, content="Export Test", inline=[InlineRun(text="Export Test")], level=1, order=0),
        Element(
            type=ElementType.PARAGRAPH,
            content="Bold text here.",
            inline=[InlineRun(text="Bold", marks=[Mark(type=MarkType.BOLD)]), InlineRun(text=" text here.")],
            order=1,
        ),
        Element(
            type=ElementType.LIST,
            content="First item",
            listItems=[ListItem(inline=[InlineRun(text="First item")], level=0)],
            ordered=False,
            order=2,
        ),
        Element(
            type=ElementType.TABLE,
            content="Header",
            table=TableContent(rows=[TableRow(cells=[TableCell(inline=[InlineRun(text="Header")], header=True)])], hasHeaderRow=True),
            order=3,
        ),
    ]
    document = Document(metadata=DocumentMetadata(title="PDF Export Test"), elements=elements)
    template = BUILTIN_TEMPLATES["academic-default"]
    apply_formatting(document, template_id=template.id, template_rules=template.rules, instruction_rules=[])
    return document


def test_build_pdf_produces_valid_readable_pdf():
    document = sample_document()

    pdf_bytes = build_pdf(document)

    assert pdf_bytes.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Export Test" in text
    assert "Bold" in text
    assert "First item" in text
    assert "Header" in text


def test_build_pdf_handles_empty_document():
    document = Document(metadata=DocumentMetadata(title="Empty"), elements=[])

    pdf_bytes = build_pdf(document)

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1


def test_build_pdf_page_break_produces_a_second_physical_page():
    document = Document(
        metadata=DocumentMetadata(title="Page Break Test"),
        elements=[
            Element(type=ElementType.PARAGRAPH, content="Page one text", inline=[InlineRun(text="Page one text")], order=0),
            Element(type=ElementType.PAGE_BREAK, content="", order=1),
            Element(type=ElementType.PARAGRAPH, content="Page two text", inline=[InlineRun(text="Page two text")], order=2),
        ],
    )

    pdf_bytes = build_pdf(document)

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 2
    assert "Page one text" in (reader.pages[0].extract_text() or "")
    assert "Page two text" in (reader.pages[1].extract_text() or "")


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


def test_build_pdf_defaults_include_everything():
    document = _document_with_header_footer_and_page_numbers()

    reader = PdfReader(io.BytesIO(build_pdf(document)))

    assert len(reader.pages) == 2
    text = reader.pages[0].extract_text() or ""
    assert "My Header" in text
    assert "My Footer" in text
    assert "Page 1" in text


def test_build_pdf_can_omit_page_breaks():
    document = _document_with_header_footer_and_page_numbers()

    reader = PdfReader(io.BytesIO(build_pdf(document, include_page_breaks=False)))

    assert len(reader.pages) == 1


def test_build_pdf_can_omit_headers_and_footer():
    document = _document_with_header_footer_and_page_numbers()

    reader = PdfReader(io.BytesIO(build_pdf(document, include_headers=False)))

    text = reader.pages[0].extract_text() or ""
    assert "My Header" not in text
    assert "My Footer" not in text
    assert "Page 1" in text  # page numbers alone are untouched by include_headers


def test_build_pdf_can_omit_page_numbers_while_keeping_footer_text():
    document = _document_with_header_footer_and_page_numbers()

    reader = PdfReader(io.BytesIO(build_pdf(document, include_page_numbers=False)))

    text = reader.pages[0].extract_text() or ""
    assert "My Footer" in text
    assert "Page 1" not in text
