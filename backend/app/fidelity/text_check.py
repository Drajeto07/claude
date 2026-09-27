"""The AI fidelity check (brief §18, tracker AI-001 and AI-002): text an AI answer
must keep exactly -- structure analysis only adds structure -- compared with its
source token by token, in order. Tokens are words, numbers with their sign,
decimals, separators and percent sign, and every punctuation mark. Only the
same tokens in the same order pass: a missing "not", 5 mg that became 50 mg, a
dropped, added, repeated or reordered sentence, a changed comma all fail.

What isn't content: spacing and line breaks, typographic variants (curly or
straight quotes, the kind of dash, … or ...), table cell separators, and the list
and heading marks at the start of a line (•, -, 1., a), #) that become structure.

Each difference is classified -- a number, a unit, a negation, a whole sentence,
a duplicate, a reordering, punctuation, other words -- so a caller can say what
changed, and log it, without the text. Numbers (dates, percentages, identifiers
with digits) and units are protected facts: an answer that touches one never
passes without the user's explicit action."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

_TYPOGRAPHY = str.maketrans(
    {
        **dict.fromkeys("‘’‚‛′‹›", "'"),
        **dict.fromkeys("“”„‟″«»", '"'),
        **dict.fromkeys("‐‑‒–—―−", "-"),
        **dict.fromkeys("    \t|", " "),  # spaces, and table cell separators
        "…": "...",
    }
)
# List and heading marks at the start of a line: they become structure (a list
# item, a heading), not text. "1.", "(a)", "iv)", "а)" -- and Cyrillic lettering.
_LINE_MARKS = re.compile(
    r"^[ ]*(?:(?:#{1,6}|[-*+•◦▪▫‣⁃●○■□·]|\[[ xX]\]"
    r"|\(?(?:\d{1,3}|[^\W\d_]|[ivxlcdmIVXLCDM]{1,6})[.)])[ ]+)+",
    re.MULTILINE,
)
_TOKEN = re.compile(
    r"(?P<number>[-+]?\d+(?:[.,:/-]\d+)*%?)"  # 5, -5, 3.14, 3,14, 1,000, 12:30, 17.05.2024, 2024-05-17, 50%
    r"|(?P<word>\w+(?:['-]\w+)*)"  # words, with an inner apostrophe or hyphen: don't, well-known, COVID-19
    r"|(?P<mark>[^\w\s])"  # any other mark, one at a time
)
_TERMINATORS = frozenset(".!?")
_NEGATIONS = frozenset(
    {
        # English
        "not", "no", "never", "none", "nothing", "nobody", "nowhere", "neither", "nor", "without", "cannot",
        # Bulgarian
        "не", "няма", "никога", "нито", "никой", "никоя", "никое", "никои", "нищо", "никъде", "без",
    }
)

# The categories of a difference, most telling first.
NUMBER, UNIT, NEGATION, SENTENCE, DUPLICATE, REORDERED, PUNCTUATION, WORDS = (
    "number", "unit", "negation", "sentence", "duplicate", "reordered", "punctuation", "words",
)
_ORDER = (NUMBER, UNIT, NEGATION, SENTENCE, DUPLICATE, REORDERED, PUNCTUATION, WORDS)
# Facts an AI answer may never change on its own (AI-002).
PROTECTED = frozenset({NUMBER, UNIT})
_CONTEXT_TOKENS = 4


@dataclass(frozen=True)
class Token:
    text: str
    kind: str  # "number" | "word" | "mark"


def normalize(text: str) -> str:
    """The text as the check reads it: typographic variants unified, the list and
    heading marks at line starts left out."""
    text = unicodedata.normalize("NFC", text).translate(_TYPOGRAPHY)
    return _LINE_MARKS.sub("", text)


def tokens(text: str) -> list[Token]:
    return [Token(match.group(), match.lastgroup or "mark") for match in _TOKEN.finditer(normalize(text))]


def _is_negation(token: Token) -> bool:
    lowered = token.text.lower()
    return lowered in _NEGATIONS or lowered.endswith("n't")


@dataclass(frozen=True)
class TextDifference:
    kind: str  # "missing" | "added" | "changed" | "moved"
    category: str  # the most telling of `categories`
    categories: frozenset[str]
    source: str
    result: str
    context: str  # the source tokens just before it

    @property
    def protected(self) -> bool:
        """A number or a unit went missing, was added or was changed (a reordered one is still there)."""
        return self.kind != "moved" and bool(self.categories & PROTECTED)


@dataclass(frozen=True)
class TextCheck:
    verified: bool
    source_tokens: int
    result_tokens: int
    differences: tuple[TextDifference, ...] = ()

    @property
    def protected(self) -> bool:
        """A protected fact (a number, a unit) changed."""
        return any(difference.protected for difference in self.differences)

    def counts(self) -> Counter[str]:
        return Counter(difference.category for difference in self.differences)

    def summary(self) -> str:
        """What changed, without a word of the text: safe to log."""
        if self.verified:
            return "the same text"
        counts = self.counts()
        parts = ", ".join(f"{category} x{counts[category]}" for category in _ORDER if counts[category])
        return f"{len(self.differences)} difference(s): {parts}"


def _join(run: list[Token]) -> str:
    return " ".join(token.text for token in run)


def _categories(before: list[Token], after: list[Token], preceding: Token | None, moved: bool, duplicate: bool) -> frozenset[str]:
    both = [*before, *after]
    found: set[str] = set()
    if any(any(ch.isdigit() for ch in token.text) for token in both):
        found.add(NUMBER)
    elif preceding is not None and preceding.kind == "number" and any(token.kind == "word" for token in both):
        found.add(UNIT)  # "5 mg" -> "5 g"
    if any(_is_negation(token) for token in both):
        found.add(NEGATION)
    for run in (before, after):
        if sum(token.kind == "word" for token in run) >= 3 and any(token.text in _TERMINATORS for token in run):
            found.add(SENTENCE)
    if duplicate:
        found.add(DUPLICATE)
    if moved:
        found.add(REORDERED)
    if both and all(token.kind == "mark" for token in both):
        found.add(PUNCTUATION)
    return frozenset(found or {WORDS})


def _core(run: list[Token]) -> list[str]:
    """A run's words and numbers, without its punctuation."""
    return [token.text for token in run if token.kind != "mark"]


