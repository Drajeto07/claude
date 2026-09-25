"""The frontend's types are generated from frontend/types/generated/openapi.json
(корекции.docx §8/§49): the committed file must be exactly what the API says,
or the frontend would compile against an API that no longer exists."""

import json

from app.main import app
from scripts.export_openapi import SCHEMA_FILE


def test_the_committed_openapi_schema_is_current():
    committed = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))

    assert committed == app.openapi(), (
        "The API changed: run `python -m scripts.export_openapi` in backend/, then `npm run generate-types` in frontend/."
    )


def test_responses_list_every_field_they_always_send():
    document = app.openapi()["components"]["schemas"]["Document"]

    assert set(document["required"]) == set(document["properties"])


def test_errors_are_documented_as_they_are_sent():
    schema = app.openapi()

    assert "HTTPValidationError" not in schema["components"]["schemas"]
    assert set(schema["components"]["schemas"]["ApiError"]["required"]) == {"code", "message", "details", "request_id"}
    invalid = schema["paths"]["/api/v1/documents/{document_id}"]["get"]["responses"]["422"]
    assert invalid["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/ApiError"


def test_a_jobs_result_is_one_of_the_documented_shapes():
    result = schema_of("JobOut")["properties"]["result"]

    documented = {option.get("$ref", "").rsplit("/", 1)[-1] for option in result["anyOf"]}
    assert documented == {"ImportJobResult", "FormatAppliedResult", "FormatConflictsResult", "ExportJobResult", "ReferenceStyleOut", ""}


def schema_of(name: str) -> dict:
    return app.openapi()["components"]["schemas"][name]
