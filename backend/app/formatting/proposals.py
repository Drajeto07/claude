"""AI operations by what they touch (tracker AI-005), and the ones that change
content kept as proposals until the user accepts them (AI-006, brief §19):
PLAN (the AI's operations) -> VALIDATE (validate_operations) -> PREVIEW (a
ProposedChange with the text it removes, moves or adds) -> ACCEPT -> APPLY.
Formatting-only operations -- a style on one element, a page break -- still
apply at once, and are undoable like any change."""

from app.ai.schemas import AIDocumentOperation
from app.formatting.engine import InvalidOperationError, apply_operations, recompute_styles, validate_operations
from app.models.document import ChangeCategory, Document, ElementType, ProposedChange, Revision

_CATEGORY = {
    "set_style": ChangeCategory.FORMAT,
    "add_page_break": ChangeCategory.STRUCTURE,
    "insert_element": ChangeCategory.CONTENT,
    "delete_element": ChangeCategory.CONTENT,
    "move_element": ChangeCategory.CONTENT,
}
_PREVIEW_CHARS = 2000


class UnknownProposalError(Exception):
    def __init__(self, proposal_id: str) -> None:
        super().__init__(f"Unknown proposed change: {proposal_id!r}")


class StaleProposalError(Exception):
    """The document changed so that the proposal no longer fits it."""


class ContentNeedsReviewError(Exception):
    """Changes to the content are accepted one by one, never all at once (brief §58, REV-003)."""


def classify(operation: AIDocumentOperation) -> ChangeCategory:
    return _CATEGORY.get(operation.op, ChangeCategory.CONTENT)  # anything unknown is treated as the riskiest


def split_operations(operations: list[AIDocumentOperation]) -> tuple[list[AIDocumentOperation], list[AIDocumentOperation]]:
    """(apply now, propose): formatting-only operations, and the ones that change content."""
    now = [operation for operation in operations if classify(operation) != ChangeCategory.CONTENT]
    return now, [operation for operation in operations if classify(operation) == ChangeCategory.CONTENT]


def _text_of(document: Document, element_id: str | None) -> str | None:
    element = next((element for element in document.elements if element.id == element_id), None)
    return element.content[:_PREVIEW_CHARS] if element is not None else None


def propose(document: Document, operations: list[AIDocumentOperation], *, reason: str) -> list[ProposedChange]:
    """Adds a proposal per content-changing operation (already validated against
    the document), each with what it would remove, move or add. One that is
    already waiting isn't added twice."""
    added: list[ProposedChange] = []
    for operation in operations:
        proposal = ProposedChange(
            type=operation.op,  # type: ignore[arg-type] -- one of engine.CONTENT_OPERATIONS
            category=classify(operation),
            elementId=operation.element_id if operation.op != "insert_element" else None,
            afterElementId=operation.after_element_id if operation.op != "delete_element" else None,
            elementType=ElementType(operation.element_type) if operation.op == "insert_element" and operation.element_type else None,
            before=_text_of(document, operation.element_id) if operation.op != "insert_element" else None,
            after=(operation.text or "")[:10_000] if operation.op == "insert_element" else None,
            reason=" ".join(reason.split())[:500],
        )
        if any(_same(proposal, waiting) for waiting in [*document.proposals, *added]):
            continue
        added.append(proposal)
    document.proposals.extend(added)
    return added


def _same(one: ProposedChange, other: ProposedChange) -> bool:
    fields = ("type", "elementId", "afterElementId", "elementType", "after")
    return all(getattr(one, field) == getattr(other, field) for field in fields)


def _operation(proposal: ProposedChange) -> AIDocumentOperation:
    return AIDocumentOperation(
        op=proposal.type,
        element_id=proposal.elementId,
        after_element_id=proposal.afterElementId,
        element_type=proposal.elementType.value if proposal.elementType else None,
        text=proposal.after,
    )


def _find(document: Document, proposal_id: str) -> ProposedChange:
    proposal = next((proposal for proposal in document.proposals if proposal.id == proposal_id), None)
    if proposal is None:
        raise UnknownProposalError(proposal_id)
    return proposal


def describe(proposal: ProposedChange) -> str:
    """For the document's history: what was accepted."""
    if proposal.source == "health":
        return f"Health fix accepted: {proposal.reason}"[:300]
    if proposal.type == "replace_content":
        from app.translation.language import language_name

        preview = " ".join((proposal.after or "").split())
        return f"Translated a block into {language_name(proposal.targetLanguage)} (proposal accepted): “{preview[:60]}{'…' if len(preview) > 60 else ''}”"
    what = {"insert_element": "Inserted", "delete_element": "Deleted", "move_element": "Moved"}[proposal.type]
    text = proposal.after if proposal.type == "insert_element" else proposal.before
    kind = proposal.elementType.value if proposal.elementType else "text"
    preview = " ".join((text or "").split())
    return f"{what} {kind if proposal.type == 'insert_element' else 'a block'} (AI proposal accepted): “{preview[:60]}{'…' if len(preview) > 60 else ''}”"


