"""B-028: PDFium is not thread-safe, and two threads drawing thumbnails at once crashed the whole process
(access violation / heap corruption in FPDF_LoadPage). Every PDFium call in a thumbnail now holds one
process-wide lock; these tests keep it that way: the calls never overlap, everything PDFium made is closed
in order on every path, the picture outlives the bitmap it came from, and the real renderer survives many
threads at once (in a subprocess of its own, so a crash fails the test instead of the test run)."""

import base64
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.export import thumbnail as thumbnail_module
from app.main import app
from app.models.document import Document, walk_elements

_PASSWORD = "long enough password"
_BACKEND = Path(__file__).resolve().parents[1]
_GOLDEN = Path(__file__).parent / "fixtures" / "documents"


class _Pdfium:
    """A stand-in for pypdfium2 that records how many threads are inside it and what gets closed, in order.
    Each step sleeps a little, so overlapping threads would be seen."""

    def __init__(self, fail_at: str | None = None, pause: float = 0.002):
        self.fail_at = fail_at
        self.pause = pause
        self.inside = 0
        self.most_inside = 0
        self.closed: list[str] = []
        self.counter = threading.Lock()
        self.buffers: list[bytearray] = []

    def step(self, name: str) -> None:
        with self.counter:
            self.inside += 1
            self.most_inside = max(self.most_inside, self.inside)
        time.sleep(self.pause)
        with self.counter:
            self.inside -= 1
        if self.fail_at == name:
            raise RuntimeError(f"pdfium failed at {name}")

    def document(self, pdf_bytes: bytes) -> "_Document":
        assert thumbnail_module._PDFIUM_LOCK.locked(), "a PDF opened outside the lock"
        self.step("open")
        return _Document(self)


class _Document:
    def __init__(self, fake: _Pdfium):
        self.fake = fake

    def __getitem__(self, index: int) -> "_Page":
        self.fake.step("page")
        return _Page(self.fake)

    def close(self) -> None:
        self.fake.closed.append("document")


class _Page:
    def __init__(self, fake: _Pdfium):
        self.fake = fake

    def get_width(self) -> float:
        return 595.0

    def render(self, scale: float) -> "_Bitmap":
        self.fake.step("render")
        return _Bitmap(self.fake)

    def close(self) -> None:
        self.fake.closed.append("page")


class _Bitmap:
    """Pixels in a buffer the image shares (as to_pil() may), wiped when the bitmap is closed."""

    def __init__(self, fake: _Pdfium):
        self.fake = fake
        self.buffer = bytearray(b"\x20\x40\x60\xff" * 8 * 6)
        fake.buffers.append(self.buffer)

    def to_pil(self) -> Image.Image:
        self.fake.step("to_pil")
        return Image.frombuffer("RGBX", (8, 6), self.buffer, "raw", "RGBX", 0, 1)

    def close(self) -> None:
        self.buffer[:] = bytes(len(self.buffer))
        self.fake.closed.append("bitmap")


@pytest.fixture
def fake_pdfium(monkeypatch):
    fake = _Pdfium()
    monkeypatch.setattr(thumbnail_module.pypdfium2, "PdfDocument", fake.document)
    return fake


def test_pdfium_calls_from_many_threads_never_overlap(fake_pdfium):
    with ThreadPoolExecutor(max_workers=8) as pool:
        images = list(pool.map(lambda _: thumbnail_module._first_page_image(b"%PDF"), range(40)))
    assert len(images) == 40
    assert fake_pdfium.most_inside == 1  # one thread in PDFium at a time
    assert fake_pdfium.closed == ["bitmap", "page", "document"] * 40
    assert not thumbnail_module._PDFIUM_LOCK.locked()


def test_the_pdf_is_laid_out_outside_the_lock_and_drawn_inside_it(fake_pdfium, monkeypatch):
    def build_pdf(document, assets, include_page_numbers):
        assert not thumbnail_module._PDFIUM_LOCK.locked(), "build_pdf (no PDFium) should not hold the lock"
        return b"%PDF"

    monkeypatch.setattr(thumbnail_module, "build_pdf", build_pdf)
    png = thumbnail_module.render_thumbnail(Document(elements=[]))
    assert png.startswith(b"\x89PNG")
    assert not thumbnail_module._PDFIUM_LOCK.locked()


def test_the_picture_outlives_the_bitmap_it_was_drawn_into(fake_pdfium):
    image = thumbnail_module._first_page_image(b"%PDF")
    assert all(not any(buffer) for buffer in fake_pdfium.buffers)  # the bitmap is closed and its memory wiped
    assert image.mode == "RGB"
    assert image.getpixel((0, 0)) == (0x20, 0x40, 0x60)  # yet the picture still holds the page's pixels


