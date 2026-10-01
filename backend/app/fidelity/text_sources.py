"""The words of a text source, for the content check: Markdown by what it renders
(its syntax and link addresses aren't words a reader sees), and how many pictures a
PDF has (its text is all the PDF import keeps)."""

import io
import re

from pypdf import PdfReader

from app.fidelity.content import words
from app.parsers.markdown import _md

# A task list item's box, which the Markdown importer turns into a checkbox.
_TASK_BOX = re.compile(r"^\[[ xX]\]\s+")


def markdown_words(text: str) -> list[str]:
    result: list[str] = []
    item_start = False
    for token in _md.parse(text):
        if token.type == "list_item_open":
            item_start = True
        elif token.type in ("fence", "code_block"):
            result.extend(words(token.content))
        elif token.type == "inline":
            for child in token.children or []:
                if child.type == "image":
                    continue  # a picture's alt text isn't body text
                if child.type in ("text", "code_inline"):
                    content = child.content
                    if item_start:
                        content = _TASK_BOX.sub("", content)
                    result.extend(words(content))
                item_start = False
            item_start = False
    return result


def pdf_image_count(file_bytes: bytes, max_pages: int = 500) -> int | None:
    """Pictures on the PDF's pages (the first `max_pages` of them); None when they
    can't be counted -- never 0 for a file that may have some."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        total = 0
        for page in reader.pages[:max_pages]:
            total += len(page.images)
        return total
    except Exception:  # noqa: BLE001 -- whatever damage stops the count (SEC-011)
        return None