def _replace(document: Document, proposal: ProposedChange) -> None:
    """A translation's block put in place of the block it translated -- only while that block
    is still as it was when the translation was made; its id, place, style and provenance kept."""
    index = next((i for i, element in enumerate(document.elements) if element.id == proposal.elementId), None)
    if index is None or proposal.replacement is None or document.elements[index].content[:_PREVIEW_CHARS] != (proposal.before or ""):
        raise StaleProposalError("The block has changed since it was translated; translate it again.")
    current = document.elements[index]
    keep = ("id", "order", "parentId", "styleRef", "layout", "sourceBlocks", "sourceHash", "preservedAttributes", "confidence", "level")
    document.elements[index] = proposal.replacement.model_copy(deep=True, update={name: getattr(current, name) for name in keep})


def _accept_health_fix(document: Document, proposal: ProposedChange) -> None:
    """A Document Health fix (HLTH-002), only to the block exactly as it was when the fix was
    worked out: the block as fixed in its place, or the block deleted; one undoable step."""
    from app.formatting.health_fixes import element_fingerprint

    index = next((i for i, element in enumerate(document.elements) if element.id == proposal.elementId), None)
    if index is None or element_fingerprint(document.elements[index]) != proposal.elementHash:
        raise StaleProposalError("The block has changed since it was checked; check the document again.")
    if proposal.type == "delete_element":
        apply_operations(document, [_operation(proposal)], description=describe(proposal), accepted=True)
        return
    if proposal.type != "replace_content" or proposal.replacement is None or proposal.replacement.id != proposal.elementId:
        raise StaleProposalError("This fix can't be applied.")
    document.elements[index] = proposal.replacement.model_copy(deep=True, update={"order": document.elements[index].order})
    recompute_styles(document)
    document.revisions.append(Revision(description=describe(proposal)))


def accept(document: Document, proposal_id: str) -> ProposedChange:
    """Applies one proposal, validated against the document as it is now."""
    proposal = _find(document, proposal_id)
    if proposal.source == "health":
        _accept_health_fix(document, proposal)
        document.proposals = [waiting for waiting in document.proposals if waiting.id != proposal_id]
        prune_stale(document)
        return proposal
    if proposal.type == "replace_content":
        _replace(document, proposal)
        document.proposals = [waiting for waiting in document.proposals if waiting.id != proposal_id]
        return proposal
    operation = _operation(proposal)
    try:
        validate_operations(document, [operation])
    except InvalidOperationError as exc:
        raise StaleProposalError("The document has changed since this change was proposed; it no longer fits.") from exc
    apply_operations(document, [operation], description=describe(proposal), accepted=True)
    document.proposals = [waiting for waiting in document.proposals if waiting.id != proposal_id]
    prune_stale(document)  # a proposal about the block just deleted is moot
    return proposal


def changes_text(document: Document, proposal: ProposedChange) -> bool:
    """Whether accepting the proposal would change the document's words: an insert or a move,
    the deletion of a block with words in it, a block put in place with other words. Moving a
    block keeps its words but changes what the text says, so it counts."""
    if proposal.type in ("insert_element", "move_element"):
        return True
    current = next((element for element in document.elements if element.id == proposal.elementId), None)
    if current is None:
        return False  # stale: accepting it fails anyway
    if proposal.type == "delete_element":
        return bool(current.content.split())
    return proposal.replacement is None or proposal.replacement.content.split() != current.content.split()


def accept_category(document: Document, category: ChangeCategory) -> tuple[list[ProposedChange], list[ProposedChange]]:
    """Every waiting proposal of `category` accepted, in order (accepted, skipped). Changes to the
    content are never accepted this way: the CONTENT category is refused, and so is -- skipped --
    any proposal of another category that would change the words, except a translation's, which
    is what the user asked for (TRANSLATION). A proposal that no longer fits is skipped too, and
    stays to be looked at."""
    if category == ChangeCategory.CONTENT:
        raise ContentNeedsReviewError("Changes to the content are accepted one by one.")
    accepted: list[ProposedChange] = []
    skipped: list[ProposedChange] = []
    for proposal in [waiting for waiting in document.proposals if waiting.category == category]:
        if all(waiting.id != proposal.id for waiting in document.proposals):
            continue  # pruned once an earlier one was accepted
        if category != ChangeCategory.TRANSLATION and changes_text(document, proposal):
            skipped.append(proposal)
            continue
        try:
            accept(document, proposal.id)
        except StaleProposalError:
            skipped.append(proposal)
            continue
        accepted.append(proposal)
    return accepted, skipped


def reject(document: Document, proposal_id: str) -> ProposedChange:
    proposal = _find(document, proposal_id)
    document.proposals = [waiting for waiting in document.proposals if waiting.id != proposal_id]
    return proposal


def prune_stale(document: Document) -> None:
    """Drops proposals about elements that are gone -- the user deleted what an
    AI proposed to delete or move, or what an insert was to follow -- and health
    fixes for blocks that have changed since (checking again proposes new ones)."""
    from app.formatting.health_fixes import element_fingerprint

    elements = {element.id: element for element in document.elements}
    document.proposals = [
        proposal
        for proposal in document.proposals
        if (proposal.elementId is None or proposal.elementId in elements)
        and (proposal.afterElementId is None or proposal.afterElementId in elements)
        and (proposal.source != "health" or (proposal.elementId in elements and element_fingerprint(elements[proposal.elementId]) == proposal.elementHash))
    ]
