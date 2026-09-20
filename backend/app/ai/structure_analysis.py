import logging
import re

from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from app.ai.base import AIProvider, AIRefusalError, AIStructuredOutputError
from app.ai.schemas import AIBlock, AIBlockType, AIStructureResponse
from app.config import get_settings
from app.models.document import (
    Document,
    DocumentMetadata,
    Element,
    ElementType,
    InlineRun,
    ListItem,
    Section,
    TableCell,
    TableContent,
    TableRow,
    plain_text_from_inline,
)
from app.parsers.plain_text import segment_plain_text

logger = logging.getLogger(__name__)

_AI_TYPE_TO_ELEMENT_TYPE = {
    AIBlockType.HEADING: ElementType.HEADING,
    AIBlockType.PARAGRAPH: ElementType.PARAGRAPH,
    AIBlockType.QUOTE: ElementType.QUOTE,
    AIBlockType.CODE_BLOCK: ElementType.CODE_BLOCK,
    AIBlockType.CAPTION: ElementType.CAPTION,
    AIBlockType.FOOTNOTE: ElementType.FOOTNOTE,
    AIBlockType.OTHER: ElementType.OTHER,
}


async def analyze_structure(provider: AIProvider, text: str, title: str | None = None) -> Document:
    """Real AI-driven structure analysis, reserved for genuinely unstructured
    prose (spec Section 7.4's actual hard case -- Markdown-looking text and
    DOCX uploads never reach this function; see app.services.ingestion_service).

    Falls back to the naive placeholder segmenter if the AI call can't
    produce valid, trustworthy output after one retry, so document creation
    never hard-fails just because a single AI call went wrong.
    """
    prompt = _build_prompt(text)
    last_error: Exception | None = None
    max_attempts = 1 + get_settings().ai_structure_max_retries

    for attempt in range(max_attempts):
        attempt_prompt = prompt if attempt == 0 else prompt + "\n\n" + _RETRY_REMINDER
        try:
            response = await provider.complete_structured(attempt_prompt, response_model=AIStructureResponse)
            if not _passes_fidelity_check(text, response):
                raise AIStructuredOutputError("Response text diverged too far from the original input")
            return _response_to_document(response, title=title)
        except (
            ValidationError,
            AIRefusalError,
            AIStructuredOutputError,
            APIConnectionError,
            APITimeoutError,
            APIStatusError,
            # The Anthropic client raises a plain TypeError synchronously --
            # before any network call -- when no API key/auth is configured
            # at all. That's a "this AI call can't happen" case exactly like
            # the others here, and must degrade to the fallback too, not
            # surface as an unhandled 500 just because no one has added a
            # key to backend/.env yet.
            TypeError,
        ) as exc:
            last_error = exc
            logger.warning("AI structure analysis attempt %d/%d failed: %s", attempt + 1, max_attempts, exc)

    logger.warning("AI structure analysis exhausted retries (last error: %s) -- falling back to naive segmenter", last_error)
    return segment_plain_text(text, title=title)


_RETRY_REMINDER = (
    "Reminder: every confidence value must be a number strictly between 0 and 1, and every "
    "piece of block/item/cell text must be copied verbatim from the document above -- do not "
    "alter, correct, or translate any of it."
)


def _build_prompt(text: str) -> str:
    return f"""You are a document structure analyzer. You will be given raw text and must
identify its logical structure. You must NOT rewrite, correct, translate, summarize, or
paraphrase any of it -- every piece of text you return in a block must be a VERBATIM
excerpt of the input.

First classify the overall document type (e.g. "cv", "cover_letter", "essay", "report",
"letter", "complaint", "coursework", "general") with your confidence in that classification.

Then split the text into an ordered list of blocks covering the whole document. For each
block, decide its type using a COMBINATION of signals together -- position in the document,
surrounding blank lines, length, punctuation, numbering, semantic role, repetition, and its
relationship to the following content. Never decide a block's type from a single signal
alone (a short line before a long paragraph might be a heading, but only when the
surrounding context actually supports that -- do not assume every short line is a heading).

Assign each block an honest confidence between 0 and 1: use a lower value whenever the
classification is genuinely ambiguous. Do not default to a high number just because a
decision was syntactically easy to make.

<document>
{text}
</document>"""


_WORD_PATTERN = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [word.lower() for word in _WORD_PATTERN.findall(text)]


def _response_text(response: AIStructureResponse) -> str:
    parts: list[str] = []
    for block in response.blocks:
        if block.type == AIBlockType.LIST and block.items:
            parts.extend(item.text for item in block.items)
        elif block.type == AIBlockType.TABLE and block.rows:
            for row in block.rows:
                parts.extend(row.cells)
        else:
            parts.append(block.text)
    return " ".join(parts)


def _passes_fidelity_check(original_text: str, response: AIStructureResponse) -> bool:
    """Beyond schema validation: confirm the AI didn't silently alter the
    text (spec Section 13 -- AI must never change the original content).
    Word-level (not exact-sequence) comparison tolerates the AI
    reordering/splitting blocks, while still catching real paraphrasing --
    including for short responses, where a fixed "N words tolerated"
    allowance would be too generous relative to the total word count."""
    original_words = set(_tokenize(original_text))
    if not original_words:
        return True
    response_words = _tokenize(_response_text(response))
    if not response_words:
        return True
    unknown = [word for word in response_words if word not in original_words]
    return len(unknown) / len(response_words) <= 0.2


def _response_to_document(response: AIStructureResponse, title: str | None) -> Document:
    section = Section(order=0)
    elements: list[Element] = []
    for index, block in enumerate(response.blocks):
        element = _block_to_element(block, section.id, index)
        if element is not None:
            elements.append(element)

    derived_title = (
        elements[0].content if elements and elements[0].type == ElementType.HEADING else "Untitled Document"
    )
    return Document(
        metadata=DocumentMetadata(title=title or derived_title),
        documentType=response.document_type,
        sections=[section],
        elements=elements,
    )


def _block_to_element(block: AIBlock, section_id: str, order: int) -> Element | None:
    if block.type == AIBlockType.LIST and block.items:
        items = [
            ListItem(inline=[InlineRun(text=item.text)], level=item.level, checked=item.checked)
            for item in block.items
        ]
        content = "\n".join(plain_text_from_inline(item.inline) for item in items)
        return Element(
            type=ElementType.LIST,
            content=content,
            listItems=items,
            ordered=bool(block.ordered),
            parentId=section_id,
            order=order,
            confidence=block.confidence,
        )
    if block.type == AIBlockType.TABLE and block.rows:
        has_header = bool(block.has_header_row)
        table_rows = [
            TableRow(
                cells=[
                    TableCell(inline=[InlineRun(text=cell)], header=has_header and row_index == 0)
                    for cell in row.cells
                ]
            )
            for row_index, row in enumerate(block.rows)
        ]
        table = TableContent(rows=table_rows, hasHeaderRow=has_header)
        content = "\n".join(
            " | ".join(plain_text_from_inline(cell.inline) for cell in row.cells) for row in table_rows
        )
        return Element(
            type=ElementType.TABLE,
            content=content,
            table=table,
            parentId=section_id,
            order=order,
            confidence=block.confidence,
        )

    element_type = _AI_TYPE_TO_ELEMENT_TYPE.get(block.type, ElementType.OTHER)
    inline = [InlineRun(text=block.text)] if block.text else None
    return Element(
        type=element_type,
        content=block.text,
        inline=inline,
        language=block.language if element_type == ElementType.CODE_BLOCK else None,
        parentId=section_id,
        order=order,
        level=block.level,
        confidence=block.confidence,
    )
