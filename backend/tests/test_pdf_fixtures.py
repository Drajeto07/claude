"""The PDF fixtures (tests/fixtures/pdf/, tracker P2E-008) are what
scripts/make_pdf_fixtures.py makes, byte for byte, so none is edited by hand and a
rebuild changes nothing."""

import hashlib
import io

import pytest
from pypdf import PdfReader

from scripts.make_pdf_fixtures import BUILDERS, DEJAVU_SHA256, FIXTURES, build, dejavu


def _same_font() -> bool:
    """Whether this machine's DejaVu Sans is the one multilingual.pdf was built with: its
    subset is embedded, so another release of the font makes other bytes."""
    try:
        return hashlib.sha256(dejavu().read_bytes()).hexdigest() == DEJAVU_SHA256
    except FileNotFoundError:
        pytest.skip("DejaVu Sans isn't installed (CI installs fonts-dejavu-core)")


@pytest.mark.parametrize("name", list(BUILDERS))
def test_the_fixtures_are_what_the_builder_makes(name):
    committed = (FIXTURES / name).read_bytes()
    same_font = name != "multilingual.pdf" or _same_font()  # first: without the font it skips, not fails
    built = build(name)
    assert built == build(name), f"{name}: the builder isn't deterministic"
    if not same_font:  # the same pages, if not the same bytes
        assert [page.extract_text() for page in PdfReader(io.BytesIO(built)).pages] == [
            page.extract_text() for page in PdfReader(io.BytesIO(committed)).pages
        ]
        return
    assert built == committed, f"{name} is out of date: python -m scripts.make_pdf_fixtures"


def test_every_fixture_has_a_builder():
    assert sorted(path.name for path in FIXTURES.glob("*.pdf")) == sorted(BUILDERS)
