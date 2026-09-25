import logging

from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from app.ai.base import AIProvider, AIRefusalError, AIStructuredOutputError
from app.ai.prompting import UNTRUSTED_DOCUMENT, document_tag, tagged
from app.ai.schemas import AIStyleAnalysisResponse
from app.config import get_settings
from app.logging_setup import describe_error
from app.models.document import Document, Element, ElementType
from app.schemas.document import StyleAnalysisResponse, StyleFlag

logger = logging.getLogger(__name__)

_PREVIEW_LENGTH = 200


def _element_preview(el: Element) -> str:
    text = el.content or ""
    if len(text) > _PREVIEW_LENGTH:
        text = text[:_PREVIEW_LENGTH] + "..."
    return f"- id={el.id} type={el.type.value}: {text!r}"


_SYSTEM = f"""You are a writing-style reviewer. You are given a document's headings and
paragraphs (in order) and must assess consistency of tone, terminology and formality across
them -- NOT visual formatting (font, spacing, alignment, etc. are handled separately and are
not your concern here).

Score consistency from 0 (wildly inconsistent voice) to 1 (fully consistent). Describe the
overall tone in a few words (e.g. "Formal and academic", "Casual and conversational"). Write a
1-2 sentence summary of your assessment. Flag specific elements (by their exact id from the
list) that clearly break from the rest of the document's voice, each with a short reason --
only flag genuine outliers, not every minor variation, and never invent an id that is not in
the list.

Do not suggest or perform any rewrite of the text -- only describe what you observe.

{UNTRUSTED_DOCUMENT}"""

# A long document is judged from its first elements (a sample enough to hear its voice).
_MAX_ELEMENTS = 300


def _build_prompt(elements: list[Element]) -> str:
    tag = document_tag()
    element_list = "\n".join(_element_preview(el) for el in elements[:_MAX_ELEMENTS])
    return f"The document's elements are between <{tag}> and </{tag}>:\n" + tagged(tag, element_list)


async def analyze_style(provider: AIProvider, document: Document) -> StyleAnalysisResponse:
    """Read-only assessment of the document's prose (spec: AI must never
    auto-rewrite anything) -- a genuinely new analysis axis, complementary
    to the deterministic formatting engine rather than a replacement for
    any part of it. Falls back to status="ai_unavailable" rather than
    raising, matching every other AI call site's graceful-degradation
    convention (see instruction_extraction.py / structure_analysis.py)."""
    elements = [el for el in document.elements if el.type in (ElementType.HEADING, ElementType.PARAGRAPH) and (el.content or "").strip()]
    if not elements:
        return StyleAnalysisResponse(status="empty_document")

    prompt = _build_prompt(elements)
    max_attempts = 1 + get_settings().ai_structure_max_retries
    valid_ids = {el.id for el in elements[:_MAX_ELEMENTS]}

    for attempt in range(max_attempts):
        try:
            response = await provider.complete_structured(prompt, response_model=AIStyleAnalysisResponse, system=_SYSTEM)
            flagged = [StyleFlag(elementId=f.element_id, reason=f.reason) for f in response.flagged if f.element_id in valid_ids]
            return StyleAnalysisResponse(
                status="ok",
                consistencyScore=response.consistency_score,
                tone=response.tone,
                summary=response.summary,
                flagged=flagged,
            )
        except (
            ValidationError,
            AIRefusalError,
            AIStructuredOutputError,
            APIConnectionError,
            APITimeoutError,
            APIStatusError,
            # See structure_analysis.py: the Anthropic client raises a bare
            # TypeError synchronously, before any network call, when no API
            # key is configured at all.
            TypeError,
        ) as exc:
            logger.warning("Style analysis attempt %d/%d failed: %s", attempt + 1, max_attempts, describe_error(exc))

    logger.warning("Style analysis exhausted retries -- no result available")
    return StyleAnalysisResponse(status="ai_unavailable")
