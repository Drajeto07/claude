"""Project thumbnails (SmartDoc 2.0, UI review 2026-10-14): the real first page, drawn once per
revision and kept in storage, served only to the document's owner, gone with the document."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.export import thumbnail as thumbnail_module
from app.export.thumbnail import ASPECT, FIRST_PAGE_BLOCKS, WIDTH_PX, render_thumbnail
from app.main import app
from app.models.document import Document

_PASSWORD = "long enough password"


def _client(email: str) -> TestClient:
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD}).status_code == 201
    return client


def _create(client: TestClient, title: str = "Annual report") -> dict:
    text = f"{title}\n\nIntroduction\n\n" + "\n\n".join(f"Paragraph {n} of the report with some words." for n in range(1, 120))
    response = client.post("/api/v1/documents", json={"text": text, "title": title})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def drawings(monkeypatch):
    """Counts how often a thumbnail is really drawn (the cache's job is to keep this low)."""
    calls: list[int] = []
    real = render_thumbnail

    def counted(document, assets=None):
        calls.append(document.revision)
        return real(document, assets)

    monkeypatch.setattr("app.services.document_service.render_thumbnail", counted)
    return calls


def _picture(response) -> Image.Image:
    return Image.open(io.BytesIO(response.content))


def test_the_picture_is_the_top_of_the_real_first_page(api_db):
    client = _client("ann@example.com")
    document = Document.model_validate(_create(client))

    image = Image.open(io.BytesIO(render_thumbnail(document)))

    assert image.format == "PNG"
    assert image.size == (WIDTH_PX, round(WIDTH_PX * ASPECT))
    # Ink on paper: the page's text is drawn, it is not a blank or invented picture.
    grey = image.convert("L")
    dark = sum(grey.histogram()[:128])
    assert 0.002 < dark / (grey.width * grey.height) < 0.5
    assert grey.getpixel((2, 2)) > 240  # the page itself is white


def test_only_the_first_blocks_are_laid_out(api_db):
    client = _client("ben@example.com")
    document = Document.model_validate(_create(client))
    assert len(document.elements) > FIRST_PAGE_BLOCKS
    assert len(thumbnail_module.first_page_document(document).elements) == FIRST_PAGE_BLOCKS


def test_drawn_once_per_revision_and_cached(api_db, tmp_path, drawings):
    client = _client("cleo@example.com")
    created = _create(client)

    first = client.get(f"/api/v1/documents/{created['id']}/thumbnail?v=1")
    again = client.get(f"/api/v1/documents/{created['id']}/thumbnail?v=1")

    assert first.status_code == 200 and first.headers["content-type"] == "image/png"
    assert "immutable" in first.headers["cache-control"] and first.headers["cache-control"].startswith("private")
    assert again.content == first.content
    assert drawings == [created["revision"]]  # the second request came from storage
    assert (tmp_path / "assets" / "thumbnails" / f"{created['id']}.png").exists()

    renamed = client.patch(f"/api/v1/documents/{created['id']}", json={"title": "Annual report 2026"})
    assert renamed.status_code == 200
    client.get(f"/api/v1/documents/{created['id']}/thumbnail?v=2")
    assert drawings == [created["revision"], renamed.json()["revision"]]  # a new revision is drawn anew


def test_another_account_gets_nothing(api_db, drawings):
    owner = _client("dora@example.com")
    created = _create(owner)
    stranger = _client("eve@example.com")

    assert stranger.get(f"/api/v1/documents/{created['id']}/thumbnail").status_code == 404
    assert stranger.get("/api/v1/documents/not-a-document/thumbnail").status_code == 404
    assert drawings == []  # nothing of the owner's document was even drawn for the stranger


def test_the_thumbnail_goes_with_the_document(api_db, tmp_path):
    client = _client("finn@example.com")
    created = _create(client)
    assert client.get(f"/api/v1/documents/{created['id']}/thumbnail").status_code == 200
    kept = tmp_path / "assets" / "thumbnails"
    assert {path.name for path in kept.iterdir()} == {f"{created['id']}.png", f"{created['id']}.rev"}

    assert client.delete(f"/api/v1/documents/{created['id']}").status_code == 204

    assert list(kept.iterdir()) == []


def test_a_page_that_cant_be_drawn_is_a_404_not_an_error(api_db, monkeypatch):
    client = _client("gus@example.com")
    created = _create(client)

    def broken(document, assets=None):
        raise RuntimeError("pdfium is unhappy")

    monkeypatch.setattr("app.services.document_service.render_thumbnail", broken)
    assert client.get(f"/api/v1/documents/{created['id']}/thumbnail").status_code == 404
