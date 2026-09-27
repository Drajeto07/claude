"""Independent validation of the Word files the app writes (tracker TEST-023):
app/export/package_check.py reads the zip itself, not through python-docx, and
finds what makes Word refuse a file or open it "with unreadable content". Every
golden document's export -- built fresh, and written into its own original file
(DOCX-011) -- passes; each kind of damage is caught."""

import io
import zipfile
from pathlib import Path

import pytest

from app.export.docx_export import build_docx
from app.export.package_check import package_problems
from app.parsers.docx import parse_docx

FIXTURES = Path(__file__).parent / "fixtures" / "documents"
GOLDEN = sorted(path.name for path in FIXTURES.glob("*.docx"))


@pytest.mark.parametrize("name", GOLDEN)
def test_every_export_is_a_sound_package(name):
    original = (FIXTURES / name).read_bytes()
    document = parse_docx(original, name)

    assert package_problems(build_docx(document)) == []
    assert package_problems(build_docx(document, source=original)) == []


def _mutated(data: bytes, part: str, change) -> bytes:
    source, target = io.BytesIO(data), io.BytesIO()
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as after:
        for item in before.infolist():
            content = before.read(item.filename)
            if item.filename == part:
                content = change(content)
                if content is None:
                    continue
            after.writestr(item, content)
    return target.getvalue()


def test_each_kind_of_damage_is_caught():
    sound = build_docx(parse_docx((FIXTURES / "04-images.docx").read_bytes(), "04-images.docx"))
    assert package_problems(sound) == []

    no_picture = _mutated(sound, next(name for name in zipfile.ZipFile(io.BytesIO(sound)).namelist() if name.startswith("word/media/")), lambda _: None)
    assert any("points at a missing part" in problem for problem in package_problems(no_picture))

    unknown_style = _mutated(sound, "word/document.xml", lambda xml: xml.replace(b"<w:body>", b'<w:body><w:p><w:pPr><w:pStyle w:val="NoSuchStyle"/></w:pPr></w:p>', 1))
    assert "word/document.xml: style 'NoSuchStyle' isn't defined" in package_problems(unknown_style)

    broken_xml = _mutated(sound, "word/styles.xml", lambda xml: xml[: len(xml) // 2])
    assert any(problem.startswith("word/styles.xml: not well-formed XML") for problem in package_problems(broken_xml))

    untyped = _mutated(sound, "[Content_Types].xml", lambda xml: xml.replace(b'Extension="png"', b'Extension="nope"'))
    assert any(problem.endswith(": no content type") for problem in package_problems(untyped))

    assert package_problems(b"not a zip") == ["not a zip package"]
