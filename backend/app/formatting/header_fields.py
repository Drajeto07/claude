"""Fields in a header or footer's text (tracker DOCX-020A). {PAGE} and {NUMPAGES} stand for the
page number and count; any other field a header holds -- STYLEREF, DATE, a document property --
is kept as {FIELD <instruction>|<last result>}: the pages here and a PDF show its last result,
the header editor shows the placeholder (and keeps it while it isn't changed), and a Word export
writes the field again. Only fields the field policy allows (security/fields.py, SEC-015) become
placeholders, on import and again on export: one typed by hand that the policy refuses is written
as its text."""

import re

from app.security.fields import field_allowed

PAGE_TOKEN = "{PAGE}"
NUMPAGES_TOKEN = "{NUMPAGES}"
FIELD = re.compile(r"\{FIELD ([^|{}]+)\|([^{}]*)\}")
# A header or footer's text, as the model holds it at most (SectionSettings, rules).
MAX_TEXT = 500


def field_token(instruction: str, result: str) -> str | None:
    """The placeholder for a field, or None when it can't be one (the policy refuses it, or its
    instruction or result has a character the placeholder can't hold): then it is its result."""
    instruction = " ".join(instruction.split())
    if not instruction or not field_allowed(instruction) or any(c in instruction for c in "|{}") or any(c in result for c in "{}"):
        return None
    return f"{{FIELD {instruction}|{result}}}"


def shown(text: str) -> str:
    """The text as a page shows it: each field placeholder its last result."""
    return FIELD.sub(lambda match: match.group(2), text)


def fitted(text: str) -> str:
    """The text within what the model holds: placeholders made their results rather than cut."""
    return text if len(text) <= MAX_TEXT else shown(text)[:MAX_TEXT]


def parts(text: str) -> list[tuple[str, str, str]]:
    """The text in pieces to write: ("page", ...), ("numpages", ...), ("field", instruction,
    result) for a field the policy allows, and ("text", text) for the rest."""
    found: list[tuple[str, str, str]] = []
    for piece in re.split(r"(\{PAGE\}|\{NUMPAGES\}|\{FIELD [^|{}]+\|[^{}]*\})", text):
        if not piece:
            continue
        if piece == PAGE_TOKEN:
            found.append(("page", "", ""))
        elif piece == NUMPAGES_TOKEN:
            found.append(("numpages", "", ""))
        elif (match := FIELD.fullmatch(piece)) is not None:
            instruction, result = match.group(1), match.group(2)
            found.append(("field", instruction, result) if field_allowed(instruction) else ("text", result, ""))
        else:
            found.append(("text", piece, ""))
    return found
