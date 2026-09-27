"""The export report (tracker FID-003): what an export approximated or left out,
and whether the file, read back, holds every word of the document."""

import base64
import io

from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.export.docx_export import build_docx
from app.export.pdf_export import build_pdf
from app.fidelity.exports import export_report
from app.fidelity.report import FidelityPolicy, ReportBuilder
from app.main import app
from app.models.document import Document, Element, ElementType, ImageContent, InlineRun, TableCell, TableContent, TableRow


def _paragraph(text: str, order: int) -> Element:
    return Element(type=ElementType.PARAGRAPH, content=text, inline=[InlineRun(text=text)], order=order)


def _exported(document: Document, file_format: str, assets=None):
    noted = ReportBuilder()
    build = build_docx if file_format == "docx" else build_pdf
    content = build(document, assets=assets or {}, report=noted)
    return export_report(document, content, file_format, noted.items())


def _webp() -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (8, 8), "red").save(buffer, format="WEBP")
    return buffer.getvalue()


def test_both_exports_of_a_plain_document_are_verified_word_for_word():
    document = Document(elements=[_paragraph("Take 5 mg twice a day.", 0), _paragraph("Keep away from children.", 1)])

    for file_format in ("docx", "pdf"):
        report = _exported(document, file_format)
        assert report.stage == "export" and report.sourceType == file_format
        assert report.contentStatus == "verified", (file_format, report.content)
        assert report.items == []


def test_a_webp_picture_word_cannot_hold_is_reported_not_silently_dropped():
    picture = Element(type=ElementType.IMAGE, content="", image=ImageContent(src="", assetId="w1", alt="Logo"), order=1)
    document = Document(elements=[_paragraph("Our logo:", 0), picture])

    report = _exported(document, "docx", assets={"w1": _webp()})

    [item] = [item for item in report.items if item.feature == "export.docx.image_format"]
    assert item.policy == FidelityPolicy.UNSUPPORTED and item.contentChanged
    assert item.elementIds == [picture.id]
    assert report.contentLossCount == 1


def test_a_missing_picture_is_reported():
    picture = Element(type=ElementType.IMAGE, content="", image=ImageContent(src="", assetId="gone"), order=0)

    for file_format in ("docx", "pdf"):
        report = _exported(Document(elements=[picture]), file_format)
        assert [item.feature for item in report.items] == ["export.image.missing"], file_format


def test_text_the_pdf_cannot_lay_out_is_reported_and_caught_by_the_check():
    document = Document(elements=[_paragraph("Hello", 0), _paragraph("مرحبا بالعالم", 1), _paragraph("你好世界", 2)])

    pdf = _exported(document, "pdf")
    docx = _exported(document, "docx")

    [script] = [item for item in pdf.items if item.feature == "export.pdf.script"]
    assert "Arabic" in script.reason and "Chinese" in script.reason and script.contentChanged
    assert pdf.contentStatus == "changed"  # the words can't be read back
    assert docx.contentStatus == "verified" and docx.items == []  # Word keeps them


def test_a_page_break_inside_a_table_is_reported_for_the_pdf():
    cell = TableCell(inline=[InlineRun(text="a")], blocks=[_paragraph("a", 0), Element(type=ElementType.PAGE_BREAK, content="", order=1)])
    table = Element(type=ElementType.TABLE, content="a", table=TableContent(rows=[TableRow(cells=[cell])]), order=0)

    report = _exported(Document(elements=[table]), "pdf")

    assert [item.feature for item in report.items] == ["export.pdf.page_break_in_table"]
    assert report.contentStatus == "verified"


def test_the_export_job_result_carries_the_report(api_db):
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/register", json={"email": "exports@example.com", "password": "long enough password"}).status_code == 201
    webp = "data:image/webp;base64," + base64.b64encode(_webp()).decode()
    document = client.post("/api/v1/documents", json={"text": "# Report\n\nEvery word of this sentence counts."}).json()
    picture = {"type": "image", "content": "", "order": 99, "image": {"src": webp, "alt": "Logo"}}
    client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": document["elements"] + [picture]})

    docx_job = client.post("/api/v1/jobs/export", json={"documentId": document["id"], "format": "docx"}).json()
    pdf_job = client.post("/api/v1/jobs/export", json={"documentId": document["id"], "format": "pdf"}).json()

    docx_report, pdf_report = docx_job["result"]["fidelity"], pdf_job["result"]["fidelity"]
    assert docx_report["contentStatus"] == "verified" and pdf_report["contentStatus"] == "verified"
    assert [item["feature"] for item in docx_report["items"]] == ["export.docx.image_format"]
    # The PDF draws WebP fine, but its alt text has nowhere to go yet.
    assert [item["feature"] for item in pdf_report["items"]] == ["export.pdf.alt_text"]
