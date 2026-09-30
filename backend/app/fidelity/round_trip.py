"""The true fidelity test (tracker TEST-022, audit AUD-20): a Word file as it went in
(SOURCE) against the Word file that came out (RESULT) of the app's whole path --
imported as an upload imports it, formatted with a template, saved as the editor
saves it, exported to Word into the original -- compared on four axes, each on its
own, so a loss is named where it happens:

- content: the words, in order, of the body (notes included) and of the headers and
  footers, the source file's against the result file's;
- structure: the blocks each file reads as -- kinds, heading levels, list items and
  their levels, table shapes, the pictures in them;
- formatting: each kind of block's look and the marks on the text, as the formatted
  document has them against what the result file reads as;
- metadata: the files' core and custom properties.

The path runs through the functions the services call (DocumentService.create,
apply_formatting, update_content) without a database; tests/test_golden_documents.py
takes a document through the API itself. A fixture's committed
<fixture>.expected-fidelity.json (scripts/export_expected_fidelity.py) pins what each
axis differs in today, and tests/test_true_fidelity.py compares."""

import difflib
import io
import re
import zipfile
from collections import Counter
from typing import Any

from docx import Document as DocxDocument
from lxml import etree

from app.export.docx_export import build_docx
from app.export.provenance import keep_provenance, stamp
from app.fidelity.content import compare_words, words
from app.fidelity.docx_source import read_docx_source
from app.fidelity.imports import with_source_kept
from app.formatting.engine import apply_formatting, prune_dangling_element_rules, recompute_styles
from app.models.document import Document, Element, ElementType, FormattingRule, inline_runs, target_for_element, walk_elements
from app.parsers.docx import parse_docx
from app.services.ingestion_service import build_document_from_docx

_KINDS = ("Paragraph", *(f"Heading {level}" for level in range(1, 7)), "List", "Table", "Quote", "Caption", "Footnote", "CodeBlock")
_LOOK = ("font-family", "font-size", "font-weight", "font-style", "color", "text-align", "margin-top", "margin-bottom", "line-height", "margin-left", "text-indent")
# Not "modified": a file the app wrote was modified then.
_PROPERTIES = ("author", "title", "subject", "keywords", "comments", "category", "created", "last_modified_by")


def through_the_app(data: bytes, name: str, *, template_id: str, template_rules: list[FormattingRule]) -> tuple[Document, bytes]:
    """The document as the app holds it once formatted and saved, and the Word file it exports."""
    document = build_document_from_docx(data, name, None)
    recompute_styles(document)
    if document.importReport is not None:
        document.importReport = with_source_kept(document.importReport, data, document)
    stamp(document)
    apply_formatting(document, template_id=template_id, template_rules=template_rules, instruction_rules=[])
    # The editor's save: the elements as they travel back, where each came from the server's to say.
    sent = [Element.model_validate(element.model_dump(mode="json")) for element in document.elements]
    for index, element in enumerate(sent):
        element.order = index
    keep_provenance(document.elements, sent)
    document.elements = sent
    prune_dangling_element_rules(document)
    recompute_styles(document)
    return document, build_docx(document, source=data)


def _check(source: str, result: str) -> dict[str, Any]:
    check = compare_words(words(source), words(result), method="docx-text")
    return {"verified": check.verified, "missing": check.missing, "added": check.added}


def content_axis(source: bytes, result: bytes) -> dict[str, Any]:
    before, after = read_docx_source(source), read_docx_source(result)
    return {"body": _check(before.body, after.body), "headers": _check(before.header_footer, after.header_footer)}


def _blocks(document: Document) -> list[str]:
    lines = []
    for element in sorted(document.elements, key=lambda element: element.order):
        if element.type == ElementType.HEADING:
            line = f"heading {element.level}"
        elif element.type == ElementType.LIST:
            line = f"{'numbered' if element.ordered else 'bulleted'} list {[item.level for item in element.listItems or []]}"
        elif element.type == ElementType.TABLE:
            line = f"table {[len(row.cells) for row in element.table.rows]}"
        else:
            line = element.type.value
        pictures = sum(1 for block in walk_elements([element]) if block.type == ElementType.IMAGE and block is not element)
        lines.append(line + (f" with {pictures} picture{'s' if pictures != 1 else ''}" if pictures else ""))
    return lines


def structure_axis(source: Document, result: Document) -> list[str]:
    """How the result's blocks differ from the source's, as difflib lines them up."""
    before, after = _blocks(source), _blocks(result)
    changes = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes():
        if tag != "equal":
            changes.append(f"{tag} {before[i1:i2]} -> {after[j1:j2]}")
    return changes


def _value(value: str | None) -> str | None:
    """A CSS value as a comparison sees it: 12pt and 12.0pt alike, colours in one case,
    and a length of nothing the same as no length (no indent is no indent)."""
    if value is None:
        return None
    value = re.sub(r"(\d)\.0+(?=\D|$)", r"\1", value.strip().lower())
    return None if re.fullmatch(r"0(?:pt|cm|mm|px|in|em)?", value) else value


def _marks(document: Document) -> Counter:
    return Counter(mark.type.value for element in document.elements for run in inline_runs(element) for mark in run.marks)


def formatting_axis(formatted: Document, result: Document) -> list[str]:
    """What the result reads as against what the formatted document looked like: each
    kind of block it has, and how many runs carry each mark."""
    used = {target_for_element(element) for element in walk_elements(formatted.elements)}
    changes = []
    for kind in _KINDS:
        if kind not in used:
            continue
        want, got = formatted.resolvedStyles.get(kind, {}), result.resolvedStyles.get(kind, {})
        changes += [f"{kind} {prop}: {want.get(prop)} -> {got.get(prop)}" for prop in _LOOK if _value(want.get(prop)) != _value(got.get(prop))]
    before, after = _marks(formatted), _marks(result)
    changes += [f"{mark} marks: {before[mark]} -> {after[mark]}" for mark in sorted(before.keys() | after.keys()) if before[mark] != after[mark]]
    return changes


def _custom_properties(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        if "docProps/custom.xml" not in package.namelist():
            return {}
        root = etree.fromstring(package.read("docProps/custom.xml"))
    return {prop.get("name"): "".join(prop.itertext()) for prop in root}


def metadata_axis(source: bytes, result: bytes) -> list[str]:
    before, after = DocxDocument(io.BytesIO(source)).core_properties, DocxDocument(io.BytesIO(result)).core_properties
    changes = [f"{name}: {getattr(before, name)!r} -> {getattr(after, name)!r}" for name in _PROPERTIES if getattr(before, name) != getattr(after, name)]
    custom_before, custom_after = _custom_properties(source), _custom_properties(result)
    changes += [f"custom {name}: {custom_before.get(name)!r} -> {custom_after.get(name)!r}" for name in sorted(custom_before.keys() | custom_after.keys()) if custom_before.get(name) != custom_after.get(name)]
    return changes


def fidelity(data: bytes, name: str, *, template_id: str, template_rules: list[FormattingRule]) -> dict[str, Any]:
    """SOURCE against RESULT on each axis."""
    formatted, result = through_the_app(data, name, template_id=template_id, template_rules=template_rules)
    source_document, result_document = parse_docx(data, name), parse_docx(result, name)
    return {
        "template": template_id,
        "content": content_axis(data, result),
        "structure": structure_axis(source_document, result_document),
        "formatting": formatting_axis(formatted, result_document),
        "metadata": metadata_axis(data, result),
    }
