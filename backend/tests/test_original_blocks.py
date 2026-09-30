"""Blocks the user didn't change are written back as they are in the original
Word file (tracker DOCX-028): what the document model doesn't hold -- a field's
code, a content control, a double underline, hidden text, a bookmark, a section
break -- survives them. A changed or restyled block is written anew; one whose
XML isn't self-contained (tracked changes, a field running across paragraphs)
always is. Earlier sections copied with their blocks take what the page setup,
header or footer changed in the app."""

import hashlib
import io
import json
import zipfile
from uuid import uuid4

import pytest
from docx import Document as DocxDocument
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm
from fastapi.testclient import TestClient
from PIL import Image

from app.export.docx_export import build_docx
from app.export.package_check import package_problems
from app.export.provenance import _canonical, look, stamp, unchanged
from app.fidelity.content import compare_words, document_words, words
from app.fidelity.docx_source import read_docx_source
from app.fidelity.report import ReportBuilder
from app.formatting.engine import recompute_styles
from app.main import app
from app.models.document import Document, Element, ElementType
from app.parsers.docx import parse_docx
from tests.test_golden_documents import FIXTURES, GOLDEN

client = TestClient(app, base_url="https://testserver")
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_W = nsdecls("w")


def _saved(word) -> bytes:
    buffer = io.BytesIO()
    word.save(buffer)
    return buffer.getvalue()


def _word_file() -> bytes:
    word = DocxDocument()
    first = word.sections[0]
    first.orientation, first.page_width, first.page_height = WD_ORIENT.LANDSCAPE, first.page_height, first.page_width
    word.add_heading("Report", level=1)
    field = word.add_paragraph("Written by ")
    field._p.append(parse_xml(f'<w:r {_W}><w:fldChar w:fldCharType="begin"/></w:r>'))
    field._p.append(parse_xml(f'<w:r {_W}><w:instrText xml:space="preserve"> AUTHOR </w:instrText></w:r>'))
    field._p.append(parse_xml(f'<w:r {_W}><w:fldChar w:fldCharType="separate"/></w:r>'))
    field._p.append(parse_xml(f'<w:r {_W}><w:t>Ana Petrova</w:t></w:r>'))
    field._p.append(parse_xml(f'<w:r {_W}><w:fldChar w:fldCharType="end"/></w:r>'))
    word.element.body.insert(
        len(word.element.body) - 1,
        parse_xml(
            f'<w:sdt {_W}><w:sdtPr><w:alias w:val="Status"/><w:tag w:val="status"/></w:sdtPr>'
            "<w:sdtContent><w:p><w:r><w:t>Draft for review</w:t></w:r></w:p></w:sdtContent></w:sdt>"
        ),
    )
    styled = word.add_paragraph("Marked ")
    styled._p.append(parse_xml(f'<w:r {_W}><w:rPr><w:u w:val="double"/></w:rPr><w:t>twice</w:t></w:r>'))
    styled._p.append(parse_xml(f'<w:r {_W}><w:rPr><w:vanish/></w:rPr><w:t xml:space="preserve"> secret</w:t></w:r>'))
    marked = word.add_paragraph()
    marked._p.append(parse_xml(f'<w:bookmarkStart {_W} w:id="7" w:name="Results"/>'))
    marked._p.append(parse_xml(f'<w:r {_W}><w:t>The results section.</w:t></w:r>'))
    marked._p.append(parse_xml(f'<w:bookmarkEnd {_W} w:id="7"/>'))
    last = word.add_section(WD_SECTION.NEW_PAGE)  # the landscape first section ends here
    last.orientation, last.page_width, last.page_height = WD_ORIENT.PORTRAIT, last.page_height, last.page_width
    word.add_paragraph("An edited paragraph.")
    tracked = word.add_paragraph("Tracked ")
    tracked._p.append(parse_xml(f'<w:ins {_W} w:id="1" w:author="Ana" w:date="2026-01-01T00:00:00Z"><w:r><w:t>insertion</w:t></w:r></w:ins>'))
    return _saved(word)


