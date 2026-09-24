import pytest
from fastapi.testclient import TestClient

from app.formatting import templates as templates_module
from app.main import app

client = TestClient(app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def signed_in(api_db):
    client.cookies.clear()
    response = client.post("/api/auth/register", json={"email": "owner@example.com", "password": "long enough password"})
    assert response.status_code == 201
    yield
    client.cookies.clear()


def test_templates_require_a_signed_in_user():
    client.cookies.clear()

    assert client.get("/api/templates").status_code == 401
    assert client.post("/api/templates", json={"name": "x", "category": "general", "rules": []}).status_code == 401


@pytest.fixture(autouse=True)
def _isolate_custom_templates_dir(tmp_path, monkeypatch):
    """Custom templates now persist to disk -- must not write into the real
    backend/data/custom_templates/ during tests, same isolation convention
    as test_templates.py/test_persistence.py."""
    monkeypatch.setattr(templates_module, "_CUSTOM_TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(templates_module, "_custom_templates", {})


def test_list_templates_includes_builtins():
    response = client.get("/api/templates")

    assert response.status_code == 200
    ids = {template["id"] for template in response.json()}
    assert {"academic-default", "professional-cv", "official-standard"} <= ids


def test_create_and_list_custom_template():
    payload = {
        "name": "Test Template",
        "category": "academic",
        "description": "A test template",
        "rules": [{"target": "Paragraph", "property": "fontFamily", "value": "Georgia"}],
    }

    create_response = client.post("/api/templates", json=payload)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["name"] == "Test Template"

    list_response = client.get("/api/templates")
    assert created["id"] in {template["id"] for template in list_response.json()}


def test_create_template_rejects_blank_name():
    payload = {"name": "   ", "category": "academic", "rules": []}

    response = client.post("/api/templates", json=payload)

    assert response.status_code == 422


def test_list_templates_preview_reflects_real_paragraph_rules():
    response = client.get("/api/templates")

    academic = next(t for t in response.json() if t["id"] == "academic-default")
    assert academic["preview"] == {"fontFamily": "Times New Roman", "alignment": "justify", "lineSpacing": "1.5"}


def test_custom_template_without_paragraph_rule_has_empty_preview():
    payload = {
        "name": "Headings Only",
        "category": "official",
        "rules": [{"target": "Heading 1", "property": "bold", "value": "true"}],
    }

    response = client.post("/api/templates", json=payload)

    assert response.status_code == 201
    assert response.json()["preview"] == {"fontFamily": None, "alignment": None, "lineSpacing": None}
