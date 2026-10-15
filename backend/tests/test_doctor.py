"""Document Doctor v0 + SafeEdit (docs/SMARTDOC_DOCUMENT_DOCTOR_SAFEEDIT_ANALYSIS.md).

- Every Word file of the test corpus: Doctor either refuses it for a stated reason, or every repair it makes comes
  back verified -- words, untouched blocks, preserved features, a valid package.
- The labelled defect corpus (tests/fixtures/doctor, scripts/make_doctor_fixtures.py): what v0 repairs is what
  the ground truth says it should, the controls are refused or left alone, and a repaired defect is gone.
- Each SafeEdit check is shown to catch what it is for, on a deliberately damaged result.
"""

import hashlib
import io
import json
import pathlib
import re
import zipfile

import pytest
from lxml import etree

from app.doctor import word_repairs
from app.doctor.corpus import imported, run
from app.doctor.doctor import analyse, document_refusals
from app.doctor.safe_edit import verify

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
DOCTOR = FIXTURES / "doctor"
MANIFEST = json.loads((DOCTOR / "manifest.json").read_text(encoding="utf-8"))
CORPUS = sorted(path for path in FIXTURES.rglob("*.docx") if path.parent != DOCTOR)
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _document_xml(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        return package.read("word/document.xml")


def _with_document_xml(data: bytes, xml: bytes, drop: str | None = None) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            if item.filename == drop:
                continue
            target.writestr(item, xml if item.filename == "word/document.xml" else source.read(item.filename))
    return buffer.getvalue()


# -- The whole corpus: refused for a reason, or verified ---------------------------------------------------------


@pytest.mark.parametrize("path", CORPUS, ids=[path.name for path in CORPUS])
def test_every_corpus_file_is_refused_for_a_reason_or_verified(path):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    outcome = run(data, path.name)
    assert hashlib.sha256(data).hexdigest() == digest  # the original is never written to
    if outcome.refusals:
        assert outcome.result is None
        return
    assert outcome.verified, [f"{check.name}: {check.detail}" for check in outcome.result.failed()]


def test_the_corpus_refusals_are_the_known_ones():
    refused = {path.name: run(path.read_bytes(), path.name).refusals for path in CORPUS}
    assert {name: codes for name, codes in refused.items() if codes} == {
        "a06-fields.docx": ["write_back_changes"],  # the export removes its unsafe local-file link
        "a07-review.docx": ["tracked_changes"],
    }


# -- The labelled defect corpus ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(MANIFEST), ids=sorted(MANIFEST))
def test_v0_repairs_what_the_ground_truth_says(name):
    truth = MANIFEST[name]
    outcome = run((DOCTOR / name).read_bytes(), name)
    for code in truth["refusals"]:
        assert code in outcome.refusals
    if truth["refusals"]:
        assert outcome.result is None
        return
    assert outcome.refusals == []
    assert outcome.by_repair == truth["v0"], f"expected {truth['v0']}, got {outcome.by_repair}"
    assert outcome.verified, [check.detail for check in outcome.result.failed()]


def test_what_must_stay_stays():
    bookmarked = run((DOCTOR / "d07-bookmark-in-empty.docx").read_bytes(), "d07.docx")
    assert b'w:name="keep_me"' in _document_xml(bookmarked.file)
    field = run((DOCTOR / "d08-field-in-mixed-font.docx").read_bytes(), "d08.docx")
    assert b"PAGE" in _document_xml(field.file)


@pytest.mark.parametrize("name", ["d01-empty-spacing.docx", "d04-wide-table.docx", "d05-wide-picture.docx", "d06-page-breaks.docx", "d13-mixed-report.docx"])
def test_a_repaired_defect_is_gone_when_the_repaired_file_is_checked_again(name):
    first = run((DOCTOR / name).read_bytes(), name)
    again = run(first.file, name)
    kinds = set(MANIFEST[name]["v0"])
    assert not kinds & set(again.by_repair), again.by_repair
    assert again.verified


def test_the_numbers_for_the_report():
    """Planted defects against what v0 repaired, per kind (the table in the analysis document comes from here)."""
    planted: dict[str, int] = {}
    repaired: dict[str, int] = {}
    for name, truth in MANIFEST.items():
        for kind, count in truth["repairs"].items():
            planted[kind] = planted.get(kind, 0) + count
        for kind, count in truth["v0"].items():
            repaired[kind] = repaired.get(kind, 0) + count
    assert planted == {"empty_paragraphs": 11, "fonts": 4, "duplicated_formatting": 3, "wide_table": 2, "wide_picture": 1, "page_breaks": 2}
    assert repaired == {"empty_paragraphs": 10, "wide_table": 2, "wide_picture": 1, "page_breaks": 2}


# -- SafeEdit catches what it is for ----------------------------------------------------------------------------


@pytest.fixture
def repaired():
    name = "d13-mixed-report.docx"
    data = (DOCTOR / name).read_bytes()
    outcome = run(data, name)
    assert outcome.verified
    return data, outcome.file


def _checks(original: bytes, result: bytes, touched: set[int] | None = None) -> dict[str, bool]:
    return {check.name: check.passed for check in verify(original, result, touched or set()).checks}


def test_a_changed_word_fails_the_word_check(repaired):
    original, result = repaired
    xml = _document_xml(result).replace(b"Quarterly summary", b"Quarterly summery", 1)
    assert _checks(original, _with_document_xml(result, xml), set(range(20)))["words"] is False


def test_a_lost_bookmark_fails_the_preserved_check():
    original = (DOCTOR / "d07-bookmark-in-empty.docx").read_bytes()
    result = run(original, "d07.docx").file
    xml = re.sub(rb"<w:bookmarkStart[^>]*/>", b"", _document_xml(result))
    assert _checks(original, _with_document_xml(result, xml), set(range(20)))["preserved"] is False


def test_an_untouched_block_that_changed_fails_the_untouched_check(repaired):
    original, result = repaired
    root = etree.fromstring(_document_xml(result))
    last_text = [p for p in root.iter(f"{{{W}}}p") if "".join(p.itertext()).strip()][-1]
    last_text.insert(0, etree.fromstring(f'<w:pPr xmlns:w="{W}"><w:jc w:val="center"/></w:pPr>'))
    changed = _with_document_xml(result, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True))
    checks = _checks(original, changed)
    assert checks["untouched"] is False and checks["words"] is True  # same words, still caught