def _upload(email: str, data: bytes) -> dict:
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": email, "password": "long enough password"}).status_code == 201
    response = client.post("/api/v1/documents/upload", files={"file": ("report.docx", data, _DOCX)})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def uploaded(api_db):
    yield _upload("blocks@example.com", _word_file())
    client.cookies.clear()


def _export(document_id: str, **params) -> tuple[bytes, str]:
    response = client.get(f"/api/v1/documents/{document_id}/export/docx", params=params)
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as package:
        return response.content, package.read("word/document.xml").decode("utf-8")


def _report(document_id: str) -> dict:
    job = client.post("/api/v1/jobs/export", json={"documentId": document_id, "format": "docx"}).json()
    return client.get(f"/api/v1/jobs/{job['id']}").json()["result"]["fidelity"]


def _set(document_id: str, setting: str, value: str, unit: str | None = None) -> None:
    payload = {"property": setting, "value": value, **({"unit": unit} if unit else {})}
    response = client.patch(f"/api/v1/documents/{document_id}/settings", json=payload)
    assert response.status_code == 200, response.text


def _save(document_id: str, elements: list[dict]) -> dict:
    response = client.put(f"/api/v1/documents/{document_id}/content", json={"elements": elements})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("name", GOLDEN)
def test_an_unchanged_golden_document_is_copied_into_a_sound_package(name):
    original = (FIXTURES / name).read_bytes()
    document = parse_docx(original, name)
    recompute_styles(document)
    stamp(document)  # as an upload does
    report = ReportBuilder()

    exported = build_docx(document, source=original, report=report)

    assert package_problems(exported) == []  # pictures, links, lists, notes and tables copied with what they refer to
    assert compare_words(document_words(document.elements), words(read_docx_source(exported).body), method="t").verified
    assert "export.docx.original_blocks" in {item.feature for item in report.items()}


# The fields a block stored before each step of the model didn't have yet.
_ADDED_SINCE = {
    "DOCX-028": {"headerBold", "heightRule", "repeatHeader", "cantSplit", "flipHorizontal", "flipVertical"},
    "DOCX-017 part 1a": {"cantSplit", "flipHorizontal", "flipVertical"},
    "DOCX-017 part 1b": {"flipHorizontal", "flipVertical"},
}


def _stored_then(document: Document, element: Element, missing: set[str]) -> Element:
    """The element as stored before the model had the `missing` fields -- its
    fingerprint as it was stamped then (every field counted, defaults too) -- and
    loaded now, the fields it lacked at their defaults."""

    def then(value):
        if isinstance(value, dict):
            return {key: then(item) for key, item in value.items() if key not in missing}
        return [then(item) for item in value] if isinstance(value, list) else value

    stored = then(element.model_dump(mode="json"))
    loaded = Element.model_validate(stored)
    data = {"element": _canonical(stored), "look": _canonical(look(document, loaded))}
    loaded.sourceHash = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return loaded


@pytest.mark.parametrize("step", sorted(_ADDED_SINCE))
@pytest.mark.parametrize("name", ["04-images.docx", "16-table-engine.docx"])
def test_a_block_stored_before_the_model_grew_is_still_unchanged(name, step):
    document = parse_docx((FIXTURES / name).read_bytes(), name)
    recompute_styles(document)
    document.elements = [_stored_then(document, element, _ADDED_SINCE[step]) if element.sourceBlocks else element for element in document.elements]
    kept = [element for element in document.elements if element.sourceBlocks]

    assert kept and all(unchanged(document, element) for element in kept)
    stamp(document)  # stamped now: defaults left out, so the model can grow again
    assert all(unchanged(document, element) for element in kept)
    changed = next(element for element in kept if element.type in (ElementType.IMAGE, ElementType.TABLE))
    if changed.image:
        changed.image.flipVertical = True
    else:
        changed.table.rows[0].cantSplit = True
    assert not unchanged(document, changed)