def _occurs_in(run: list[Token], source: list[Token]) -> bool:
    """The run appears, as it is, somewhere in the source."""
    width = len(run)
    texts = [token.text for token in run]
    return any([token.text for token in source[start : start + width]] == texts for start in range(len(source) - width + 1))


def numbers(text: str) -> Counter[str]:
    """The text's numbers -- amounts, percentages, dates, times, identifiers with
    digits (COVID-19, ISO 9001) -- each as often as it appears."""
    return Counter(token.text for token in tokens(text) if any(ch.isdigit() for ch in token.text))


def changed_numbers(source: str, result: str) -> tuple[list[str], list[str]]:
    """(missing, added): the source's numbers the result doesn't have, and the
    result's the source didn't. For a result whose words may rightly differ --
    a translation, a rewording the user asked for -- its facts still may not."""
    before, after = numbers(source), numbers(result)
    return sorted((before - after).elements()), sorted((after - before).elements())


def check_text(source: str, result: str) -> TextCheck:
    """The result must hold the source's tokens, all of them, in the same order,
    and nothing else."""
    left, right = tokens(source), tokens(result)
    if [token.text for token in left] == [token.text for token in right]:
        return TextCheck(verified=True, source_tokens=len(left), result_tokens=len(right))

    removed: list[tuple[int, list[Token]]] = []
    inserted: list[tuple[int, list[Token]]] = []
    changed: list[tuple[int, list[Token], list[Token]]] = []
    matcher = SequenceMatcher(None, [token.text for token in left], [token.text for token in right], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "delete":
            removed.append((i1, left[i1:i2]))
        elif tag == "insert":
            inserted.append((i1, right[j1:j2]))
        elif tag == "replace":
            changed.append((i1, left[i1:i2], right[j1:j2]))

    # A run gone from one place and found, the same, at another was reordered. Its
    # words are compared: the diff may align a full stop at its edge with a neighbour's.
    moved: list[tuple[int, list[Token]]] = []
    for entry in list(removed):
        core = _core(entry[1])
        match = next((other for other in inserted if core and _core(other[1]) == core), None)
        if match is not None:
            removed.remove(entry)
            inserted.remove(match)
            moved.append(entry)

    def preceding(at: int) -> Token | None:
        return left[at - 1] if at > 0 else None

    def context(at: int) -> str:
        return _join(left[max(0, at - _CONTEXT_TOKENS) : at])

    def difference(kind: str, at: int, before: list[Token], after: list[Token]) -> tuple[int, TextDifference]:
        duplicate = kind == "added" and len(after) >= 2 and _occurs_in(after, left)
        categories = _categories(before, after, preceding(at), kind == "moved", duplicate)
        # What happened to a run says more than what is in it: a reordered or repeated sentence is that.
        category = REORDERED if kind == "moved" else DUPLICATE if duplicate else next(name for name in _ORDER if name in categories)
        return at, TextDifference(kind, category, categories, _join(before), _join(after), context(at))

    located = [
        *(difference("missing", at, run, []) for at, run in removed),
        *(difference("added", at, [], run) for at, run in inserted),
        *(difference("changed", at, before, after) for at, before, after in changed),
        *(difference("moved", at, run, []) for at, run in moved),
    ]
    return TextCheck(
        verified=False,
        source_tokens=len(left),
        result_tokens=len(right),
        differences=tuple(entry for _, entry in sorted(located, key=lambda pair: pair[0])),
    )
