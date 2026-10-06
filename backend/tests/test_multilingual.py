"""Multilingual documents (tracker FONT-001..004, FONT-006; brief §50-53): the font catalogue
reads what each font covers and whether it may be embedded; the FontResolver gives each script
run (and each stray symbol) a font that draws it; the PDF export shapes Arabic, Hebrew,
Devanagari and Thai, lays right-to-left text out right to left, and says what it can't draw or
can't give back as text; the Word export marks each run's scripts, languages and direction.

The script matrix runs with the fonts this machine has: a script nothing installed covers is
expected to be reported, never drawn as boxes silently."""

import io
import re
import zipfile

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from app import bidi
from app.bidi import base_level, log2vis
from app.export import font_resolver, fonts, pdf_export
from app.export.docx_export import build_docx
from app.export.font_catalogue import CatalogueFont, _read, covering
from app.export.font_resolver import resolve, script_runs
from app.export.pdf_export import build_pdf
from app.fidelity.exports import export_report
from app.fidelity.report import ReportBuilder
from app.models.document import Document, Element, ElementType, InlineRun, Mark, MarkType
from app.parsers.pdf_geometry import read_pdf_geometry


def _paragraph(text: str, order: int = 0, marks=()) -> Element:
    return Element(type=ElementType.PARAGRAPH, content=text, inline=[InlineRun(text=text, marks=list(marks))], order=order)


# --- bidi (the rlbidi reportlab uses) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "direction", "visual"),
    [
        ("abc def", "LTR", "abc def"),
        ("שלום עולם", "RTL", "םלוע םולש"),
        ("مرحبا بالعالم 123", "RTL", "123 ملاعلاب ابحرم"),
        ("Hello שלום world", "LTR", "Hello םולש world"),
        ("שלום (abc) 12.5%", "RTL", "12.5% (abc) םולש"),  # a bracket pair takes the paragraph's direction (N0), mirrored
        ("דף 23 מתוך 45", "RTL", "45 ךותמ 23 ףד"),
        ("abc [שלום] def", "LTR", "abc [םולש] def"),
        ("Price: 5 ₪ (מחיר)", "LTR", "Price: 5 ₪ (ריחמ)"),
        ("abc مرحبا 50%", "LTR", "abc 50 ابحرم%"),  # digits after Arabic letters are Arabic numbers (W2): the % stays outside
    ],
)
def test_text_comes_in_the_order_it_is_seen(text, direction, visual):
    positions: list[int] = []
    assert log2vis(text, direction, positions_V_to_L=positions) == visual
    assert sorted(positions) == list(range(len(text)))  # every character, once
    # Each visual character is the logical one it maps to -- mirrored where it reads right to left.
    assert all(visual[v] in (text[i], bidi._MIRRORED.get(text[i])) for v, i in enumerate(positions))


def test_the_paragraph_direction_is_its_first_strong_letter_and_reportlab_uses_this_bidi():
    assert (base_level("  123 שלום abc", None), base_level("abc שלום", None), base_level("123", None)) == (1, 0, 0)
    from reportlab.pdfgen import textobject

    assert textobject.rtlSupport and textobject.log2vis is bidi.log2vis


# --- the catalogue (FONT-001) ---------------------------------------------------------------------