def test_a_changed_header_word_fails_the_header_check():
    original = (FIXTURES / "documents" / "10-header-footer.docx").read_bytes()
    result = run(original, "10.docx").file
    source = zipfile.ZipFile(io.BytesIO(result))
    header = next(name for name in source.namelist() if re.match(r"word/header\d*\.xml", name) and re.search(rb"<w:t[^>]*>[A-Za-z]", source.read(name)))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == header:
                content = re.sub(rb"(<w:t[^>]*>)([A-Za-z])", rb"\1Changed \2", content, count=1)
            target.writestr(item, content)
    assert _checks(original, buffer.getvalue())["headers"] is False


def test_a_broken_package_fails_the_package_check(repaired):
    original, result = repaired
    assert _checks(original, _with_document_xml(result, _document_xml(result), drop="word/styles.xml"))["package"] is False


def test_an_unreadable_result_is_a_failed_check_not_a_crash(repaired):
    original, _ = repaired
    outcome = verify(original, b"not a zip", set())
    assert not outcome.verified and outcome.checks[0].name == "words"


# -- Refusals ---------------------------------------------------------------------------------------------------


def test_a_document_without_a_word_file_is_refused():
    document = imported((DOCTOR / "d09-clean.docx").read_bytes(), "d09.docx")
    document.sourcePackage = None
    assert [refusal.code for refusal in document_refusals(document, None)] == ["no_word_file"]


