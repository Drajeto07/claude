"""B-033: writing a document back into its Word file keeps the file's own headers and footers -- their references,
their parts, their pictures and the media those pictures point to -- unless the document changed them; and SafeEdit
never calls a file verified when a header's or footer's content was lost.

Found by the Validation Pack (S2-100: 4 corpus files lost an empty default header or footer on write-back). A
one-section document's own header without text was taken for "same as the previous section", which has nothing to
show: the reference and its part were dropped -- with a logo, when the header held only a picture.

Everything here is read from the files' XML and package (independently of the export code); nothing is rendered.
"""

import hashlib
import io
import re
import zipfile

import pytest
from docx.enum.section import WD_SECTION
from docx.shared import Cm
from lxml import etree

from app.doctor.corpus import imported, run
from app.doctor.safe_edit import verify
from app.export.docx_export import build_docx
from scripts.make_doctor_fixtures import _fixed_dates, new_document, png, save, text_paragraphs

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


# -- Reading headers and footers from the package itself --------------------------------------------------------


def _parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        return {name: package.read(name) for name in package.namelist()}


def _rels(parts: dict[str, bytes], part: str) -> dict[str, tuple[str, str]]:
    folder, name = part.rsplit("/", 1)
    blob = parts.get(f"{folder}/_rels/{name}.rels")
    return {} if blob is None else {rel.get("Id"): (rel.get("Type"), rel.get("Target")) for rel in etree.fromstring(blob)}


def headers_and_footers(data: bytes) -> list[dict]:
    """Per section, in order: {(kind, type): (text, drawings, sha256 of each picture's media part)}."""
    parts = _parts(data)
    document_rels = _rels(parts, "word/document.xml")
    found = []
    for section in etree.fromstring(parts["word/document.xml"]).iter(f"{{{W}}}sectPr"):
        own = {}
        for reference in section:
            kind = etree.QName(reference).localname
            if kind not in ("headerReference", "footerReference"):
                continue
            _, target = document_rels[reference.get(f"{{{R}}}id")]
            part = f"word/{target}"
            root = etree.fromstring(parts[part])
            text = " ".join("".join(t.text or "" for t in p.iter(f"{{{W}}}t")) for p in root.iter(f"{{{W}}}p")).strip()
            rels = _rels(parts, part)
            media = sorted(
                hashlib.sha256(parts["word/" + rels[blip.get(f"{{{R}}}embed")][1]]).hexdigest()
                for blip in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
                if rels.get(blip.get(f"{{{R}}}embed"), ("", ""))[0] == IMAGE
            )
            own[(kind.replace("Reference", ""), reference.get(f"{{{W}}}type"))] = (text, sum(1 for _ in root.iter(f"{{{W}}}drawing")), tuple(media))
        found.append(own)
    return found


# -- Building the cases ------------------------------------------------------------------------------------------


def _logo(part) -> None:
    part.is_linked_to_previous = False
    part.paragraphs[0].add_run().add_picture(png(120, 40), width=Cm(3))


def _text(part, words: str) -> None:
    part.is_linked_to_previous = False
    part.paragraphs[0].text = words


def _empty(part) -> None:
    part.is_linked_to_previous = False


def _document(*sections) -> bytes:
    """One section per function given; each sets up its section (headers, footers) on the python-docx Section."""
    document = new_document()
    for index, setup in enumerate(sections):
        section = document.sections[0] if index == 0 else document.add_section(WD_SECTION.NEW_PAGE)
        setup(section)
        text_paragraphs(document, 2, index)
    return _fixed_dates(save(document))


def _nothing(section) -> None:
    pass


CASES = {
    "one-section-empty-header-and-footer": (lambda s: (_empty(s.header), _empty(s.footer)),),
    "one-section-logo-only-header": (lambda s: _logo(s.header),),
    "one-section-logo-only-footer": (lambda s: _logo(s.footer),),
    "one-section-text-and-logo-header": (lambda s: (_logo(s.header), s.header.paragraphs[0].add_run(" Northwind Ltd")),),
    "one-section-text-header-and-footer": (lambda s: (_text(s.header, "Northwind Ltd"), _text(s.footer, "Confidential")),),
    "one-section-no-header-or-footer": (_nothing,),
    "two-sections-text-then-inherited": (lambda s: _text(s.header, "Northwind Ltd"), _nothing),
    "two-sections-logo-then-inherited": (lambda s: _logo(s.header), _nothing),
    "two-sections-logo-then-own-empty": (lambda s: _logo(s.header), lambda s: _empty(s.header)),
    "two-sections-text-then-own-logo": (lambda s: _text(s.header, "Northwind Ltd"), lambda s: _logo(s.header)),
    "two-sections-inherited-then-own-logo-footer": (_nothing, lambda s: _logo(s.footer)),
    "first-page-logo-default-text": (lambda s: (setattr(s, "different_first_page_header_footer", True), _logo(s.first_page_header), _text(s.header, "Northwind Ltd")),),
    "first-page-text-default-logo": (lambda s: (setattr(s, "different_first_page_header_footer", True), _text(s.first_page_header, "Cover"), _logo(s.header)),),
    "even-page-logo": (lambda s: (_logo(s.even_page_header), _text(s.header, "Northwind Ltd")),),
}


