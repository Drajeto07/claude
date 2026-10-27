"""Validation Pack v1 (S2-100): Doctor v0 measured on the labelled scenarios R01-R10 by scripts/doctor_validation.py
(files and ground truth: scripts/make_validation_pack.py, tests/fixtures/doctor/validation_pack.json).

- The pack is what its generator makes, its labels agree with the Doctor corpus's manifest, and every label is found.
- The measuring harness itself catches what it is for: a changed number, a swapped cell, a lost header, a symbol
  set in another font, a lost object, a decoy emptied.
- The baseline, failures included, first measured on 2026-10-22. Any change to what Doctor finds or repairs moves a
  number here: update the baseline on purpose, keep what it was in HISTORY, give the reason in the tracker -- never
  to make a regression pass.
- Invariants that are never relaxed (no undetected change of text, numbers, tables or objects; every expected
  refusal; nothing proposed on a control), and the section 29 targets: those not met yet are strict xfails, so the
  day one is met it fails here and gets promoted to a plain test.

All synthetic: the development set. Nothing here measures real documents (S2-107).
"""

import hashlib
import io
import json
import zipfile
from collections import Counter

import pytest

from scripts import make_validation_pack
from scripts.doctor_validation import (
    FIXTURES,
    PACK,
    FileResult,
    LabelNotFound,
    body_blocks,
    differences,
    kept,
    locate,
    measure,
    measure_corpus,
    score,
)

PACK_DATA = json.loads(PACK.read_text(encoding="utf-8"))
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
FILES = sorted(PACK_DATA["files"])


def _digests() -> dict[str, str]:
    return {name: hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() for name in FILES}


@pytest.fixture(scope="module")
def measured():
    before = _digests()
    results, report = measure(PACK_DATA)
    return {"results": results, "report": report, "before": before, "after": _digests()}


@pytest.fixture(scope="module")
def corpus():
    return measure_corpus()


def _with_document_xml(data: bytes, change) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            content = source.read(item.filename)
            target.writestr(item, change(content) if item.filename == "word/document.xml" else content)
    return buffer.getvalue()


def _without_part_reference(data: bytes, kind: str) -> bytes:
    import re

    return _with_document_xml(data, lambda xml: re.sub(rb'<w:%sReference w:type="default"[^>]*/>' % kind.encode(), b"", xml, count=1))


# -- The pack itself ---------------------------------------------------------------------------------------------


def test_the_pack_is_what_its_generator_makes():
    files, pack = make_validation_pack.build()
    assert pack == PACK_DATA
    assert all(name.startswith("r") for name in files)  # the Doctor corpus (d01-d13) is labelled, never rewritten
    for name, data in files.items():
        assert (FIXTURES / name).read_bytes() == data, name


def test_every_file_of_the_doctor_corpus_is_in_the_pack():
    assert set(MANIFEST) <= set(PACK_DATA["files"])
    assert all((FIXTURES / name).exists() for name in FILES)


def _repair_kind(label: dict) -> str:
    where = label["where"]
    if "empty_after" in where:
        return "empty_paragraphs"
    if "breaks_after" in where or "breaks_at_start" in where:
        return "page_breaks"
    if "picture" in where:
        return "wide_picture"
    return {"R04": "wide_table", "R05": "fonts", "R09": "duplicated_formatting"}[label["category"]]


@pytest.mark.parametrize("name", sorted(MANIFEST), ids=sorted(MANIFEST))
def test_the_labels_agree_with_the_doctor_manifest(name):
    labels = [label for label in PACK_DATA["files"][name]["labels"] if "refusal" not in label]
    # d08's field paragraph is labelled as an R10 risk; the manifest leaves it out of its repairs ("left for a person").
    counted = Counter()
    for label in labels:
        if label["defects"] and not (label["category"] == "R10" and "text" in label["where"]):
            counted[_repair_kind(label)] += label["defects"]
    assert dict(counted) == MANIFEST[name]["repairs"]
    assert sorted(label["refusal"] for label in PACK_DATA["files"][name]["labels"] if "refusal" in label) == sorted(MANIFEST[name]["refusals"])


@pytest.mark.parametrize("name", FILES, ids=FILES)
def test_every_label_is_found_where_it_says(name):
    blocks = body_blocks((FIXTURES / name).read_bytes())
    for label in PACK_DATA["files"][name]["labels"]:
        assert len(locate(label["where"], blocks)) == label["found"], label["id"]
        assert 0 <= label["defects"] <= max(label["found"], 1), label["id"]


