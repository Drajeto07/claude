"""What a save and a Word export cost (tracker PERF-008), held where it was measured:
a patch save dumps the document twice, not four times; an export works out each style's
id once, not once a paragraph; and the numbering ids of many lists are found without
scanning every list before them. The output is unchanged (the golden and fixture tests)."""

import io
import zipfile

from docx.parts.document import DocumentPart
from fastapi.testclient import TestClient
from lxml import etree

from app.export.docx_export import build_docx
from app.formatting.engine import recompute_styles
from app.main import app
from app.parsers.markdown import parse_markdown
from app.repositories import document_repository
from app.services import document_service

client = TestClient(app, base_url="https://testserver")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _long_markdown(sections: int) -> str:
    parts = ["# Title"]
    for n in range(sections):
        parts += [f"## Section {n}", f"Paragraph {n}.", f"- item {n}\n- another {n}", f"> a quote {n}", f"```\ncode {n}\n```"]
    return "\n\n".join(parts)


def test_a_patch_save_dumps_the_document_twice(api_db, monkeypatch):
    assert client.post("/api/v1/auth/register", json={"email": "costs@example.com", "password": "long enough password"}).status_code == 201
    document = client.post("/api/v1/documents", json={"text": _long_markdown(5)}).json()
    calls = []
    real = document_repository.dump_document
    for module in (document_service, document_repository):  # the service's dumps and the row's
        monkeypatch.setattr(module, "dump_document", lambda model: calls.append(1) or real(model))
    edited = dict(document["elements"][2], content="Changed.", inline=[{"text": "Changed.", "marks": []}])

    saved = client.patch(f"/api/v1/documents/{document['id']}/content", json={"changed": [edited]}, headers={"If-Match": str(document["revision"])})

    assert saved.status_code == 200
    # Before and after the change: the row, the undo step and the answer share the second.
    assert len(calls) == 2


def test_an_export_works_out_each_style_id_once(monkeypatch):
    document = parse_markdown(_long_markdown(60), "long")
    recompute_styles(document)
    asked = []
    real = DocumentPart.get_style_id
    monkeypatch.setattr(DocumentPart, "get_style_id", lambda part, style, kind: asked.append(getattr(style, "style_id", style)) or real(part, style, kind))

    build_docx(document)

    assert asked and len(asked) == len(set(asked))  # each style once, however many paragraphs use it


def test_many_lists_get_their_own_numbering_in_order():
    document = parse_markdown(_long_markdown(60), "long")
    recompute_styles(document)

    with zipfile.ZipFile(io.BytesIO(build_docx(document))) as package:
        numbering = etree.fromstring(package.read("word/numbering.xml"))
        body = etree.fromstring(package.read("word/document.xml"))
    num_ids = [int(num.get(f"{_W}numId")) for num in numbering.iter(f"{_W}num")]
    used = {int(value.get(f"{_W}val")) for value in body.iter(f"{_W}numId")}

    assert len(num_ids) == len(set(num_ids)) and num_ids == sorted(num_ids)
    assert len(used) >= 60 and used <= set(num_ids)  # a numbering of its own for every list
