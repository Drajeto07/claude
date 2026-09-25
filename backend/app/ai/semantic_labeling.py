"""AI help for Format by Example (корекции.docx §17): which paragraphs of a
reference document are headings, and of what level, when the reference doesn't
use Word's heading styles. The AI only labels. How anything looks is still read
from the document itself (formatting/reference_style.py)."""

import logging
from typing import Literal, Optional

from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, ValidationError

from app.ai.base import AIProvider, AIRefusalError, AIStructuredOutputError
from app.ai.prompting import UNTRUSTED_DOCUMENT, document_tag, tagged
from app.formatting.reference_style import ParagraphLook
from app.logging_setup import describe_error
from app.models.document import Document, Element, ElementType

logger = logging.getLogger(__name__)

_MAX_CANDIDATES = 80
_TEXT_LIMIT = 150
_CONTEXT_LIMIT = 60


class AIParagraphLabel(BaseModel):
    id: str
    role: Literal["heading", "body", "caption"]
    level: Optional[int] = None


class AIParagraphLabels(BaseModel):
    labels: list[AIParagraphLabel]


def _line(element: Element, look: ParagraphLook, following: Element | None) -> str:
    size = f"{look.size_pt:g}pt" if look.size_pt else "size ?"
    flags = " ".join(flag for flag, on in (("bold", look.bold), ("italic", look.italic)) if on) or "regular"
    alignment = look.alignment or "left"
    text = " ".join(element.content.split())[:_TEXT_LIMIT]
    after = " ".join(following.content.split())[:_CONTEXT_LIMIT] if following is not None else ""
    return f'- id={element.id} | {size}, {flags}, {alignment} | text: "{text}" | next: "{after}"'


_SYSTEM = (
    "You are helping reproduce the design of a reference Word document. It doesn't use Word's heading styles, "
    "so its headings are ordinary paragraphs that only look different. You are given its short paragraphs, "
    "each with its id, how it looks, its text and the start of the text after it.\n\n"
    "For each paragraph, say whether it is a heading (with its level: 1 for the document title or top-level "
    "sections, 2 for subsections, and so on up to 6), a caption (a label under a figure or table), or body "
    "text. Judge from the wording and from how it looks compared with the body text. Headings of the same "
    "level normally look the same. Use only the ids given, label every paragraph once, and never invent text.\n\n"
    + UNTRUSTED_DOCUMENT
)


def _prompt(lines: list[str], body: ParagraphLook) -> str:
    body_size = f"{body.size_pt:g}pt" if body.size_pt else "unknown size"
    body_flags = "bold" if body.bold else "not bold"
    tag = document_tag()
    return (
        f"Its body text is {body_size}, {body_flags}. Its short paragraphs are between <{tag}> and </{tag}>:\n"
        + tagged(tag, "\n".join(lines))
    )


async def label_headings(
    provider: AIProvider,
    document: Document,
    candidates: list[Element],
    looks: dict[str, ParagraphLook],
    body: ParagraphLook,
) -> dict[str, int] | None:
    """Element id -> heading level for the candidates the AI calls headings
    (an empty dict: it found none). None when the AI can't be used -- no key,
    an error, a refusal -- or its answer doesn't hold up, so the caller falls
    back to judging by look."""
    candidates = candidates[:_MAX_CANDIDATES]
    if not candidates:
        return {}
    position = {element.id: index for index, element in enumerate(document.elements)}
    lines = []
    for element in candidates:
        index = position[element.id]
        following = document.elements[index + 1] if index + 1 < len(document.elements) else None
        lines.append(_line(element, looks[element.id], following))

    try:
        answer = await provider.complete_structured(_prompt(lines, body), response_model=AIParagraphLabels, max_tokens=4096, system=_SYSTEM)
    except (
        ValidationError,
        AIRefusalError,
        AIStructuredOutputError,
        APIConnectionError,
        APITimeoutError,
        APIStatusError,
        TypeError,  # the Anthropic client raises it before any request when no API key is set
    ) as exc:
        logger.warning("AI heading labelling unavailable: %s", describe_error(exc))
        return None

    known = {element.id for element in candidates}
    levels: dict[str, int] = {}
    for label in answer.labels:
        if label.id not in known:
            logger.warning("AI heading labelling named an unknown paragraph; ignoring its answer")
            return None
        if label.role == "heading":
            if label.level is None or not 1 <= label.level <= 6:
                logger.warning("AI heading labelling gave a heading without a valid level; ignoring its answer")
                return None
            levels[label.id] = label.level
    paragraphs = sum(1 for element in document.elements if element.type == ElementType.PARAGRAPH and element.content.strip())
    if len(levels) * 2 > paragraphs:
        logger.warning("AI heading labelling called most paragraphs headings; ignoring its answer")
        return None
    return levels
