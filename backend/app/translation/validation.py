"""Checking a translation before anything is done with it (tracker TRAN-003, brief §48): a
translation may change every word, never a fact. Across languages the comparison can't be
word for word, so it is of what must survive any translation:

  tags        every <mN>, </mN>, <xN/> and <br/> of the source, each as often, none added,
              and parsed back into runs (segments.untag);
  numbers     the same digit groups, however they are grouped or separated -- 3.14 may be
              3,14, 1,000 may be 1 000, 17/05/2024 may be 17.05.2024 -- but never another
              number, one more or one fewer (dates and identifiers with digits included);
  percentages as many percent signs (50% may be 50 %);
  units       each unit after a number, by what it measures -- mg may be мг, never g;
  identifiers codes of letters and digits (ISO-9001, AB-123, v2.1) exactly as they are;
  glossary    a locked term in the source has its locked translation in the target;
  length      not so much shorter or longer that words must have been dropped or invented.

A translation with a problem is never used without the user's explicit action: its segment
is "invalid", and why is said in words, never with its text in a log."""

import re
from collections import Counter
from dataclasses import dataclass

from app.translation.segments import Segment, TagError, plain_text, untag

_TAGS = re.compile(r"</?m\d+>|<x\d+/>|<br/>")
_DIGITS = re.compile(r"\d+")
_IDENTIFIER = re.compile(r"\b(?=[A-Za-z0-9-]*[A-Za-z])(?=[A-Za-z0-9-]*\d)[A-Za-z0-9]+(?:[-.][A-Za-z0-9]+)*\b")
# Units after a number, by what they measure: the same unit in the scripts translations use.
_UNITS = {
    "mg": "mg", "мг": "mg", "mcg": "mcg", "µg": "mcg", "μg": "mcg", "мкг": "mcg", "g": "g", "г": "g", "gr": "g", "kg": "kg", "кг": "kg",
    "ml": "ml", "мл": "ml", "l": "l", "л": "l", "mm": "mm", "мм": "mm", "cm": "cm", "см": "cm", "m": "m", "м": "m", "km": "km",
    "км": "km", "h": "h", "ч": "h", "min": "min", "мин": "min", "s": "s", "сек": "s", "iu": "iu", "ме": "iu", "mmol": "mmol",
    "ммол": "mmol", "°c": "°c", "°f": "°f", "kcal": "kcal", "ккал": "kcal", "mg/kg": "mg/kg", "мг/кг": "mg/kg", "%": "%",
}
_UNIT = re.compile(r"\d\s?(°[CFcf]|[A-Za-zА-Яа-яµμ]+(?:/[A-Za-zА-Яа-я]+)?)")
# A translation may be this much shorter or longer than its source (characters) before it is suspect.
SHORTEST, LONGEST, MEASURED_FROM = 0.33, 3.0, 24

TAGS, NUMBER, PERCENT, UNIT, IDENTIFIER, GLOSSARY, LENGTH, EMPTY = (
    "tags", "number", "percent", "unit", "identifier", "glossary", "length", "empty",
)
_SAID = {
    TAGS: "its formatting marks don't match the original's",
    NUMBER: "a number differs from the original",
    PERCENT: "a percentage differs from the original",
    UNIT: "a unit of measure differs from the original",
    IDENTIFIER: "a code or identifier differs from the original",
    GLOSSARY: "a locked glossary term wasn't translated as the glossary says",
    LENGTH: "it is far shorter or longer than the original: words may be missing or added",
    EMPTY: "it is empty",
}


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    source: str
    target: str
    locked: bool = True
    case_sensitive: bool = False


def describe(problems: list[str]) -> str:
    return "; ".join(_SAID[problem] for problem in problems)


def _units(text: str) -> Counter[str]:
    found: Counter[str] = Counter()
    for match in _UNIT.finditer(text):
        unit = _UNITS.get(match.group(1).lower())
        if unit is not None:
            found[unit] += 1
    return found


def _contains(text: str, term: str, case_sensitive: bool) -> bool:
    if not case_sensitive:
        text, term = text.lower(), term.lower()
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def problems_of(segment: Segment, target: str, glossary: list[GlossaryEntry] | None = None) -> list[str]:
    """What is wrong with `target` as a translation of `segment` (an empty list: nothing)."""
    found: list[str] = []
    if not target.strip():
        return [EMPTY]
    if Counter(_TAGS.findall(segment.source)) != Counter(_TAGS.findall(target)):
        found.append(TAGS)
    else:
        try:
            untag(target, segment.marks, segment.placeholders)
        except TagError:
            found.append(TAGS)
    source_text = plain_text(segment.source, segment)
    try:
        target_text = plain_text(target, segment)
    except (KeyError, ValueError):
        target_text = target
    # Placeholders are restored as they were, so their digits are compared through the tags.
    kept = "".join(placeholder.text for placeholder in segment.placeholders.values())
    without = lambda text: text.replace(kept, "") if kept else text  # noqa: E731
    if Counter(_DIGITS.findall(without(source_text))) != Counter(_DIGITS.findall(without(target_text))):
        found.append(NUMBER)
    if source_text.count("%") != target_text.count("%"):
        found.append(PERCENT)
    if _units(source_text) - _units(target_text):
        found.append(UNIT)
    if Counter(_IDENTIFIER.findall(source_text)) - Counter(_IDENTIFIER.findall(target_text)):
        found.append(IDENTIFIER)
    for entry in glossary or []:
        if entry.locked and _contains(source_text, entry.source, entry.case_sensitive) and not _contains(
            target_text, entry.target, entry.case_sensitive
        ):
            found.append(GLOSSARY)
            break
    if len(source_text) >= MEASURED_FROM and not SHORTEST <= len(target_text) / len(source_text) <= LONGEST:
        found.append(LENGTH)
    return found
