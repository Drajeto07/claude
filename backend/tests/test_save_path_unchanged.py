"""What a save stores and answers is the same as before PERF-008 (cheaper saves, off the
event loop): for a fixed sequence of edits -- patches, whole saves, a merged autosave, a
picture, a rename, undo/redo, a restore, and two documents from before version history --
the stored row, every version record and the answer are byte for byte what the code
before the change wrote.

`save_path_golden.json` holds the SHA-256 of each of them, recorded by the code of
8966ec7 (the base of PERF-008) with `SMARTDOC_RECORD_SAVE_GOLDEN=1 pytest
tests/test_save_path_unchanged.py`. Ids and times are different on every run, so before
hashing they are replaced by their order of appearance (`<id1>`, `<time>`); nothing else is
touched, so key order, separators, escapes and the compressed versions' JSON are compared as
written."""

import hashlib
import json
import os
import re
import uuid
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.db.models.document import pack_snapshot, unpack_snapshot
from app.db.types import dump_json
from app.main import app
from app.models.document import Document
from app.repositories.document_repository import dump_document
from tests.fakes import FakeAIProvider
from tests.test_content_patch import _patch, _picture

client = TestClient(app, base_url="https://testserver")
_GOLDEN = Path(__file__).parent / "fixtures" / "save_path_golden.json"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)")
_SHA = re.compile(r"\b[0-9a-f]{64}\b")
_TEXT = "# Report\n\nThe first paragraph.\n\n## Метод\n\nВторият параграф, на български.\n\nThe third paragraph.\n"


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 3)
    assert client.post("/api/v1/auth/register", json={"email": "golden@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


class _Normaliser:
    """Ids by order of first appearance, across every text of the run."""

    def __init__(self) -> None:
        self.ids: dict[str, str] = {}

    def __call__(self, text: str) -> str:
        text = _TIME.sub("<time>", text)
        text = _SHA.sub("<sha>", text)
        return _UUID.sub(lambda found: self.ids.setdefault(found.group(0), f"<id{len(self.ids) + 1}>"), text)


def _digest(text: str) -> dict:
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "chars": len(text)}


def _fixed_id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"save-path/{name}"))


def _paragraph(name: str, text: str) -> dict:
    return {"id": _fixed_id(name), "type": "paragraph", "content": text, "order": 0, "inline": [{"text": text, "marks": []}]}


def _retyped(element: dict, text: str) -> dict:
    return {**element, "content": text, "inline": [{"text": text, "marks": []}]}


def _stored(api_db, document_id: str, normalise: _Normaliser, answer: str) -> dict:
    with api_db.connect() as connection:
        row = connection.exec_driver_sql("SELECT data, revision, current_version FROM documents WHERE id = ?", (document_id,)).one()
        versions = connection.exec_driver_sql(
            "SELECT revision_number, kind, description, compressed_data, data FROM document_versions WHERE document_id = ? ORDER BY revision_number",
            (document_id,),
        ).all()
    return {
        "row": {**_digest(normalise(row.data)), "revision": row.revision, "current_version": row.current_version},
        "versions": [
            {
                "number": version.revision_number,
                "kind": version.kind,
                "description": version.description,
                **_digest(normalise(zlib.decompress(version.compressed_data).decode("utf-8") if version.compressed_data is not None else version.data)),
            }
            for version in versions
        ],
        "answer": _digest(normalise(answer)),
    }


def _legacy(api_db, document_id: str, extra: list[dict] | None = None) -> None:
    """The document as an older version of the app left it: its JSON with \\u escapes
    (and, when asked, with a picture still inline) and no version rows at all."""
    data = client.get(f"/api/v1/documents/{document_id}").json()
    data.pop("revision")
    data["elements"] = data["elements"] + (extra or [])
    with api_db.begin() as connection:
        connection.exec_driver_sql("DELETE FROM document_versions WHERE document_id = ?", (document_id,))
        connection.exec_driver_sql("UPDATE documents SET data = ? WHERE id = ?", (json.dumps(data), document_id))


