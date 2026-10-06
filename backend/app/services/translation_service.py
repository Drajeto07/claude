"""Translation of a document's blocks as proposals (tracker TRAN-005) and of a whole document as
a translated version of it (TRAN-006), metered by the characters sent (TRAN-009).

Selection -> segments -> translate -> validate -> preview -> accept/reject (brief §47): a
proposal per block, reviewed like any other (formatting/proposals.py), each saying in words
which parts stayed as they were and why. Whole document: the original is never touched -- a
new document is made, linked to it (metadata.translatedFrom), with a report of what wasn't
translated. The provider is called with no lock held; the document is read again to add the
proposals, and a proposal whose block changed meanwhile can't be accepted."""

import base64
from contextlib import nullcontext
from dataclasses import dataclass, field
from uuid import uuid4

from app.billing import units
from app.fidelity.report import FidelityItem, FidelityPolicy, FidelityReport, FidelityStage
from app.models.document import ChangeCategory, Document, Element, ProposedChange, TranslationOrigin, walk_elements
from app.services.document_service import DocumentService
from app.services.entitlements_service import UsageReservations
from app.translation.language import detect, language_name
from app.translation.providers import TranslationProvider
from app.translation.service import LABEL, Translation, collect, document_language, glossary_for, joined, rebuilt, selected, translate


class UnknownBlockError(Exception):
    """A block asked for isn't in the document."""


@dataclass(slots=True)
class TranslationOutcome:
    document: Document
    proposals: int
    source_language: str | None
    characters: int
    # Blocks not proposed, with why: can't be translated yet, or no part of the translation passed.
    not_translated: dict[str, list[str]] = field(default_factory=dict)


def _held(reservations: UsageReservations | None, characters: int):
    return reservations.held(units.TRANSLATION, characters) if reservations is not None and characters else nullcontext()


