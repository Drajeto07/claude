"""Right-to-left text in reading order for the PDF export (tracker FONT-003): the Unicode
bidirectional algorithm (UAX #9) without explicit embeddings -- the parts documents need:
each character's bidirectional type, numbers and neutrals resolved by what is around them,
levels, runs reversed level by level, brackets mirrored in right-to-left runs.

reportlab lays out right-to-left and mixed lines through a module named `rlbidi` and its
`log2vis(text, base_direction, clean, positions_V_to_L)`, which isn't on PyPI; this module is
registered under that name before reportlab's text layer is imported (app/__init__.py). It
gives the visual order of a logical string and, for each visual position, the logical one
reportlab maps fragments and fonts back through.

Explicit embeddings and overrides (LRE, RLE, LRO, RLO, PDF, and the isolates) are read as
neutral: documents rarely hold them, and their text keeps its order around them."""

import unicodedata

LTR, RTL, ON = "LTR", "RTL", "ON"

_STRONG_R = frozenset({"R", "AL"})
_NEUTRAL = frozenset({"B", "S", "WS", "ON", "BN", "LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"})
_MIRRORED = {
    "(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<", "«": "»", "»": "«",
    "‹": "›", "›": "‹", "⁅": "⁆", "⁆": "⁅", "⟨": "⟩", "⟩": "⟨", "≤": "≥", "≥": "≤",
}


def _types(text: str) -> list[str]:
    return [unicodedata.bidirectional(character) or "ON" for character in text]


_OPENING = {"(": ")", "[": "]", "{": "}", "«": "»", "‹": "›", "⟨": "⟩"}


def _pairs(text: str, types: list[str]) -> list[tuple[int, int]]:
    """The bracket pairs (opening, closing) of neutral brackets, in the order they open."""
    stack: list[tuple[str, int]] = []
    pairs: list[tuple[int, int]] = []
    for i, character in enumerate(text):
        if types[i] != "ON":
            continue
        if character in _OPENING:
            stack.append((_OPENING[character], i))
        elif stack and character in _OPENING.values():
            for depth in range(len(stack) - 1, -1, -1):
                if stack[depth][0] == character:
                    pairs.append((stack[depth][1], i))
                    del stack[depth:]
                    break
    return sorted(pairs)


def base_level(text: str, direction: str | None) -> int:
    """0 (left to right) or 1: as asked, else as the first strong character says."""
    if direction:
        if direction.upper() == RTL:
            return 1
        if direction.upper() == LTR:
            return 0
    for kind in _types(text):
        if kind in _STRONG_R:
            return 1
        if kind == "L":
            return 0
    return 0


def levels(text: str, direction: str | None = None) -> list[int]:
    """Each character's embedding level (even: left to right, odd: right to left)."""
    base = base_level(text, direction)
    types = _types(text)
    edge = "R" if base else "L"
    # W1: a non-spacing mark takes the type of what it follows.
    for i, kind in enumerate(types):
        if kind == "NSM":
            types[i] = types[i - 1] if i else edge
    # W2, W3: European digits after Arabic letters are Arabic numbers; AL is R.
    last_strong = edge
    for i, kind in enumerate(types):
        if kind in ("L", "R", "AL"):
            last_strong = kind
        elif kind == "EN" and last_strong == "AL":
            types[i] = "AN"
    types = ["R" if kind == "AL" else kind for kind in types]
    # W4: one separator between two numbers of one kind is that kind.
    for i in range(1, len(types) - 1):
        if types[i] == "ES" and types[i - 1] == types[i + 1] == "EN":
            types[i] = "EN"
        elif types[i] == "CS" and types[i - 1] == types[i + 1] and types[i - 1] in ("EN", "AN"):
            types[i] = types[i - 1]
    # W5: terminators (%, currency) next to European numbers are European numbers.
    for i, kind in enumerate(types):
        if kind == "ET":
            j = i
            while j < len(types) and types[j] == "ET":
                j += 1
            if (i > 0 and types[i - 1] == "EN") or (j < len(types) and types[j] == "EN"):
                for k in range(i, j):
                    types[k] = "EN"
    # W6: remaining separators and terminators are neutral.
    types = ["ON" if kind in ("ES", "ET", "CS") else kind for kind in types]
    # W7: European numbers after a left-to-right letter are left to right.
    last_strong = edge
    for i, kind in enumerate(types):
        if kind in ("L", "R"):
            last_strong = kind
        elif kind == "EN" and last_strong == "L":
            types[i] = "L"
    # N0: a pair of brackets takes the paragraph's direction when its content does, or when
    # its content goes the other way but so does the text before it -- else the other way.
    strong = lambda kind: "R" if kind in ("R", "EN", "AN") else "L" if kind == "L" else None  # noqa: E731
    for opening, closing in _pairs(text, types):
        inside = {strong(kind) for kind in types[opening + 1 : closing]} - {None}
        if edge in inside:
            resolved = edge
        elif inside:
            before = next((strong(kind) for kind in reversed(types[:opening]) if strong(kind)), edge)
            resolved = before if before != edge else edge
        else:
            continue
        types[opening] = types[closing] = resolved
    # N1, N2: neutrals between characters of one direction take it, else the paragraph's.
    i = 0
    while i < len(types):
        if types[i] not in _NEUTRAL:
            i += 1
            continue
        j = i
        while j < len(types) and types[j] in _NEUTRAL:
            j += 1
        before = edge if i == 0 else ("R" if types[i - 1] in ("R", "EN", "AN") else "L")
        after = edge if j == len(types) else ("R" if types[j] in ("R", "EN", "AN") else "L")
        resolved = before if before == after else edge
        for k in range(i, j):
            types[k] = resolved
        i = j
    # I1, I2: the levels.
    result = []
    for kind in types:
        if base % 2 == 0:
            result.append(base + (1 if kind == "R" else 2 if kind in ("AN", "EN") else 0))
        else:
            result.append(base + (1 if kind in ("L", "EN", "AN") else 0))
    # L1: whitespace at the end of the line is at the paragraph's level.
    k = len(text) - 1
    while k >= 0 and unicodedata.bidirectional(text[k]) in ("WS", "S", "B", "BN"):
        result[k] = base
        k -= 1
    return result


def visual_order(text: str, direction: str | None = None) -> list[int]:
    """For each visual position, the logical one (L2: runs reversed from the highest level down)."""
    if not text:
        return []
    found = levels(text, direction)
    order = list(range(len(text)))
    highest = max(found)
    lowest_odd = min((level for level in found if level % 2), default=highest + 1)
    for level in range(highest, lowest_odd - 1, -1):
        i = 0
        while i < len(order):
            if found[order[i]] >= level:
                j = i
                while j < len(order) and found[order[j]] >= level:
                    j += 1
                order[i:j] = reversed(order[i:j])
                i = j
            else:
                i += 1
    return order


def log2vis(text: str, base_direction: str | None = None, clean: bool = False, positions_V_to_L: list | None = None, **_: object) -> str:
    """`text` in visual order, brackets mirrored where they read right to left; fills
    `positions_V_to_L` (visual index -> logical index) when given."""
    order = visual_order(text, base_direction)
    found = levels(text, base_direction) if text else []
    visual = "".join(_MIRRORED.get(text[i], text[i]) if found[i] % 2 else text[i] for i in order)
    if positions_V_to_L is not None:
        positions_V_to_L[:] = order
    return visual
