"""PDF page operations (tracker PDF-020): reorder, rotate, delete, duplicate and extract pages,
split a PDF, merge PDFs -- a service of its own, on the PDF's bytes. Each page is told apart by
the text it shows ("Page 1".."Page 5"), so the tests read back which page went where."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject
from reportlab.pdfgen import canvas

from app.main import app
from app.parsers.pdf import PdfParseError
from app.services import pdf_pages
from app.services.pdf_pages import Delete, Duplicate, Extract, PdfPagesError, Reorder, Rotate

client = TestClient(app, base_url="https://testserver")


def _pdf(pages: int = 5, prefix: str = "Page") -> bytes:
    out = io.BytesIO()
    drawing = canvas.Canvas(out, pagesize=(300, 400))
    for number in range(1, pages + 1):
        drawing.drawString(50, 300, f"{prefix} {number}")
        drawing.showPage()
    drawing.save()
    return out.getvalue()


def _shown(data: bytes) -> list[str]:
    """What each page of a PDF shows, and its rotation when it has one."""
    reader = PdfReader(io.BytesIO(data))
    return [page.extract_text().strip() + (f" @{page.rotation % 360}" if page.rotation % 360 else "") for page in reader.pages]


def test_operations_are_done_one_after_the_other_on_the_pages_as_they_stand():
    result = pdf_pages.apply_operations(
        _pdf(),
        [
            Delete(op="delete", pages=[2]),  # 1 3 4 5
            Rotate(op="rotate", pages=[1], degrees=90),
            Duplicate(op="duplicate", pages=[2]),  # 1 3 3 4 5
            Reorder(op="reorder", order=[5, 4, 3, 2, 1]),  # 5 4 3 3 1
        ],
    )
    assert _shown(result) == ["Page 5", "Page 4", "Page 3", "Page 3", "Page 1 @90"]


def test_a_page_and_its_copy_are_two_pages():
    result = pdf_pages.apply_operations(_pdf(2), [Duplicate(op="duplicate", pages=[1]), Rotate(op="rotate", pages=[2], degrees=90)])
    assert _shown(result) == ["Page 1", "Page 1 @90", "Page 2"]


def test_extract_keeps_those_pages_alone_in_the_order_asked():
    assert _shown(pdf_pages.apply_operations(_pdf(), [Extract(op="extract", pages=[4, 2])])) == ["Page 4", "Page 2"]


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (Delete(op="delete", pages=[1, 2, 3, 4, 5]), "not every page can be deleted"),
        (Rotate(op="rotate", pages=[9], degrees=90), "there is no page 9"),
        (Reorder(op="reorder", order=[1, 2, 3]), "names every page once"),
        (Reorder(op="reorder", order=[1, 1, 2, 3, 4]), "more than once"),
    ],
)
def test_what_cant_be_done_is_refused_before_anything_is_written(operation, message):
    with pytest.raises(PdfPagesError, match=message):
        pdf_pages.apply_operations(_pdf(), [operation])


def test_split_by_ranges_or_every_so_many_pages():
    assert [_shown(part) for part in pdf_pages.split(_pdf(), ranges=[(1, 2), (3, 5)])] == [["Page 1", "Page 2"], ["Page 3", "Page 4", "Page 5"]]
    assert [len(_shown(part)) for part in pdf_pages.split(_pdf(), every=2)] == [2, 2, 1]
    with pytest.raises(PdfPagesError, match="first page comes before"):
        pdf_pages.split(_pdf(), ranges=[(3, 2)])


def test_merge_puts_the_pdfs_one_after_the_other():
    assert _shown(pdf_pages.merge([_pdf(2, "A"), _pdf(1, "B")])) == ["A 1", "A 2", "B 1"]
    with pytest.raises(PdfPagesError, match="Merge 2"):
        pdf_pages.merge([_pdf()])


def _with_actions(data: bytes) -> bytes:
    """The PDF with a JavaScript open action, a page action, and links: one to JavaScript, one to the web."""
    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    writer.append(reader)
    writer._root_object[NameObject("/OpenAction")] = DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("app.alert('hi');")})
    page = writer.pages[0]
    page[NameObject("/AA")] = DictionaryObject({NameObject("/O"): DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("x")})})
    annotations = ArrayObject()
    for action in (
        {NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("evil()")},
        {NameObject("/S"): NameObject("/URI"), NameObject("/URI"): TextStringObject("https://example.com/")},
    ):
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): ArrayObject([]),
                NameObject("/A"): DictionaryObject(action),
            }
        )
        annotations.append(writer._add_object(annotation))
    page[NameObject("/Annots")] = annotations
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.security  # the security regression suite (TEST-030)
def test_no_script_comes_along_and_a_web_link_stays():
    result = pdf_pages.apply_operations(_with_actions(_pdf(2)), [Rotate(op="rotate", pages=[1], degrees=180)])
    assert b"JavaScript" not in result and b"evil" not in result and b"app.alert" not in result
    links = [annotation.get_object().get("/A") for annotation in PdfReader(io.BytesIO(result)).pages[0]["/Annots"]]
    assert [link.get_object()["/URI"] if link else None for link in links] == [None, "https://example.com/"]


def test_a_file_that_isnt_a_readable_pdf_is_refused_as_an_import_refuses_it():
    with pytest.raises(PdfParseError):
        pdf_pages.apply_operations(b"%PDF-1.4 nonsense", [Delete(op="delete", pages=[1])])


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "pages@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()


def _file(data: bytes, name: str = "report.pdf"):
    return ("file", (name, data, "application/pdf"))


def test_the_api_does_each_operation_and_says_what_cant_be(signed_in):
    info = client.post("/api/v1/pdf/info", files=[_file(_pdf(3))])
    assert info.status_code == 200 and [page["number"] for page in info.json()] == [1, 2, 3] and info.json()[0]["widthPt"] == 300

    operations = json.dumps([{"op": "rotate", "pages": [2], "degrees": 270}, {"op": "delete", "pages": [1]}])
    done = client.post("/api/v1/pdf/pages", files=[_file(_pdf(3))], data={"operations": operations})
    assert done.status_code == 200 and done.headers["content-type"] == "application/pdf"
    assert "report.pdf" in done.headers["content-disposition"] and _shown(done.content) == ["Page 2 @270", "Page 3"]

    refused = client.post("/api/v1/pdf/pages", files=[_file(_pdf(3))], data={"operations": json.dumps([{"op": "delete", "pages": [7]}])})
    assert refused.status_code == 422 and refused.json()["code"] == "pdf_pages" and "no page 7" in refused.json()["message"]
    invalid = client.post("/api/v1/pdf/pages", files=[_file(_pdf(3))], data={"operations": json.dumps([{"op": "shred", "pages": [1]}])})
    assert invalid.status_code == 422
    not_pdf = client.post("/api/v1/pdf/pages", files=[_file(b"hello", "notes.txt")], data={"operations": operations})
    assert not_pdf.status_code == 400

    parts = client.post("/api/v1/pdf/split", files=[_file(_pdf(3))], data={"every": "2"})
    assert parts.status_code == 200 and parts.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(parts.content)) as package:
        assert package.namelist() == ["report-1.pdf", "report-2.pdf"]
        assert _shown(package.read("report-2.pdf")) == ["Page 3"]

    merged = client.post("/api/v1/pdf/merge", files=[_file(_pdf(1, "A"), "a.pdf"), ("files", ("b.pdf", _pdf(1, "B"), "application/pdf"))])
    assert merged.status_code == 422  # the first under the wrong field: one file only
    merged = client.post("/api/v1/pdf/merge", files=[("files", ("a.pdf", _pdf(1, "A"), "application/pdf")), ("files", ("b.pdf", _pdf(1, "B"), "application/pdf"))])
    assert merged.status_code == 200 and _shown(merged.content) == ["A 1", "B 1"]


def test_the_api_is_for_people_signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/pdf/info", files=[_file(_pdf(1))]).status_code == 401