class TranslationService:
    def __init__(self, documents: DocumentService, reservations: UsageReservations | None = None) -> None:
        self._documents = documents
        self._reservations = reservations

    async def propose(
        self,
        document_id: str,
        *,
        element_ids: list[str],
        target: str,
        source: str | None,
        provider: TranslationProvider,
        selection: tuple[int, int] | None = None,
    ) -> TranslationOutcome | None:
        """Proposals translating the blocks (or, with `selection`, part of one block's text)."""
        document = await self._documents.get(document_id)
        if document is None:
            return None
        by_id = {element.id: element for element in document.elements}
        unknown = [element_id for element_id in element_ids if element_id not in by_id]
        if unknown or not element_ids:
            raise UnknownBlockError("A block to translate isn't in the document.")
        chosen = [element for element in document.elements if element.id in set(element_ids)]
        parts: dict[str, tuple[list, list]] = {}
        if selection is not None:
            part, head, tail = selected(chosen[0], *selection)
            parts[part.id] = (head, tail)
            translation = collect([part])
            originals = {part.id: chosen[0]}
            chosen = [part]
        else:
            translation = collect(chosen)
            originals = {element.id: element for element in chosen}
        source = source or detect(" ".join(element.content for element in chosen)).language or document_language(document)
        outcome = TranslationOutcome(document=document, proposals=0, source_language=source, characters=translation.characters)
        for element_id, why in translation.skipped.items():
            outcome.not_translated[element_id] = [why]
        if not translation.segments:
            return outcome
        async with _held(self._reservations, translation.characters):
            await translate(translation, provider, source=source, target=target, glossary=glossary_for(document, source, target))
        proposals = []
        for element in chosen:
            new, problems = rebuilt(element, translation.segments, target)
            original = originals[element.id]
            if new is None:
                if problems or any(segment.element_id == element.id for segment in translation.segments):
                    outcome.not_translated[element.id] = problems or ["no part of its translation passed the check"]
                continue
            if element.id in parts:
                new = joined(original, new, *parts[element.id])
            proposals.append(
                ProposedChange(
                    type="replace_content",
                    category=ChangeCategory.TRANSLATION,
                    source="translation",
                    elementId=original.id,
                    elementType=original.type,
                    before=original.content[:2000],
                    after=new.content[:10_000],
                    replacement=new,
                    problems=problems[:50],
                    targetLanguage=target,
                    reason=f"Translated into {language_name(target)} by {provider.name}. {LABEL}"[:500],
                )
            )
        if proposals:
            saved = await self._documents.add_translation_proposals(document_id, proposals)
            if saved is None:
                return None
            outcome.document = saved
        outcome.proposals = len(proposals)
        return outcome

    async def translated_version(
        self, document_id: str, *, target: str, source: str | None, provider: TranslationProvider, user_id: str | None = None
    ) -> Document | None:
        """A new document: the original's translation, linked to it, the original untouched."""
        original = await self._documents.get(document_id)
        if original is None:
            return None
        translation = collect(original.elements)
        source = source or document_language(original)
        if translation.segments:
            async with _held(self._reservations, translation.characters):
                await translate(translation, provider, source=source, target=target, glossary=glossary_for(original, source, target))
        version = original.model_copy(deep=True)
        version.id = str(uuid4())
        kept: dict[str, list[str]] = {}
        elements: list[Element] = []
        for element in version.elements:
            new, problems = rebuilt(element, translation.segments, target)
            if problems:
                kept[element.id] = problems
            elements.append(new if new is not None else element)
        version.elements = elements
        await self._copy_pictures(version)
        title = f"{original.metadata.title} ({language_name(target)})"[:500]
        version.metadata = original.metadata.model_copy(
            update={
                "title": title,
                "sourceType": "translation",
                "language": target,
                "translatedFrom": TranslationOrigin(
                    documentId=original.id, revision=original.revision, title=original.metadata.title[:500],
                    sourceLanguage=source, targetLanguage=target, provider=provider.name,
                ),
            }
        )
        version.proposals = []
        version.sourcePackage = None
        version.sourceBlockUse = None
        version.trackedChanges = None
        version.pdfInspection = None
        version.pdfConversion = None
        version.importReport = _report(translation, kept, target)
        return await self._documents.create(version)

    async def _copy_pictures(self, version: Document) -> None:
        """Each stored picture brought along as its bytes, to be stored again as the new
        document's own (an asset belongs to one document)."""
        for element in walk_elements(version.elements):
            if element.image is not None and element.image.assetId:
                found = await self._documents.image_bytes(element.image.assetId)
                if found is not None:
                    content_type, data = found
                    element.image.src = f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"
                    element.image.assetId = None


def _report(translation: Translation, kept: dict[str, list[str]], target: str) -> FidelityReport:
    items = [
        FidelityItem(
            feature="translation.ai_assisted",
            policy=FidelityPolicy.LOSSY,
            reason=f"Translated into {language_name(target)}: {LABEL} Numbers, units, codes and glossary terms were checked; "
            "the meaning wasn't -- read it before you use it.",
            confidence=0.75,
        )
    ]
    if kept:
        samples = "; ".join(problem for problems in list(kept.values())[:3] for problem in problems[:1])
        items.append(
            FidelityItem(
                feature="translation.kept_original",
                policy=FidelityPolicy.LOSSY,
                reason=f"{len(kept)} block{'s' if len(kept) != 1 else ''} kept part of {'their' if len(kept) != 1 else 'its'} original text, "
                f"because its translation didn't pass the check: {samples}"[:1000],
                elementIds=list(kept)[:50],
                count=len(kept),
                contentChanged=True,
            )
        )
    if translation.skipped:
        items.append(
            FidelityItem(
                feature="translation.not_translated",
                policy=FidelityPolicy.UNSUPPORTED,
                reason=f"{len(translation.skipped)} block{'s' if len(translation.skipped) != 1 else ''} weren't translated: "
                + "; ".join(sorted(set(translation.skipped.values()))),
                elementIds=list(translation.skipped)[:50],
                count=len(translation.skipped),
                contentChanged=True,
            )
        )
    return FidelityReport(stage=FidelityStage.TRANSLATION, sourceType="translation", items=items)
