"""A PDF's pictures in the document made of it (tracker P2E-003): each goes in where it
stood -- before the text below it -- at its size, no wider than the text, and is stored
as an asset like any other picture; a scanned page with no text comes in as its picture.
A logo repeated on the pages, the scan under a text layer, a rule or a dot, and any picture
past the decoding limits or unreadable are reported, never dropped silently."""

import asyncio
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.main import app
from app.models.document import ElementType
from app.parsers import pdf_pictures
from app.parsers.pdf_geometry import PdfChar, PdfImage, PdfPage
from app.parsers.pdf_pictures import MISSING, TOO_LARGE, TOO_MANY, UNREADABLE, Picture, PictureRef, decode_pictures
from app.parsers.pdf_structure import build_pdf_document, page_lines, picture_plan
from app.services.ingestion_service import build_document_from_upload
from tests.fakes import FakeAIProvider

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"
client = TestClient(app, base_url="https://testserver")


def _ai() -> FakeAIProvider:
    return FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)


def _upload(data: bytes, name: str):
    return asyncio.run(build_document_from_upload(data, name, None, _ai()))


def _features(document) -> dict:
    return {item.feature: item for item in document.importReport.items}


def test_pictures_go_in_where_they_stood():
    document = _upload((FIXTURES / "pictures.pdf").read_bytes(), "pictures.pdf")
    kinds = [element.type for element in document.elements]
    # Side by side, both before the caption under them.
    assert kinds == [ElementType.PARAGRAPH, ElementType.IMAGE, ElementType.IMAGE, ElementType.CAPTION]
    first, second = document.elements[1].image, document.elements[2].image
    assert (first.mime, first.widthCm, first.heightCm, second.widthCm, second.heightCm) == ("image/png", 7.06, 4.23, 4.23, 4.23)
    assert first.src.startswith("data:image/png;base64,") and first.name == "Page 1, picture 1"
    layout = document.elements[1].layout
    assert (layout.page, layout.x, layout.width, layout.source) == (1, 72.0, 200.0, "pdf-picture")
    with Image.open(io.BytesIO(__import__("base64").b64decode(first.src.partition(",")[2]))) as picture:
        assert picture.size == (200, 120)  # its own pixels, not the page's points
    assert _features(document)["pdf.picture_position"].count == 2 and "pdf.images" not in _features(document)
    conversion = document.pdfConversion
    assert {aspect.aspect: aspect.confidence for aspect in conversion.aspects}["pictures"] == 0.75 and conversion.confidence > 0.6


def test_a_scanned_page_comes_in_as_its_picture_no_wider_than_the_text():
    document = _upload((FIXTURES / "hybrid.pdf").read_bytes(), "hybrid.pdf")
    scan = document.elements[-1]
    settings = document.settings
    text_width = round(settings.pageWidthMm / 10 - settings.marginLeftCm - settings.marginRightCm, 2)
    assert scan.type == ElementType.IMAGE and scan.layout.page == 3 and scan.image.widthCm == text_width
    assert round(scan.image.heightCm / scan.image.widthCm, 2) == round(841.89 / 595.28, 2)  # its proportions kept


def _jpeg_pdf() -> bytes:
    picture = Image.new("RGB", (64, 48), (200, 40, 40))
    jpeg = io.BytesIO()
    picture.save(jpeg, format="JPEG")
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    canvas.setFont("Helvetica", 11)
    canvas.drawString(72, 780, "A photograph follows.")
    canvas.drawImage(ImageReader(io.BytesIO(jpeg.getvalue())), 72, 600, width=128, height=96)
    canvas.drawString(72, 540, "The text goes on well under it.")  # further down than a caption sits
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def test_a_jpeg_stays_a_jpeg():
    document = _upload(_jpeg_pdf(), "photo.pdf")
    image = next(element.image for element in document.elements if element.type == ElementType.IMAGE)
    assert image.mime == "image/jpeg" and image.src.startswith("data:image/jpeg;base64,/9j/")  # FF D8: the JPEG as it was
    assert [element.type for element in document.elements] == [ElementType.PARAGRAPH, ElementType.IMAGE, ElementType.PARAGRAPH]


