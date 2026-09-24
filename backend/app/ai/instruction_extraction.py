import logging

from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, ValidationError

from app.ai.base import AIProvider, AIRefusalError, AIStructuredOutputError
from app.ai.schemas import AIDocumentOperation, AIInstructionExtractionResponse
from app.config import get_settings
from app.formatting.priorities import Priority
from app.models.document import COARSE_TARGETS, Document, FormattingProperty, FormattingRule

logger = logging.getLogger(__name__)

_VALID_TARGETS = COARSE_TARGETS
_VALID_OPS = {"set_style", "delete_element", "insert_element", "move_element", "add_page_break"}
_VALID_INSERT_TYPES = {"paragraph", "heading"}
_PREVIEW_LENGTH = 60


class DocumentEdits(BaseModel):
    """What one instruction resolves to: coarse-type style rules (existing
    behaviour) plus a bounded set of structural/targeted-style operations
    (new). `ai_unavailable` distinguishes "the AI call itself failed" (no
    API key, network error, ...) from "the AI ran and legitimately found
    nothing to change" -- both currently produce empty rules/operations, but
    the frontend needs to tell them apart to avoid a fake-looking success
    when nothing actually happened (spec AC-INSTRUCTION-11/12)."""

    rules: list[FormattingRule] = []
    operations: list[AIDocumentOperation] = []
    ai_unavailable: bool = False


async def extract_document_edits(provider: AIProvider, instructions_text: str, document: Document) -> DocumentEdits:
    """Turns free-text instructions (typed manually or extracted from an
    uploaded rules document -- spec FR-IN-004/005, Section 7.8) into
    structured style rules and/or structural operations, with real document
    context so a specific element (not just a coarse type) can be targeted.

    Falls back to empty rules/operations -- not an error -- if the AI call
    can't produce valid output after one retry, so applying a template never
    hard-fails just because the instructions couldn't be parsed; the
    template/defaults still apply on their own. `ai_unavailable=True` in
    that case specifically (vs. a genuine "nothing to change" empty result)
    so the caller can tell the user why."""
    if not instructions_text.strip():
        return DocumentEdits()

    prompt = _build_prompt(instructions_text, document)
    max_attempts = 1 + get_settings().ai_structure_max_retries

    for attempt in range(max_attempts):
        attempt_prompt = prompt if attempt == 0 else prompt + "\n\n" + _RETRY_REMINDER
        try:
            response = await provider.complete_structured(attempt_prompt, response_model=AIInstructionExtractionResponse)
            return _response_to_edits(response)
        except (
            ValidationError,
            AIRefusalError,
            AIStructuredOutputError,
            APIConnectionError,
            APITimeoutError,
            APIStatusError,
            # See app.ai.structure_analysis for why this is here: the
            # Anthropic client raises a bare TypeError synchronously, before
            # any network call, when no API key is configured at all.
            TypeError,
        ) as exc:
            logger.warning("Instruction extraction attempt %d/%d failed: %s", attempt + 1, max_attempts, exc)

    logger.warning("Instruction extraction exhausted retries -- proceeding with no instruction-derived edits")
    return DocumentEdits(ai_unavailable=True)


_RETRY_REMINDER = (
    "Reminder: `property` must be one of the exact allowed property names listed above, `target`/`element_id` "
    "must be one of the exact allowed target names or a real element id listed above, and `op` must be one of "
    "the exact allowed operation names -- do not invent new ones."
)


def _element_preview(el) -> str:  # noqa: ANN001 -- Element, kept loose to avoid a heavier import here
    text = el.content or ""
    if len(text) > _PREVIEW_LENGTH:
        text = text[:_PREVIEW_LENGTH] + "..."
    return f"- id={el.id} type={el.type.value} text={text!r}"


def _build_prompt(instructions_text: str, document: Document) -> str:
    properties = ", ".join(p.value for p in FormattingProperty)
    targets = ", ".join(sorted(_VALID_TARGETS))
    ordered_elements = sorted(document.elements, key=lambda el: el.order)
    element_list = "\n".join(_element_preview(el) for el in ordered_elements) or "(document has no elements yet)"

    return f"""You are a document-editing instruction interpreter. You will be given the CURRENT
document's elements (in order) and free-text instructions (written by a user, possibly
informally), and must turn the instructions into structured edits.

Current document elements:
{element_list}

Two kinds of edit are available:

1. A style rule (coarse, type-level -- e.g. "make all headings red"): target one of
   {targets}, property one of {properties}, value as plain text, unit only when relevant
   (e.g. "pt", "cm").
2. An operation (specific, instance-level -- e.g. "delete this paragraph", "make THIS
   heading bold"): op is one of {sorted(_VALID_OPS)}.
   - set_style: element_id (a real id from the list above), property, value, unit.
   - delete_element: element_id (a real id from the list above).
   - insert_element: after_element_id (a real id, or omit to insert at the very end),
     element_type ("paragraph" or "heading"), text (the new content).
   - move_element: element_id (a real id), after_element_id (a real id, or omit for the end).
   - add_page_break: after_element_id (a real id, or omit for the end).

Rules:
- Only ever reference element ids that are literally in the list above -- never invent one,
  and never reference an element another operation in this same response is about to create.
- Only emit an edit for something the instructions actually say -- do not invent changes
  that were never mentioned.
- "Make the document more professional" or similarly open-ended requests: interpret as a
  bounded set of style rules (consistent heading sizes, spacing, a standard professional
  font) -- never rewrite the actual wording of any element's text.

<instructions>
{instructions_text}
</instructions>"""


def _response_to_edits(response: AIInstructionExtractionResponse) -> DocumentEdits:
    rules: list[FormattingRule] = []
    for item in response.rules:
        if item.target not in _VALID_TARGETS:
            continue
        try:
            property_enum = FormattingProperty(item.property)
        except ValueError:
            continue
        rules.append(
            FormattingRule(
                target=item.target,
                property=property_enum,
                value=item.value,
                unit=item.unit,
                priority=Priority.INSTRUCTION,
                source="instruction",
            )
        )

    operations: list[AIDocumentOperation] = []
    for op in response.operations:
        if op.op not in _VALID_OPS:
            continue
        if op.op == "insert_element" and op.element_type not in _VALID_INSERT_TYPES:
            continue
        if op.op == "set_style":
            try:
                FormattingProperty(op.property)
            except ValueError:
                continue
        operations.append(op)

    return DocumentEdits(rules=rules, operations=operations)
