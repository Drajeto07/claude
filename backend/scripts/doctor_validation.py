"""Validation Pack v1 (S2-100): Doctor v0 measured on the labelled scenarios R01-R10 (tests/fixtures/doctor,
scripts/make_validation_pack.py), the way the app runs it (app/doctor/corpus.py) -- no second Doctor, no change
to what Doctor does.

    python -m scripts.doctor_validation               the report (about a minute)
    python -m scripts.doctor_validation --json        the same numbers as JSON
    python -m scripts.doctor_validation --no-corpus   without the preservation run over the Word corpus

Three measures, kept apart -- never one score:

1. Detection. A finding is one Document Health check (warn or fail, as Doctor shows it) naming one block.
   Recall = labelled defects found by their scenario's own checks / labelled defects.
   Precision = findings on a labelled defect / all findings of the scenario checks (decoys, controls and
   unlabelled blocks are the false ones). R06 and R08 have no check: their defects count as missed.
2. Repair. Doctor's safe repairs accepted, the repaired file written and checked (SafeEdit). A defect is repaired
   when it is gone from the repaired file and the file is verified; "blocked" when it is gone but SafeEdit did
   not verify the file (nobody gets that file); refused, by document or by block, with the reason; not repaired.
   Unsafe: a decoy or a kept object lost, a region emptied of more than its defects, or a content difference.
3. Preservation, read here independently of SafeEdit, from both files' XML: the body's text, numbers and dates,
   table cells and merges, sections, headers and footers, objects (bookmarks, fields, links, content controls,
   comments, drawings) and symbol-font characters. A difference SafeEdit verified is an undetected change.
   Also run over the Word corpus of Doctor's invariant tests (no labels: preservation only).

All of it is synthetic (the development set); it proves nothing about real documents (S2-107).
"""

import argparse
import io
import json
import pathlib
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field

from lxml import etree

from app.doctor.corpus import imported, run
from app.doctor.doctor import analyse
from app.doctor.word_repairs import find_all
from app.formatting import health
from app.models.document import walk_elements

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "doctor"
PACK = FIXTURES / "validation_pack.json"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": W, "r": R}
SYMBOL_FONTS = {"symbol", "wingdings", "wingdings 2", "wingdings 3", "webdings", "marlett", "zapf dingbats", "mt extra"}
NUMBER = re.compile(r"\d+(?:[.,:/-]\d+)*")


def _w(name: str) -> str:
    return f"{{{W}}}{name}"


# -- Reading the Word file itself ------------------------------------------------------------------------------


def parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        return {name: package.read(name) for name in package.namelist()}


def body_blocks(data: bytes) -> list[etree._Element]:
    """The children of the main document's body, as Doctor's block indexes count them."""
    root = etree.fromstring(parts(data)["word/document.xml"])
    body = root.find(_w("body"))
    return list(body) if body is not None else []


def text_of(element: etree._Element) -> str:
    return "".join(node.text or "" for node in element.iter(_w("t")))


def _page_break_paragraph(block: etree._Element) -> bool:
    return block.tag == _w("p") and not text_of(block).strip() and any(br.get(_w("type")) == "page" for br in block.iter(_w("br")))


def _starts_new_page(block: etree._Element) -> bool:
    flag = block.find("w:pPr/w:pageBreakBefore", NS)
    return flag is not None and flag.get(_w("val"), "true") not in ("0", "false", "off")


def _empty_paragraph(block: etree._Element) -> bool:
    if block.tag != _w("p") or text_of(block).strip() or _page_break_paragraph(block):
        return False
    return block.find(".//w:drawing", NS) is None and block.find(".//w:pict", NS) is None and block.find("w:pPr/w:sectPr", NS) is None


class LabelNotFound(ValueError):
    pass