def test_every_scenario_has_defects_and_a_control():
    by_category = {category: Counter() for category in PACK_DATA["categories"]}
    for entry in PACK_DATA["files"].values():
        for label in entry["labels"]:
            by_category[label["category"]]["defects" if label["defects"] else "decoys"] += 1
        if entry["kind"] == "control" and entry["category"] in by_category:
            by_category[entry["category"]]["controls"] += 1
    for category, counts in by_category.items():
        assert counts["defects"] >= 2, category
        assert counts["controls"] >= 1 or category == "R10", category  # R10's controls are its refusals and decoys


def test_a_label_that_isnt_unique_is_an_error_not_a_guess():
    blocks = body_blocks((FIXTURES / "d03-repeated-formatting.docx").read_bytes())
    with pytest.raises(LabelNotFound):
        locate({"text": make_validation_pack.LOREM[0]}, blocks)  # in the file twice


# -- The harness catches what it is for --------------------------------------------------------------------------


@pytest.mark.parametrize("name", FILES, ids=FILES)
def test_a_file_compared_with_itself_has_no_differences(name):
    data = (FIXTURES / name).read_bytes()
    assert not any(differences(data, data).values())
    assert kept(PACK_DATA["files"][name]["keep"], data) == []


def test_a_changed_date_in_a_table_is_a_number_table_and_text_difference():
    data = (FIXTURES / "r04-tables.docx").read_bytes()
    changed = _with_document_xml(data, lambda xml: xml.replace(b"2026-01-15", b"2026-01-16", 1))
    found = differences(data, changed)
    assert found["numbers"] and found["tables"] and found["text"]


def test_two_swapped_cells_are_a_table_difference_with_the_same_numbers():
    data = (FIXTURES / "r04-tables.docx").read_bytes()
    changed = _with_document_xml(data, lambda xml: xml.replace(b"Cost 00", b"@@").replace(b"Cost 01", b"Cost 00").replace(b"@@", b"Cost 01"))
    found = differences(data, changed)
    assert found["tables"] and not found["numbers"]


def test_a_dropped_header_is_a_structure_difference():
    data = (FIXTURES / "r08-headers.docx").read_bytes()
    assert differences(data, _without_part_reference(data, "header"))["structure"]


def test_a_symbol_set_in_another_font_is_a_symbol_difference():
    data = (FIXTURES / "r05-fonts.docx").read_bytes()
    changed = _with_document_xml(data, lambda xml: xml.replace(b'w:ascii="Wingdings" w:hAnsi="Wingdings"', b'w:ascii="Arial" w:hAnsi="Arial"'))
    assert changed != data
    assert differences(data, changed)["symbols"]
    assert kept(PACK_DATA["files"]["r05-fonts.docx"]["keep"], changed) == ["Wingdings character"]


def test_a_lost_bookmark_and_link_are_object_differences_and_reported_as_missing():
    data = (FIXTURES / "r10-objects.docx").read_bytes()
    import re

    changed = _with_document_xml(data, lambda xml: re.sub(rb"<w:bookmarkStart [^>]*/>", b"", re.sub(rb"<w:hyperlink [^>]*>(.*?)</w:hyperlink>", rb"\1", xml)))
    assert differences(data, changed)["objects"]
    assert sorted(kept(PACK_DATA["files"]["r10-objects.docx"]["keep"], changed)) == ["bookmark signed_copy", "link https://example.com/prices"]


def test_a_decoy_region_emptied_by_a_repair_is_unsafe():
    entry = PACK_DATA["files"]["r02-spacing.docx"]
    decoy = next(label for label in entry["labels"] if label["id"] == "r02-x")
    result = FileResult("r02-spacing.docx", entry, verified=True)
    blocks = body_blocks((FIXTURES / "r02-spacing.docx").read_bytes())
    result.regions = {label["id"]: locate(label["where"], blocks) for label in entry["labels"]}
    result.regions_after = {**result.regions, "r02-x": []}
    result.differences = {}
    report = score([result], PACK_DATA["categories"])
    assert report["repair"]["unsafe"] == ["r02-spacing.docx r02-x: 1 block(s) of a decoy region removed"]
    assert report["labels"][decoy["id"]]["outcome"] == {"decoy region removed": 1}


