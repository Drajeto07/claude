import io
from pathlib import Path

from docx import Document as DocxDocument
from fastapi.testclient import TestClient

from app.ai.factory import get_ai_provider
from app.ai.schemas import AIBlock, AIBlockType, AIFormattingRule, AIInstructionExtractionResponse, AIStructureResponse
from app.config import get_settings
from app.main import app
from tests.fakes import FakeAIProvider

client = TestClient(app)
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_fetch_document_round_trip():
    # Markdown-looking input takes the deterministic parser path, so this
    # needs no AI provider override to be predictable.
    create_response = client.post("/api/documents", json={"text": "# Hello\n\nWorld is a longer paragraph here."})
    assert create_response.status_code == 201
    created = create_response.json()
    assert len(created["elements"]) == 2

    get_response = client.get(f"/api/documents/{created['id']}")
    assert get_response.status_code == 200
    assert get_response.json() == created


def test_get_unknown_document_returns_404():
    response = client.get("/api/documents/does-not-exist")
    assert response.status_code == 404


def test_create_document_rejects_blank_text():
    response = client.post("/api/documents", json={"text": "   "})
    assert response.status_code == 422


def test_plain_prose_routes_to_ai_provider():
    fake_response = AIStructureResponse(
        document_type="essay",
        document_type_confidence=0.7,
        blocks=[AIBlock(type=AIBlockType.PARAGRAPH, text="Ordinary unstructured prose text for the API test.", confidence=0.8)],
    )
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([fake_response])
    try:
        response = client.post("/api/documents", json={"text": "Ordinary unstructured prose text for the API test."})
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 201
    body = response.json()
    assert body["documentType"] == "essay"
    assert body["elements"][0]["confidence"] == 0.8


def test_upload_txt_file():
    response = client.post(
        "/api/documents/upload",
        files={"file": ("notes.txt", b"# A Heading\n\nSome body text.", "text/plain")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["metadata"]["sourceType"] == "uploaded_txt"
    assert body["metadata"]["originalFilename"] == "notes.txt"


def test_upload_docx_file():
    doc = DocxDocument()
    doc.add_heading("Uploaded Title", level=1)
    doc.add_paragraph("Body paragraph.")
    buf = io.BytesIO()
    doc.save(buf)

    response = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "report.docx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["elements"][0]["content"] == "Uploaded Title"
    assert body["metadata"]["sourceType"] == "uploaded_docx"


def test_upload_pdf_file():
    # The fixture's extracted text is plain prose (no Markdown cues), so this
    # exercises the upload -> PDF-text-extraction -> AI-routing path -- needs
    # a fake provider, same as test_plain_prose_routes_to_ai_provider.
    pdf_bytes = (FIXTURES_DIR / "sample.pdf").read_bytes()
    fake_response = AIStructureResponse(
        document_type="general",
        document_type_confidence=0.6,
        blocks=[AIBlock(type=AIBlockType.PARAGRAPH, text="Hello World Sample PDF Text", confidence=0.75)],
    )
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([fake_response])
    try:
        response = client.post(
            "/api/documents/upload",
            files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
        )
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 201
    body = response.json()
    assert "Hello World Sample PDF Text" in body["elements"][0]["content"]


def test_upload_rejects_unsupported_extension():
    response = client.post(
        "/api/documents/upload",
        files={"file": ("image.png", b"not text", "image/png")},
    )
    assert response.status_code == 400


def test_upload_rejects_corrupt_docx():
    response = client.post(
        "/api/documents/upload",
        files={
            "file": (
                "bad.docx",
                b"this is not a real docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 400


def test_upload_rejects_oversized_file():
    settings = get_settings()
    original_max = settings.max_upload_size_mb
    settings.max_upload_size_mb = 0
    try:
        response = client.post(
            "/api/documents/upload",
            files={"file": ("small.txt", b"just a few bytes", "text/plain")},
        )
        assert response.status_code == 413
    finally:
        settings.max_upload_size_mb = original_max


def _create_document() -> str:
    response = client.post("/api/documents", json={"text": "# Hello\n\nWorld is a longer paragraph here."})
    return response.json()["id"]


def test_format_document_with_builtin_template():
    document_id = _create_document()

    response = client.post(f"/api/documents/{document_id}/format", data={"templateId": "academic-default"})

    assert response.status_code == 200
    body = response.json()
    assert body["templateId"] == "academic-default"
    assert body["resolvedStyles"]["Paragraph"]["font-family"] == "Times New Roman"
    assert body["elements"][0]["styleRef"] == "Heading 1"


def test_format_document_with_instructions_overrides_template():
    document_id = _create_document()
    instruction_response = AIInstructionExtractionResponse(
        rules=[AIFormattingRule(target="Heading 1", property="color", value="red")]
    )
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([instruction_response])
    try:
        response = client.post(
            f"/api/documents/{document_id}/format",
            data={"templateId": "academic-default", "instructionsText": "make headings red"},
        )
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 200
    assert response.json()["resolvedStyles"]["Heading 1"]["color"] == "red"


def test_format_document_with_instructions_file():
    document_id = _create_document()
    instruction_response = AIInstructionExtractionResponse(
        rules=[AIFormattingRule(target="Paragraph", property="fontFamily", value="Georgia")]
    )
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([instruction_response])
    try:
        response = client.post(
            f"/api/documents/{document_id}/format",
            files={"instructionsFile": ("rules.txt", b"Use Georgia font for body text.", "text/plain")},
        )
    finally:
        app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 200
    assert response.json()["resolvedStyles"]["Paragraph"]["font-family"] == "Georgia"


def test_format_document_rejects_unsupported_instructions_file_type():
    document_id = _create_document()

    response = client.post(
        f"/api/documents/{document_id}/format",
        files={
            "instructionsFile": (
                "rules.docx",
                b"not really a docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 400


def test_format_document_rejects_unknown_template():
    document_id = _create_document()

    response = client.post(f"/api/documents/{document_id}/format", data={"templateId": "does-not-exist"})

    assert response.status_code == 400


def test_format_unknown_document_returns_404():
    response = client.post("/api/documents/does-not-exist/format", data={"templateId": "academic-default"})

    assert response.status_code == 404
