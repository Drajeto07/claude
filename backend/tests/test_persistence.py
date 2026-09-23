import json

from app.models.document import Document, DocumentMetadata, Element, ElementType
from app.services import persistence


def _document() -> Document:
    return Document(
        metadata=DocumentMetadata(title="Persisted"),
        elements=[Element(type=ElementType.PARAGRAPH, content="Body", order=0)],
    )


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_DATA_DIR", tmp_path)
    document = _document()

    persistence.save_document(document)
    loaded = persistence.load_all_documents()

    assert document.id in loaded
    assert loaded[document.id].metadata.title == "Persisted"
    assert loaded[document.id].elements[0].content == "Body"


def test_save_is_atomic_no_tmp_file_left_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_DATA_DIR", tmp_path)
    document = _document()

    persistence.save_document(document)

    files = list(tmp_path.glob("*"))
    assert len(files) == 1
    assert files[0].suffix == ".json"


def test_load_all_documents_skips_corrupt_file_without_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_DATA_DIR", tmp_path)
    good = _document()
    persistence.save_document(good)
    (tmp_path / "corrupt.json").write_text("{not valid json", encoding="utf-8")

    loaded = persistence.load_all_documents()

    assert good.id in loaded
    assert len(loaded) == 1


def test_load_all_documents_returns_empty_dict_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_DATA_DIR", tmp_path / "does-not-exist-yet")

    assert persistence.load_all_documents() == {}


def test_delete_document_file_removes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_DATA_DIR", tmp_path)
    document = _document()
    persistence.save_document(document)

    persistence.delete_document_file(document.id)

    assert persistence.load_all_documents() == {}


def test_saved_file_is_readable_plain_json(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "_DATA_DIR", tmp_path)
    document = _document()

    persistence.save_document(document)

    raw = json.loads((tmp_path / f"{document.id}.json").read_text(encoding="utf-8"))
    assert raw["id"] == document.id
