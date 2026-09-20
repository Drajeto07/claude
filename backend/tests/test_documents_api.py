import io
import json
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


def test_set_and_clear_element_style():
    document_id = _create_document()
    formatted = client.post(f"/api/documents/{document_id}/format", data={"templateId": "academic-default"}).json()
    paragraph_id = formatted["elements"][1]["id"]  # index 0 is the heading

    set_response = client.patch(
        f"/api/documents/{document_id}/elements/{paragraph_id}/style",
        json={"property": "fontFamily", "value": "Georgia"},
    )
    assert set_response.status_code == 200
    body = set_response.json()
    assert body["resolvedStyles"][paragraph_id]["font-family"] == "Georgia"
    assert body["elements"][1]["styleRef"] == paragraph_id
    # The coarse "Paragraph" target (and any other paragraph) is unaffected.
    assert body["resolvedStyles"]["Paragraph"]["font-family"] == "Times New Roman"

    clear_response = client.delete(f"/api/documents/{document_id}/elements/{paragraph_id}/style/fontFamily")
    assert clear_response.status_code == 200
    cleared_body = clear_response.json()
    assert paragraph_id not in cleared_body["resolvedStyles"]
    assert cleared_body["elements"][1]["styleRef"] == "Paragraph"


def test_set_element_style_rejects_unknown_element():
    document_id = _create_document()

    response = client.patch(
        f"/api/documents/{document_id}/elements/does-not-exist/style",
        json={"property": "fontFamily", "value": "Georgia"},
    )

    assert response.status_code == 404


def test_set_element_style_unknown_document_returns_404():
    response = client.patch(
        "/api/documents/does-not-exist/elements/also-does-not-exist/style",
        json={"property": "fontFamily", "value": "Georgia"},
    )

    assert response.status_code == 404


def test_format_document_returns_409_when_conflict_exists():
    document_id = _create_document()
    formatted = client.post(f"/api/documents/{document_id}/format", data={"templateId": "academic-default"}).json()
    paragraph_id = formatted["elements"][1]["id"]
    client.patch(f"/api/documents/{document_id}/elements/{paragraph_id}/style", json={"property": "color", "value": "red"})

    custom = client.post(
        "/api/templates",
        json={
            "name": "Conflict Test Template",
            "category": "academic",
            "rules": [{"target": "Paragraph", "property": "color", "value": "blue"}],
        },
    ).json()

    response = client.post(f"/api/documents/{document_id}/format", data={"templateId": custom["id"]})

    assert response.status_code == 409
    conflicts = response.json()["detail"]["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["elementId"] == paragraph_id
    assert conflicts[0]["property"] == "color"
    assert conflicts[0]["currentValue"] == "red"
    assert conflicts[0]["requiredValue"] == "blue"

    # Nothing was actually applied -- the document is unchanged.
    unchanged = client.get(f"/api/documents/{document_id}").json()
    assert unchanged["templateId"] == "academic-default"
    assert unchanged["resolvedStyles"][paragraph_id]["color"] == "red"


def test_format_document_with_resolutions_applies_correctly():
    document_id = _create_document()
    formatted = client.post(f"/api/documents/{document_id}/format", data={"templateId": "academic-default"}).json()
    paragraph_id = formatted["elements"][1]["id"]
    client.patch(f"/api/documents/{document_id}/elements/{paragraph_id}/style", json={"property": "color", "value": "red"})

    custom = client.post(
        "/api/templates",
        json={
            "name": "Conflict Test Template 2",
            "category": "academic",
            "rules": [{"target": "Paragraph", "property": "color", "value": "blue"}],
        },
    ).json()

    resolutions = [{"elementId": paragraph_id, "property": "color", "resolution": "apply_recommended"}]
    response = client.post(
        f"/api/documents/{document_id}/format",
        data={"templateId": custom["id"], "resolutions": json.dumps(resolutions)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["templateId"] == custom["id"]
    assert body["resolvedStyles"]["Paragraph"]["color"] == "blue"
    # The override was dropped (resolution: apply_recommended) -- no more per-element entry.
    assert paragraph_id not in body["resolvedStyles"]


def test_undo_redo_round_trip_through_format_and_override():
    document_id = _create_document()
    original = client.get(f"/api/documents/{document_id}").json()
    assert original["templateId"] is None

    client.post(f"/api/documents/{document_id}/format", data={"templateId": "academic-default"})
    after_format = client.get(f"/api/documents/{document_id}").json()
    assert after_format["templateId"] == "academic-default"

    undo_response = client.post(f"/api/documents/{document_id}/undo")
    assert undo_response.status_code == 200
    assert undo_response.json()["templateId"] is None

    redo_response = client.post(f"/api/documents/{document_id}/redo")
    assert redo_response.status_code == 200
    assert redo_response.json()["templateId"] == "academic-default"


def test_undo_with_nothing_to_undo_returns_400():
    document_id = _create_document()

    response = client.post(f"/api/documents/{document_id}/undo")

    assert response.status_code == 400


def test_redo_with_nothing_to_redo_returns_400():
    document_id = _create_document()

    response = client.post(f"/api/documents/{document_id}/redo")

    assert response.status_code == 400


def test_undo_unknown_document_returns_404():
    response = client.post("/api/documents/does-not-exist/undo")

    assert response.status_code == 404


def test_redo_unknown_document_returns_404():
    response = client.post("/api/documents/does-not-exist/redo")

    assert response.status_code == 404