def _run(api_db) -> list[dict]:
    normalise = _Normaliser()
    steps: list[dict] = []
    path = ""
    revision = 0
    document_id = ""

    def record(name: str, response) -> None:
        nonlocal revision
        assert response.status_code in (200, 201), (name, response.text[:300])
        steps.append({"step": name, **_stored(api_db, document_id, normalise, response.text)})
        revision = client.get(f"/api/v1/documents/{document_id}").json()["revision"]

    def patch(name: str, base: list[dict], new: list[dict], styles: list[dict] | None = None) -> None:
        body = {**_patch(base, [{**element, "order": index} for index, element in enumerate(new)]), "styles": styles or []}
        record(name, client.patch(path, json=body, headers={"If-Match": str(revision)}))

    created = client.post("/api/v1/documents", json={"text": _TEXT})
    document_id = created.json()["id"]
    path = f"/api/v1/documents/{document_id}/content"
    record("create", created)
    elements = created.json()["elements"]

    # Typing, twice: the second merges into the first one's undo step.
    typed = [_retyped(elements[1], "The first paragraph, typed."), *elements[2:]]
    patch("patch: type", elements, [elements[0], *typed])
    stored = client.get(f"/api/v1/documents/{document_id}").json()["elements"]
    patch("patch: type again (merges)", stored, [stored[0], _retyped(stored[1], "The first paragraph, typed twice."), *stored[2:]])

    # A whole save: a block inserted, a heading's level changed, a block centred.
    stored = client.get(f"/api/v1/documents/{document_id}").json()["elements"]
    whole = [stored[0], _paragraph("inserted", "Inserted, with “quotes” and a tab\t."), {**stored[2], "level": 3}, *stored[1:2], *stored[3:]]
    whole = [{**element, "order": index} for index, element in enumerate(whole)]
    styles = [{"elementId": stored[1]["id"], "property": "alignment", "value": "center", "unit": None}]
    record("put: whole list", client.put(path, json={"elements": whole, "styles": styles}, headers={"If-Match": str(revision)}))

    # A pasted picture; then a patch that changes, adds and removes at once.
    stored = client.get(f"/api/v1/documents/{document_id}").json()["elements"]
    picture = {**_picture(), "id": _fixed_id("picture")}
    patch("patch: picture", stored, [stored[0], picture, *stored[1:]])
    stored = client.get(f"/api/v1/documents/{document_id}").json()["elements"]
    patch(
        "patch: change, add, remove",
        stored,
        [_retyped(stored[0], "Report, retitled"), *stored[1:3], _paragraph("tail", "A new last block."), *stored[4:]],
    )

    # Writes of other kinds, and undo/redo/restore (which only move the pointer).
    record("rename", client.patch(f"/api/v1/documents/{document_id}", json={"title": "Renamed — преименуван"}))
    record("add a page", client.post(f"/api/v1/documents/{document_id}/pages", json={"afterElementId": None}))
    record("undo", client.post(f"/api/v1/documents/{document_id}/undo"))
    record("undo again", client.post(f"/api/v1/documents/{document_id}/undo"))
    record("redo", client.post(f"/api/v1/documents/{document_id}/redo"))
    record("restore the original", client.post(f"/api/v1/documents/{document_id}/versions/1/restore"))
    stored = client.get(f"/api/v1/documents/{document_id}").json()["elements"]
    record("put after a restore", client.put(path, json={"elements": [_retyped(stored[0], "After the restore"), *stored[1:]]}))

    # A document from before version history, escaped JSON and no steps: its pre-change
    # state becomes the base step.
    _legacy(api_db, document_id)
    stored = client.get(f"/api/v1/documents/{document_id}").json()
    revision = stored["revision"]
    patch("legacy: patch", stored["elements"], [stored["elements"][0], *[_retyped(stored["elements"][1], "Typed on an old row")], *stored["elements"][2:]])

    # The same, with a picture still inline in the old JSON: it moves before any step is recorded.
    old_picture = {"id": _fixed_id("old-picture"), "type": "image", "content": "", "order": 99, "image": _picture()["image"]}
    _legacy(api_db, document_id, extra=[old_picture])
    stored = client.get(f"/api/v1/documents/{document_id}").json()
    revision = stored["revision"]
    patch("legacy with a picture: patch", stored["elements"], [_retyped(stored["elements"][0], "Typed on an old row with a picture"), *stored["elements"][1:]])
    record("legacy with a picture: rename", client.patch(f"/api/v1/documents/{document_id}", json={"title": "After"}))
    return steps


