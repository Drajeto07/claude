"""List numbering as Word counts it (tracker DOCX-016): its number formats, a level's
label made from its pattern ("%1.%2.", "Чл. %1."), and which counters an item starts
again. The importer, the exports and the editor (editor/listLabels.ts mirrors it) all
number a list this way."""

from __future__ import annotations

import re
from collections.abc import Sequence

_ROMAN = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))
# Word's Cyrillic letters (russianLower): а..и, к..щ, э..я -- without ё, й, ъ, ы, ь (ECMA-376 17.18.59).
_CYRILLIC = "абвгдежзиклмнопрстуфхцчшщэюя"
_REFERENCE = re.compile(r"%([1-9])")
# How far each level of a list the exporters write is indented, and its label hangs: 0.63 cm.
LEVEL_INDENT_TWIPS = 357


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