def test_what_the_model_doesnt_hold_survives_in_unchanged_blocks(uploaded):
    exported, body = _export(uploaded["id"])

    assert "AUTHOR" in body and 'w:fldCharType="begin"' in body  # the field's code, not only its result
    assert '<w:alias w:val="Status"/>' in body  # the content control
    assert 'w:val="double"' in body and "<w:vanish/>" in body  # the double underline, the hidden text
    assert 'w:name="Results"' in body  # the bookmark
    assert body.count("<w:sectPr") == 2 and 'w:orient="landscape"' in body  # the landscape first section
    assert package_problems(exported) == []
    assert compare_words(document_words(Document.model_validate(uploaded).elements), words(read_docx_source(exported).body), method="t").verified


def test_a_changed_block_is_written_anew_and_the_rest_kept(uploaded):
    elements = uploaded["elements"]
    edited = next(element for element in elements if element["content"] == "Marked twice secret")
    edited["content"] = "Marked once"
    edited["inline"] = [{"text": "Marked once", "marks": []}]
    _save(uploaded["id"], elements)

    exported, body = _export(uploaded["id"])

    assert "Marked once" in body and 'w:val="double"' not in body  # written anew
    assert "AUTHOR" in body and '<w:alias w:val="Status"/>' in body  # the others as they were
    assert package_problems(exported) == []


def test_a_block_restyled_here_is_written_anew_and_page_breaks_keep_their_sections(uploaded):
    assert client.post(f"/api/v1/documents/{uploaded['id']}/format", data={"templateId": "academic-default"}).status_code == 200

    exported, body = _export(uploaded["id"])

    # Written anew in the template's look, not copied -- its content control around it again (DOCX-023).
    assert '<w:alias w:val="Status"/><w:tag w:val="status"/></w:sdtPr><w:sdtContent><w:p><w:pPr/>' in body
    assert body.count("<w:sectPr") == 2  # the section break sits on the page break's own paragraph: kept
    assert package_problems(exported) == []
    assert "export.docx.section_lost" not in {item["feature"] for item in _report(uploaded["id"])["items"]}


def test_where_a_block_came_from_is_the_servers_to_say(uploaded):
    elements = uploaded["elements"]
    original = next(element for element in elements if element["content"] == "Marked twice secret")
    heading = next(element for element in elements if element["content"] == "Report")
    copy = {**original, "id": str(uuid4())}  # a second copy of the block, claiming its original XML
    elements.insert(elements.index(original) + 1, copy)
    heading["sourceBlocks"] = [0, 1, 2, 3]  # and a block claiming more of it

    saved = {element["id"]: element for element in _save(uploaded["id"], elements)["elements"]}

    assert saved[copy["id"]]["sourceBlocks"] is None and saved[copy["id"]]["sourceHash"] is None
    assert saved[heading["id"]]["sourceBlocks"] == [0]
    _, body = _export(uploaded["id"])
    assert body.count(">twice<") == 2  # both copies written: never one child for two blocks
    assert body.count("AUTHOR") == 1


def test_tracked_changes_are_copied_unless_they_are_accepted(uploaded):
    """DOCX-022: kept for Word by default; accepted, as chosen, they are in no export."""
    _, body = _export(uploaded["id"])
    assert '<w:ins w:id="1" w:author="Ana"' in body  # the unchanged paragraph copied with its insertion

    assert client.put(f"/api/v1/documents/{uploaded['id']}/tracked-changes", json={"choice": "accepted"}).status_code == 200
    _, body = _export(uploaded["id"])

    assert "<w:ins " not in body and "Tracked insertion" in body.replace("</w:t></w:r><w:r><w:t>", "")


def test_a_moved_block_is_copied_where_the_document_has_it(uploaded):
    elements = uploaded["elements"]
    heading = elements.pop(0)
    elements.append(heading)  # the heading moved to the end, unchanged
    for order, element in enumerate(elements):
        element["order"] = order
    _save(uploaded["id"], elements)

    exported, body = _export(uploaded["id"])

    assert body.index("Report") > body.index("An edited paragraph.")
    assert package_problems(exported) == []


