from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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
