"""More of Word's number styles (tracker DOCX-016B): 1st, ①, 一, 十一, א, أ, ก ... -- each list label
as Word itself shows it (tests/fixtures/word_number_labels.json, read from Word for every style),
kept through an import, shown, and written back to Word; only the styles that spell numbers in a
language (One, First) are still numbered 1, 2, 3 and reported."""

import io
import json
import zipfile
from pathlib import Path

import pytest
from docx import Document as DocxDocument

from app.export.docx_export import build_docx
from app.export.package_check import package_problems
from app.formatting.list_numbering import format_number, level_label
from app.formatting.number_formats import MORE_FORMATS
from app.parsers.docx import parse_docx
from tests.test_docx_numbering import _import, _item, _lists, _num, _numbering, _pdf_text

WORD = json.loads((Path(__file__).parent / "fixtures" / "word_number_labels.json").read_text(encoding="utf-8"))["labels"]


@pytest.mark.parametrize("fmt", sorted(WORD))
def test_each_label_is_the_one_word_shows(fmt):
    wrong = {value: (label, format_number(int(value), fmt)) for value, label in WORD[fmt].items() if format_number(int(value), fmt) != label}
    assert wrong == {}


def test_every_style_here_was_checked_against_word():
    assert set(MORE_FORMATS) - set(WORD) == set()


def test_a_label_pattern_takes_any_style():
    assert level_label("%1.%2", [3, 11], ["ideographDigital", "japaneseCounting"]) == "三.十一"
    assert level_label("(%1)", [2], ["ordinal"]) == "(2nd)"
    assert format_number(0, "ordinal") == "0" and format_number(-1, "hebrew1") == "-1"  # nothing to show: as it is


def _styled(document):
    for number, fmt in enumerate(("ordinal", "decimalEnclosedCircle", "ideographDigital", "hebrew1"), start=120):
        _numbering(document, number, [(fmt, "%1.", 2)])
        _num(document, number, number)
        _item(document, f"in {fmt}", number)
        document.add_paragraph("between")


def test_a_style_is_kept_through_an_import_and_a_word_export_without_a_word_about_it():
    imported = _import(_styled)

    assert [element.numbering.format for element in _lists(imported)] == ["ordinal", "decimalEnclosedCircle", "ideographDigital", "hebrew1"]
    assert "docx.list_numbering.format" not in {item.feature for item in imported.importReport.items}
    exported = build_docx(imported)
    assert package_problems(exported) == []
    with zipfile.ZipFile(io.BytesIO(exported)) as package:
        numbering = package.read("word/numbering.xml").decode("utf-8")
    for fmt in ("ordinal", "decimalEnclosedCircle", "ideographDigital", "hebrew1"):
        assert f'w:numFmt w:val="{fmt}"' in numbering
    again = parse_docx(exported, "again.docx")
    assert [(element.numbering.format, element.numbering.start) for element in _lists(again)] == [
        (element.numbering.format, element.numbering.start) for element in _lists(imported)
    ]


def test_numbers_spelled_in_words_are_still_numbered_and_said():
    def build(document):
        _numbering(document, 130, [("ordinalText", "%1", 1)])
        _num(document, 130, 130)
        _item(document, "first", 130)

    imported = _import(build)

    assert _lists(imported)[0].numbering.levels[0].format == "decimal"  # 1, 2, 3
    [note] = [item for item in imported.importReport.items if item.feature == "docx.list_numbering.format"]
    assert note.contentChanged and "words" in note.reason


def test_a_pdf_draws_the_labels_in_their_style():
    def build(document):
        for number, fmt in ((140, "decimalEnclosedCircle"), (141, "ordinal")):
            _numbering(document, number, [(fmt, "%1", 1)])
            _num(document, number, number)
            _item(document, f"one in {fmt}", number)
            _item(document, f"two in {fmt}", number)
            document.add_paragraph("between")

    text = _pdf_text(_import(build))

    assert "①" in text and "②" in text
    assert "1st" in text and "2nd" in text


def test_a_pdf_draws_each_numbered_label_in_fonts_for_its_script(monkeypatch):
    """A label after which a space follows is drawn through the same font choice as text: 一 or א in a
    font that draws it, whatever the text's own font is."""
    from app.export import pdf_export

    drawn = []
    real = pdf_export._fonted

    def fonted(text, family):
        drawn.append(text)
        return real(text, family)

    monkeypatch.setattr(pdf_export, "_fonted", fonted)

    def build(document):
        _numbering(document, 150, [("ideographDigital", "%1", 3)])
        _num(document, 150, 150)
        _item(document, "three", 150)

    document = _import(build)
    document.elements[0].numbering.levels[0].suffix = "space"
    pdf_export.build_pdf(document)

    assert "三" in drawn


def test_a_label_set_apart_by_a_tab_is_drawn_in_a_font_that_draws_it(monkeypatch):
    """A label in another script than the text's font draws is drawn in the font resolved for it."""
    from app.export import pdf_export
    from app.export.font_resolver import FontRun

    monkeypatch.setattr(pdf_export, "resolved_family", lambda family: "Own")
    monkeypatch.setattr(pdf_export, "pdf_font", lambda family: type("Font", (), {"regular": f"{family}-Regular"})())
    monkeypatch.setattr(pdf_export, "resolve", lambda text, family: [FontRun(text, "Own" if text.isascii() else "Han Font", None, "ltr")])

    assert pdf_export._label_font("2.", "Own-Regular", "Own") == "Own-Regular"
    assert pdf_export._label_font("三", "Own-Regular", "Own") == "Han Font-Regular"


def test_an_unchanged_document_still_says_nothing_new():
    """The fixture is Word's output from a synthetic file: no document of anyone's."""
    document = DocxDocument()
    document.add_paragraph("plain")
    buffer = io.BytesIO()
    document.save(buffer)
    assert parse_docx(buffer.getvalue(), "plain.docx").importReport.items == []
