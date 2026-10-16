"""Translating blocks of a document (tracker TRAN-005/006): their segments sent to the provider,
each answer checked (validation.py), and the blocks rebuilt with the translations that pass
-- each run's formatting where its words went, the block's id, kind and style kept. A segment
whose translation fails the check, or isn't given, stays as it was, and says why: nothing is
changed silently, nothing that changes a fact is used.

What can't be translated yet is said, never skipped silently: code (never translated), blocks
nested in a quote, a list item or a table cell, and blocks holding Word content placed by its
position in the text (fields, bookmarks, comments: translating moves the words under them)."""

from dataclasses import dataclass, field

from app.config import get_settings
from app.models.document import Document, Element, ElementType, InlineRun, LanguageTag, plain_text_from_inline
from app.translation.language import detect, language_name
from app.translation.providers import AITranslator, PseudoTranslator, SegmentText, TranslationProvider
from app.translation.segments import SKIPPED, Segment, segments_of, untag, untranslatable
from app.translation.validation import GlossaryEntry, describe, problems_of

# Said wherever a translation is shown (brief §48): never "certified".
LABEL = "AI-assisted translation — review required."
UNTRANSLATABLE = "holds blocks inside it (a quote, a list item or a table cell with more than text) that can't be translated yet"
PRESERVED = "holds Word content placed by its text (a field, a bookmark, a comment) that translating would misplace"
NOT_GIVEN = "the translation service gave no translation for it"


@dataclass(slots=True)
class Translation:
    segments: list[Segment]
    skipped: dict[str, str] = field(default_factory=dict)  # element id -> why
    source_language: str | None = None

    @property
    def characters(self) -> int:
        """What is sent to be translated, as the plan counts it: the text, tags left out."""
        return sum(len(segment.plain) for segment in self.segments)


def provider_for(ai) -> TranslationProvider:
    choice = get_settings().translation_provider
    if choice == "pseudo":
        return PseudoTranslator()
    if choice == "ai":
        return AITranslator(ai)
    raise ValueError(f"Unknown TRANSLATION_PROVIDER: {choice}")


def glossary_for(document: Document, source: str | None, target: str) -> list[GlossaryEntry]:
    """The document's terms that apply between these languages (a term without languages: always)."""

    def matches(term_language: str | None, language: str | None) -> bool:
        return term_language is None or (language is not None and term_language.split("-")[0].lower() == language.split("-")[0].lower())

    return [
        GlossaryEntry(term.source, term.target, term.locked, term.caseSensitive)
        for term in document.glossary
        if matches(term.sourceLanguage, source) and matches(term.targetLanguage, target)
    ]


def document_language(document: Document) -> str | None:
    """The language the user set, else the one the text reads as (None: it can't be told)."""
    if document.metadata.language:
        return document.metadata.language
    return detect(" ".join(element.content for element in document.elements[:200])[:20_000]).language


def collect(elements: list[Element]) -> Translation:
    segments: list[Segment] = []
    skipped: dict[str, str] = {}
    for element in elements:
        if element.type in SKIPPED:
            continue
        if untranslatable(element):
            skipped[element.id] = UNTRANSLATABLE
            continue
        if element.preservedAttributes and element.preservedAttributes.get("ooxml"):
            skipped[element.id] = PRESERVED
            continue
        segments.extend(segments_of(element))
    return Translation(segments=segments, skipped=skipped)


async def translate(translation: Translation, provider: TranslationProvider, *, source: str | None, target: str, glossary: list[GlossaryEntry]) -> None:
    """Every segment translated and checked: "translated", "invalid" (with its problems) or "failed"."""
    answers = await provider.translate(
        [SegmentText(segment.id, segment.source) for segment in translation.segments], source=source, target=target, glossary=glossary
    )
    for segment in translation.segments:
        segment.source_language, segment.target_language, segment.provider = source, target, provider.name
        segment.glossary_terms = [entry.source for entry in glossary]
        answer = answers.get(segment.id)
        if answer is None:
            segment.status, segment.problems = "failed", [NOT_GIVEN]
            continue
        problems = problems_of(segment, answer, glossary)
        segment.target = answer
        segment.status = "invalid" if problems else "translated"
        segment.problems = [describe(problems)] if problems else []


def _runs(segment: Segment) -> list[InlineRun] | None:
    if segment.status != "translated" or segment.target is None:
        return None
    return untag(segment.target, segment.marks, segment.placeholders)


def rebuilt(element: Element, segments: list[Segment], target: LanguageTag) -> tuple[Element | None, list[str]]:
    """The element with its translated segments in place (None: none passed), and why any
    part of it stayed as it was."""
    mine = {segment.path: segment for segment in segments if segment.element_id == element.id}
    problems = [f"{language_name(target)}: {segment.problems[0]}" for segment in mine.values() if segment.problems]
    applied = {path: runs for path, segment in mine.items() if (runs := _runs(segment)) is not None}
    if not applied:
        return None, problems
    new = element.model_copy(deep=True)
    if new.listItems:
        for item in new.listItems:
            if (runs := applied.get(f"item/{item.id}")) is not None:
                item.inline = runs
        new.content = "\n".join(plain_text_from_inline(item.inline) for item in new.listItems)
    elif new.table:
        for row in new.table.rows:
            for cell in row.cells:
                if (runs := applied.get(f"cell/{cell.id}")) is not None:
                    cell.inline = runs
        new.content = "\n".join(" | ".join(plain_text_from_inline(cell.inline) for cell in row.cells) for row in new.table.rows)
    elif (runs := applied.get("")) is not None:
        new.inline = runs
        new.content = plain_text_from_inline(runs)
    new.language = target
    return new, problems


def _split(runs: list[InlineRun], at: int) -> tuple[list[InlineRun], list[InlineRun]]:
    before: list[InlineRun] = []
    after: list[InlineRun] = []
    position = 0
    for run in runs:
        end = position + len(run.text)
        if end <= at:
            before.append(run)
        elif position >= at:
            after.append(run)
        else:
            before.append(InlineRun(text=run.text[: at - position], marks=run.marks))
            after.append(InlineRun(text=run.text[at - position :], marks=run.marks))
        position = end
    return before, after


class RangeError(ValueError):
    """A selection that isn't text of one paragraph-like block."""


def selected(element: Element, start: int, end: int) -> tuple[Element, list[InlineRun], list[InlineRun]]:
    """The part of a paragraph-like block between `start` and `end` (characters of its text)
    as an element of its own to translate, and the runs before and after it."""
    if element.type in SKIPPED or element.listItems or element.table or element.children or not element.inline:
        raise RangeError("Only text inside one paragraph, heading or caption can be translated as a selection.")
    text = plain_text_from_inline(element.inline)
    if not 0 <= start < end <= len(text):
        raise RangeError("The selection isn't inside the block's text.")
    head, rest = _split(element.inline, start)
    middle, tail = _split(rest, end - start)
    part = element.model_copy(deep=True)
    part.inline = middle
    part.content = plain_text_from_inline(middle)
    return part, head, tail


def joined(element: Element, translated_part: Element, head: list[InlineRun], tail: list[InlineRun]) -> Element:
    new = element.model_copy(deep=True)
    new.inline = [*head, *(translated_part.inline or []), *tail]
    new.content = plain_text_from_inline(new.inline)
    return new


def is_text(element: Element) -> bool:
    return element.type not in SKIPPED and element.type != ElementType.OTHER