def locate(where: dict, blocks: list[etree._Element]) -> list[int]:
    """The block indexes of a label's region (scripts/make_validation_pack.py describes the forms)."""
    if "document" in where:
        return []
    if "picture" in where:
        holding = [index for index, block in enumerate(blocks) if block.find(".//w:drawing", NS) is not None]
        if len(holding) <= where["picture"]:
            raise LabelNotFound(f"picture {where['picture']}")
        return [holding[where["picture"]]]
    if "breaks_at_start" in where:
        found = []
        for index, block in enumerate(blocks):
            if not _page_break_paragraph(block):
                break
            found.append(index)
        return found
    marker = where.get("text") or where.get("empty_after") or where.get("breaks_after")
    matches = [index for index, block in enumerate(blocks) if marker in text_of(block)]
    nth = where.get("nth", 0)
    if len(matches) <= nth or ("nth" not in where and len(matches) != 1):
        raise LabelNotFound(f"{marker!r}: {len(matches)} blocks")
    anchor = matches[nth]
    if "text" in where:
        return [anchor]
    found = []
    for index in range(anchor + 1, len(blocks)):
        block = blocks[index]
        if "empty_after" in where and _empty_paragraph(block):
            found.append(index)
        elif "breaks_after" in where and _page_break_paragraph(block):
            found.append(index)
        elif "breaks_after" in where and _starts_new_page(block):
            found.append(index)
            break
        else:
            break
    return found


# -- Preservation, read independently -------------------------------------------------------------------------


def _relationships(files: dict[str, bytes], part: str) -> dict[str, str]:
    folder, name = part.rsplit("/", 1)
    rels = files.get(f"{folder}/_rels/{name}.rels")
    if rels is None:
        return {}
    return {rel.get("Id"): rel.get("Target") for rel in etree.fromstring(rels)}


def _paragraph_texts(root: etree._Element) -> list[str]:
    return [" ".join(text_of(paragraph).split()) for paragraph in root.iter(_w("p")) if text_of(paragraph).strip()]


def _run_font(run: etree._Element) -> str:
    fonts = run.find("w:rPr/w:rFonts", NS)
    return "" if fonts is None else (fonts.get(_w("ascii")) or fonts.get(_w("hAnsi")) or fonts.get(_w("cs")) or "")


def content(data: bytes) -> dict:
    """What a repair must not change, read from the package's XML."""
    files = parts(data)
    root = etree.fromstring(files["word/document.xml"])
    rels = _relationships(files, "word/document.xml")
    sections = []
    for section in root.iter(_w("sectPr")):
        references = []
        for reference in section:
            if reference.tag in (_w("headerReference"), _w("footerReference")):
                target = rels.get(reference.get(f"{{{R}}}id"), "")
                part = files.get(f"word/{target}")
                references.append((etree.QName(reference).localname, reference.get(_w("type")), tuple(_paragraph_texts(etree.fromstring(part))) if part else None))
        sections.append(tuple(sorted(references, key=str)))
    tables = []
    for table in root.iter(_w("tbl")):
        rows = []
        for row in table.findall("w:tr", NS):
            cells = []
            for cell in row.findall("w:tc", NS):
                span = cell.find("w:tcPr/w:gridSpan", NS)
                merge = cell.find("w:tcPr/w:vMerge", NS)
                cells.append((" ".join(text_of(cell).split()), span.get(_w("val")) if span is not None else "1", None if merge is None else merge.get(_w("val"), "continue")))
            rows.append(tuple(cells))
        tables.append(tuple(rows))
    other_text = []
    for name in sorted(files):
        if re.fullmatch(r"word/(header|footer)\d*\.xml|word/(footnotes|endnotes|comments)\.xml", name):
            other_text += _paragraph_texts(etree.fromstring(files[name]))
    body = _paragraph_texts(root)
    symbols = sorted(
        (text_of(run), _run_font(run)) for run in root.iter(_w("r")) if _run_font(run).lower() in SYMBOL_FONTS and text_of(run)
    ) + sorted((symbol.get(_w("font")) or "", symbol.get(_w("char")) or "") for symbol in root.iter(_w("sym")))
    links = sorted(rels.get(link.get(f"{{{R}}}id"), "") if link.get(f"{{{R}}}id") else "#" + (link.get(_w("anchor")) or "") for link in root.iter(_w("hyperlink")))
    comments = files.get("word/comments.xml")
    return {
        "text": body,
        "numbers": sorted(Counter(NUMBER.findall(" ".join(body + other_text))).items()),
        "tables": tables,
        "sections": sections,
        "objects": {
            "bookmarks": sorted(mark.get(_w("name")) or "" for mark in root.iter(_w("bookmarkStart"))),
            "fields": sorted(
                [(field.get(_w("instr")) or "").strip() for field in root.iter(_w("fldSimple"))]
                + [(code.text or "").strip() for code in root.iter(_w("instrText"))]
            ),
            "links": links,
            "content_controls": sorted((tag.get(_w("val")) or "") for tag in root.iter(_w("tag"))),
            "comments": 0 if comments is None else sum(1 for _ in etree.fromstring(comments).iter(_w("comment"))),
            "comment_marks": sum(1 for _ in root.iter(_w("commentRangeStart"))),
            "drawings": sum(1 for _ in root.iter(_w("drawing"))),
            "notes": sum(1 for _ in root.iter(_w("footnoteReference"))) + sum(1 for _ in root.iter(_w("endnoteReference"))),
            "tracked": sum(1 for _ in root.iter(_w("ins"))) + sum(1 for _ in root.iter(_w("del"))),
        },
        "symbols": symbols,
        "colours": sorted(
            (text_of(run), colour.get(_w("val")) or "", run.find("w:rPr/w:b", NS) is not None)
            for run in root.iter(_w("r"))
            if (colour := run.find("w:rPr/w:color", NS)) is not None and text_of(run).strip()
        ),
        "styles": sorted(style.get(_w("styleId")) or "" for style in etree.fromstring(files["word/styles.xml"]).iter(_w("style"))) if "word/styles.xml" in files else [],
        "parts": sorted(files),
    }