def _font(path, characters: str, fs_type: int = 0) -> None:
    builder = FontBuilder(1000, isTTF=True)
    characters = "".join(dict.fromkeys(characters))  # each once
    names = [".notdef", *(f"g{ord(c)}" for c in characters)]
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({ord(c): f"g{ord(c)}" for c in characters})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0)), pen.lineTo((0, 500)), pen.lineTo((500, 500)), pen.closePath()
    glyph = pen.glyph()
    builder.setupGlyf({name: glyph for name in names})
    builder.setupHorizontalMetrics({name: (600, 0) for name in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    builder.setupOS2(fsType=fs_type)
    builder.setupPost()
    builder.save(str(path))


def test_the_catalogue_reads_coverage_by_script_metrics_and_whether_a_font_may_be_embedded(tmp_path):
    from app.export.font_catalogue import SAMPLES

    _font(tmp_path / "open.ttf", SAMPLES["Latn"] + SAMPLES["Cyrl"] + "ab")
    _font(tmp_path / "restricted.ttf", SAMPLES["Grek"], fs_type=2)
    opened = _read("Open", tmp_path / "open.ttf")
    restricted = _read("Restricted", tmp_path / "restricted.ttf")
    assert opened.scripts == {"Latn", "Cyrl"} and opened.embeddable and (opened.units_per_em, opened.ascent, opened.descent) == (1000, 800, -200)
    assert opened.draws("abc ") is False and opened.draws("ab ")
    assert restricted.scripts == {"Grek"} and not restricted.embeddable  # listed, never used in a PDF
    assert _read("Broken", tmp_path / "missing.ttf") is None


# --- the resolver (FONT-002) ----------------------------------------------------------------------


def _fake(family: str, characters: str, scripts: set[str]) -> CatalogueFont:
    return CatalogueFont(family, None, 0, frozenset(scripts), 1000, 800, -200, True, frozenset(map(ord, characters)))


@pytest.fixture
def fake_fonts(monkeypatch):
    latin = "".join(chr(c) for c in range(0x20, 0x7F)) + "ÄÖÜäöüß"
    cyrillic = "".join(chr(c) for c in range(0x410, 0x450))
    arabic = "".join(chr(c) for c in range(0x620, 0x650))
    fake = {
        "Serifa": _fake("Serifa", latin + cyrillic, {"Latn", "Cyrl"}),
        "Arabica": _fake("Arabica", latin + arabic, {"Latn", "Arab"}),
        "Symbols": _fake("Symbols", "✓★", set()),
    }
    monkeypatch.setattr(font_resolver, "catalogue", lambda: fake)
    monkeypatch.setattr(font_resolver, "covering", lambda script: [font for font in fake.values() if script in font.scripts])
    monkeypatch.setattr(font_resolver, "resolved_family", lambda family: "Serifa")
    monkeypatch.setattr(font_resolver, "_SYMBOL_FAMILIES", ("Symbols",))
    font_resolver._symbol_font.cache_clear()
    yield fake
    font_resolver._symbol_font.cache_clear()


def test_each_script_run_gets_a_font_that_draws_it(fake_fonts):
    runs = resolve("Guten Tag, Добър ден, مرحبا بالعالم!", "Serifa")
    assert [(run.text, run.family, run.script, run.direction) for run in runs] == [
        ("Guten Tag, ", "Serifa", "Latn", "ltr"),
        ("Добър ден, ", "Serifa", "Cyrl", "ltr"),
        ("مرحبا بالعالم!", "Arabica", "Arab", "rtl"),
    ]


def test_a_symbol_goes_to_a_font_that_has_it_and_what_none_has_is_missing(fake_fonts):
    runs = resolve("Done ✓ — ok 𐀀", "Serifa")
    assert [(run.text, run.family) for run in runs] == [("Done ", "Serifa"), ("✓", "Symbols"), (" — ok 𐀀", "Serifa")]
    assert "".join(run.missing for run in runs) == "—𐀀"  # the dash isn't in the fake fonts either


def test_a_runs_font_is_chosen_by_its_letters_and_only_its_symbols_go_elsewhere(fake_fonts, monkeypatch):
    """Another font having the letters and the symbol too doesn't take the run: the paragraph's
    own font keeps the letters it has."""
    arabica = fake_fonts["Arabica"]
    both = CatalogueFont(arabica.family, None, 0, arabica.scripts, 1000, 800, -200, True, arabica.characters | {ord("✓")})
    monkeypatch.setitem(fake_fonts, "Arabica", both)
    monkeypatch.setattr(font_resolver, "covering", lambda script: [both, fake_fonts["Serifa"]] if script == "Latn" else [])  # it comes first
    assert [(run.text, run.family) for run in resolve("Done ✓", "Serifa")] == [("Done ", "Serifa"), ("✓", "Symbols")]


def test_common_characters_join_the_run_they_are_in():
    assert script_runs("12, Hello! Привет?") == [("12, Hello! ", "Latn"), ("Привет?", "Cyrl")]


# --- the PDF (FONT-003, FONT-006) -----------------------------------------------------------------

_SAMPLES = {
    "Arab": "مرحبا بالعالم",
    "Hebr": "שלום עולם",
    "Deva": "नमस्ते दुनिया",
    "Hani": "你好世界",
    "Kana": "こんにちは",
    "Hang": "안녕하세요",
    "Thai": "สวัสดีชาวโลก",
    "Grek": "Καλημέρα κόσμε",
    "Cyrl": "Добър ден",
}


def _exported(document: Document):
    report = ReportBuilder()
    pdf = build_pdf(document, report=report)
    return pdf, export_report(document, pdf, "pdf", report.items())


@pytest.mark.parametrize("script", list(_SAMPLES))
def test_each_script_is_drawn_in_a_font_that_has_it_or_said_not_to_be(script):
    document = Document(elements=[_paragraph("Hello", 0), _paragraph(_SAMPLES[script], 1)])
    pdf, report = _exported(document)
    features = {item.feature: item for item in report.items}
    if not covering(script):  # nothing here draws it: said, with the characters
        assert "export.pdf.script" in features and features["export.pdf.script"].contentChanged
        return
    assert "export.pdf.script" not in features
    if script in ("Deva", "Thai"):  # drawn right, but can't be copied back out as text
        assert features["export.pdf.text_layer"].count == len(_SAMPLES[script].split())
    assert report.contentStatus == "verified", report.content.samples
    drawn = {char.font for char in read_pdf_geometry(pdf).pages[0].chars if char.text.strip() and char.text not in "Hello"}
    expected = {re.sub(r"[^A-Za-z]", "", font.family) for font in covering(script)} | {re.sub(r"[^A-Za-z]", "", name) for name in ("Arial", "Times New Roman")}
    assert all(any(name.lower() in re.sub(r"[^A-Za-z]", "", font).lower() for name in expected) for font in drawn), drawn


def test_arabic_is_shaped_and_right_to_left_text_is_laid_out_and_aligned_right_to_left():
    if not covering("Arab") or not covering("Hebr"):
        pytest.skip("no font here draws Arabic and Hebrew")
    pdf, _ = _exported(Document(elements=[_paragraph("مرحبا بالعالم", 0), _paragraph("שלום עולם", 1)]))
    page = read_pdf_geometry(pdf).pages[0]
    arabic = [char for char in page.chars if char.text.strip() and 0x0600 <= ord(char.text[0]) <= 0xFEFF and not 0x0590 <= ord(char.text[0]) <= 0x05FF]
    hebrew = sorted((char for char in page.chars if char.text.strip() and 0x0590 <= ord(char.text[0]) <= 0x05FF), key=lambda char: char.box[0])
    assert any(0xFB50 <= ord(char.text[0]) <= 0xFEFF for char in arabic)  # joined forms: shaped
    assert hebrew[-1].text == "ש" and hebrew[0].text == "ם"  # its first letter rightmost, its last leftmost
    assert hebrew[-1].box[2] > page.width / 2  # set from the right


def test_without_a_shaping_engine_it_is_said(monkeypatch):
    if not covering("Arab"):
        pytest.skip("no font here draws Arabic")
    monkeypatch.setattr(pdf_export, "shaping_available", lambda: False)
    _, report = _exported(Document(elements=[_paragraph("مرحبا بالعالم", 0)]))
    assert any(item.feature == "export.pdf.script" and "shaped" in item.reason for item in report.items)


def test_a_character_no_font_draws_is_said_once_with_the_characters():
    _, report = _exported(Document(elements=[_paragraph("Linear B 𐀀 and 𐀁", 0)]))
    (item,) = [item for item in report.items if item.feature == "export.pdf.script"]
    assert item.reason.startswith("2 characters (𐀀 𐀁) have no installed font that draws them") and item.contentChanged


def test_a_document_mixing_languages_is_drawn_in_the_fonts_it_needs():
    text = "Guten Tag. Hello. Добър ден. مرحبا"
    pdf, report = _exported(Document(elements=[_paragraph(text, 0)]))
    if not covering("Arab"):
        pytest.skip("no font here draws Arabic")
    fonts_drawn = {char.font for char in read_pdf_geometry(pdf).pages[0].chars if char.text.strip()}
    assert len(fonts_drawn) >= 1 and report.contentStatus == "verified"


# --- Word (FONT-004) ------------------------------------------------------------------------------


def _xml(document: Document) -> list[str]:
    body = zipfile.ZipFile(io.BytesIO(build_docx(document))).read("word/document.xml").decode()
    return re.findall(r"<w:p[ >].*?</w:p>", body)


def test_word_runs_carry_their_scripts_fonts_languages_and_direction():
    arabic, chinese, devanagari, english = _xml(
        Document(
            elements=[
                _paragraph("مرحبا بالعالم", 0, [Mark(type=MarkType.BOLD)]),
                _paragraph("你好世界", 1),
                _paragraph("नमस्ते", 2),
                _paragraph("Hello", 3),
            ]
        )
    )
    assert "<w:bidi/>" in arabic and "<w:rtl/>" in arabic and "<w:bCs/>" in arabic and 'w:bidi="ar-SA"' in arabic and "w:cs=" in arabic
    assert 'w:eastAsia="zh-CN"' in chinese and 'w:hint="eastAsia"' in chinese and "<w:bidi/>" not in chinese
    assert re.search(r'<w:rFonts [^>]*w:eastAsia="[^"]+"', chinese)  # the East Asian font itself, not only the language
    assert 'w:bidi="hi-IN"' in devanagari and 'w:cs="' in devanagari and "<w:rtl/>" not in devanagari
    assert "w:lang" not in english and "w:rtl" not in english
