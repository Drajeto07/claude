import logging
import re

from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from app.ai.base import AIProvider, AIRefusalError, AIStructuredOutputError
from app.ai.prompting import UNTRUSTED_DOCUMENT, document_tag, tagged
from app.ai.schemas import AIBlock, AIBlockType, AIStructureResponse
from app.config import get_settings
from app.logging_setup import describe_error
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

# Long text goes to the AI in pieces of about this many characters, cut
# between paragraphs (корекции.docx §21): each piece's answer -- its text
# again, in blocks -- then stays well within one response's token budget.
CHUNK_CHARS = 8_000
MAX_OUTPUT_TOKENS = 8192
# At most this many pieces of one document go to the AI (about 60 pages); the
# rest is split into paragraphs without it, and the document says so.
MAX_AI_CHUNKS = 20
# The latest headings found so far, shown with the next piece so its levels continue theirs.
_CONTEXT_HEADINGS = 12
_CONTEXT_HEADING_CHARS = 120

_AI_TYPE_TO_ELEMENT_TYPE = {
    AIBlockType.HEADING: ElementType.HEADING,
    AIBlockType.PARAGRAPH: ElementType.PARAGRAPH,
    AIBlockType.QUOTE: ElementType.QUOTE,
    AIBlockType.CODE_BLOCK: ElementType.CODE_BLOCK,
    AIBlockType.CAPTION: ElementType.CAPTION,
    AIBlockType.FOOTNOTE: ElementType.FOOTNOTE,
    AIBlockType.OTHER: ElementType.OTHER,
}

_AI_ERRORS = (
    ValidationError,
    AIRefusalError,
    AIStructuredOutputError,
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    # The Anthropic client raises a plain TypeError synchronously -- before any
    # network call -- when no API key/auth is configured at all. That's a "this
    # AI call can't happen" case exactly like the others here, and must degrade
    # to the fallback too, not surface as an unhandled 500 just because no one
    # has added a key to backend/.env yet.
    TypeError,
)


async def analyze_structure(provider: AIProvider, text: str, title: str | None = None) -> Document:
    """Real AI-driven structure analysis, reserved for genuinely unstructured
    prose (spec Section 7.4's actual hard case -- Markdown-looking text and
    DOCX uploads never reach this function; see app.services.ingestion_service).

    Long text is analysed a piece at a time, in order, each piece told the
    headings found before it, and the pieces' blocks are joined into one
    document. A piece whose AI answer can't be trusted after one retry is split
    into paragraphs by the naive segmenter instead -- that piece only -- so
    document creation never hard-fails just because an AI call went wrong.
    """
    chunks = split_into_chunks(text)
    if len(chunks) <= 1:
        response = await _analyze_piece(provider, text, part=None, earlier_headings=[])
        return _response_to_document(response, title=title) if response is not None else segment_plain_text(text, title=title)

    section = Section(order=0)
    elements: list[Element] = []
    notes: list[str] = []
    document_type: str | None = None
    for index, chunk in enumerate(chunks):
        response = None
        if index < MAX_AI_CHUNKS:
            response = await _analyze_piece(provider, chunk, part=(index + 1, len(chunks)), earlier_headings=_headings(elements))
        elif index == MAX_AI_CHUNKS:
            notes.append(
                f"This text is long, so the AI found the structure of about its first {MAX_AI_CHUNKS * CHUNK_CHARS // 1000:,}k "
                "characters; the rest was split into paragraphs. Check its headings and lists."
            )
        if response is None:
            elements.extend(_segmented(chunk, section.id, first=index == 0))
            continue
        document_type = document_type or response.document_type
        elements.extend(element for block in response.blocks if (element := _block_to_element(block, section.id, 0)) is not None)
    for order, element in enumerate(elements):
        element.order = order

    derived_title = elements[0].content if elements and elements[0].type == ElementType.HEADING else "Untitled Document"
    return Document(
        metadata=DocumentMetadata(title=title or derived_title),
        documentType=document_type or "general",
        sections=[section],
        elements=elements,
        unsupportedFeatures=notes,
    )


async def _analyze_piece(
    provider: AIProvider, text: str, *, part: tuple[int, int] | None, earlier_headings: list[tuple[int, str]]
) -> AIStructureResponse | None:
    """The AI's structure for one piece of text, or None when after the retries
    it still has none that keeps the text as it is."""
    prompt = _build_prompt(text, document_tag(), part, earlier_headings)
    max_attempts = 1 + get_settings().ai_structure_max_retries
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        attempt_prompt = prompt if attempt == 0 else prompt + "\n\n" + _RETRY_REMINDER
        try:
            response = await provider.complete_structured(
                attempt_prompt, response_model=AIStructureResponse, max_tokens=MAX_OUTPUT_TOKENS, system=_SYSTEM
            )
            if not _passes_fidelity_check(text, response):
                raise AIStructuredOutputError("Response text diverged too far from the original input")
            return response
        except _AI_ERRORS as exc:
            last_error = exc
            logger.warning("AI structure analysis attempt %d/%d failed: %s", attempt + 1, max_attempts, describe_error(exc))

    logger.warning(
        "AI structure analysis exhausted retries (last error: %s) -- falling back to naive segmenter",
        describe_error(last_error) if last_error else None,
    )
    return None


