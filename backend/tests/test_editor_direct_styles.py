"""Alignment typed with a shortcut or pasted, and a picture's size, live on the
editor's blocks themselves; a content save carries them and they become each
element's own style (tracker EDIT-008, EDIT-009), checked like any other value."""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.main import app

client = TestClient(app, base_url="https://testserver")


@pytest.fixture
def document(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "direct@example.com", "password": "long enough password"}).status_code == 201
    yield client.post("/api/v1/documents", json={"text": "First paragraph.\n\nSecond paragraph."}).json()
    client.cookies.clear()


def _png_data_uri() -> str:
    buffer = io.BytesIO()
    PILImage.new("RGB", (30, 20), "red").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _save(document: dict, elements: list[dict], styles: list[dict]):
    return client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements, "styles": styles})


def test_alignment_and_picture_size_become_the_elements_own_style(document):
    first = document["elements"][0]
    picture = {"id": "pasted-picture", "type": "image", "content": "", "image": {"src": _png_data_uri()}, "order": 2}
    elements = [*document["elements"], picture]
    styles = [
        {"elementId": first["id"], "property": "alignment", "value": "center"},
        {"elementId": "pasted-picture", "property": "imageWidth", "value": "46.7", "unit": "%"},
    ]

    saved = _save(document, elements, styles)

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["resolvedStyles"][first["id"]]["text-align"] == "center"
    assert body["elements"][0]["styleRef"] == first["id"]
    assert body["resolvedStyles"]["pasted-picture"]["width"] == "46.7%"
    assert body["resolvedStyles"]["Paragraph"].get("text-align") != "center"  # only that paragraph
    assert len(body["revisions"]) == len(document["revisions"])  # part of the typing, not a change of its own

    again = _save(document | {"revision": body["revision"]}, body["elements"], styles).json()
    assert [rule for rule in again["formattingRules"] if rule["target"] == first["id"]] == [
        rule for rule in body["formattingRules"] if rule["target"] == first["id"]
    ]


def test_only_what_the_editor_sets_on_a_block_and_only_usable_values(document):
    first = document["elements"][0]

    for style in (
        {"elementId": first["id"], "property": "fontFamily", "value": "Georgia"},  # the Properties panel's, not the editor's
        {"elementId": first["id"], "property": "alignment", "value": "center;color:red"},
        {"elementId": first["id"], "property": "imageWidth", "value": "300", "unit": "px"},
    ):
        assert _save(document, document["elements"], [style]).status_code == 422, style

    ignored = _save(document, document["elements"], [{"elementId": "not-there", "property": "alignment", "value": "right"}])
    assert ignored.status_code == 200
    assert all(rule["target"] != "not-there" for rule in ignored.json()["formattingRules"])
