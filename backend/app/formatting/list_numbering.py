"""List numbering as Word counts it (tracker DOCX-016): its number formats, a level's
label made from its pattern ("%1.%2.", "Чл. %1."), and which counters an item starts
again. The importer, the exports and the editor (editor/listLabels.ts mirrors it) all
number a list this way."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.document import HeadingNumbering, ListNumbering

_ROMAN = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))
# Word's Cyrillic letters (russianLower): а..и, к..щ, э..я -- without ё, й, ъ, ы, ь (ECMA-376 17.18.59).
_CYRILLIC = "абвгдежзиклмнопрстуфхцчшщэюя"
_REFERENCE = re.compile(r"%([1-9])")
# How far each level of a list the exporters write is indented, and its label hangs: 0.63 cm.
LEVEL_INDENT_TWIPS = 357
WORD_LEVELS = 9
# The exporters' own levels, where a list has none: 1., a., i. in turn, or •, ◦, ▪.
DEFAULT_FORMATS = ("decimal", "lowerLetter", "lowerRoman")
DEFAULT_BULLETS = ("•", "◦", "▪")


def format_number(value: int, fmt: str) -> str:
    """A number as Word shows it in a list label or a page number: letters a..z, then
    aa, bb, cc..; Roman numerals up to 3999; 01..09 then 10; Cyrillic а..я, then аа..;
    their capital forms. Any other number is shown as it is."""
    if fmt in ("lowerLetter", "upperLetter") and value > 0:
        letters = chr(ord("a") + (value - 1) % 26) * ((value - 1) // 26 + 1)
        return letters.upper() if fmt == "upperLetter" else letters
    if fmt in ("russianLower", "russianUpper") and value > 0:
        letters = _CYRILLIC[(value - 1) % len(_CYRILLIC)] * ((value - 1) // len(_CYRILLIC) + 1)
        return letters.upper() if fmt == "russianUpper" else letters
    if fmt in ("lowerRoman", "upperRoman") and 0 < value < 4000:
        result = ""
        for amount, numeral in _ROMAN:
            while value >= amount:
                result += numeral
                value -= amount
        return result.upper() if fmt == "upperRoman" else result
    if fmt == "decimalZero" and 0 <= value < 10:
        return f"0{value}"
    return str(value)


def level_label(text: str, values: Sequence[int], formats: Sequence[str], *, legal: bool = False) -> str:
    """A level's label: its pattern with %n as level n's number in its format -- in 1, 2, 3
    with legal numbering. A level the list hasn't reached shows its start less one, as
    Word's "1.0.1" does; one it has no number for, nothing."""

    def number(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1
        if index >= len(values):
            return ""
        return format_number(values[index], "decimal" if legal else formats[index])

    return _REFERENCE.sub(number, text)


class Counters:
    """A list's counters while its items are numbered: each level's value, which an item
    advances at its level and starts again at the levels below it -- after any level
    above (Word's default), never (restart 0), or only after level n (restart n, 1-based)."""

    def __init__(self, starts: Sequence[int], restarts: Sequence[int | None]) -> None:
        self.starts, self.restarts = list(starts), list(restarts)
        self.values = [start - 1 for start in self.starts]

    def advance(self, level: int) -> list[int]:
        """Numbers an item at `level`; the values of the levels up to it, as its label shows them."""
        self.values[level] += 1
        for deeper in range(level + 1, len(self.values)):
            restart = self.restarts[deeper]
            if restart is not None and restart > 0 and restart - 1 >= deeper:
                restart = None  # a level at or below this one can't restart it: Word ignores that
            if restart is None or (restart > 0 and level <= restart - 1):
                self.values[deeper] = self.starts[deeper] - 1
        return self.values[: level + 1]


@dataclass(frozen=True)
class Level:
    """One of a list's nine Word levels as the exports write it: format, label, start,
    indent and hanging (twips), legal numbering, restart, what follows the label."""

    fmt: str
    text: str
    start: int
    left: int
    hanging: int
    legal: bool = False
    restart: int | None = None
    suffix: str = "tab"


def list_levels(kind: str, numbering: ListNumbering | None, base_level: int = 0) -> list[Level]:
    """A list's nine Word levels: its own (ListNumbering.levels, DOCX-016) from
    `base_level` -- the Word level its top one sits at -- and the usual ones elsewhere:
    1., a., i. in turn (the top one in the list's format) or •, ◦, ▪; an indent step
    each. `kind` is "number", "bullet" or "none" (a checklist). A label's %n are counted
    from the list's top, so they move down with it."""
    own = (numbering.levels or []) if numbering is not None else []
    levels: list[Level] = []
    for ilvl in range(WORD_LEVELS):
        left = LEVEL_INDENT_TWIPS * (ilvl + 1)
        if kind == "none":  # a checklist: just the indent; the checkbox leads the text
            levels.append(Level("none", "", 1, left, 0, suffix="nothing"))
            continue
        index = ilvl - base_level
        mine = own[index] if 0 <= index < len(own) else None
        if mine is None:
            fmt, text = ("bullet", DEFAULT_BULLETS[ilvl % 3]) if kind == "bullet" else (DEFAULT_FORMATS[ilvl % 3], f"%{ilvl + 1}.")
            if kind == "number" and index == 0 and numbering is not None:
                fmt = numbering.format
            levels.append(Level(fmt, text, 1, left, LEVEL_INDENT_TWIPS))
            continue
        fmt = mine.format
        if kind == "number" and index == 0 and fmt not in ("bullet", "none"):
            fmt = numbering.format  # the top level counts as the list says (the editor may have changed it)
        if fmt == "bullet":
            text = mine.text or DEFAULT_BULLETS[ilvl % 3]
        else:
            text = mine.text if mine.text is not None else f"%{index + 1}."
            text = _REFERENCE.sub(lambda match: f"%{min(int(match.group(1)) + base_level, WORD_LEVELS)}", text)
        restart = mine.restartAfter + base_level if mine.restartAfter else mine.restartAfter
        levels.append(
            Level(
                fmt,
                text,
                mine.start,
                round(mine.indentCm * 566.929) if mine.indentCm is not None else left,
                round(mine.hangingCm * 566.929) if mine.hangingCm is not None else LEVEL_INDENT_TWIPS,
                mine.legal,
                restart,
                mine.suffix,
            )
        )
    return levels


def list_counters(levels: Sequence[Level], numbering: ListNumbering | None, kind: str, base_level: int = 0) -> Counters:
    """The counters a list is numbered with: each level from its start -- the top one from
    where the list starts (ListNumbering.start) -- restarting as its levels say."""
    starts = [level.start for level in levels]
    if kind == "number" and numbering is not None:
        starts[base_level] = numbering.start
    return Counters(starts, [level.restart for level in levels])


def heading_labels(headings: Sequence[tuple[str, int, bool]], numbering: HeadingNumbering | None) -> dict[str, str]:
    """Each numbered heading's number (DOCX-016A), by id: the headings -- (id, level
    1-9, numbered) in order -- counted as a list's items at their levels, as Word counts
    them. One not numbered counts for nothing; a level the numbering doesn't define, or
    one whose label is empty, shows no number."""
    from app.models.document import ListNumbering

    if numbering is None or not numbering.levels:
        return {}
    own = ListNumbering(start=numbering.levels[0].start, format=numbering.levels[0].format, levels=numbering.levels)
    levels = list_levels("number", own)
    counters = list_counters(levels, own, "number")
    labels: dict[str, str] = {}
    for element_id, level, numbered in headings:
        index = min(max(level, 1), WORD_LEVELS) - 1
        if not numbered or index >= len(numbering.levels) or numbering.levels[index].format in ("bullet", "none"):
            continue
        label = item_label(levels, counters, index).strip()
        if label:
            labels[element_id] = label
    return labels


def item_label(levels: Sequence[Level], counters: Counters, level: int) -> str:
    """Numbers an item at Word level `level` and gives its label: its level's pattern
    with the numbers filled in, a bullet, or nothing."""
    values = counters.advance(level)
    spec = levels[level]
    if spec.fmt == "bullet":
        return spec.text
    return level_label(spec.text, values, [each.fmt for each in levels], legal=spec.legal)