def _even_pages(data: bytes) -> bytes:
    """The settings part told that even and odd pages have their own headers (python-docx has no switch for it)."""
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "word/settings.xml":
                content = re.sub(rb"(<w:settings[^>]*>)", rb"\1<w:evenAndOddHeaders/>", content, count=1)
            target.writestr(item, content)
    return buffer.getvalue()


def case_file(name: str) -> bytes:
    data = _document(*CASES[name])
    return _even_pages(data) if name.startswith("even-page") else data


def _written_back(data: bytes) -> bytes:
    return build_docx(imported(data, "case.docx"), source=data)


# -- Write-back keeps what the document didn't change ------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CASES), ids=sorted(CASES))
def test_write_back_keeps_every_header_and_footer_with_its_pictures(name):
    data = case_file(name)
    result = _written_back(data)
    assert headers_and_footers(result) == headers_and_footers(data)
    lost_parts = sorted(set(_parts(data)) - set(_parts(result)))
    assert lost_parts == []


@pytest.mark.parametrize("name", sorted(CASES), ids=sorted(CASES))
def test_doctor_keeps_them_too_and_its_check_agrees(name):
    data = case_file(name)
    outcome = run(data, f"{name}.docx")
    if outcome.refusals:
        pytest.fail(f"refused: {outcome.refusals}")
    assert headers_and_footers(outcome.file) == headers_and_footers(data)
    assert outcome.verified, [check.detail for check in outcome.result.failed()]


def test_a_one_section_document_without_headers_gets_none():
    data = case_file("one-section-no-header-or-footer")
    assert headers_and_footers(data) == [{}]
    assert headers_and_footers(_written_back(data)) == [{}]


# -- What the document changed is still written ------------------------------------------------------------------


def test_a_header_text_changed_in_the_document_is_written():
    data = case_file("one-section-text-header-and-footer")
    document = imported(data, "case.docx")
    document.settings.header = "Northwind Limited"
    after = headers_and_footers(build_docx(document, source=data))
    assert after[0][("header", "default")][0] == "Northwind Limited"
    assert after[0][("footer", "default")][0] == "Confidential"


def test_a_header_text_cleared_in_the_document_is_cleared():
    data = case_file("one-section-text-header-and-footer")
    document = imported(data, "case.docx")
    document.settings.header = None
    after = headers_and_footers(build_docx(document, source=data))
    assert after[0].get(("header", "default"), ("",))[0] == ""  # no header text any more, however Word is told so
    assert after[0][("footer", "default")][0] == "Confidential"


def test_an_inherited_header_stays_inherited():
    data = case_file("two-sections-text-then-inherited")
    after = headers_and_footers(_written_back(data))
    assert ("header", "default") not in after[1]  # the second section still shows the first one's


# -- SafeEdit: a lost header picture is never verified ------------------------------------------------------------


def _without(data: bytes, part_name: str, change) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            content = source.read(item.filename)
            target.writestr(item, change(content) if item.filename == part_name else content)
    return buffer.getvalue()


def _header_part(data: bytes, kind: str = "header") -> str:
    parts = _parts(data)
    rels = _rels(parts, "word/document.xml")
    xml = parts["word/document.xml"].decode("utf-8")
    rid = re.search(rf'<w:{kind}Reference w:type="default" r:id="(rId\d+)"', xml).group(1)
    return "word/" + rels[rid][1]


@pytest.mark.parametrize("kind", ["header", "footer"])
def test_safeedit_refuses_a_header_or_footer_whose_picture_was_removed(kind):
    data = case_file(f"one-section-logo-only-{kind}")
    part = _header_part(data, kind)
    damaged = _without(data, part, lambda xml: re.sub(rb"<w:drawing>.*?</w:drawing>", b"", xml, flags=re.S))
    assert headers_and_footers(damaged) != headers_and_footers(data)
    result = verify(data, damaged, set())
    assert not result.verified
    assert any(check.name == "preserved" and kind in check.detail for check in result.failed())


@pytest.mark.parametrize("kind", ["header", "footer"])
def test_safeedit_refuses_a_header_or_footer_dropped_whole(kind):
    data = case_file(f"one-section-logo-only-{kind}")
    damaged = _without(data, "word/document.xml", lambda xml: re.sub(rb'<w:%sReference w:type="default"[^>]*/>' % kind.encode(), b"", xml, count=1))
    result = verify(data, damaged, set())
    assert not result.verified
    assert any(check.name == "preserved" and kind in check.detail for check in result.failed())


def test_safeedit_refuses_an_empty_own_header_dropped():
    data = case_file("one-section-empty-header-and-footer")
    damaged = _without(data, "word/document.xml", lambda xml: re.sub(rb'<w:headerReference w:type="default"[^>]*/>', b"", xml, count=1))
    assert not verify(data, damaged, set()).verified


def test_safeedit_refuses_a_header_picture_pointing_at_other_media():
    data = case_file("one-section-logo-only-header")
    media = next(name for name in _parts(data) if name.startswith("word/media/"))
    damaged = _without(data, media, lambda blob: _parts(_fixed_dates(save(_other_picture())))[next(n for n in _parts(_fixed_dates(save(_other_picture()))) if n.startswith("word/media/"))])
    assert headers_and_footers(damaged) != headers_and_footers(data)
    assert not verify(data, damaged, set()).verified


def _other_picture():
    document = new_document()
    document.add_picture(png(60, 60), width=Cm(2))
    return document


def test_safeedit_verifies_an_untouched_file_with_header_pictures():
    for name in CASES:
        data = case_file(name)
        assert verify(data, data, set()).verified, name