# -- The baseline, failures included ------------------------------------------------------------------------------
# First measured 2026-10-22 (S2-100). Every later change is listed in HISTORY with what it was; nothing is dropped.
HISTORY = {
    "S2-100 baseline, 2026-10-22": {
        "repairs that came out right": (21, 24),  # r05's Wingdings decoy changed by the font fix
        "unsafe": ["r05-fonts.docx: lost Wingdings character (SafeEdit verified the file)"],
        "undetected changes (pack)": ["r05-fonts.docx: symbols -- 1 symbol-font characters before, 0 kept"],
        "r05-x": {"changed": 1},
    },
    "B-032 fix, 2026-10-22 (symbol fonts kept by the font fix, checked by SafeEdit)": {
        "repairs that came out right": (21, 23),
        "unsafe": [],
        "undetected changes (pack)": [],
        "r05-x": {"left as it was": 1},
    },
    "B-033 fix (local, 2026-10-23): a one-section document's own header/footer without text kept on write-back": {
        "repairs that came out right": (21, 23),
        "unsafe": [],
        "undetected changes (pack)": [],
        "r05-x": {"left as it was": 1},
        "undetected changes (corpus)": [],  # before: the 4 files of BASELINE_CORPUS_UNDETECTED_BEFORE_B033
    },
    "S2-140 (local, 2026-10-27): R06 and R08 get checks -- fake_headings, headers_footers -- diagnosis only": {
        # Detection only: no repair, proposal or write path changed, so these stay as they were.
        "repairs that came out right": (21, 23),
        "unsafe": [],
        "undetected changes (pack)": [],
        "r05-x": {"left as it was": 1},
        "undetected changes (corpus)": [],
        # (detected, defects, true findings, findings) before -> after; labels and denominators unchanged.
        "detection before": {"R06": (0, 3, 0, 0), "R08": (0, 2, 0, 0), "overall": (36, 46, 54, 60)},
        "detection after": {"R06": (3, 3, 3, 3), "R08": (2, 2, 1, 1), "overall": (41, 46, 58, 64)},
        # The 6 false findings are the earlier checks' (decoys and r01-clean's title), unchanged; the new checks add none,
        # on the pack's controls (r06-clean, r08-clean, d09-clean) or on the 37-file corpus.
        "false findings": {"before": 6, "after": 6, "of the new checks": 0},
    },
}