def test_a_field_across_paragraphs_is_written_anew(api_db):
    word = DocxDocument()
    start = word.add_paragraph()
    start._p.append(parse_xml(f'<w:r {_W}><w:fldChar w:fldCharType="begin"/></w:r>'))
    start._p.append(parse_xml(f'<w:r {_W}><w:instrText xml:space="preserve"> TOC \\o "1-3" </w:instrText></w:r>'))
    start._p.append(parse_xml(f'<w:r {_W}><w:fldChar w:fldCharType="separate"/></w:r>'))
    start._p.append(parse_xml(f'<w:r {_W}><w:t>Introduction 1</w:t></w:r>'))
    end = word.add_paragraph()
    end._p.append(parse_xml(f'<w:r {_W}><w:t>Results 2</w:t></w:r>'))
    end._p.append(parse_xml(f'<w:r {_W}><w:fldChar w:fldCharType="end"/></w:r>'))
    word.add_paragraph("Body text.")
    document = _upload("toc@example.com", _saved(word))

    exported, body = _export(document["id"])
    client.cookies.clear()

    assert package_problems(exported) == []
    assert body.count('w:fldCharType="begin"') == body.count('w:fldCharType="end"')  # never half a field


def test_the_export_report_says_blocks_were_kept(uploaded):
    report = _report(uploaded["id"])

    assert {"export.docx.source_package", "export.docx.original_blocks"} <= {item["feature"] for item in report["items"]}
    assert report["content"]["verified"]


def test_a_page_setup_changed_here_applies_to_every_section(uploaded):
    _set(uploaded["id"], "marginLeft", "3", "cm")
    _set(uploaded["id"], "pageSize", "Letter")

    exported, _ = _export(uploaded["id"])

    first, last = DocxDocument(io.BytesIO(exported)).sections
    assert round(first.left_margin.cm, 2) == round(last.left_margin.cm, 2) == 3.0
    assert first.orientation == WD_ORIENT.LANDSCAPE and last.orientation == WD_ORIENT.PORTRAIT  # each keeps its own
    assert (round(first.page_width.cm, 1), round(first.page_height.cm, 1)) == (27.9, 21.6)  # Letter, turned
    assert (round(last.page_width.cm, 1), round(last.page_height.cm, 1)) == (21.6, 27.9)
    assert package_problems(exported) == []


def _chapters(first_footer: str | None = None, *, page_number: bool = False) -> DocxDocument:
    word = DocxDocument()
    word.sections[0].header.paragraphs[0].text = "Old running head"
    if first_footer is not None:
        footer = word.sections[0].footer.paragraphs[0]
        footer.text = first_footer
        if page_number:
            footer._p.append(parse_xml(f'<w:fldSimple {_W} w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'))
    word.add_paragraph("Chapter one.")
    word.add_section(WD_SECTION.NEW_PAGE)  # without headers or footers of its own: it shows the first section's
    word.add_paragraph("Chapter two.")
    return word


def test_a_header_changed_here_is_the_last_sections_own(api_db):
    document = _upload("linked@example.com", _saved(_chapters()))
    _set(document["id"], "header", "New running head")

    exported, _ = _export(document["id"])
    client.cookies.clear()

    first, last = DocxDocument(io.BytesIO(exported)).sections
    assert not last.header.is_linked_to_previous and last.header.paragraphs[0].text == "New running head"
    assert first.header.paragraphs[0].text == "Old running head"  # the earlier section keeps its own, as the pages here show
    assert package_problems(exported) == []



def test_a_header_cleared_here_shows_the_previous_sections_again(api_db):
    word = _chapters()
    last = word.sections[-1]
    last.header.is_linked_to_previous = False
    last.header.paragraphs[0].text = "Chapter two"
    document = _upload("cleared@example.com", _saved(word))
    assert client.delete(f"/api/v1/documents/{document['id']}/settings/header").status_code == 200

    exported, _ = _export(document["id"])
    client.cookies.clear()

    first, last = DocxDocument(io.BytesIO(exported)).sections
    assert last.header.is_linked_to_previous  # none of its own now: the previous section's, as the pages here show
    assert first.header.paragraphs[0].text == "Old running head"
    assert package_problems(exported) == []