def test_a_picture_past_the_limits_is_reported_not_decoded(monkeypatch):
    monkeypatch.setattr(pdf_pictures, "MAX_PDF_PICTURE_PIXELS", 100)
    document = _upload((FIXTURES / "pictures.pdf").read_bytes(), "pictures.pdf")
    assert ElementType.IMAGE not in [element.type for element in document.elements]
    item = _features(document)["pdf.images"]
    assert (item.count, item.contentChanged, item.reason) == (2, True, f"2 of the PDF's pictures weren't imported: 2 {TOO_LARGE}.")
    pictures = next(aspect for aspect in document.pdfConversion.aspects if aspect.aspect == "pictures")
    assert (pictures.confidence, pictures.count) == (0.0, 2) and document.pdfConversion.confidence <= 0.6

    monkeypatch.setattr(pdf_pictures, "MAX_PDF_PICTURE_PIXELS", 25_000_000)
    monkeypatch.setattr(pdf_pictures, "MAX_PDF_PICTURES", 1)
    document = _upload((FIXTURES / "pictures.pdf").read_bytes(), "pictures.pdf")
    assert [element.type for element in document.elements].count(ElementType.IMAGE) == 1
    assert _features(document)["pdf.images"].reason == f"1 of the PDF's pictures wasn't imported: 1 {TOO_MANY}."


def test_decoding_never_raises():
    refs = [PictureRef(1, 0, "FormXob.cf59e656b85e427745ba9401ecccac68", (200, 120)), PictureRef(1, 1, None, (10, 10)), PictureRef(1, 2, "Nowhere", (10, 10))]
    data = (FIXTURES / "pictures.pdf").read_bytes()
    results = decode_pictures(data, refs)
    assert isinstance(results[(1, 0)], Picture) and results[(1, 1)] == MISSING and results[(1, 2)] == MISSING
    assert decode_pictures(b"%PDF-1.4 not a pdf at all", refs[:1]) == {(1, 0): UNREADABLE}
    assert decode_pictures(data, [PictureRef(1, 0, "x", None)]) == {(1, 0): TOO_LARGE}  # a size it won't say


def _page(number: int, images: list[PdfImage], text: str = "Body text on this page.") -> PdfPage:
    page = PdfPage(number=number, width=595.0, height=842.0, rotation=0, boxes={})
    x = 72.0
    for character in text:
        page.chars.append(PdfChar(character, "Helvetica", 10.0, "#000000", (x, 300, x + 5, 310), False, True))
        x += 5
    page.images = images
    return page


def test_a_logo_on_every_page_and_a_rule_are_reported_not_put_in():
    logo = PdfImage(box=(480, 30, 540, 60), pixels=(60, 30), name="Logo")
    rule = PdfImage(box=(72, 400, 523, 401), pixels=(1, 1), name="Rule")
    pages = [page_lines(_page(number, [logo, rule] if number == 1 else [logo])) for number in (1, 2, 3)]
    wanted, left_out = picture_plan(pages)
    assert wanted == [] and sorted(left_out.values()) == ["running", "running", "running", "tiny"]
    structure = build_pdf_document(pages, None, {})
    features = {item.feature: item for item in structure.items}
    assert features["pdf.running_pictures"].count == 3
    assert features["pdf.images"].reason == "1 of the PDF's pictures wasn't imported: 1 too small to be more than a rule or a dot."
    assert all(element.type != ElementType.IMAGE for element in structure.document.elements)
    # On one page only, it is no logo: it goes in.
    single = [page_lines(_page(1, [logo]))]
    assert [ref.name for ref in picture_plan(single)[0]] == ["Logo"]


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = _ai
    assert client.post("/api/v1/auth/register", json={"email": "pictures@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def test_imported_pictures_are_stored_assets_and_export(signed_in):
    response = client.post("/api/v1/documents/upload", files={"file": ("pictures.pdf", (FIXTURES / "pictures.pdf").read_bytes(), "application/pdf")})
    assert response.status_code == 201, response.text[:300]
    document = response.json()
    images = [element["image"] for element in document["elements"] if element["type"] == "image"]
    assert len(images) == 2 and all(image["assetId"] and image["src"] == "" for image in images)  # no bytes in the document
    exported = client.get(f"/api/v1/documents/{document['id']}/export/docx")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as package:
        assert len([name for name in package.namelist() if name.startswith("word/media/")]) == 2