def test_a_stored_file_that_cant_be_used_is_refused_with_its_reason():
    document = imported((DOCTOR / "d09-clean.docx").read_bytes(), "d09.docx")
    refusals = document_refusals(document, None, "The stored original Word file isn't the one this document came from.")
    assert refusals[0].code == "source_unreadable" and "isn't the one" in refusals[0].message


def test_an_import_whose_word_check_didnt_pass_is_refused():
    data = (DOCTOR / "d09-clean.docx").read_bytes()
    document = imported(data, "d09.docx")
    report = document.importReport
    document.importReport = report.model_copy(update={"content": report.content.model_copy(update={"verified": False, "missing": 1})})
    assert document.importReport.contentStatus == "changed"
    assert "import_not_verified" in [refusal.code for refusal in analyse(document, data).refusals]


def test_a_refused_document_gets_no_repairs():
    data = (DOCTOR / "d10-signed.docx").read_bytes()
    analysis = analyse(imported(data, "d10.docx"), data)
    assert not analysis.available and analysis.repairable == 0 and analysis.wordRepairs == []


# -- Repairs in the file: what they never touch -----------------------------------------------------------------


def _body(paragraphs: str) -> bytes:
    source = (DOCTOR / "d09-clean.docx").read_bytes()
    root = etree.fromstring(_document_xml(source))
    body = root.find(f"{{{W}}}body")
    section = body.find(f"{{{W}}}sectPr")
    for child in list(body):
        body.remove(child)
    for xml in paragraphs.split("|"):
        body.append(etree.fromstring(f'<w:root xmlns:w="{W}">{xml}</w:root>')[0])
    body.append(section)
    return _with_document_xml(source, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True))


TEXT = "<w:p><w:r><w:t>Some text</w:t></w:r></w:p>"
EMPTY = "<w:p/>"
TABLE = "<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w='1000'/></w:tblGrid><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>"


def test_empty_paragraphs_next_to_a_table_or_at_the_end_or_carrying_something_stay():
    data = _body("|".join([TEXT, EMPTY, TABLE, EMPTY, TEXT, "<w:p><w:pPr><w:pageBreakBefore/></w:pPr></w:p>", TEXT, EMPTY]))
    assert word_repairs.find_empty_spacing(data) == []


def test_a_run_of_empties_is_one_repair_with_its_space_given_to_the_paragraph_before():
    data = _body("|".join([TEXT, EMPTY, EMPTY, TEXT, TEXT]))
    [repair] = word_repairs.find_empty_spacing(data)
    assert repair.blocks == (1, 2) and repair.neighbour == 0 and repair.side == "after" and repair.points == pytest.approx(25.3)


def test_the_spacing_goes_where_the_schema_puts_it():
    paragraph = etree.fromstring(f'<w:p xmlns:w="{W}"><w:pPr><w:pStyle w:val="Normal"/><w:jc w:val="left"/><w:rPr/></w:pPr></w:p>')
    word_repairs._add_spacing(paragraph, "after", 12)
    assert [etree.QName(child).localname for child in paragraph.find(f"{{{W}}}pPr")] == ["pStyle", "spacing", "jc", "rPr"]
    assert paragraph.find(f".//{{{W}}}spacing").get(f"{{{W}}}after") == "240"


def test_a_repair_whose_blocks_dont_line_up_is_skipped_not_guessed():
    original = _body("|".join([TEXT, EMPTY, TEXT, TEXT]))
    repairs = word_repairs.find_empty_spacing(original)
    # The result's first paragraph differs from the original's (it was edited): the repair's neighbour can't be found.
    edited = _body("|".join(["<w:p><w:r><w:t>Edited text</w:t></w:r></w:p>", EMPTY, TEXT, TEXT]))
    result, touched, skipped = word_repairs.apply(original, edited, repairs)
    assert skipped == [repairs[0].id] and touched == set() and result.count(b"<w:p/>") == edited.count(b"<w:p/>")
