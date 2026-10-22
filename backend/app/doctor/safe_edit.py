"""SafeEdit (docs/SMARTDOC_DOCUMENT_DOCTOR_SAFEEDIT_ANALYSIS.md section 1): what a repaired Word file is checked
for against the original, every time, by reading both files -- never by trusting the code that wrote them.

1. Words: the body's words, and the headers' and footers', are the same, in the same order (the independent
   reader of fidelity/docx_source.py and the word comparison of fidelity/content.py).
2. Untouched blocks: every block of the original's body that no repair touched is in the result, byte for byte
   (canonical XML), in the same order.
3. Preserved features: what the app keeps without editing it -- bookmarks, fields, drawings, content controls,
   section breaks, notes, comments, tracked changes, equations, links, symbol characters -- is all still there:
   none fewer. And every character whose look depends on its font (B-032: a symbol font's -- Wingdings, Symbol,
   Webdings... -- or text in the Private Use Area) is still there in that same font, in the same order: the words
   check compares Unicode text, which stays the same when a Wingdings tick is set in Arial and shows another sign.
4. A valid package: every part parses, every relationship resolves, every style and list referenced exists
   (export/package_check.py).

All four must hold for the result to be called verified. Each failure says what and how many, never the text of
the document (the person's own content stays in their document, not in a report or a log).
"""

import io
import re
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
    "symbol characters": f"{{{_W}}}sym",
}

# The fonts whose characters are pictures of their own -- SafeEdit's own list, not the repair code's
# (formatting/health_fixes.py SYMBOL_FONTS), so a gap in one isn't a gap in the other.
SYMBOL_FONTS = frozenset(
    {
        "symbol", "wingdings", "wingdings 2", "wingdings 3", "webdings", "marlett", "zapf dingbats", "zapfdingbats",
        "itc zapf dingbats", "mt extra", "bookshelf symbol 7", "ms reference specialty", "ms outlook",
    }
)
_PRIVATE_USE = re.compile(r"[\ue000-\uf8ff\U000f0000-\U0010ffff]")
_TEXT_PARTS = re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml")


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


def _run_font(properties: etree._Element | None) -> str | None:
    """The font run or style properties set for Latin text (ascii, else hAnsi), lower-case; None if they set none."""
    fonts = properties.find(f"{{{_W}}}rFonts") if properties is not None else None
    if fonts is None:
        return None
    font = fonts.get(f"{{{_W}}}ascii") or fonts.get(f"{{{_W}}}hAnsi")
    return font.strip().lower() if font else None


class _Styles:
    """The font a style gives, through the styles it is based on; the document's default paragraph style and font."""

    def __init__(self, styles: bytes | None) -> None:
        self.font: dict[str, str | None] = {}
        self.based_on: dict[str, str] = {}
        self.default_paragraph: str | None = None
        self.default_font: str | None = None
        if styles is None:
            return
        root = etree.fromstring(styles)
        self.default_font = _run_font(root.find(f"{{{_W}}}docDefaults/{{{_W}}}rPrDefault/{{{_W}}}rPr"))
        for style in root.iter(f"{{{_W}}}style"):
            style_id = style.get(f"{{{_W}}}styleId") or ""
            self.font[style_id] = _run_font(style.find(f"{{{_W}}}rPr"))
            based_on = style.find(f"{{{_W}}}basedOn")
            if based_on is not None:
                self.based_on[style_id] = based_on.get(f"{{{_W}}}val") or ""
            if style.get(f"{{{_W}}}type") == "paragraph" and style.get(f"{{{_W}}}default") in ("1", "true"):
                self.default_paragraph = style_id

    def of(self, style_id: str | None) -> str | None:
        seen: set[str] = set()
        while style_id and style_id not in seen:
            seen.add(style_id)
            if self.font.get(style_id):
                return self.font[style_id]
            style_id = self.based_on.get(style_id)
        return None


def _font_dependent(data: bytes) -> list[tuple[str, str, str]]:
    """(part, font, characters) for each stretch of text whose look depends on its font -- in a symbol font (set on
    the run, by its character style or by its paragraph's), in the Private Use Area, or a w:sym -- paragraph by
    paragraph, in order; consecutive runs in one font together, so splitting or joining runs isn't a change.
    Theme fonts (w:asciiTheme) aren't resolved: they name a theme's text fonts, never a symbol font in practice."""
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        names = package.namelist()
        styles = _Styles(package.read("word/styles.xml") if "word/styles.xml" in names else None)
        parts = {name: package.read(name) for name in names if _TEXT_PARTS.fullmatch(name)}
    found: list[tuple[str, str, str]] = []
    for name in sorted(parts, key=lambda part: (part != "word/document.xml", part)):
        for paragraph in etree.fromstring(parts[name]).iter(f"{{{_W}}}p"):
            style = paragraph.find(f"{{{_W}}}pPr/{{{_W}}}pStyle")
            paragraph_font = styles.of(style.get(f"{{{_W}}}val") if style is not None else styles.default_paragraph) or styles.default_font
            stretches: list[tuple[str, str, str]] = []
            for run in paragraph.iter(f"{{{_W}}}r"):
                if next(run.iterancestors(f"{{{_W}}}p"), None) is not paragraph:
                    continue  # a run of a paragraph inside this one (a text box): counted with that paragraph
                properties = run.find(f"{{{_W}}}rPr")
                character_style = properties.find(f"{{{_W}}}rStyle") if properties is not None else None
                font = _run_font(properties) or (styles.of(character_style.get(f"{{{_W}}}val")) if character_style is not None else None) or paragraph_font or ""
                for child in run:
                    if child.tag == f"{{{_W}}}t" and child.text and (font in SYMBOL_FONTS or _PRIVATE_USE.search(child.text)):
                        piece = (font, child.text)
                    elif child.tag == f"{{{_W}}}sym":
                        piece = ((child.get(f"{{{_W}}}font") or "").strip().lower(), "sym:" + (child.get(f"{{{_W}}}char") or "").upper())
                    else:
                        continue
                    if stretches and stretches[-1][1] == piece[0]:
                        stretches[-1] = (name, piece[0], stretches[-1][2] + piece[1])
                    else:
                        stretches.append((name, *piece))
            found += stretches
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
    try:
        symbols_before, symbols_after = _font_dependent(original), _font_dependent(result)
    except Exception:  # noqa: BLE001 -- what can't be read can't be called kept
        lost["symbol-font texts that couldn't be checked"] = 1
    else:
        if symbols_before != symbols_after:
            lost["symbol-font texts changed or set in another font"] = sum(1 for a, b in zip(symbols_before, symbols_after) if a != b) + abs(len(symbols_before) - len(symbols_after))
    outcome.checks.append(
        Check("preserved", not lost, "Bookmarks, fields, pictures, notes, comments, sections and links are all kept." if not lost else "Lost: " + ", ".join(f"{count} {name}" for name, count in lost.items()) + ".")
    )

    problems = package_problems(result)
    outcome.checks.append(Check("package", not problems, "The file is a valid Word package." if not problems else f"{len(problems)} package problems (Word may refuse or repair the file)."))
    return outcome