DIFFERENCE_KINDS = ("text", "numbers", "tables", "structure", "objects", "symbols")


def differences(original: bytes, result: bytes) -> dict[str, list[str]]:
    """What changed that a layout repair may not change, by kind. Empty lists: nothing did."""
    before, after = content(original), content(result)
    found: dict[str, list[str]] = {kind: [] for kind in DIFFERENCE_KINDS}
    if before["text"] != after["text"]:
        changed = sum(1 for a, b in zip(before["text"], after["text"]) if a != b) + abs(len(before["text"]) - len(after["text"]))
        found["text"].append(f"{changed} of {len(before['text'])} paragraphs' text differ")
    if before["numbers"] != after["numbers"]:
        lost = Counter(dict(before["numbers"])) - Counter(dict(after["numbers"]))
        added = Counter(dict(after["numbers"])) - Counter(dict(before["numbers"]))
        found["numbers"].append(f"{sum(lost.values())} numbers or dates missing, {sum(added.values())} added")
    if before["tables"] != after["tables"]:
        if len(before["tables"]) != len(after["tables"]):
            found["tables"].append(f"{len(before['tables'])} tables became {len(after['tables'])}")
        for index, (a, b) in enumerate(zip(before["tables"], after["tables"])):
            if a != b:
                found["tables"].append(f"table {index + 1}: cells, rows or merges differ")
    if before["sections"] != after["sections"]:
        found["structure"].append("sections or their headers and footers differ")
    lost_parts = sorted(set(before["parts"]) - set(after["parts"]))
    if lost_parts:
        found["structure"].append(f"{len(lost_parts)} package parts gone")
    lost_styles = sorted(set(before["styles"]) - set(after["styles"]))
    if lost_styles:
        found["structure"].append(f"{len(lost_styles)} styles gone")
    for name, value in before["objects"].items():
        if value != after["objects"][name]:
            found["objects"].append(f"{name} differ")
    if before["symbols"] != after["symbols"]:
        found["symbols"].append(f"{len(before['symbols'])} symbol-font characters before, {len(after['symbols'])} kept")
    return found


def kept(keep: dict, result: bytes) -> list[str]:
    """The label file's `keep` list checked in the repaired file: what is missing."""
    after = content(result)
    missing = []
    for name in ("bookmarks", "links", "content_controls"):
        missing += [f"{name[:-1]} {value}" for value in keep.get(name, []) if value not in after["objects"][name]]
    missing += [f"field {value}" for value in keep.get("fields", []) if not any(value in code for code in after["objects"]["fields"])]
    for name in ("drawings", "comments"):
        if name in keep and after["objects"][name] < keep[name]:
            missing.append(f"{keep[name] - after['objects'][name]} {name}")
    missing += [f"{font} character" for text, font in keep.get("symbols", []) if (text, font) not in after["symbols"]]
    missing += [f"colour {colour} of {text}" for text, colour in keep.get("colours", []) if not any(t == text and c.upper() == colour for t, c, _ in after["colours"])]
    return missing


