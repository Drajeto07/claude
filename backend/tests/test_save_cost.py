"""The pieces PERF-008 made a save out of, each held to what it replaced: JSON written a piece
at a time, the document read from a row's text, the stored form that is made once and
shared, the shorter way of working out what a patch changed, the row read as text, and the
garbage collector's setting. The save as a whole is held to its old output by
test_save_path_unchanged.py."""

import gc
import json
import random
import zlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app import main
from app.db import types
from app.db.base import Base
from app.db.models import DocumentVersion
from app.db.models.document import pack_snapshot
from app.db.session import make_engine
from app.db.types import EncodedJSON, dump_json, dumps_in_pieces
from app.formatting.engine import recompute_styles
from app.models.document import Document, InlineRun
from app.repositories.document_repository import DocumentRepository, document_from_json, dump_document, stored_form
from app.services.auth_service import AuthService
from app.services.content_patch import content_delta
from app.services.document_service import DocumentService
from app.services.ingestion_service import build_document_from_docx
from app.storage.local_provider import LocalStorageProvider
from scripts.benchmark import blocks_document
from tests.conftest import _enable_sqlite_fk

_FIXTURES = Path(__file__).parent / "fixtures"
_DOCX = sorted((_FIXTURES / "documents").glob("*.docx")) + sorted((_FIXTURES / "word").glob("*.docx"))


def _blocks(count: int) -> Document:
    return Document.model_validate({"elements": blocks_document(count)})


# -- JSON in pieces ---------------------------------------------------------------------


@pytest.mark.parametrize("options", [{}, {"separators": (",", ":")}, {"ensure_ascii": False}, {"ensure_ascii": False, "separators": (",", ":")}])
@pytest.mark.parametrize("count", [0, 1, 199, 200, 201, 400, 401, 1000])
def test_json_in_pieces_is_json_dumps(count, options):
    data = dump_document(_blocks(count))
    assert dumps_in_pieces(data, **options) == json.dumps(data, **options)


def test_json_in_pieces_is_json_dumps_for_what_a_document_does_not_hold_too():
    odd = {"empty": [], "list": [[1, 2.5, None, True, "ü \ud800"]] * 450, "nested": {"a": [{}] * 301}, "text": "Български \"текст\"\n", "n": -0.0, 7: "int key"}
    for options in ({}, {"ensure_ascii": False}, {"separators": (",", ":")}):
        assert dumps_in_pieces(odd, **options) == json.dumps(odd, **options)
    for other in ([1, 2, 3], "text", None, 5, [{"a": 1}] * 500):
        assert dumps_in_pieces(other) == json.dumps(other)


def test_json_in_pieces_never_dumps_more_than_a_piece_in_one_call(monkeypatch):
    """The point of the pieces: no single json.dumps (one C call, which keeps the
    interpreter's lock to its end) gets more than a piece of a list."""
    data = dump_document(_blocks(1000))
    longest, calls = [], []
    real = json.dumps

    def spy(value, **options):
        calls.append(1)
        longest.append(len(value) if isinstance(value, list) else 0)
        return real(value, **options)

    monkeypatch.setattr(types.json, "dumps", spy)
    text = dumps_in_pieces(data, ensure_ascii=False)
    monkeypatch.undo()

    assert max(longest) <= 200 and len(calls) >= 5  # 1000 elements, a piece is 200
    assert text == json.dumps(data, ensure_ascii=False)


def test_dump_json_is_the_same_text_in_pieces_surrogates_included():
    data = dump_document(_blocks(450))
    assert dump_json(data, in_pieces=True) == dump_json(data)
    data["elements"][300]["content"] = "lone \ud83d surrogate"  # only the escaped form can be written as UTF-8
    assert "\\ud83d" in dump_json(data, in_pieces=True)
    assert dump_json(data, in_pieces=True) == dump_json(data)
    wide = {"elements": [{"content": "x" * 600_000}] * 5, "tail": "\ud800"}  # past the size scanned at a time
    assert dump_json(wide, in_pieces=True) == dump_json(wide)


