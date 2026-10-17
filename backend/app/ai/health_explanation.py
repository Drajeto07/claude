"""AI explanations of Document Health's findings (tracker HLTH-003, brief §38): the checks score
the document and find what to fix, deterministically (formatting/health.py); the AI only says,
in plain words, why a finding matters and what to do about it. It is never sent the score and
never gives one: it is shown the failing checks -- their titles, summaries, issues and a few
words of the blocks they name -- and an answer that rates the document, or explains a check it
wasn't asked about, is not used."""

import logging
import re

from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, Field, ValidationError

from app.ai.base import AIProvider, AIRefusalError, AIStructuredOutputError
from app.ai.prompting import UNTRUSTED_DOCUMENT, document_tag, tagged
from app.formatting.health import HealthReport
from app.logging_setup import describe_error
from app.models.base import ApiModel
from app.models.document import Document, walk_elements

logger = logging.getLogger(__name__)

_MAX_ISSUES = 5
_MAX_BLOCKS = 3
_PREVIEW = 100
MAX_EXPLANATION = 600
# What a rating looks like: a score, "x out of 100", a grade.
_RATING = re.compile(r"\bscores?\b|\b\d{1,3}\s*(?:/|out of)\s*100\b|\brat(?:e|ed|ing)\b|\bgrade\b", re.IGNORECASE)


class AIHealthExplanation(BaseModel):
    checkId: str
    explanation: str


class AIHealthExplanations(BaseModel):
    explanations: list[AIHealthExplanation]


class HealthExplanation(ApiModel):
    checkId: str
    explanation: str = Field(max_length=MAX_EXPLANATION)


_SYSTEM = (
    "You help someone fix the formatting of their document. A deterministic checker has already found what is "
    "wrong; you are given its findings -- each check's id, title, summary and issues, with a few words of the "
    "blocks they concern. For each check, write two or three short sentences in plain language: why it matters "
    "to a reader, and what to do about it in the editor (the checker can also propose fixes for some). Explain "
    "only the findings given, each once, under its own id. Never rate, score or grade the document or any check, "
    "never say how good or bad it is overall, and never add findings of your own.\n\n" + UNTRUSTED_DOCUMENT
)


def _prompt(document: Document, report: HealthReport, check_ids: list[str]) -> str:
    blocks = {element.id: element for element in walk_elements(document.elements)}
    lines: list[str] = []
    for check in report.checks:
        if check.id not in check_ids:
            continue
        lines.append(f"- check id={check.id} | {check.title} | {check.summary}")
        for issue in check.issues[:_MAX_ISSUES]:
            words = [" ".join(blocks[element_id].content.split())[:_PREVIEW] for element_id in issue.elementIds[:_MAX_BLOCKS] if element_id in blocks]
            shown = "; ".join(f'"{text}"' for text in words if text)
            lines.append(f"  - {issue.message}" + (f" | in: {shown}" if shown else ""))
    tag = document_tag()
    return f"The checker's findings, with words from the document, are between <{tag}> and </{tag}>:\n" + tagged(tag, "\n".join(lines))


def failing(report: HealthReport) -> list[str]:
    """The checks with something to explain: a warning or a failure (not passed, not skipped)."""
    return [check.id for check in report.checks if check.status in ("warn", "fail")]


async def explain_health(provider: AIProvider, document: Document, report: HealthReport, check_ids: list[str] | None = None) -> list[HealthExplanation] | None:
    """An explanation for each failing check asked about (all of them, when None). [] when none
    has anything to explain; None when the AI can't be used, or its answer doesn't hold up."""
    wanted = [check_id for check_id in failing(report) if check_ids is None or check_id in check_ids]
    if not wanted:
        return []
    try:
        answer = await provider.complete_structured(_prompt(document, report, wanted), response_model=AIHealthExplanations, max_tokens=2048, system=_SYSTEM)
    except (ValidationError, AIRefusalError, AIStructuredOutputError, APIConnectionError, APITimeoutError, APIStatusError, TypeError) as exc:
        logger.warning("AI health explanations unavailable: %s", describe_error(exc))
        return None
    explained: dict[str, str] = {}
    for item in answer.explanations:
        if item.checkId not in wanted or item.checkId in explained:
            logger.warning("AI health explanations named a check it wasn't asked about; ignoring its answer")
            return None
        text = " ".join(item.explanation.split())
        if not text or _RATING.search(text):
            continue  # an explanation that rates isn't shown; the others are
        explained[item.checkId] = text[:MAX_EXPLANATION]
    return [HealthExplanation(checkId=check_id, explanation=explained[check_id]) for check_id in wanted if check_id in explained]
