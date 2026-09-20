import re

_ATX_HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s+\S|\s*$)", re.MULTILINE)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})", re.MULTILINE)
_TABLE_DELIMITER_ROW = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", re.MULTILINE)

_BOLD_OR_ITALIC = re.compile(r"(\*\*[^*\n]+\*\*|\*[^*\n]+\*)")
_BLOCKQUOTE_LINE = re.compile(r"^ {0,3}>", re.MULTILINE)
_INLINE_LINK = re.compile(r"\[[^\]\n]+\]\([^)\n]+\)")

_STRONG_SIGNALS = (_ATX_HEADING, _FENCE, _TABLE_DELIMITER_ROW)
_MODERATE_SIGNALS = (_BOLD_OR_ITALIC, _BLOCKQUOTE_LINE, _INLINE_LINK)


def looks_like_markdown(text: str) -> bool:
    """Tiered sniff for whether `text` is Markdown-formatted, not plain prose.

    A single strong signal (ATX heading, fenced code block, GFM table delimiter
    row) is enough on its own. Anything weaker needs at least two different
    moderate signals together (bold/italic, a blockquote line, an inline link) —
    a lone `*`/`-` list marker or stray asterisk is extremely common in plain
    prose (the exact case spec Section 7.4's heuristics target) and must never
    trigger this by itself, so list markers are deliberately not a signal here
    at all.
    """
    if any(pattern.search(text) for pattern in _STRONG_SIGNALS):
        return True

    moderate_hits = sum(1 for pattern in _MODERATE_SIGNALS if pattern.search(text))
    return moderate_hits >= 2