# Per scenario: (defects detected, labelled defects, true findings, findings of the scenario's checks).
BASELINE_DETECTION = {
    "R01": (2, 2, 2, 4),  # the title (Title style) is read as a Heading 1 of another size: flagged, in r01-clean too
    "R02": (17, 18, 17, 17),  # d13-d, the empty paragraph after a table, is left alone (manifest gap)
    "R03": (2, 2, 2, 3),  # a heading starting with a year ("2026 targets") is taken for a numbering gap
    "R04": (4, 4, 5, 5),
    "R05": (5, 5, 24, 27),  # its checks are shared with R09: the Wingdings symbol and the deliberate red warning
    "R06": (3, 3, 3, 3),  # fake_headings (S2-140): the three bold 16 pt Normal paragraphs; r06-clean clean
    "R07": (4, 4, 4, 4),
    "R08": (2, 2, 1, 1),  # headers_footers (S2-140): one document-level finding (section 2: header year/name, empty footer)
    # counts for both document-level labels -- the harness's rule for {"document": 1} regions; r08-clean clean
    "R09": (2, 6, 24, 27),  # repeated formatting is folded away on import (d03, r09-c)
}
BASELINE_OVERALL = {"defects": 46, "detected": 41, "findings": 64, "true findings": 58}  # 36, 60, 54 before S2-140 (HISTORY)
BASELINE_OUTSIDE = {"alt_text": 2, "captions": 7, "sections": 2, "unsupported": 20}
BASELINE_REPAIR = {"repaired": 21, "blocked (SafeEdit)": 2, "refused (document)": 0, "refused (block)": 2, "not repaired": 25}
BASELINE_RIGHT = (21, 23)  # the others: r07's two (SafeEdit blocked the file); before B-032 also r05's Wingdings decoy
BASELINE_REQUIRED = (15, 23)  # R01, R02, R06: "proposes"
BASELINE_REFUSED = {"broken_package": 2, "macros": 1, "signed": 1, "tracked_changes": 1}
BASELINE_UNSAFE: list[str] = []  # before B-032: r05's lost Wingdings character (HISTORY)
BASELINE_UNDETECTED: list[str] = []  # before B-032: r05's symbol (HISTORY)
BASELINE_NEW_AFTER_REPAIR = {"direct_formatting": 7, "spacing": 7}  # space given to the paragraph next to a removed empty one
BASELINE_CORPUS_UNDETECTED: list[str] = []  # before B-033: the list below
BASELINE_CORPUS_UNDETECTED_BEFORE_B033 = [  # an empty default header or footer replaced by "same as previous" on write-back
    "word/a04-images.docx: structure -- sections or their headers and footers differ; 1 package parts gone",
    "word/r01-university-paper.docx: structure -- sections or their headers and footers differ; 1 package parts gone",
    "word/r03-contract.docx: structure -- sections or their headers and footers differ; 1 package parts gone",
    "word/r05-invoice.docx: structure -- sections or their headers and footers differ; 1 package parts gone",
]
BASELINE_LABELS = {
    "d01-a": {"repaired": 2}, "d01-b": {"repaired": 3}, "d01-c": {"repaired": 1},
    "d02-a": {"not repaired": 1}, "d02-b": {"not repaired": 1},
    "d03-a": {"not repaired": 1}, "d03-b": {"not repaired": 1}, "d03-c": {"not repaired": 1},
    "d04-a": {"repaired": 1}, "d05-a": {"repaired": 1},
    "d06-a": {"repaired": 1}, "d06-b": {"repaired": 1},
    "d07-a": {"repaired": 1}, "d07-b": {"repaired": 1},
    "d08-a": {"not repaired": 1}, "d08-b": {"not repaired": 1},
    "d10-a": {"refused": "signed"}, "d11-a": {"refused": "macros"}, "d12-a": {"refused": "tracked_changes"},
    "d13-a": {"repaired": 2}, "d13-b": {"not repaired": 1}, "d13-c": {"repaired": 1}, "d13-d": {"not repaired": 1},
    "r01-a": {"not repaired": 1}, "r01-b": {"not repaired": 1}, "r01-x": {"left as it was": 1},
    "r02-a": {"not repaired": 1}, "r02-b": {"not repaired": 1}, "r02-x": {"left as it was": 1},
    "r03-a": {"not repaired": 1}, "r03-b": {"not repaired": 1}, "r03-x": {"left as it was": 1},
    "r04-a": {"not repaired": 1}, "r04-b": {"not repaired": 1}, "r04-c": {"repaired": 2},
    "r05-a": {"repaired": 1}, "r05-x": {"left as it was": 1},  # before B-032: changed
    "r06-a": {"not repaired": 1}, "r06-b": {"not repaired": 1}, "r06-c": {"not repaired": 1},
    "r07-a": {"blocked (SafeEdit)": 1}, "r07-b": {"blocked (SafeEdit)": 1},
    "r08-a": {"not repaired": 1}, "r08-b": {"not repaired": 1}, "r08-c": {"repaired": 1},
    "r09-a": {"not repaired": 1}, "r09-b": {"not repaired": 1}, "r09-c": {"not repaired": 1}, "r09-x": {"left as it was": 1},
    "r10-d": {"refused": "broken_package"}, "r10-a": {"refused (block)": 1}, "r10-b": {"refused (block)": 1}, "r10-c": {"repaired": 2},
}


def test_the_history_keeps_every_earlier_baseline():
    first = HISTORY["S2-100 baseline, 2026-10-22"]
    assert first["repairs that came out right"] == (21, 24) and first["undetected changes (pack)"] != []
    latest = list(HISTORY.values())[-1]
    assert latest["repairs that came out right"] == BASELINE_RIGHT and latest["unsafe"] == BASELINE_UNSAFE
    assert latest["undetected changes (pack)"] == BASELINE_UNDETECTED and latest["r05-x"] == BASELINE_LABELS["r05-x"]
    assert latest["undetected changes (corpus)"] == BASELINE_CORPUS_UNDETECTED
    assert len(BASELINE_CORPUS_UNDETECTED_BEFORE_B033) == 4
    s2_140 = HISTORY["S2-140 (local, 2026-10-27): R06 and R08 get checks -- fake_headings, headers_footers -- diagnosis only"]
    assert s2_140["detection before"]["overall"] == (36, 46, 54, 60)
    assert s2_140["detection after"]["overall"] == tuple(BASELINE_OVERALL[key] for key in ("detected", "defects", "true findings", "findings"))


def test_the_originals_are_never_written(measured):
    assert measured["after"] == measured["before"]


def test_detection_baseline(measured):
    detection = measured["report"]["detection"]
    assert {category: (row["detected"], row["defects"], row["true findings"], row["findings"]) for category, row in detection["by_category"].items()} == BASELINE_DETECTION
    assert {key: detection["overall"][key] for key in BASELINE_OVERALL} == BASELINE_OVERALL
    assert detection["outside_the_scenarios"] == BASELINE_OUTSIDE
    assert detection["R07 cause named"] == {"detected": 4, "cause named": 3}  # r07-b: the paragraph's "page break before" isn't named


