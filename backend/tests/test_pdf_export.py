import io

from pypdf import PdfReader

from app.export.pdf_export import build_pdf
from app.formatting.engine import apply_formatting
from app.formatting.templates import BUILTIN_TEMPLATES
from app.models.document import (
    Document,
    DocumentMetadata,
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