def test_a_snapshot_is_packed_as_it_always_was():
    data = dump_document(_blocks(450))
    assert pack_snapshot(data) == zlib.compress(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode(), 6)


# -- the stored form --------------------------------------------------------------------


def test_the_stored_form_is_the_dump_and_its_text_and_cannot_be_changed():
    document = _blocks(450)
    stored = stored_form(document)

    assert stored == dump_document(document) and isinstance(stored, dict)
    assert stored.text == dump_json(dump_document(document)) == dump_json(stored)
    assert json.loads(stored.text) == stored
    for change in (lambda: stored.__setitem__("id", "x"), lambda: stored.update(id="x"), lambda: stored.pop("id"), lambda: stored.clear(), lambda: stored.setdefault("q", 1)):
        with pytest.raises(TypeError):
            change()
    assert stored == dump_document(document)


def test_what_a_dict_holding_its_text_writes_is_that_text():
    data = EncodedJSON({"a": 1})
    data.text = '{"a":    1}'  # whatever text was made, dump_json hands on
    assert dump_json(data) == '{"a":    1}'
    assert dump_json({"a": 1}) == '{"a": 1}'


# -- the document from a row's text ---------------------------------------------------------


@pytest.fixture
def small_pieces(monkeypatch):
    monkeypatch.setattr(types, "_PIECE", 3)


@pytest.mark.parametrize("path", _DOCX, ids=lambda path: path.parent.name + "/" + path.name)
def test_a_fixture_is_stored_and_read_back_as_it_was(path, small_pieces):
    document = build_document_from_docx(path.read_bytes(), path.name, None)
    plain = dump_document(document)

    stored = stored_form(document)

    assert stored == plain and list(stored) == list(plain)
    assert stored.text == json.dumps(plain, ensure_ascii=False) == dump_json(plain)
    # Read back as a row's text is read: the same model as validating the dict, styles resolved again.
    whole = Document.model_validate({**json.loads(stored.text), "revision": 4})
    recompute_styles(whole)
    again = document_from_json(stored.text, 4)
    assert again == whole
    assert json.dumps(dump_document(again)) == json.dumps(dump_document(whole))


def test_a_row_s_text_with_other_spacing_or_escapes_reads_the_same():
    data = dump_document(_blocks(30))
    text = json.dumps(data, indent=2)  # as an older row, or another database, may hold it: spaced out, \u escapes
    assert json.dumps(dump_document(document_from_json(text, 3))) == json.dumps(dump_document(document_from_json(json.dumps(data, ensure_ascii=False), 3)))
    assert document_from_json(text, 3).revision == 3


def test_an_invalid_stored_document_still_fails_to_read():
    data = dump_document(_blocks(10))
    data["elements"][5]["type"] = "not-a-type"
    with pytest.raises(ValueError):
        document_from_json(json.dumps(data), 1)


# -- what a patch changed -----------------------------------------------------------------


def _old_delta(before: dict, after: dict, asked: list[str]) -> dict:
    """content_delta as it was written before PERF-008."""

    def without_order(element):
        return {key: value for key, value in element.items() if key != "order"}

    was = {element["id"]: without_order(element) for element in before["elements"]}
    order = [element["id"] for element in after["elements"]]
    return {
        "changed": [element for element in after["elements"] if was.get(element["id"]) != without_order(element)],
        "order": None if order == asked else order,
        "fields": {key: value for key, value in after.items() if key != "elements" and before.get(key) != value},
    }


