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
