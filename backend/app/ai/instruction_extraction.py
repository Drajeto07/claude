import logging

from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from app.ai.base import AIProvider, AIRefusalError, AIStructuredOutputError
from app.ai.schemas import AIInstructionExtractionResponse
from app.config import get_settings
from app.formatting.engine import PRIORITY_INSTRUCTION
from app.models.document import FormattingProperty, FormattingRule

logger = logging.getLogger(__name__)

_VALID_TARGETS = {
    "Heading 1", "Heading 2", "Heading 3", "Heading 4", "Heading 5", "Heading 6",
    "Paragraph", "List", "Table", "Quote", "Caption", "Footnote", "CodeBlock", "Image", "Document",
}


async def extract_formatting_rules(provider: AIProvider, instructions_text: str) -> list[FormattingRule]:
    """Turns free-text formatting instructions (typed manually or extracted
    from an uploaded rules document -- spec FR-IN-004/005, Section 7.8) into
    structured FormattingRules.

    Falls back to an empty list -- not an error -- if the AI call can't
    produce valid output after one retry, so applying a template never
    hard-fails just because the instructions couldn't be parsed; the
    template/defaults still apply on their own. Mirrors
    app.ai.structure_analysis's retry/fallback shape exactly.
    """
    if not instructions_text.strip():
        return []

    prompt = _build_prompt(instructions_text)
    max_attempts = 1 + get_settings().ai_structure_max_retries

    for attempt in range(max_attempts):
        attempt_prompt = prompt if attempt == 0 else prompt + "\n\n" + _RETRY_REMINDER
        try:
            response = await provider.complete_structured(attempt_prompt, response_model=AIInstructionExtractionResponse)
            return _response_to_rules(response)
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

    logger.warning("Instruction extraction exhausted retries -- proceeding with no instruction-derived rules")
    return []


_RETRY_REMINDER = (
    "Reminder: `property` must be one of the exact allowed property names listed above, and `target` must be "
    "one of the exact allowed target names listed above -- do not invent new ones."
)


def _build_prompt(instructions_text: str) -> str:
    properties = ", ".join(p.value for p in FormattingProperty)
    targets = ", ".join(sorted(_VALID_TARGETS))
    return f"""You are a formatting-instruction extractor. You will be given free-text formatting
instructions (written by a user, possibly informally) and must turn them into structured
formatting rules.

Each rule needs:
- target: exactly one of: {targets}
- property: exactly one of: {properties}
- value: the value as plain text (e.g. "Times New Roman", "14", "true", "justify")
- unit: only when relevant (e.g. "pt", "cm"), otherwise omit

Only emit a rule for something the instructions actually say -- do not invent formatting
preferences that were never mentioned.

<instructions>
{instructions_text}
</instructions>"""


def _response_to_rules(response: AIInstructionExtractionResponse) -> list[FormattingRule]:
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
                priority=PRIORITY_INSTRUCTION,
                source="instruction",
            )
        )
    return rules