def test_what_a_save_stores_and_answers_is_what_it_was_before_perf_008(signed_in, api_db):
    steps = _run(api_db)

    if os.environ.get("SMARTDOC_RECORD_SAVE_GOLDEN"):
        _GOLDEN.write_text(json.dumps(steps, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        pytest.skip("recorded")
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert [step["step"] for step in steps] == [step["step"] for step in golden]
    for step, expected in zip(steps, golden):
        assert step["row"] == expected["row"], f"{step['step']}: the stored row differs"
        assert step["versions"] == expected["versions"], f"{step['step']}: a version record differs"
        assert step["answer"] == expected["answer"], f"{step['step']}: the answer differs"


# -- what is stored is what a fresh dump of the saved state is ---------------------------


def test_the_row_and_the_newest_version_are_both_a_fresh_dump_of_the_saved_document(signed_in, api_db):
    """The row, the version record and the answer share one dump (PERF-008). Each is
    compared with a dump made afresh from what the API gives back, after every save."""
    created = client.post("/api/v1/documents", json={"text": _TEXT}).json()
    path = f"/api/v1/documents/{created['id']}/content"
    elements = created["elements"]
    revision = created["revision"]

    for step in range(4):
        edited = [elements[0], _retyped(elements[1], f"Typed {step}."), *elements[2:]]
        if step % 2:
            answer = client.put(path, json={"elements": [{**element, "order": index} for index, element in enumerate(edited)]})
            assert answer.status_code == 200
            revision = answer.json()["revision"]
        else:
            answer = client.patch(path, json=_patch(elements, [{**e, "order": i} for i, e in enumerate(edited)]), headers={"If-Match": str(revision)})
            assert answer.status_code == 200
            revision = answer.json()["revision"]
        saved = client.get(f"/api/v1/documents/{created['id']}").json()
        elements = saved["elements"]
        fresh = dump_document(Document.model_validate(saved))
        with api_db.connect() as connection:
            row = connection.exec_driver_sql("SELECT data FROM documents").scalar_one()
            newest = connection.exec_driver_sql("SELECT compressed_data FROM document_versions ORDER BY revision_number DESC LIMIT 1").scalar_one()
        assert row == dump_json(fresh), step
        assert zlib.decompress(newest) == pack_text(fresh), step
        assert unpack_snapshot(newest, None) == fresh, step


def test_a_save_dumps_the_document_twice_not_four_times(signed_in, monkeypatch):
    """Before the change and after it: a patch and a whole save each dumped it four times
    (before, the row, the version record, the answer), a rename three times."""
    created = client.post("/api/v1/documents", json={"text": _TEXT}).json()
    path = f"/api/v1/documents/{created['id']}/content"
    elements = created["elements"]
    dumps: list[int] = []
    real = Document.model_dump

    def counting(self, *args, **kwargs):
        if type(self) is Document:
            dumps.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Document, "model_dump", counting)
    edited = [elements[0], _retyped(elements[1], "Typed."), *elements[2:]]
    steps = {
        "patch": lambda: client.patch(path, json=_patch(elements, [{**e, "order": i} for i, e in enumerate(edited)]), headers={"If-Match": str(created["revision"])}),
        "put": lambda: client.put(path, json={"elements": [{**e, "order": i} for i, e in enumerate(edited)]}),
        "rename": lambda: client.patch(f"/api/v1/documents/{created['id']}", json={"title": "Renamed"}),
    }
    for name, save in steps.items():
        dumps.clear()
        assert save().status_code == 200, name
        assert len(dumps) == 2, (name, len(dumps))


def pack_text(data: dict) -> bytes:
    # What pack_snapshot compresses: compact JSON in UTF-8.
    assert zlib.decompress(pack_snapshot(data)) == json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