def split_into_chunks(text: str, limit: int | None = None) -> list[str]:
    """The text in consecutive pieces of at most `limit` characters (CHUNK_CHARS),
    cut between paragraphs -- a paragraph longer than that between its lines,
    a line longer than that between words. Nothing but whitespace at the cuts
    is lost, and the order is kept."""
    limit = limit or CHUNK_CHARS
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) <= limit:
        return [normalized] if normalized else []
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", normalized):
        paragraph = paragraph.strip()
        if paragraph:
            pieces.extend(_cut(paragraph, limit) if len(paragraph) > limit else [paragraph])
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for piece in pieces:
        if current and size + 2 + len(piece) > limit:
            chunks.append("\n\n".join(current))
            current, size = [], 0
        size += len(piece) + (2 if current else 0)
        current.append(piece)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _cut(text: str, limit: int) -> list[str]:
    """Text longer than `limit` in pieces: at line ends where it has them, else
    between words, else (one enormous word) anywhere."""
    for separator in ("\n", " "):
        units = text.split(separator)
        if len(units) == 1:
            continue
        pieces: list[str] = []
        current = ""
        for unit in units:
            candidate = f"{current}{separator}{unit}" if current else unit
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                pieces.append(current)
            current = unit
            if len(current) > limit:
                *done, current = _cut(current, limit)
                pieces.extend(done)
        if current:
            pieces.append(current)
        return pieces
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def _headings(elements: list[Element]) -> list[tuple[int, str]]:
    found = [(element.level or 1, element.content[:_CONTEXT_HEADING_CHARS]) for element in elements if element.type == ElementType.HEADING]
    return found[-_CONTEXT_HEADINGS:]


def _segmented(text: str, section_id: str, *, first: bool) -> list[Element]:
    """A piece split into paragraphs without the AI. Only a document's first
    piece may open with a heading (the segmenter's one guess)."""
    elements = segment_plain_text(text).elements
    for element in elements:
        element.parentId = section_id
        if not first and element.type == ElementType.HEADING:
            element.type, element.level = ElementType.PARAGRAPH, None
    return elements


_RETRY_REMINDER = (
    "Reminder: every confidence value must be a number strictly between 0 and 1, and every "
    "piece of block/item/cell text must be copied verbatim from the document -- do not "
    "alter, correct, or translate any of it."
)

_SYSTEM = f"""You are a document structure analyzer. You are given raw text and must identify
its logical structure. You must NOT rewrite, correct, translate, summarize, or paraphrase any
of it -- every piece of text you return in a block must be a VERBATIM excerpt of the input.

First classify the overall document type (e.g. "cv", "cover_letter", "essay", "report",
"letter", "complaint", "coursework", "general") with your confidence in that classification.

Then split the text into an ordered list of blocks covering the whole of it. For each block,
decide its type using a COMBINATION of signals together -- position in the document,
surrounding blank lines, length, punctuation, numbering, semantic role, repetition, and its
relationship to the following content. Never decide a block's type from a single signal
alone (a short line before a long paragraph might be a heading, but only when the
surrounding context actually supports that -- do not assume every short line is a heading).

Assign each block an honest confidence between 0 and 1: use a lower value whenever the
classification is genuinely ambiguous. Do not default to a high number just because a
decision was syntactically easy to make.

When the text is one part of a longer document, you are told which part, and shown the
headings found in the parts before it (as "level: text"). Continue their levels
consistently -- a subsection of the last section is one level below it -- and only return
blocks for the text of this part.

{UNTRUSTED_DOCUMENT}"""


def _build_prompt(text: str, tag: str, part: tuple[int, int] | None, earlier_headings: list[tuple[int, str]]) -> str:
    sections: list[str] = []
    if part is not None:
        number, total = part
        sections.append(f"This is part {number} of {total} of a longer document.")
        if earlier_headings:
            headings_tag = f"{tag}-earlier-headings"
            listing = "\n".join(f"{level}: {heading}" for level, heading in earlier_headings)
            sections.append(f"The headings in the parts before it are between <{headings_tag}> and </{headings_tag}>:\n" + tagged(headings_tag, listing))
    sections.append(f"Identify the structure of the text between <{tag}> and </{tag}>:\n" + tagged(tag, text))
    return "\n\n".join(sections)


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
