"""SafeEdit (docs/SMARTDOC_DOCUMENT_DOCTOR_SAFEEDIT_ANALYSIS.md section 1): what a repaired Word file is checked
for against the original, every time, by reading both files -- never by trusting the code that wrote them.

1. Words: the body's words, and the headers' and footers', are the same, in the same order (the independent
   reader of fidelity/docx_source.py and the word comparison of fidelity/content.py).
2. Untouched blocks: every block of the original's body that no repair touched is in the result, byte for byte
   (canonical XML), in the same order.
3. Preserved features: what the app keeps without editing it -- bookmarks, fields, drawings, content controls,
   section breaks, notes, comments, tracked changes, equations, links -- is all still there: none fewer.
4. A valid package: every part parses, every relationship resolves, every style and list referenced exists
   (export/package_check.py).

All four must hold for the result to be called verified. Each failure says what and how many, never the text of
the document (the person's own content stays in their document, not in a report or a log).
"""

import io
import zipfile
from collections import Counter
from dataclasses import dataclass, field

from lxml import etree

from app.export.package_check import package_problems
from app.fidelity.content import compare_words, words
from app.fidelity.docx_source import read_docx_source

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"

# What a layout repair must never lose. Counted in the whole main document part.
PRESERVED = {
    "bookmarks": f"{{{_W}}}bookmarkStart",
    "fields": f"{{{_W}}}fldSimple",
    "complex fields": f"{{{_W}}}fldChar",
    "drawings": f"{{{_W}}}drawing",
    "legacy pictures": f"{{{_W}}}pict",
    "embedded objects": f"{{{_W}}}object",
    "content controls": f"{{{_W}}}sdt",
    "section breaks": f"{{{_W}}}sectPr",
    "footnote references": f"{{{_W}}}footnoteReference",
    "endnote references": f"{{{_W}}}endnoteReference",
    "comments": f"{{{_W}}}commentRangeStart",
    "tracked insertions": f"{{{_W}}}ins",
    "tracked deletions": f"{{{_W}}}del",
    "equations": f"{{{_M}}}oMath",
    "links": f"{{{_W}}}hyperlink",
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class SafeEditResult:
    checks: list[Check] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def failed(self) -> list[Check]:
        return [check for check in self.checks if not check.passed]


def _body_children(data: bytes) -> list[etree._Element]:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    body = root.find(f"{{{_W}}}body")
    return list(body) if body is not None else []


def _canonical(element: etree._Element) -> bytes:
    return etree.tostring(element, method="c14n")


def _features(data: bytes) -> Counter:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    found: Counter = Counter()
    for name, tag in PRESERVED.items():
        found[name] = sum(1 for _ in root.iter(tag))
    return found


def _is_ordered_subsequence(needed: list[bytes], found: list[bytes]) -> tuple[int, int]:
    """How many of `needed` appear in `found`, in order: (matched, needed). One that isn't found counts as missing
    and the search goes on from where it was, so a single changed block counts once."""
    position, matched = 0, 0
    for item in needed:
        at = next((index for index in range(position, len(found)) if found[index] == item), None)
        if at is None:
            continue
        matched += 1
        position = at + 1
    return matched, len(needed)


def verify(original: bytes, result: bytes, touched_blocks: set[int]) -> SafeEditResult:
    """The four checks of a repaired file. `touched_blocks`: the indexes of the original's body children that the
    repairs were allowed to change or remove (everything else must come through unchanged)."""
    outcome = SafeEditResult()

    try:
        before, after = read_docx_source(original), read_docx_source(result)
    except Exception:  # noqa: BLE001 -- an unreadable result is a failed check, not a crash
        outcome.checks.append(Check("words", False, "The repaired file can't be read back."))
        return outcome
    body = compare_words(words(before.body), words(after.body), method="docx-text")
    outcome.checks.append(
        Check("words", body.verified, f"All {body.sourceWords} words of the body are unchanged and in order." if body.verified else f"Words differ: {body.missing} missing, {body.added} added, {body.moved} moved.")
    )
    headers = compare_words(words(before.header_footer), words(after.header_footer), method="docx-text")
    outcome.checks.append(
        Check("headers", headers.verified, "Headers and footers have the same words." if headers.verified else f"Header/footer words differ: {headers.missing} missing, {headers.added} added.")
    )

    original_children = _body_children(original)
    untouched = [_canonical(child) for index, child in enumerate(original_children) if index not in touched_blocks and etree.QName(child).localname != "sectPr"]
    matched, needed = _is_ordered_subsequence(untouched, [_canonical(child) for child in _body_children(result)])
    outcome.checks.append(
        Check("untouched", matched == needed, f"{needed} untouched blocks are identical to the original." if matched == needed else f"{needed - matched} of {needed} blocks nobody repaired came out different.")
    )

    lost = {name: count - _features(result)[name] for name, count in _features(original).items()}
    lost = {name: count for name, count in lost.items() if count > 0}
    outcome.checks.append(
        Check("preserved", not lost, "Bookmarks, fields, pictures, notes, comments, sections and links are all kept." if not lost else "Lost: " + ", ".join(f"{count} {name}" for name, count in lost.items()) + ".")
    )

    problems = package_problems(result)
    outcome.checks.append(Check("package", not problems, "The file is a valid Word package." if not problems else f"{len(problems)} package problems (Word may refuse or repair the file)."))
    return outcome
