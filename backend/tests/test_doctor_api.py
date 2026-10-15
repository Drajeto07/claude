"""Document Doctor v0 through the API: upload -> analyse -> propose -> accept -> check -> download (verified only)."""

import io
import pathlib
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app, base_url="https://testserver")
DOCTOR = pathlib.Path(__file__).parent / "fixtures" / "doctor"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(autouse=True)
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "doctor@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()


def _upload(name: str) -> dict:
    response = client.post("/api/v1/documents/upload", files={"file": (name, (DOCTOR / name).read_bytes(), DOCX)})
    assert response.status_code in (200, 201), response.text
    return response.json()


def _body(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        return package.read("word/document.xml")


def test_the_whole_flow_with_repairs_made_in_the_file():
    document = _upload("d13-mixed-report.docx")
    report = client.get(f"/api/v1/documents/{document['id']}/doctor").json()
    assert report["prototype"] is True and report["available"] is True and report["refusals"] == []
    kinds = sorted(repair["kind"] for repair in report["wordRepairs"])
    assert kinds == ["empty_paragraphs", "wide_table"]
    assert all(repair["where"] for repair in report["wordRepairs"])  # each says where it is
    assert all(finding["summary"] for finding in report["findings"])  # and each finding why

    chosen = {"wordRepairs": [repair["id"] for repair in report["wordRepairs"]]}
    check = client.post(f"/api/v1/documents/{document['id']}/doctor/check", json=chosen).json()
    assert check["verified"] is True
    assert [entry["name"] for entry in check["checks"]] == ["words", "headers", "untouched", "preserved", "package"]

    download = client.post(f"/api/v1/documents/{document['id']}/doctor/download", json=chosen)
    assert download.status_code == 200 and download.headers["X-SafeEdit"] == "verified"
    assert "repaired" in download.headers["content-disposition"]
    original = (DOCTOR / "d13-mixed-report.docx").read_bytes()
    assert _body(download.content).count(b"<w:p/>") < _body(original).count(b"<w:p/>")


def test_nothing_chosen_is_nothing_repaired_in_the_file_and_still_verified():
    document = _upload("d01-empty-spacing.docx")
    download = client.post(f"/api/v1/documents/{document['id']}/doctor/download", json={"wordRepairs": []})
    assert download.status_code == 200
    original = (DOCTOR / "d01-empty-spacing.docx").read_bytes()
    assert _body(download.content).count(b"<w:p/>") == _body(original).count(b"<w:p/>")


def test_editor_repairs_are_proposed_for_review_then_accepted_then_verified():
    document = _upload("d06-page-breaks.docx")
    proposed = client.post(f"/api/v1/documents/{document['id']}/doctor/proposals").json()
    assert proposed["proposalCount"] == 2
    waiting = [proposal for proposal in proposed["document"]["proposals"] if proposal["source"] == "health"]
    assert len(waiting) == 2  # nothing changed yet: proposals only
    for proposal in waiting:
        assert client.post(f"/api/v1/documents/{document['id']}/proposals/{proposal['id']}/accept").status_code == 200
    check = client.post(f"/api/v1/documents/{document['id']}/doctor/check", json={}).json()
    assert check["verified"] is True


def test_a_signed_file_is_refused_and_nothing_is_handed_out():
    document = _upload("d10-signed.docx")
    report = client.get(f"/api/v1/documents/{document['id']}/doctor").json()
    assert report["available"] is False and "signed" in [refusal["code"] for refusal in report["refusals"]]
    assert report["wordRepairs"] == [] and report["modelRepairs"] == 0
    assert client.post(f"/api/v1/documents/{document['id']}/doctor/proposals").status_code == 409
    refused = client.post(f"/api/v1/documents/{document['id']}/doctor/download", json={})
    assert refused.status_code == 409 and refused.json()["code"] == "not_verified"


def test_a_document_without_a_word_file_is_refused():
    document = client.post("/api/v1/documents", json={"text": "# Title\n\nA paragraph long enough to be one."}).json()
    report = client.get(f"/api/v1/documents/{document['id']}/doctor").json()
    assert report["available"] is False and report["refusals"][0]["code"] == "no_word_file"


def test_a_repair_that_no_longer_applies_is_refused():
    document = _upload("d01-empty-spacing.docx")
    response = client.post(f"/api/v1/documents/{document['id']}/doctor/check", json={"wordRepairs": ["empty:999"]})
    assert response.status_code == 409 and response.json()["code"] == "stale_repairs"


def test_the_original_is_kept_as_it_was():
    document = _upload("d13-mixed-report.docx")
    before = client.get(f"/api/v1/documents/{document['id']}").json()["sourcePackage"]
    report = client.get(f"/api/v1/documents/{document['id']}/doctor").json()
    client.post(f"/api/v1/documents/{document['id']}/doctor/download", json={"wordRepairs": [repair["id"] for repair in report["wordRepairs"]]})
    assert client.get(f"/api/v1/documents/{document['id']}").json()["sourcePackage"] == before


def test_the_feature_flag_turns_it_off(monkeypatch):
    document = _upload("d09-clean.docx")
    monkeypatch.setattr(get_settings(), "doctor_enabled", False)
    assert client.get(f"/api/v1/documents/{document['id']}/doctor").status_code == 404
    assert client.post(f"/api/v1/documents/{document['id']}/doctor/download", json={}).status_code == 404


def test_another_users_document_is_not_found():
    document = _upload("d09-clean.docx")
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": "long enough password"}).status_code == 201
    assert client.get(f"/api/v1/documents/{document['id']}/doctor").status_code == 404
    assert client.post(f"/api/v1/documents/{document['id']}/doctor/download", json={}).status_code == 404