def test_page_numbers_left_out_are_left_out_of_every_section(api_db):
    document = _upload("numbers@example.com", _saved(_chapters("Page ", page_number=True)))

    exported, body = _export(document["id"], includePageNumbers="false")
    client.cookies.clear()

    sections = DocxDocument(io.BytesIO(exported)).sections
    # The first section's numbered footer, which the last one showed too, is left out whole: empty, still its own.
    assert [section.footer._element.xml.count("PAGE") for section in sections] == [0, 0]
    assert all(paragraph.text == "" for section in sections for paragraph in section.footer.paragraphs)
    assert "headerReference" in body  # the header, without page numbers, stays
    assert sections[-1].header.paragraphs[0].text == "Old running head"
    assert package_problems(exported) == []


def test_page_numbers_asked_for_here_are_on_every_sections_pages(api_db):
    word = _chapters("Draft")
    later = word.sections[-1]
    later.footer.is_linked_to_previous = False
    later.footer.paragraphs[0].text = "Final"
    document = _upload("pages@example.com", _saved(word))
    _set(document["id"], "showPageNumbers", "true")

    exported, _ = _export(document["id"])
    client.cookies.clear()

    footers = [section.footer._element.xml for section in DocxDocument(io.BytesIO(exported)).sections]
    assert all(">PAGE<" in footer for footer in footers)
    assert "Draft" in footers[0] and "Final" in footers[1]


def test_a_section_ending_in_a_changed_paragraph_is_written_from_its_section_break(api_db):
    word = DocxDocument()
    first = word.sections[0]
    first.orientation, first.page_width, first.page_height = WD_ORIENT.LANDSCAPE, first.page_height, first.page_width
    ending = word.add_paragraph("The wide table's notes.")
    word.add_section(WD_SECTION.NEW_PAGE)
    holder = next(p for p in word.element.body.iterchildren(qn("w:p")) if p.find(f"{qn('w:pPr')}/{qn('w:sectPr')}") is not None)
    ending._p.get_or_add_pPr().append(holder.find(f"{qn('w:pPr')}/{qn('w:sectPr')}"))  # the section ends in the text itself
    word.element.body.remove(holder)
    word.add_paragraph("The narrow part.")
    document = _upload("lost@example.com", _saved(word))
    assert _export(document["id"])[1].count("<w:sectPr") == 2  # unchanged: kept

    elements = document["elements"]
    ending_element = next(element for element in elements if element["content"] == "The wide table's notes.")
    ending_element["content"] = "The wide table's notes, revised."
    ending_element["inline"] = [{"text": "The wide table's notes, revised.", "marks": []}]
    _save(document["id"], elements)

    exported, body = _export(document["id"])
    features = {item["feature"] for item in _report(document["id"])["items"]}

    assert body.count("<w:sectPr") == 2 and "revised" in body  # the section, written from its section break (DOCX-015)
    assert 'w:orient="landscape"' in body and "export.docx.section_lost" not in features
    assert package_problems(exported) == []

    elements = [element for element in _save(document["id"], elements)["elements"] if element["type"] != "section_break"]
    _save(document["id"], elements)  # the section break deleted: the two sections are one
    exported, body = _export(document["id"])
    lost = [item for item in _report(document["id"])["items"] if item["feature"] == "export.docx.section_lost"]
    client.cookies.clear()

    assert body.count("<w:sectPr") == 1
    assert lost and lost[0]["policy"] == "lossy" and lost[0]["count"] == 1


# -- a block deleted here (DOCX-028B) ---------------------------------------------------


def _with_spacing() -> bytes:
    word = DocxDocument()
    word.add_paragraph("Keep this paragraph.")
    word.add_paragraph("Delete this paragraph.")
    word.add_paragraph()  # a spacing paragraph: the import leaves it out, an export into the file keeps it
    word.add_paragraph("And keep this one.")
    return _saved(word)


