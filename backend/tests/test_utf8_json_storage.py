"""Document JSON is stored as UTF-8 (PERF-006): Cyrillic as the letters, not as six-byte
\\uXXXX escapes, so a Bulgarian document's rows are about half the size. Rows written
before that (escaped) read as they always did, since json.loads takes both."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from app.db import session as db_session_module
from app.db.models import Document as DocumentRow
from app.db.models import ProcessingJob, Workspace
from app.db.session import get_engine as real_get_engine  # imported before the autouse fixture that refuses it
from app.db.session import make_engine
from app.db.types import dump_json
from app.main import app

TITLE = "Договор за наем"
MARKDOWN = f"# {TITLE}\n\nНаемодателят предоставя жилището на наемателя за срок от дванадесет месеца.\n\n- Първа точка\n- Втора точка"

client = TestClient(app, base_url="https://testserver")


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    response = client.post("/api/v1/auth/register", json={"email": "owner@example.com", "password": "long enough password"})
    assert response.status_code == 201
    yield api_db
    client.cookies.clear()


def _create() -> str:
    response = client.post("/api/v1/documents", json={"text": MARKDOWN})
    assert response.status_code == 201
    return response.json()["id"]


def _raw(engine, query: str) -> list[str]:
    """The column's text exactly as the database holds it, not as the model reads it."""
    with engine.connect() as connection:
        return [row[0] for row in connection.execute(text(query))]


# -- the serializer ----------------------------------------------------------------


def test_the_serializer_writes_letters_and_otherwise_matches_the_default():
    value = {"b": [1, 2.5, None, True], "a": "Договор", "nested": {"ключ": "стойност"}}

    assert dump_json(value) == json.dumps(value, ensure_ascii=False)
    assert "\\u04" not in dump_json(value)
    # Nothing else differs from what SQLAlchemy used (json.dumps): separators, key order, NaN.
    ascii_only = {"b": [1, {"x": "y"}], "a": float("nan"), "c": "é\n\"quoted\""}
    assert dump_json(ascii_only).replace("é", "\\u00e9") == json.dumps(ascii_only)
    assert dump_json({"a": float("nan")}) == '{"a": NaN}'


def test_an_unpaired_surrogate_keeps_its_escape_because_it_cannot_be_utf8():
    stored = dump_json({"text": "a\ud800b"})

    stored.encode("utf-8")  # would raise if the lone surrogate had been written raw
    assert json.loads(stored) == {"text": "a\ud800b"}


def test_the_applications_engine_uses_it(monkeypatch):
    monkeypatch.setattr(db_session_module, "get_settings", lambda: SimpleNamespace(database_url="sqlite+aiosqlite:///:memory:"))
    monkeypatch.setattr(db_session_module, "_engine", None)

    engine = real_get_engine()

    assert engine.sync_engine.dialect._json_serializer is dump_json
    monkeypatch.setattr(db_session_module, "_engine", None)


def test_every_engine_made_by_make_engine_uses_it():
    assert make_engine("sqlite+aiosqlite:///:memory:").sync_engine.dialect._json_serializer is dump_json


# -- what the database holds -------------------------------------------------------


def test_a_stored_document_holds_cyrillic_as_letters_not_escapes(signed_in):
    document_id = _create()

    stored = _raw(signed_in, "SELECT data FROM documents")
    versions = _raw(signed_in, "SELECT data FROM document_versions")

    assert len(stored) == 1 and TITLE in stored[0] and "\\u04" not in stored[0]
    assert versions and all("\\u04" not in data for data in versions)
    assert json.loads(stored[0])["metadata"]["title"] == TITLE
    # And after a save from the editor (the other way a row is written).
    elements = client.get(f"/api/v1/documents/{document_id}").json()["elements"]
    elements[1]["content"] = "Променен текст на абзаца."
    elements[1]["inline"] = [{"text": "Променен текст на абзаца.", "marks": []}]
    assert client.put(f"/api/v1/documents/{document_id}/content", json={"elements": elements}).status_code == 200
    assert all("Променен текст" in data and "\\u04" not in data for data in _raw(signed_in, "SELECT data FROM documents"))


async def test_any_json_column_is_written_as_letters(db_session):
    workspace = Workspace(name="Acme", slug="acme")
    db_session.add(workspace)
    await db_session.flush()
    db_session.add(ProcessingJob(workspace_id=workspace.id, job_type="import_text", payload={"text": "Здравей, свят"}, result={"title": TITLE}))
    await db_session.commit()

    rows = (await db_session.execute(text("SELECT payload, result FROM processing_jobs"))).all()

    assert rows[0][0] == '{"text": "Здравей, свят"}' and rows[0][1] == f'{{"title": "{TITLE}"}}'


def test_a_row_written_with_escapes_before_this_still_reads_and_is_rewritten_as_letters(signed_in):
    document_id = _create()
    letters = _raw(signed_in, "SELECT data FROM documents")[0]
    escaped = json.dumps(json.loads(letters))  # what every row looked like until PERF-006
    assert "\\u04" in escaped and TITLE not in escaped
    with signed_in.begin() as connection:
        connection.execute(text("UPDATE documents SET data = :data WHERE id = :id"), {"data": escaped, "id": document_id})
        connection.execute(text("UPDATE document_versions SET data = :data WHERE document_id = :id"), {"data": escaped, "id": document_id})

    with OrmSession(signed_in) as db:  # through the model
        row = db.get(DocumentRow, document_id)
    assert row is not None and row.data["metadata"]["title"] == TITLE
    assert row.data == json.loads(letters)
    loaded = client.get(f"/api/v1/documents/{document_id}")  # and through the API
    assert loaded.status_code == 200 and loaded.json()["metadata"]["title"] == TITLE
    assert client.patch(f"/api/v1/documents/{document_id}", json={"title": "Нов договор"}).status_code == 200
    assert "Нов договор" in _raw(signed_in, "SELECT data FROM documents")[0]


def test_a_bulgarian_text_takes_about_half_the_bytes_it_did(signed_in):
    document_id = _create()
    sentence = "Наемодателят предоставя жилището на наемателя за срок от дванадесет месеца. "
    elements = [
        {"id": f"p{n}", "type": "paragraph", "content": sentence * 5, "inline": [{"text": sentence * 5, "marks": []}], "order": n}
        for n in range(200)
    ]
    assert client.put(f"/api/v1/documents/{document_id}/content", json={"elements": elements}).status_code == 200

    letters = _raw(signed_in, "SELECT data FROM documents")[0]
    before = len(json.dumps(json.loads(letters)).encode("utf-8"))  # what the same row took with escapes
    after = len(letters.encode("utf-8"))

    # The text is two bytes a letter instead of six; the document's ASCII (its styles, the
    # field names) is the same, so the whole is a little over half.
    assert after < before * 0.6, (before, after)


# -- what goes out ----------------------------------------------------------------


def test_a_response_goes_out_as_utf8_letters(signed_in):
    document_id = _create()

    response = client.get(f"/api/v1/documents/{document_id}")

    assert response.headers["content-type"].split(";")[0] == "application/json"  # JSON is UTF-8 by definition: no charset to give
    assert TITLE.encode("utf-8") in response.content and b"\\u04" not in response.content
    assert json.loads(response.content.decode("utf-8"))["metadata"]["title"] == TITLE
