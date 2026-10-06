"""Tables drawn with ruling lines in a PDF (tracker P2E-004): the grid the lines make is the
table, each cell takes the text inside it, a missing edge merges cells, a shaded or bold
first row is the header, and the table goes in where it stood. Lines with no text in them,
a lone box, a turned page's grid aren't tables; columns set by space alone stay text, a row
a paragraph, and the report says so."""

import asyncio
import io
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.fidelity.pdf_conversion import conversion_summary
from app.main import app
from app.models.document import ElementType
from app.models.pdf_inspection import PdfInspection
from app.parsers.pdf_geometry import PdfChar, PdfPage, PdfPath, read_pdf_geometry
from app.parsers.pdf_structure import SURE, LIKELY, build_pdf_document, page_lines
from app.parsers.pdf_tables import find_grids
from app.services.ingestion_service import build_document_from_upload
from tests.fakes import FakeAIProvider

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"
client = TestClient(app, base_url="https://testserver")


def _ai() -> FakeAIProvider:
    return FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)


def _upload(data: bytes, name: str = "table.pdf"):
    return asyncio.run(build_document_from_upload(data, name, None, _ai()))


def _cells(table) -> list[list[tuple]]:
    return [[("".join(run.text for run in cell.inline), cell.colspan, cell.rowspan, cell.header) for cell in row.cells] for row in table.rows]


def test_a_ruled_table_cell_by_cell():
    document = _upload((FIXTURES / "table.pdf").read_bytes())
    heading, table = document.elements
    assert (heading.type, heading.level, table.type, table.confidence) == (ElementType.HEADING, 1, ElementType.TABLE, SURE)
    assert _cells(table.table) == [
        [("Item", 1, 1, True), ("Size", 1, 1, True), ("Count", 1, 1, True), ("Price", 1, 1, True)],
        [("Pen", 1, 1, False), ("S", 1, 1, False), ("10", 1, 1, False), ("1.20", 1, 1, False)],
        [("Book", 1, 1, False), ("M", 1, 1, False), ("2", 1, 1, False), ("9.50", 1, 1, False)],
        [("Desk", 1, 1, False), ("L", 1, 1, False), ("1", 1, 1, False), ("120.00", 1, 1, False)],
    ]
    content = table.table
    assert content.hasHeaderRow and {cell.background for cell in content.rows[0].cells} == {"#d9d9d9"}
    assert content.columnWidthsCm == [3.95] * 4  # 112 points each
    # The header's bold is the header's: not marked again on its runs.
    assert all(not run.marks for cell in content.rows[0].cells for run in cell.inline)
    layout = table.layout
    assert (layout.page, layout.x, layout.y, layout.width, layout.height, layout.lines) == (1, 72.0, 101.89, 448.0, 96.0, 4)
    assert document.importReport.content.verified


def _grid_pdf(draw) -> bytes:
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    canvas.setFont("Helvetica", 10)
    canvas.drawString(72, 790, "A table follows.")
    draw(canvas)
    canvas.drawString(72, 500, "And the text after it.")
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def test_merged_cells():
    """Three columns, three rows: the top row's first two cells one (no line between them),
    the first column's two lower cells one (no line between them)."""

    def draw(canvas):
        left, top, width, height = 72, 740, 100, 20
        xs = [left + i * width for i in range(4)]
        ys = [top - i * height for i in range(4)]
        canvas.line(xs[0], ys[0], xs[3], ys[0])
        canvas.line(xs[0], ys[3], xs[3], ys[3])
        canvas.line(xs[0], ys[1], xs[3], ys[1])
        canvas.line(xs[1], ys[2], xs[3], ys[2])  # not under the first column: rows 2 and 3 merge there
        canvas.line(xs[0], ys[0], xs[0], ys[3])
        canvas.line(xs[3], ys[0], xs[3], ys[3])
        canvas.line(xs[1], ys[1], xs[1], ys[3])  # not in the top row: its first two cells merge
        canvas.line(xs[2], ys[0], xs[2], ys[3])
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(xs[0] + 5, ys[0] - 14, "Both columns")
        canvas.drawString(xs[2] + 5, ys[0] - 14, "Third")
        canvas.setFont("Helvetica", 10)
        canvas.drawString(xs[0] + 5, ys[1] - 14, "Two rows")
        for row, values in ((1, ("b1", "c1")), (2, ("b2", "c2"))):
            canvas.drawString(xs[1] + 5, ys[row] - 14, values[0])
            canvas.drawString(xs[2] + 5, ys[row] - 14, values[1])

    document = _upload(_grid_pdf(draw), "merged.pdf")
    assert [element.type for element in document.elements] == [ElementType.PARAGRAPH, ElementType.TABLE, ElementType.PARAGRAPH]
    table = document.elements[1]
    assert _cells(table.table) == [
        [("Both columns", 2, 1, True), ("Third", 1, 1, True)],
        [("Two rows", 1, 2, False), ("b1", 1, 1, False), ("c1", 1, 1, False)],
        [("b2", 1, 1, False), ("c2", 1, 1, False)],
    ]
    # Bold, not shaded: the header all the same; merged cells: a little less sure.
    assert table.table.hasHeaderRow and table.confidence == LIKELY
    assert document.importReport.content.verified