def _paragraphs(data: bytes) -> list[str]:
    return [paragraph.text for paragraph in DocxDocument(io.BytesIO(data)).paragraphs]


@pytest.mark.parametrize("stamped_before", [False, True], ids=["as stamped now", "stamped before DOCX-028B"])
@pytest.mark.parametrize(
    ("deleted", "left"),
    [
        ("Keep this paragraph.", ["Delete this paragraph.", "", "And keep this one."]),
        ("Delete this paragraph.", ["Keep this paragraph.", "", "And keep this one."]),
        ("And keep this one.", ["Keep this paragraph.", "Delete this paragraph.", ""]),
    ],
)
def test_a_block_deleted_here_never_comes_back(deleted, left, stamped_before):
    """Found while finishing DOCX-021: the copy plan took a deleted block's original for a
    spacing paragraph the import left out, and copied it with the block before it."""
    source = _with_spacing()
    document = parse_docx(source, "deleted.docx")
    recompute_styles(document)
    stamp(document)
    if stamped_before:
        document.sourceBlockUse = None  # stored so before DOCX-028B: the file is read again, as its import read it
    document.elements = [element for element in document.elements if element.content != deleted]
    report = ReportBuilder()

    exported = build_docx(document, source=source, report=report)

    assert _paragraphs(exported) == left  # the spacing paragraph kept, the deleted one not
    assert "export.docx.original_blocks" in {item.feature for item in report.items()}  # the others still copied
    assert package_problems(exported) == []


def test_a_picture_deleted_from_its_paragraph_never_comes_back():
    picture = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(picture, "PNG")
    word = DocxDocument()
    word.add_paragraph("Before.")
    word.add_paragraph("A line with a picture ").add_run().add_picture(io.BytesIO(picture.getvalue()), width=Cm(2))
    word.add_paragraph("After.")
    source = _saved(word)
    document = parse_docx(source, "picture.docx")
    recompute_styles(document)
    stamp(document)
    assert document.sourceBlockUse == [1, 2, 1]  # the paragraph and its picture came from one child
    document.elements = [element for element in document.elements if element.type != ElementType.IMAGE]

    exported = build_docx(document, source=source)

    assert len(DocxDocument(io.BytesIO(exported)).inline_shapes) == 0  # written anew, without it
    assert _paragraphs(exported) == ["Before.", "A line with a picture ", "After."]
    assert package_problems(exported) == []


def test_a_block_deleted_in_the_editor_is_gone_from_the_word_export(uploaded):
    assert uploaded["sourceBlockUse"]  # kept by the upload, as imported
    _save(uploaded["id"], [element for element in uploaded["elements"] if element["content"] != "Marked twice secret"])

    exported, body = _export(uploaded["id"])

    assert ">twice<" not in body and "secret" not in body
    assert "AUTHOR" in body and '<w:alias w:val="Status"/>' in body  # the others still copied as they were
    assert package_problems(exported) == []


def test_a_section_break_deleted_here_never_comes_back():
    word = DocxDocument()
    ending = word.add_paragraph("The first section's last words.")
    word.add_section(WD_SECTION.NEW_PAGE)
    holder = next(p for p in word.element.body.iterchildren(qn("w:p")) if p.find(f"{qn('w:pPr')}/{qn('w:sectPr')}") is not None)
    ending._p.get_or_add_pPr().append(holder.find(f"{qn('w:pPr')}/{qn('w:sectPr')}"))  # the section ends in the text itself
    word.element.body.remove(holder)
    word.add_paragraph("The second section.")
    source = _saved(word)
    document = parse_docx(source, "sections.docx")
    recompute_styles(document)
    stamp(document)
    document.elements = [element for element in document.elements if element.type != ElementType.SECTION_BREAK]

    exported = build_docx(document, source=source)

    assert _document_xml_of(exported).count("<w:sectPr") == 1  # one section: the paragraph written anew without it
    assert _paragraphs(exported) == ["The first section's last words.", "The second section."]


def _document_xml_of(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        return package.read("word/document.xml").decode("utf-8")