def test_the_s2_140_checks_find_only_their_defects(measured):
    """R06 and R08's own checks (S2-140): every finding on a labelled defect, their controls and the clean document
    clean -- no false finding, so the 6 the pack counts stay the earlier checks'."""
    detection = measured["report"]["detection"]
    for category, check in (("R06", "fake_headings"), ("R08", "headers_footers")):
        row = detection["by_category"][category]
        assert row["false findings"] == 0 and row["missed"] == 0, category
        assert all(control.endswith(": clean") for control in row["controls"]), row["controls"]
        by_check = detection["by_check"][check]
        assert by_check["findings"] == by_check["true"] and by_check["precision"] == 1.0, by_check
    overall = detection["overall"]
    assert overall["findings"] - overall["true findings"] == 6


def test_repair_baseline(measured):
    repair = measured["report"]["repair"]
    assert repair["outcomes"] == BASELINE_REPAIR
    assert (repair["repairs that came out right"]["repaired"], repair["repairs that came out right"]["of attempted"]) == BASELINE_RIGHT
    assert (repair["required repairs done"]["repaired"], repair["required repairs done"]["of"]) == BASELINE_REQUIRED
    assert repair["refused documents"] == BASELINE_REFUSED
    assert repair["block refusals"] == 2  # r10-objects: the link's and the bookmark's paragraphs
    assert repair["SafeEdit blocked"] == {"untouched": 1}  # r07: a block next to the removed page break came out different
    assert repair["unsafe"] == BASELINE_UNSAFE


def test_preservation_baseline(measured, corpus):
    preservation = measured["report"]["preservation"]
    assert preservation["files repaired and compared"] == 29
    assert preservation["verified by SafeEdit"] == 28
    assert preservation["blocks changed outside the labels"] == 0
    assert preservation["undetected changes"] == BASELINE_UNDETECTED
    assert preservation["new findings after repair, by check"] == BASELINE_NEW_AFTER_REPAIR
    assert (corpus["files"], corpus["refused"], corpus["repaired and compared"], corpus["verified by SafeEdit"]) == (37, 2, 35, 35)
    assert corpus["undetected changes"] == BASELINE_CORPUS_UNDETECTED


def test_every_label_baseline(measured):
    assert {label_id: record["outcome"] for label_id, record in measured["report"]["labels"].items()} == BASELINE_LABELS


# -- Invariants: never relaxed ---------------------------------------------------------------------------------


def test_no_undetected_change_of_text_numbers_tables_or_objects(measured, corpus):
    never = ("text", "numbers", "tables", "objects")
    lines = measured["report"]["preservation"]["undetected changes"] + corpus["undetected changes"]
    assert [line for line in lines if line.split(": ", 1)[1].split(" --")[0] in never] == []


def test_every_expected_refusal_is_made_and_a_refused_file_gets_no_repair(measured):
    for result in measured["results"]:
        for label in result.entry["labels"]:
            if "refusal" in label:
                assert label["refusal"] in result.refusals, label["id"]
        if result.refusals:
            assert result.verified is None and not result.regions_after, result.name


def test_nothing_is_repaired_on_a_control(measured):
    for result in measured["results"]:
        if result.entry["kind"] == "control":
            assert result.by_repair == {} and result.verified is True and not result.changed_blocks, result.name


def test_r10_objects_are_kept_or_their_repair_refused(measured):
    assert measured["report"]["R10"]["safe outcomes"] == "8/8"
    for result in measured["results"]:
        if result.entry["category"] == "R10" and result.verified is not None:
            assert result.missing == [], result.name


# -- Section 29 targets (strict xfail where not met yet) ---------------------------------------------------------


def test_target_detection_precision_at_least_90_percent(measured):
    assert measured["report"]["detection"]["overall"]["precision"] >= 0.90


def test_target_detection_recall_at_least_85_percent(measured):  # met since S2-140 (41/46 = 89.1 %); a strict xfail before (36/46)
    assert measured["report"]["detection"]["overall"]["recall"] >= 0.85


@pytest.mark.xfail(strict=True, reason="21/23 = 91.3% (87.5% before B-032): r07's repairs blocked by SafeEdit")
def test_target_repairs_right_at_least_95_percent(measured):
    assert measured["report"]["repair"]["repairs that came out right"]["rate"] >= 0.95


def test_target_zero_undetected_changes(measured, corpus):  # met since B-032 (pack) and B-033 (corpus); a strict xfail before
    assert measured["report"]["preservation"]["undetected changes"] + corpus["undetected changes"] == []


def test_target_every_predefined_unsupported_case_recognised(measured):
    r10 = measured["report"]["R10"]
    assert r10["refused as expected"] == r10["refusals expected"] == 4