def test_a_lone_box_lines_with_nothing_in_them_and_a_turned_page_aren_t_tables():
    def boxed(canvas):
        canvas.rect(72, 700, 300, 40, stroke=1, fill=0)  # a box around a note
        canvas.drawString(80, 715, "A note in a box.")
        canvas.grid([72, 172, 272], [560, 600, 640])  # a grid with nothing in it: a drawing

    document = _upload(_grid_pdf(boxed), "boxed.pdf")
    assert ElementType.TABLE not in [element.type for element in document.elements]
    assert "A note in a box." in [element.content for element in document.elements]
    page = PdfPage(number=1, width=595, height=842, rotation=90, boxes={})
    page.lines = [PdfPath((72, y, 300, y + 0.5), 0.5, "#000000", None) for y in (100, 120, 140)]
    page.lines += [PdfPath((x, 100, x + 0.5, 140), 0.5, "#000000", None) for x in (72, 150, 300)]
    assert find_grids(page) == []
    page.rotation = 0
    assert len(find_grids(page)) == 1  # upright, the same lines are one


def test_columns_of_space_alone_stay_text_and_are_said_to():
    page = PdfPage(number=1, width=595, height=842, rotation=0, boxes={})
    for row, (name, value) in enumerate([("Name", "Value"), ("Pen", "1.20"), ("Book", "9.50")]):
        for x0, text in ((72, name), (300, value)):
            x = x0
            for character in text:
                page.chars.append(PdfChar(character, "Helvetica", 10.0, "#000000", (x, 100 + row * 14, x + 5, 110 + row * 14), False, True))
                x += 5
    structure = build_pdf_document([page_lines(page)], None)
    assert [element.content for element in structure.document.elements] == ["Name Value", "Pen 1.20", "Book 9.50"]
    item = {item.feature: item for item in structure.items}["pdf.unruled_tables"]
    assert item.count == 3 and "a paragraph each" in item.reason
    conversion = conversion_summary(structure.document, structure, PdfInspection(pageCount=1, complete=True))
    tables = next(aspect for aspect in conversion.aspects if aspect.aspect == "tables")
    assert (tables.confidence, tables.count) == (0.3, 3) and conversion.confidence <= 0.6


def test_grids_on_the_fixtures():
    found = {
        name: sum(len(find_grids(page)) for page in read_pdf_geometry((FIXTURES / name).read_bytes()).pages)
        for name in ("table.pdf", "text.pdf", "form.pdf", "pictures.pdf", "structure.pdf", "columns.pdf")
    }
    assert found == {"table.pdf": 1, "text.pdf": 0, "form.pdf": 0, "pictures.pdf": 0, "structure.pdf": 0, "columns.pdf": 0}


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = _ai
    assert client.post("/api/v1/auth/register", json={"email": "tables@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def test_a_rebuilt_table_exports_to_word_as_a_table(signed_in):
    document = client.post("/api/v1/documents/upload", files={"file": ("table.pdf", (FIXTURES / "table.pdf").read_bytes(), "application/pdf")}).json()
    exported = client.get(f"/api/v1/documents/{document['id']}/export/docx")
    assert exported.status_code == 200
    (table,) = DocxDocument(io.BytesIO(exported.content)).tables
    assert [[cell.text for cell in row.cells] for row in table.rows][:2] == [["Item", "Size", "Count", "Price"], ["Pen", "S", "10", "1.20"]]
