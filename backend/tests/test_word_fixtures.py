"""The Word-authored fixtures (tracker TEST-020, audit AUD-20): documents written by
Microsoft Word itself (scripts/make_word_fixtures.py), so the importer and the exports
meet the OOXML a real user's Word writes, which python-docx's golden documents don't.
They are synthetic, and carry nothing that would identify the machine they were made
on or its user -- checked here on the committed files, so a rebuild that let
something through can't be committed quietly."""

import json
import re
import zipfile
from pathlib import Path

import pytest

from app.export.docx_export import build_docx
from app.export.package_check import package_problems
from app.services.ingestion_service import build_document_from_docx

WORD = Path(__file__).parent / "fixtures" / "word"
FIXTURES = sorted(path.name for path in WORD.glob("*.docx"))
MANIFEST = json.loads((WORD / "manifest.json").read_text(encoding="utf-8"))

# The fixtures' own made-up people and places (scripts/make_word_fixtures.py SYNTHETIC_*).
_PEOPLE = {"Word User", "Reviewer A", "Reviewer B", "Author C", "Audit Author"}
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_MADE_UP_EMAIL = re.compile(r"@example\.(?:com|org|net)$")


def _parts(name: str) -> dict[str, str]:
    with zipfile.ZipFile(WORD / name) as package:
        return {part: package.read(part).decode("utf-8", "replace") for part in package.namelist() if part.endswith((".xml", ".rels"))}


def test_there_are_twenty_and_each_holds_what_its_manifest_says():
    assert len(FIXTURES) == 20
    assert sorted(MANIFEST) == FIXTURES
    for name in FIXTURES:
        assert MANIFEST[name]["ok"] and not MANIFEST[name]["failed"], (name, MANIFEST[name]["failed"])


@pytest.mark.parametrize("name", FIXTURES)
def test_nothing_identifies_the_machine_or_its_user(name):
    parts = _parts(name)
    text = "\n".join(parts.values())

    assert "MSIP_Label_" not in text  # Office's sensitivity labels carry the organisation's tenant
    assert "presenceInfo" not in text  # a comment author's sign-in identity
    assert not re.search(r"[A-Za-z]:\\Users\\|/Users/", text)  # nobody's home folder
    assert all(_MADE_UP_EMAIL.search(address) for address in _EMAIL.findall(text)), _EMAIL.findall(text)
    assert set(re.findall(r'w(?:15)?:author="([^"]*)"', text)) <= _PEOPLE
    core, app = parts.get("docProps/core.xml", ""), parts.get("docProps/app.xml", "")
    assert set(re.findall(r"<(?:dc:creator|cp:lastModifiedBy)>([^<]*)<", core)) <= {"Word User", "Audit Author"}
    assert set(re.findall(r"<Company>([^<]*)</Company>", app)) <= {"", "Example Ltd"} and "<Manager>" not in app


@pytest.mark.parametrize("name", FIXTURES)
def test_each_imports_and_goes_back_into_a_sound_word_file(name):
    document = build_document_from_docx((WORD / name).read_bytes(), name, None)

    assert document.elements and document.importReport is not None
    assert package_problems(build_docx(document)) == []
