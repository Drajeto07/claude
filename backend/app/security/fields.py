"""Which Word fields a document may hold (SEC-015). A field is code Word runs when it
updates the document, and some reach outside it: DDE and DDEAUTO start a program,
INCLUDETEXT, INCLUDEPICTURE, INCLUDE, IMPORT, LINK, RD and DATABASE pull in outside
content (and tell its server the file was opened), MACROBUTTON runs a macro, PRINT sends
raw printer codes. So only the fields that show what the document itself holds or works
out are kept as fields; any other keeps its last result, as text -- in the Word file kept
as the original (security/package.py: no export carries one out) and in the fragments an export
writes back.
"""

import re

from lxml import etree

from app.security.links import safe_href

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Numbers and pages, dates, the document's own properties, cross-references, tables of
# contents and indexes, citations, form fields, formulas and mail-merge fields.
ALLOWED_FIELDS = frozenset(
    {
        "PAGE", "NUMPAGES", "SECTIONPAGES", "SECTION", "PAGEREF", "REF", "NOTEREF", "STYLEREF", "GOTOBUTTON",
        "SEQ", "LISTNUM", "AUTONUM", "AUTONUMLGL", "AUTONUMOUT", "REVNUM",
        "DATE", "TIME", "CREATEDATE", "SAVEDATE", "PRINTDATE", "EDITTIME",
        "AUTHOR", "LASTSAVEDBY", "TITLE", "SUBJECT", "KEYWORDS", "COMMENTS", "DOCPROPERTY", "DOCVARIABLE", "INFO",
        "FILENAME", "FILESIZE", "NUMWORDS", "NUMCHARS", "TEMPLATE", "USERNAME", "USERINITIALS", "USERADDRESS",
        "TOC", "TOA", "TA", "TC", "XE", "INDEX", "CITATION", "BIBLIOGRAPHY", "ADDIN",
        "FORMTEXT", "FORMCHECKBOX", "FORMDROPDOWN",
        "=", "IF", "COMPARE", "QUOTE", "SET", "SYMBOL", "EQ", "ADVANCE", "BARCODE", "DISPLAYBARCODE", "EMBED", "PRIVATE",
        "MERGEFIELD", "MERGEREC", "MERGESEQ", "NEXT", "NEXTIF", "SKIPIF", "ASK", "FILLIN", "GREETINGLINE", "ADDRESSBLOCK",
    }
)  # fmt: skip
_NAME = re.compile(r"\s*(=|[A-Za-z][A-Za-z0-9]*)")
_QUOTED = re.compile(r'\s*"([^"]*)"')
_BARE = re.compile(r"\s*([^\s\\][^\s]*)")
_BOOKMARK = re.compile(r"\\l\b")


def field_allowed(instr: str | None) -> bool:
    """Whether a field with this instruction (' PAGE \\* MERGEFORMAT ') may stay a field."""
    match = _NAME.match(instr or "")
    if match is None:
        return False
    name = match.group(1).upper()
    if name == "HYPERLINK":
        return _link_allowed(instr[match.end() :])
    return name in ALLOWED_FIELDS


def _link_allowed(rest: str) -> bool:
    """A HYPERLINK field to an address a link may have (SEC-014), or to a bookmark (\\l)."""
    target = _QUOTED.match(rest) or _BARE.match(rest)
    if target is None:
        return _BOOKMARK.search(rest) is not None
    return safe_href(target.group(1)) is not None


def neutralize_fields(root: etree._Element) -> int:
    """Every field `field_allowed` refuses, in this story (a body, a header, notes...), made
    its last result: a simple field its runs, a complex one without its start, instruction
    (nested fields in it too), separator and end. Deleted ones as well -- rejecting the
    deletion would bring them back. How many there were."""
    count = 0
    for simple in list(root.iter(f"{_W}fldSimple")):
        if field_allowed(simple.get(f"{_W}instr")):
            continue
        parent = simple.getparent()
        for offset, child in enumerate(list(simple)):
            parent.insert(parent.index(simple) + offset, child)
        parent.remove(simple)
        count += 1
    runs = list(root.iter(f"{_W}r"))
    open_fields: list[dict] = []
    refused: list[dict] = []
    for index, run in enumerate(runs):
        for child in run:
            if child.tag == f"{_W}fldChar":
                kind = child.get(f"{_W}fldCharType")
                if kind == "begin":
                    open_fields.append({"begin": index, "marks": [child], "instr": "", "separate": None})
                elif kind == "separate" and open_fields and open_fields[-1]["separate"] is None:
                    open_fields[-1]["separate"] = index
                    open_fields[-1]["marks"].append(child)
                elif kind == "end" and open_fields:
                    field = open_fields.pop()
                    field["marks"].append(child)
                    if not field_allowed(field["instr"]):
                        field["end"] = index
                        refused.append(field)
            elif child.tag in (f"{_W}instrText", f"{_W}delInstrText") and open_fields and open_fields[-1]["separate"] is None:
                open_fields[-1]["instr"] += child.text or ""
                open_fields[-1]["marks"].append(child)
    for field in refused:
        count += 1
        # All that lies between its start and its result is its instruction.
        for index in range(field["begin"] + 1, field["separate"] if field["separate"] is not None else field["end"]):
            _drop(runs[index])
        for mark in field["marks"]:
            if mark.getparent() is not None:
                mark.getparent().remove(mark)
    for run in runs:  # the runs that held only field marks
        if run.getparent() is not None and all(child.tag == f"{_W}rPr" for child in run):
            _drop(run)
    return count


def _drop(element: etree._Element) -> None:
    if element.getparent() is not None:
        element.getparent().remove(element)


# The parts that hold text a field can be in: the body, headers and footers, notes,
# comments, and the building blocks.
STORIES = frozenset(
    f"{_W}{name}" for name in ("document", "hdr", "ftr", "footnotes", "endnotes", "comments", "glossaryDocument")
)