# -- Measuring one file ---------------------------------------------------------------------------------------


@dataclass
class Finding:
    check: str
    blocks: list[int]
    message: str


@dataclass
class FileResult:
    name: str
    entry: dict
    refusals: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    after: list[Finding] = field(default_factory=list)
    block_refusals: list[tuple[str, list[int]]] = field(default_factory=list)
    verified: bool | None = None
    failed_checks: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    by_repair: dict[str, int] = field(default_factory=dict)
    regions: dict[str, list[int]] = field(default_factory=dict)
    regions_after: dict[str, list[int] | None] = field(default_factory=dict)
    changed_blocks: set[int] = field(default_factory=set)
    differences: dict[str, list[str]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


# Doctor also finds, in the Word file itself, what it repairs there (shown in its report next to the checks):
# counted as findings of the check they belong to, once per block, unless a check already named that block.
WORD_REPAIR_CHECK = {"empty_paragraphs": "empty_paragraphs", "wide_table": "layout", "wide_picture": "layout"}


def _add_word_repairs(findings: list, repairs) -> None:
    for repair in repairs:
        check = WORD_REPAIR_CHECK[repair.kind]
        for block in repair.blocks:
            if not any(finding.check == check and block in finding.blocks for finding in findings):
                findings.append(Finding(check, [block], f"repair in the Word file: {repair.kind}"))


def _canonical(block: etree._Element) -> bytes:
    return etree.tostring(block, method="c14n")


def measure_file(name: str, entry: dict, data: bytes) -> FileResult:
    result = FileResult(name, entry)
    blocks = body_blocks(data)
    result.regions = {label["id"]: locate(label["where"], blocks) for label in entry["labels"]}

    document = imported(data, name)
    analysis = analyse(document, data, name=name)
    result.refusals = [refusal.code for refusal in analysis.refusals]
    elements = {element.id: element for element in walk_elements(document.elements)}
    result.findings = [
        Finding(finding.checkId, list(elements[element_id].sourceBlocks or []) if element_id in elements else [], issue["message"])
        for finding in analysis.findings
        for issue in (finding.issues or [{"message": finding.summary, "elementIds": []}])
        for element_id in (issue["elementIds"] or [None])
    ]
    _add_word_repairs(result.findings, analysis.wordRepairs)
    result.block_refusals = [(refusal.checkId, list(elements[refusal.elementId].sourceBlocks or []) if refusal.elementId in elements else []) for refusal in analysis.blockRefusals]

    outcome = run(data, name)
    result.by_repair, result.skipped = dict(outcome.by_repair), list(outcome.skipped)
    if outcome.refusals or outcome.file is None:
        return result
    repaired = outcome.file
    result.verified = outcome.verified
    result.failed_checks = [f"{check.name}: {check.detail}" for check in outcome.result.failed()] if outcome.result else []
    after_blocks = body_blocks(repaired)
    for label in entry["labels"]:
        try:
            result.regions_after[label["id"]] = locate(label["where"], after_blocks)
        except LabelNotFound:
            result.regions_after[label["id"]] = None
    after_document = imported(repaired, name)
    result.after = [
        Finding(check.id, list(element.sourceBlocks or []) if (element := {e.id: e for e in walk_elements(after_document.elements)}.get(element_id)) else [], issue.message)
        for check in health.check_health(after_document).checks
        if check.status in ("warn", "fail")
        for issue in (check.issues or [health.HealthIssue(message=check.summary, elementIds=[])])
        for element_id in (issue.elementIds or [None])
    ]
    _add_word_repairs(result.after, find_all(repaired))
    remaining = Counter(_canonical(block) for block in after_blocks)
    for index, block in enumerate(blocks):
        key = _canonical(block)
        if remaining[key] > 0:
            remaining[key] -= 1
        elif etree.QName(block).localname != "sectPr":
            result.changed_blocks.add(index)
    result.differences = differences(data, repaired)
    result.missing = kept(entry.get("keep", {}), repaired)
    return result


# -- The numbers ----------------------------------------------------------------------------------------------


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def score(results: list[FileResult], categories: dict) -> dict:
    detectors = {category: set(spec["detectors"]) for category, spec in categories.items()}
    scenario_checks = set().union(*(detectors[category] for category in categories if category != "R10"))
    per_category = {category: Counter() for category in categories}
    per_check: dict[str, Counter] = {}
    outside: Counter = Counter()
    clean: dict[str, list[str]] = {category: [] for category in categories}
    repair = Counter()
    refused_documents: Counter = Counter()
    blocked_by: Counter = Counter()
    unsafe: list[str] = []
    preservation = Counter()
    undetected: list[str] = []
    explained = Counter()
    r10 = Counter()
    misses: list[str] = []
    per_label: dict[str, dict] = {}
    new_after: Counter = Counter()

    for result in results:
        labels = result.entry["labels"]
        regions = result.regions
        # Detection -- every finding of a scenario check, against the labels.
        budget = {(label["id"], check): label["defects"] for label in labels for check in scenario_checks}
        for finding in result.findings:
            if finding.check not in scenario_checks:
                outside[finding.check] += 1
                continue
            counter = per_check.setdefault(finding.check, Counter())
            counter["findings"] += 1
            owner = next((label for label in labels if set(regions[label["id"]]) & set(finding.blocks)), None)
            if owner is None and not finding.blocks:
                owner = next((label for label in labels if "document" in label["where"] and finding.check in detectors[label["category"]] and label["defects"]), None)
            if owner is not None and budget[(owner["id"], finding.check)] > 0:
                budget[(owner["id"], finding.check)] -= 1
                kind = "true"
            else:
                kind = "decoy" if owner is not None and owner["defects"] == 0 else ("excess" if owner is not None else ("control" if result.entry["kind"] == "control" else "unlabelled"))
            counter[kind] += 1
            for category in categories:
                if category != "R10" and finding.check in detectors[category]:
                    per_category[category]["findings"] += 1
                    per_category[category][kind] += 1
        if result.entry["kind"] == "control" and result.entry["category"] in categories:
            category = result.entry["category"]
            flagged = [finding.check for finding in result.findings if finding.check in detectors[category]]
            clean[category].append(f"{result.name}: {'clean' if not flagged else ', '.join(sorted(set(flagged)))}")
        if result.name == "d09-clean.docx":
            for category in categories:
                flagged = [finding.check for finding in result.findings if finding.check in detectors[category]]
                if category != "R10":
                    clean[category].append(f"{result.name}: {'clean' if not flagged else ', '.join(sorted(set(flagged)))}")

        for label in labels:
            category, defects = label["category"], label["defects"]
            region = set(regions[label["id"]])
            record = per_label[label["id"]] = {"file": result.name, "category": category, "defects": defects}
            if category == "R10":
                r10["labels"] += 1
            # Recall, per labelled defect.
            if defects and category != "R10":
                per_category[category]["defects"] += defects
                if "document" in label["where"]:
                    hit = min(defects, 1 if any(finding.check in detectors[category] for finding in result.findings) else 0)
                else:
                    flagged_blocks = {block for finding in result.findings if finding.check in detectors[category] for block in finding.blocks} & region
                    hit = min(defects, len(flagged_blocks))
                per_category[category]["detected"] += hit
                record["detected"] = hit
                if hit < defects:
                    misses.append(f"{label['id']} ({category}): {defects - hit} of {defects} missed -- {label['about']}")
                if category == "R07" and hit:
                    messages = " ".join(finding.message.lower() for finding in result.findings if finding.check == "page_breaks" and set(finding.blocks) & region)
                    explained["detected"] += hit
                    explained["cause named"] += hit if any(phrase in messages for phrase in label.get("explains", [])) else 0
            # Repair, per labelled defect.
            if "refusal" in label:
                r10["refusals expected"] += 1
                r10["refused as expected"] += 1 if label["refusal"] in result.refusals else 0
                record["outcome"] = {"refused" if label["refusal"] in result.refusals else "NOT refused": label["refusal"]}
                continue
            if not defects:
                record["flagged by"] = sorted({finding.check for finding in result.findings if finding.check in scenario_checks and set(finding.blocks) & region})
                after = result.regions_after.get(label["id"])
                gone = len(region) - len(after) if region and after is not None else 0
                if gone > 0:
                    unsafe.append(f"{result.name} {label['id']}: {gone} block(s) of a decoy region removed")
                record["outcome"] = {"refused (document)": 1} if result.refusals else ({"decoy region removed": gone} if gone > 0 else {"changed" if result.changed_blocks & region else "left as it was": 1})
                if not result.refusals and (gone > 0 or result.changed_blocks & region):
                    repair["repairs of a decoy"] += 1
                    if category == "R10":
                        r10["unsafe"] += 1
                continue
            units = Counter()
            if result.refusals:
                units["refused (document)"] += defects
            else:
                after = result.regions_after.get(label["id"])
                refused_here = any(set(blocks) & region for _, blocks in result.block_refusals)
                if after is None:
                    fixed = 0
                    unsafe.append(f"{result.name} {label['id']}: the labelled block is gone from the repaired file")
                elif "empty_after" in label["where"] or "breaks_after" in label["where"] or "breaks_at_start" in label["where"]:
                    removed = len(region) - len(after)
                    fixed = max(0, min(defects, removed))
                    if removed > defects:
                        unsafe.append(f"{result.name} {label['id']}: {removed - defects} block(s) removed beyond the defects")
                else:
                    checks = detectors[category]
                    before = any(finding.check in checks and set(finding.blocks) & region for finding in result.findings)
                    still = any(finding.check in checks and set(finding.blocks) & set(after) for finding in result.after)
                    fixed = 1 if before and not still else 0
                if fixed:
                    units["repaired" if result.verified else "blocked (SafeEdit)"] += fixed
                rest = defects - fixed
                if rest:
                    units["refused (block)" if refused_here else "not repaired"] += rest
            record["outcome"] = dict(units)
            for outcome, count in units.items():
                repair[outcome] += count
                repair[f"{categories[category]['mvp']}:{outcome}"] += count
                if category == "R10":
                    r10[outcome] += count
            repair["defects"] += defects
            repair[f"{categories[category]['mvp']}:defects"] += defects
            if category == "R10":
                r10["defects"] += defects

        for code in result.refusals:
            refused_documents[code] += 1
        if result.verified is None:
            continue
        preservation["files repaired and compared"] += 1
        preservation["verified by SafeEdit" if result.verified else "not verified by SafeEdit"] += 1
        if not result.verified:
            for detail in result.failed_checks:
                blocked_by[detail.split(":")[0]] += 1
        for kind, found in result.differences.items():
            if found:
                preservation[f"{kind} differences"] += 1
                if result.verified:
                    undetected.append(f"{result.name}: {kind} -- {'; '.join(found)}")
        for missing in result.missing:
            unsafe.append(f"{result.name}: lost {missing}" + (" (SafeEdit verified the file)" if result.verified else " (SafeEdit blocked the file)"))
        before_checks = Counter(finding.check for finding in result.findings if finding.check in scenario_checks)
        after_checks = Counter(finding.check for finding in result.after if finding.check in scenario_checks)
        for check, count in (after_checks - before_checks).items():
            new_after[check] += count
            preservation["new findings after repair"] += count
        labelled = {block for blocks in result.regions.values() for block in blocks}
        # A removed empty paragraph's space goes to the paragraph before it, or after it (word_repairs.py).
        receivers = {index for blocks in result.regions.values() if blocks for index in (min(blocks) - 1, max(blocks) + 1)}
        outside_changes = result.changed_blocks - labelled - receivers
        preservation["blocks changed outside the labels"] += len(outside_changes)
        if result.skipped:
            preservation["word repairs skipped"] += len(result.skipped)

    detection = {}
    totals = Counter()
    for category, counter in per_category.items():
        if category == "R10":
            continue
        true, findings, defects, detected = counter["true"], counter["findings"], counter["defects"], counter["detected"]
        detection[category] = {
            "scenario": categories[category]["scenario"],
            "checks": sorted(detectors[category]),
            "defects": defects,
            "detected": detected,
            "missed": defects - detected,
            "recall": _ratio(detected, defects),
            "findings": findings,
            "true findings": true,
            "false findings": findings - true,
            "false by kind": {kind: counter[kind] for kind in ("decoy", "excess", "control", "unlabelled") if counter[kind]},
            "precision": _ratio(true, findings),
            "controls": clean[category],
        }
        totals["defects"] += defects
        totals["detected"] += detected
    all_findings = sum(counter["findings"] for counter in per_check.values())
    all_true = sum(counter["true"] for counter in per_check.values())
    attempted = repair["repaired"] + repair["blocked (SafeEdit)"] + repair["repairs of a decoy"]
    return {
        "files": len(results),
        "detection": {
            "overall": {
                "defects": totals["defects"],
                "detected": totals["detected"],
                "recall": _ratio(totals["detected"], totals["defects"]),
                "findings": all_findings,
                "true findings": all_true,
                "precision": _ratio(all_true, all_findings),
            },
            "by_category": detection,
            "by_check": {check: {**dict(counter), "precision": _ratio(counter["true"], counter["findings"])} for check, counter in sorted(per_check.items())},
            "outside_the_scenarios": dict(sorted(outside.items())),
            "R07 cause named": dict(explained),
            "missed": misses,
        },
        "repair": {
            "defects": repair["defects"],
            "outcomes": {outcome: repair[outcome] for outcome in ("repaired", "blocked (SafeEdit)", "refused (document)", "refused (block)", "not repaired")},
            "by_mvp": {
                mvp: {
                    "defects": repair[f"{mvp}:defects"],
                    **{outcome: repair[f"{mvp}:{outcome}"] for outcome in ("repaired", "blocked (SafeEdit)", "refused (document)", "refused (block)", "not repaired") if repair[f"{mvp}:{outcome}"]},
                }
                for mvp in ("repair", "detect", "diagnose", "safe")
            },
            "required repairs done": {"repaired": repair["repair:repaired"], "of": repair["repair:defects"], "rate": _ratio(repair["repair:repaired"], repair["repair:defects"])},
            "repairs that came out right": {
                "repaired": repair["repaired"],
                "of attempted": attempted,
                "rate": _ratio(repair["repaired"], attempted),
                "the others": {"blocked (SafeEdit)": repair["blocked (SafeEdit)"], "repairs of a decoy": repair["repairs of a decoy"]},
            },
            "refused documents": dict(sorted(refused_documents.items())),
            "block refusals": sum(len(result.block_refusals) for result in results),
            "SafeEdit blocked": dict(sorted(blocked_by.items())),
            "unsafe": unsafe,
        },
        "preservation": {**{key: preservation[key] for key in sorted(preservation)}, "new findings after repair, by check": dict(sorted(new_after.items())), "undetected changes": undetected},
        "R10": {**dict(r10), "safe outcomes": f"{r10['labels'] - r10['unsafe'] - (r10['refusals expected'] - r10['refused as expected'])}/{r10['labels']}"},
        "labels": per_label,
    }


CORPUS = sorted(path for path in FIXTURES.parent.rglob("*.docx") if path.parent != FIXTURES)  # as tests/test_doctor.py


def measure_corpus(paths: list[pathlib.Path] = CORPUS) -> dict:
    """Preservation only, on the Word corpus Doctor's invariant tests use (no labels): each file repaired as the
    app would, then compared here independently of SafeEdit."""
    found = Counter()
    undetected: list[str] = []
    for path in paths:
        data = path.read_bytes()
        outcome = run(data, path.name)
        found["files"] += 1
        if outcome.refusals or outcome.file is None:
            found["refused"] += 1
            continue
        found["repaired and compared"] += 1
        found["verified by SafeEdit" if outcome.verified else "not verified by SafeEdit"] += 1
        for kind, differences_found in differences(data, outcome.file).items():
            if differences_found:
                found[f"{kind} differences"] += 1
                if outcome.verified:
                    undetected.append(f"{path.parent.name}/{path.name}: {kind} -- {'; '.join(differences_found)}")
    return {**{key: found[key] for key in sorted(found)}, "undetected changes": undetected}


def load_pack() -> dict:
    return json.loads(PACK.read_text(encoding="utf-8"))


def measure(pack: dict | None = None) -> tuple[list[FileResult], dict]:
    pack = pack or load_pack()
    results = [measure_file(name, entry, (FIXTURES / name).read_bytes()) for name, entry in pack["files"].items()]
    return results, score(results, pack["categories"])


def _print(report: dict) -> None:
    def percent(value: float | None) -> str:
        return "n/a" if value is None else f"{100 * value:.1f}%"

    detection = report["detection"]
    overall = detection["overall"]
    print(f"Validation Pack v1 -- {report['files']} synthetic files (development set; not real documents)\n")
    print("1. DETECTION")
    print(f"   recall    {overall['detected']}/{overall['defects']} = {percent(overall['recall'])}   (target >= 85%)")
    print(f"   precision {overall['true findings']}/{overall['findings']} = {percent(overall['precision'])}   (target >= 90%)")
    print(f"   {'':5} {'recall':>14} {'precision':>14}  checks")
    for category, row in detection["by_category"].items():
        print(
            f"   {category:5} {row['detected']:>3}/{row['defects']:<3} {percent(row['recall']):>7} {row['true findings']:>3}/{row['findings']:<3} {percent(row['precision']):>7}  "
            f"{', '.join(row['checks']) or '(no check)'}  false: {row['false by kind'] or '-'}"
        )
    print(f"   R07 cause named: {detection['R07 cause named']}")
    print(f"   findings outside the scenarios (not counted): {detection['outside_the_scenarios']}")
    print("   missed:")
    for line in detection["missed"]:
        print(f"     - {line}")
    repair = report["repair"]
    print("\n2. REPAIR")
    print(f"   outcomes over {repair['defects']} labelled defects: {repair['outcomes']}")
    for mvp, row in repair["by_mvp"].items():
        print(f"     {mvp:9} {row}")
    required, right = repair["required repairs done"], repair["repairs that came out right"]
    print(f"   required by the scenario (R01, R02, R06): {required['repaired']}/{required['of']} = {percent(required['rate'])}")
    print(f"   repairs that came out right: {right['repaired']}/{right['of attempted']} = {percent(right['rate'])}   (target >= 95%); the others: {right['the others']}")
    print(f"   refused documents: {repair['refused documents']}; block refusals: {repair['block refusals']}; SafeEdit blocked: {repair['SafeEdit blocked']}")
    print("   unsafe:")
    for line in repair["unsafe"] or ["none"]:
        print(f"     - {line}")
    print("\n3. PRESERVATION (independent of SafeEdit)")
    for key, value in report["preservation"].items():
        if key != "undetected changes":
            print(f"   {key}: {value}")
    print(f"   undetected changes (SafeEdit verified, a difference found here): {len(report['preservation']['undetected changes'])}   (target 0)")
    for line in report["preservation"]["undetected changes"]:
        print(f"     - {line}")
    if "corpus preservation" in report:
        corpus = report["corpus preservation"]
        print(f"\n   Word corpus ({corpus['files']} files, no labels): " + ", ".join(f"{key} {value}" for key, value in corpus.items() if key not in ("files", "undetected changes")))
        print(f"   undetected changes on the corpus: {len(corpus['undetected changes'])}   (target 0)")
        for line in corpus["undetected changes"]:
            print(f"     - {line}")
    print(f"\nR10: {report['R10']}")
    print("\nPER LABEL")
    for label_id, record in report["labels"].items():
        if "detected" in record:
            seen = f"detected {record['detected']}/{record['defects']}"
        elif "flagged by" in record:
            seen = "decoy, flagged by " + (", ".join(record["flagged by"]) or "nothing")
        else:
            seen = ""
        print(f"   {label_id:7} {record['category']} {record['file']:30} {seen:42} {record.get('outcome', {})}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON")
    parser.add_argument("--no-corpus", action="store_true", help="skip the preservation run over the Word corpus")
    arguments = parser.parse_args(argv)
    _, report = measure()
    if not arguments.no_corpus:
        report["corpus preservation"] = measure_corpus()
    if arguments.json:
        json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        _print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