@pytest.mark.parametrize(
    ("fail_at", "closed"),
    [
        ("open", []),
        ("page", ["document"]),
        ("render", ["page", "document"]),
        ("to_pil", ["bitmap", "page", "document"]),
    ],
)
def test_whatever_fails_everything_made_so_far_is_closed_once_and_the_lock_let_go(monkeypatch, fail_at, closed):
    fake = _Pdfium(fail_at=fail_at)
    monkeypatch.setattr(thumbnail_module.pypdfium2, "PdfDocument", fake.document)
    with pytest.raises(RuntimeError, match=f"failed at {fail_at}"):
        thumbnail_module._first_page_image(b"%PDF")
    assert fake.closed == closed
    assert not thumbnail_module._PDFIUM_LOCK.locked()
    # ...and the next thumbnail is drawn as usual.
    monkeypatch.setattr(thumbnail_module.pypdfium2, "PdfDocument", _Pdfium().document)
    assert thumbnail_module._first_page_image(b"%PDF").size == (8, 6)


def _client(email: str) -> TestClient:
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD}).status_code == 201
    return client


def _documents(client: TestClient) -> list[dict]:
    """A short text, a long one, and a Word file with pictures and a table -- with the pictures' bytes."""
    created = [
        client.post("/api/v1/documents", json={"text": "Short note\n\nOne paragraph.", "title": "Short note"}).json(),
        client.post("/api/v1/documents", json={"text": "Report\n\n" + "\n\n".join(f"Paragraph {n} with some words." for n in range(80)), "title": "Report"}).json(),
    ]
    with open(_GOLDEN / "17-pictures.docx", "rb") as handle:
        response = client.post("/api/v1/documents/upload", files={"file": ("17-pictures.docx", handle, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert response.status_code in (200, 201), response.text
    created.append(response.json())
    out = []
    for raw in created:
        document = Document.model_validate(raw)
        assets = {}
        for element in walk_elements(document.elements):
            if element.image and element.image.assetId:
                assets[element.image.assetId] = base64.b64encode(client.get(f"/api/v1/assets/{element.image.assetId}").content).decode()
        out.append({"document": raw, "assets": assets})
    assert any(entry["assets"] for entry in out)  # at least one with pictures
    return out


_STRESS = textwrap.dedent(
    """
    import base64, json, sys
    from concurrent.futures import ThreadPoolExecutor
    from app.export.thumbnail import render_thumbnail
    from app.models.document import Document

    entries = json.load(open(sys.argv[1], encoding="utf-8"))
    jobs = [(Document.model_validate(e["document"]), {k: base64.b64decode(v) for k, v in e["assets"].items()}) for e in entries]
    expected = [render_thumbnail(document, assets) for document, assets in jobs]  # one at a time first
    rounds = int(sys.argv[2])
    with ThreadPoolExecutor(max_workers=int(sys.argv[3])) as pool:
        got = list(pool.map(lambda n: (n % len(jobs), render_thumbnail(*jobs[n % len(jobs)])), range(rounds * len(jobs))))
    print(json.dumps({"drawn": len(got), "same_as_one_at_a_time": all(png == expected[i] for i, png in got)}))
    """
)


def test_the_real_renderer_survives_many_threads_at_once(api_db, tmp_path):
    """The real render_thumbnail from 8 threads at once, in a subprocess with only temporary test documents:
    without the lock this crashed the process every time (B-028); a crash or a hang fails the test."""
    entries = tmp_path / "documents.json"
    entries.write_text(json.dumps(_documents(_client("stress@example.com"))), encoding="utf-8")
    script = tmp_path / "stress.py"
    script.write_text(_STRESS, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(entries), "40", "8"],
        cwd=_BACKEND,
        # Nothing of the developer's environment (no DATABASE_URL, no storage keys): only what Python needs.
        env={"PATH": "", "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PYTHONPATH": str(_BACKEND)},
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr[-2000:]}"
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report == {"drawn": 120, "same_as_one_at_a_time": True}


def test_a_dashboard_of_thumbnails_asked_for_at_once_is_all_drawn(api_db):
    """As a dashboard asks: every project's thumbnail at the same time, through the API. Each is drawn (a
    PNG, not the 404 a failed drawing gives) and is the picture the document gets when asked again."""
    client = _client("dashboard@example.com")
    ids = [client.post("/api/v1/documents", json={"text": f"Project {n}\n\nSome words of project {n}.", "title": f"Project {n}"}).json()["id"] for n in range(9)]
    with ThreadPoolExecutor(max_workers=9) as pool:
        answers = dict(zip(ids, pool.map(lambda document_id: client.get(f"/api/v1/documents/{document_id}/thumbnail"), ids)))
    assert all(response.status_code == 200 and response.headers["content-type"] == "image/png" for response in answers.values())
    # Asked again, one at a time (now from storage): the same pictures, so what was drawn at once was whole.
    assert all(client.get(f"/api/v1/documents/{document_id}/thumbnail").content == response.content for document_id, response in answers.items())
