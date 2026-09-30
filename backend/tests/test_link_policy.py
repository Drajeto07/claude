"""Which addresses a link may have (tracker SEC-014): one policy, app/security/links.py,
for every way a link reaches a document and every export that writes one. The cases are
the editor's too (frontend/tests/fixtures/link-policy.json, read by
frontend/editor/linkPolicy.test.ts), so the two can't drift apart."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.export.docx_export import build_docx
from app.export.pdf_export import build_pdf
from app.formatting.engine import recompute_styles
from app.formatting.health import check_health
from app.main import app
from app.models.document import Document, DocumentMetadata, Element, ElementType, InlineRun, Mark, MarkType
from app.parsers.markdown import parse_markdown
from app.security.links import safe_href

client = TestClient(app, base_url="https://testserver")
_CASES = json.loads((Path(__file__).resolve().parents[2] / "frontend" / "tests" / "fixtures" / "link-policy.json").read_text(encoding="utf-8"))["cases"]


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "links@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()


@pytest.mark.parametrize(("href", "expected"), _CASES, ids=[ascii(case[0])[:40] for case in _CASES])
def test_the_policy_answers_every_case_as_the_editor_does(href, expected):
    assert safe_href(href) == expected


def test_an_address_too_long_to_follow_or_to_read_is_no_link():
    assert safe_href("https://example.com/" + "a" * 2028) is not None  # 2048 in all
    assert safe_href("https://example.com/" + "a" * 2029) is None
    # One urlsplit can't read (an IPv6 bracket left open). The editor's check doesn't parse
    # the host, so it would show this one as a link until the document is opened again.
    assert safe_href("https://[::1/x") is None


def _run(text: str, href: str) -> dict:
    return {"text": text, "marks": [{"type": "link", "href": href}]}


def test_a_link_keeps_only_an_address_a_document_can_open(signed_in):
    run = InlineRun(text="Click", marks=[Mark(type=MarkType.LINK, href="javascript:alert(1)"), Mark(type=MarkType.BOLD)])
    assert [mark.type for mark in run.marks] == [MarkType.BOLD] and run.text == "Click"
    assert InlineRun(text="Site", marks=[Mark(type=MarkType.LINK, href="www.example.com")]).marks[0].href == "https://www.example.com"

    # Whoever sends it: here the API, as a client other than the editor could.
    document = client.post("/api/v1/documents", json={"text": "# Links\n\nSome text."}).json()
    paragraph = {
        "type": "paragraph",
        "content": "run open wiki site",
        "order": 1,
        "inline": [_run("run ", "javascript:alert(1)"), _run("open ", "file:///c:/secret.docx"), _run("wiki ", "/wiki/Page"), _run("site", "https://example.com")],
    }
    saved = client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": [document["elements"][0], paragraph]})

    assert saved.status_code == 200, saved.text[:300]
    runs = saved.json()["elements"][1]["inline"]
    assert "".join(run["text"] for run in runs) == "run open wiki site"
    assert [mark["href"] for run in runs for mark in run["marks"]] == ["https://example.com"]


def test_markdown_links_to_other_addresses_keep_their_text_and_are_said_to():
    document = parse_markdown("[page](relative.html), [chat](irc://irc.example.com/room) and [site](https://example.com).")

    runs = document.elements[0].inline
    assert [mark.href for run in runs for mark in run.marks if mark.type == MarkType.LINK] == ["https://example.com"]
    assert document.elements[0].content == "page, chat and site."
    item = {item.feature: item for item in document.importReport.items}["markdown.link.unsafe"]
    assert (item.count, item.policy.value, item.contentChanged) == (2, "lossy", False)


def _with_unsafe_link() -> Document:
    """A document holding a javascript: link -- which the model never lets in, so it is
    put there past it, as an export could only ever be handed one by a bug."""
    element = Element(type=ElementType.PARAGRAPH, content="Click here", order=0, inline=[InlineRun(text="Click here", marks=[Mark(type=MarkType.LINK, href="https://example.com")])])
    element.inline[0].marks[0].href = "javascript:alert(1)"
    document = Document(metadata=DocumentMetadata(title="Links"), elements=[element])
    recompute_styles(document)
    return document


def test_no_export_writes_a_live_link_to_an_unsafe_address():
    word = build_docx(_with_unsafe_link())
    with zipfile.ZipFile(io.BytesIO(word)) as package:
        relationships = package.read("word/_rels/document.xml.rels").decode("utf-8")
        body = package.read("word/document.xml").decode("utf-8")
    assert "javascript" not in relationships and "w:hyperlink" not in body and "Click here" in body

    pdf = build_pdf(_with_unsafe_link())
    assert b"javascript" not in pdf
    assert "Click here" in PdfReader(io.BytesIO(pdf)).pages[0].extract_text()


def test_the_health_check_never_calls_an_unsafe_address_usable():
    links = next(check for check in check_health(_with_unsafe_link()).checks if check.id == "links")
    assert links.status == "fail"