def test_the_changes_of_a_patch_are_found_as_they_were():
    rng = random.Random(8)
    for round_ in range(60):
        elements = [{"id": f"e{n}", "order": n, "content": f"text {n}", "inline": [{"text": f"text {n}"}]} for n in range(rng.randint(0, 12))]
        before = {"elements": elements, "metadata": {"t": 1}, "rules": [1], "title": "a"}
        new = [dict(element, inline=list(element["inline"])) for element in elements]
        for _ in range(rng.randint(0, 4)):
            kind = rng.choice(["edit", "move", "drop", "add", "shuffle", "same-id-twice"])
            if kind == "edit" and new:
                rng.choice(new)["content"] = f"changed {rng.random()}"
            elif kind == "move" and new:
                new.insert(rng.randrange(len(new) + 1), new.pop(rng.randrange(len(new))))
            elif kind == "drop" and new:
                del new[rng.randrange(len(new))]
            elif kind == "add":
                new.insert(rng.randint(0, len(new)), {"id": f"n{rng.random()}", "order": 0, "content": "new"})
            elif kind == "shuffle":
                rng.shuffle(new)
            elif kind == "same-id-twice" and new:
                new.append(dict(rng.choice(new)))
        for index, element in enumerate(new):
            element["order"] = index
        after = {**before, "elements": new, "metadata": {"t": rng.choice([1, 2])}, "title": rng.choice(["a", "b"])}
        asked = [element["id"] for element in new] if rng.random() < 0.5 else [element["id"] for element in new][::-1]

        assert content_delta(before, after, asked) == _old_delta(before, after, asked), round_


# -- the database -------------------------------------------------------------------------


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def save_database(request):
    """Where the save runs: None for a SQLite file, else PostgreSQL's sessions (TEST-031,
    CI's migrations job), where the row's JSON is jsonb and comes back as text through a
    cast."""
    return request.getfixturevalue("postgres_sessions") if request.param == "postgres" else None


async def test_a_save_reads_the_row_as_text_and_writes_it_as_its_stored_form(save_database, tmp_path):
    engine = None
    if save_database is not None:
        sessions = save_database
    else:
        path = tmp_path / "save.db"
        sync_engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()
        engine = make_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
        event.listen(engine.sync_engine, "connect", _enable_sqlite_fk)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
    storage = LocalStorageProvider(tmp_path / "assets")
    try:
        async with sessions() as session:
            user = await AuthService(session).register("cost@example.com", "long enough password", None)
            created = await DocumentService(session, user_id=user.id, storage=storage).create(_blocks(450))
        async with sessions() as session:
            found = await DocumentRepository(session).get_row_with_json_for_user(created.id, user.id)
            assert found is not None
            row, text = found
            assert isinstance(text, str) and json.loads(text) == dump_document(created)
            assert "data" not in row.__dict__  # the row's own copy of the JSON is left unloaded
            assert await DocumentRepository(session).get_row_with_json_for_user(created.id, "someone-else") is None

        async with sessions() as session:
            element = created.elements[3]
            changed = element.model_copy(update={"content": "Typed in a patch.", "inline": [InlineRun(text="Typed in a patch.")]})
            saved, delta = await DocumentService(session, user_id=user.id, storage=storage).patch_content(
                created.id, changed=[changed], added=[], removed=[], styles=[]
            )
        async with sessions() as session:
            row = await DocumentRepository(session).get_row_for_user(created.id, user.id)
            stored = row.data
            newest = (
                await session.execute(select(DocumentVersion).where(DocumentVersion.document_id == created.id).order_by(DocumentVersion.revision_number.desc()))
            ).scalars().first()
            assert stored == dump_document(DocumentRepository.to_model(row)) and stored["elements"][3]["content"] == "Typed in a patch."
            assert newest.data == stored and row.revision == saved.revision == 2
            assert [item["id"] for item in delta["changed"]] == [element.id]
    finally:
        if engine is not None:
            await engine.dispose()


# -- the collector ------------------------------------------------------------------------


async def test_the_server_raises_the_collectors_young_threshold_at_start(monkeypatch):
    thresholds = gc.get_threshold()
    # Not the background jobs: they would reach for the real database.
    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={"job_backend": "eager", "gc_gen0_threshold": 12_345}))
    try:
        async with main.lifespan(main.app):
            assert gc.get_threshold() == (12_345, *thresholds[1:])
    finally:
        gc.set_threshold(*thresholds)


async def test_zero_leaves_the_interpreters_thresholds_alone(monkeypatch):
    thresholds = gc.get_threshold()
    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={"job_backend": "eager", "gc_gen0_threshold": 0}))
    async with main.lifespan(main.app):
        assert gc.get_threshold() == thresholds
