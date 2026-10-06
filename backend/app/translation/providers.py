"""Translation providers (tracker TRAN-002): one interface, so the engine can be swapped --
the AI (any AIProvider) and a deterministic pseudo-translation for tests and development.
A provider gets segments' tagged text, never the document's structure, and gives back
tagged text by segment id; nothing it says is used before validation.py has checked it.

The AI is told the text is data, never instructions (ai/prompting.py), to keep every tag
and placeholder, every number, unit and identifier, and the glossary's locked terms; to
translate and nothing else -- no explanation, no addition, no omission."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, Field, ValidationError

from app.ai.base import AIProvider, AIRefusalError, AIStructuredOutputError
from app.ai.prompting import UNTRUSTED_DOCUMENT, document_tag, tagged
from app.translation.segments import _TAG, escape
from app.translation.validation import GlossaryEntry

logger = logging.getLogger(__name__)

# What one AI call carries at most: segments and characters.
BATCH_SEGMENTS, BATCH_CHARS = 40, 6000


class TranslationUnavailable(Exception):
    """The provider couldn't translate at all (no key, a refusal, the service down)."""


@dataclass(frozen=True, slots=True)
class SegmentText:
    id: str
    text: str  # tagged


class TranslationProvider(Protocol):
    name: str

    async def translate(self, segments: list[SegmentText], *, source: str | None, target: str, glossary: list[GlossaryEntry]) -> dict[str, str]:
        """Each segment's translation by id (a segment it couldn't translate: left out).
        `source`: the segments' language, None to tell; `target`: always given."""
        ...


# --- the AI ---------------------------------------------------------------------------------------


class AITranslation(BaseModel):
    id: str = Field(max_length=200)
    text: str = Field(max_length=40_000)


class AITranslations(BaseModel):
    translations: list[AITranslation] = Field(max_length=BATCH_SEGMENTS)


_SYSTEM = f"""You translate pieces of a document into another language. You translate and do nothing else.

{UNTRUSTED_DOCUMENT}

Each piece has an id and a text. The text holds tags that carry its formatting: <m1>...</m1> (any number), <x1/>
(any number) and <br/>. Rules:
- Keep every tag, exactly as written and exactly as often. Move a <mN>...</mN> pair with the words it surrounds; never
  add, drop, rename or nest tags. Never put anything in place of an <xN/>: it is text that is not translated.
- Keep every number's digits. You may write a number's decimal and thousands separators, and a date's separators, as
  the target language does, but never change, round, add or drop a number, a date, a percentage, a dose or a unit.
  Write units as the target language writes them (mg may become мг), never as another unit.
- Keep codes and identifiers (ISO-9001, AB-123, v2.1), names of products and people's names as they are.
- Use the glossary's translations for its terms wherever they appear.
- Never add, explain, summarise, correct or leave out anything. Keep &amp;, &lt; and &gt; as they are.
- Answer with one translation per piece, with the piece's id."""


def _batches(segments: list[SegmentText]) -> Iterator[list[SegmentText]]:
    batch: list[SegmentText] = []
    size = 0
    for segment in segments:
        if batch and (len(batch) >= BATCH_SEGMENTS or size + len(segment.text) > BATCH_CHARS):
            yield batch
            batch, size = [], 0
        batch.append(segment)
        size += len(segment.text)
    if batch:
        yield batch


def _glossary_lines(glossary: list[GlossaryEntry]) -> str:
    if not glossary:
        return ""
    lines = "\n".join(f"- {escape(entry.source)} => {escape(entry.target)}" for entry in glossary[:200])
    return f"\nThe glossary (source => target):\n{lines}\n"


class AITranslator:
    """Translation by the AI (any AIProvider)."""

    name = "ai"

    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider

    async def translate(self, segments: list[SegmentText], *, source: str | None, target: str, glossary: list[GlossaryEntry]) -> dict[str, str]:
        results: dict[str, str] = {}
        for batch in _batches(segments):
            tag = document_tag()
            pieces = "\n".join(f'<piece id="{segment.id}">{segment.text}</piece>' for segment in batch)
            prompt = (
                f"Translate each piece {'from ' + source + ' ' if source else ''}into the language whose BCP 47 tag is {target}."
                f"{_glossary_lines(glossary)}\nThe pieces are between <{tag}> and </{tag}>:\n{tagged(tag, pieces)}"
            )
            try:
                answer = await self._provider.complete_structured(prompt, response_model=AITranslations, max_tokens=16_000, system=_SYSTEM)
            except (ValidationError, AIRefusalError, AIStructuredOutputError, APIConnectionError, APITimeoutError, APIStatusError, TypeError) as exc:
                logger.warning("AI translation unavailable: %s", type(exc).__name__)
                raise TranslationUnavailable("The translation service couldn't be reached.") from exc
            known = {segment.id for segment in batch}
            for item in answer.translations:
                if item.id in known and item.id not in results:
                    results[item.id] = item.text
        return results


# --- a deterministic pseudo-translation -----------------------------------------------------------

_PSEUDO = str.maketrans(
    "aeiouAEIOUcnsyzCNSYZ",
    "áéíóúÁÉÍÓÚçñšýžÇÑŠÝŽ",
)


class PseudoTranslator:
    """Every letter of the text outside the tags changed to an accented one, everything else
    kept -- what a translation must keep, kept, so the whole path can be tested and shown
    without an AI. Never a real translation: its target is any language asked for."""

    name = "pseudo"

    async def translate(self, segments: list[SegmentText], *, source: str | None, target: str, glossary: list[GlossaryEntry]) -> dict[str, str]:
        results = {}
        for segment in segments:
            parts, last = [], 0
            for match in _TAG.finditer(segment.text):
                parts.append(self._words(segment.text[last : match.start()], glossary))
                parts.append(match.group())
                last = match.end()
            parts.append(self._words(segment.text[last:], glossary))
            results[segment.id] = "".join(parts)
        return results

    @staticmethod
    def _words(text: str, glossary: list[GlossaryEntry]) -> str:
        for index, entry in enumerate(glossary):
            text = text.replace(entry.source, f"\x00{index}\x00")  # kept from the accents below
        # Entities (&amp;) and codes with digits (ISO-9001) stay as they are.
        out = []
        for word in text.split(" "):
            out.append(word if (word.startswith("&") and word.endswith(";")) or any(ch.isdigit() for ch in word) else word.translate(_PSEUDO))
        text = " ".join(out)
        for index, entry in enumerate(glossary):
            text = text.replace(f"\x00{index}\x00", entry.target)
        return text
