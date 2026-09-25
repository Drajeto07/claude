"""Format by Example (корекции.docx §17): a reference .docx in, the StyleSystem it
uses out. Nothing is stored here. Saving the result as a template and applying
it to a document go through the template and formatting endpoints, like any
other template, so it can be reviewed, edited and re-applied the same way."""

import asyncio
from pathlib import PurePath

from app.ai.base import AIProvider
from app.ai.semantic_labeling import label_headings
from app.formatting.reference_style import (
    ReferenceStyle,
    body_look,
    extract_reference_style,
    heading_candidates,
    infer_heading_levels,
    paragraph_looks,
)
from app.parsers.docx import import_docx


async def extract_from_docx(file_bytes: bytes, filename: str, provider: AIProvider | None) -> ReferenceStyle:
    """Raises DocxParseError for a file that isn't a readable .docx."""
    imported = await asyncio.to_thread(import_docx, file_bytes, filename)
    document = imported.document
    heading_levels: dict[str, int] = {}
    source: str | None = None
    candidates = heading_candidates(document)  # empty when the reference uses heading styles
    if candidates:
        looks = paragraph_looks(document)
        labels = await label_headings(provider, document, candidates, looks, body_look(document, looks)) if provider else None
        if labels is not None:
            heading_levels, source = labels, "ai"
        else:
            heading_levels, source = infer_heading_levels(document), "look"
    return extract_reference_style(document, heading_levels=heading_levels, headings_from=source, notes=imported.style_notes)


def suggested_name(filename: str, taken: set[str] | frozenset[str] = frozenset()) -> str:
    """"<file name> style", numbered when the workspace already has a template of that name."""
    stem = " ".join(PurePath(filename).stem.split()) or "Reference"
    name = f"{stem[:240]} style"
    number = 2
    candidate = name
    while candidate in taken:
        candidate = f"{name} {number}"
        number += 1
    return candidate
