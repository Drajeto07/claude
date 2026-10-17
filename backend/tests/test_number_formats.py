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
from app.formatting.number_formats import MORE_FORMATS, WORD_FORMATS
from app.parsers.docx import parse_docx
from tests.test_docx_numbering import _import, _item, _lists, _num, _numbering, _pdf_text

WORD = json.loads((Path(__file__).parent / "fixtures" / "word_number_labels.json").read_text(encoding="utf-8"))["labels"]
# Numbers in words, by the paragraph's language (DOCX-016C): read from Word too.
WORDS = json.loads((Path(__file__).parent / "fixtures" / "word_number_words.json").read_text(encoding="utf-8"))["labels"]
# How far each language is spelled here as Word spells it (past that: the number as it is).
SPELLED_UP_TO = {"en-US": 999_999, "bg-BG": 999}


@pytest.mark.parametrize("fmt", sorted(WORD))
def test_each_label_is_the_one_word_shows(fmt):
    wrong = {value: (label, format_number(int(value), fmt)) for value, label in WORD[fmt].items() if format_number(int(value), fmt) != label}
    assert wrong == {}


def test_every_style_here_was_checked_against_word():
    assert set(MORE_FORMATS) - set(WORD) - set(WORD_FORMATS) == set()
    assert set(WORD_FORMATS) <= set(WORDS)


@pytest.mark.parametrize("fmt", WORD_FORMATS)
@pytest.mark.parametrize("language", sorted(SPELLED_UP_TO))
def test_numbers_in_words_are_the_ones_word_writes_in_the_lists_language(fmt, language):
    labels = WORDS[fmt][language]
    wrong = {
        value: (label, format_number(int(value), fmt, language))
        for value, label in labels.items()
        if int(value) <= SPELLED_UP_TO[language] and format_number(int(value), fmt, language) != label
    }
    assert wrong == {} and len(labels) > 40
    assert format_number(SPELLED_UP_TO[language] + 1, fmt, language) == str(SPELLED_UP_TO[language] + 1)  # past that: as it is
    assert format_number(3, fmt, "de-DE") == "3"  # a language not spelled here


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


def _words_list(document, number: int, fmt: str, language: str | None) -> None:
    """A list numbered in words, its paragraphs in `language`."""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    _numbering(document, number, [(fmt, "%1.", 1)])
    _num(document, number, number)
    for text in ("first item", "second item"):
        _item(document, text, number)
        if language:
            run = document.paragraphs[-1].runs[0]._r
            run.get_or_add_rPr().append(parse_xml(f'<w:lang {nsdecls("w")} w:val="{language}"/>'))
    document.add_paragraph("between")


def test_a_list_in_words_keeps_its_style_and_language_and_is_spelled_in_it():
    def build(document):
        _words_list(document, 130, "ordinalText", "bg-BG")
        _words_list(document, 131, "cardinalText", None)  # none of its own: the document's (python-docx's: en-US)

    imported = _import(build)

    bulgarian, english = _lists(imported)
    assert (bulgarian.numbering.format, bulgarian.numbering.language) == ("ordinalText", "bg-BG")
    assert (english.numbering.format, english.numbering.language) == ("cardinalText", "en-US")
    assert "docx.list_numbering.format" not in {item.feature for item in imported.importReport.items}
    text = _pdf_text(imported)
    assert "Първият." in text and "Вторият." in text and "One." in text and "Two." in text
    with zipfile.ZipFile(io.BytesIO(build_docx(imported))) as package:
        numbering = package.read("word/numbering.xml").decode("utf-8")
    assert 'w:numFmt w:val="ordinalText"' in numbering and 'w:numFmt w:val="cardinalText"' in numbering
    # Word spells an item's number in its paragraph mark's language: each Bulgarian item's mark says so
    # (read back by Word, the labels are "Първият." and "Вторият.").
    from docx.oxml.ns import qn

    exported = DocxDocument(io.BytesIO(build_docx(imported)))
    marks = [paragraph._p.pPr.find(qn("w:rPr")) for paragraph in exported.paragraphs if paragraph.text.endswith("item")][:2]
    assert [mark.find(qn("w:lang")).get(qn("w:val")) for mark in marks] == ["bg-BG", "bg-BG"]
    again = _lists(parse_docx(build_docx(imported), "again.docx"))
    assert [(element.numbering.format, element.numbering.language) for element in again] == [("ordinalText", "bg-BG"), ("cardinalText", "en-US")]


def test_words_in_a_language_not_spelled_here_show_numbers_and_are_said_and_other_word_styles_too():
    def build(document):
        _words_list(document, 140, "cardinalText", "de-DE")
        _words_list(document, 141, "hindiCounting", None)

    imported = _import(build)

    german, hindi = _lists(imported)
    assert (german.numbering.format, german.numbering.language) == ("cardinalText", "de-DE")  # kept for a Word export
    assert hindi.numbering is None  # not a style here: 1, 2, 3, as any list
    reasons = [item.reason for item in imported.importReport.items if item.feature == "docx.list_numbering.format"]
    assert any("de-DE" in reason for reason in reasons) and any("Hindi" in reason for reason in reasons)
    assert "1." in _pdf_text(imported)


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
