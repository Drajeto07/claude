"""Clean copy (tracker REV-005, brief §59): a new document made from this one with what the person
chose taken out -- each action explicit, none done unless asked:

- removeComments: every comment (the kept comment fragments, DOCX-021);
- acceptTrackedChanges: the tracked changes accepted. A clean copy is written from the document
  itself, never from the original Word file, so it can't keep them: a copy of a document that keeps
  them for Word is refused unless this is chosen (or they are rejected first, DOCX-022A);
- removeHiddenText: every run of hidden text;
- removeMetadata: the Word file's own properties (author, who saved it last, dates, subject,
  keywords, description, category);
- normaliseFormatting: the formatting set on blocks and runs apart from their kind's style -- fonts,
  sizes, colours, alignment set here or kept from the file -- so every block looks as its kind does.
  Bold, italic, underline, links and the like are what the text says, not formatting: they stay.

The original is left as it is. The copy has no original file behind it: its Word export is written
from the document alone, so what only that file held (charts, header pictures, custom properties)
isn't in it, and the summary says so."""

from uuid import uuid4

from app.models.base import ApiModel
from app.models.document import Document, Element, InlineRun, MarkType, plain_text_from_inline, walk_elements


class CleanCopyOptions(ApiModel):
    removeComments: bool = False
    acceptTrackedChanges: bool = False
    removeHiddenText: bool = False
    removeMetadata: bool = False
    normaliseFormatting: bool = False


class CleanCopySummary(ApiModel):
    commentsRemoved: int = 0
    trackedChangesAccepted: bool = False
    hiddenRunsRemoved: int = 0
    metadataRemoved: list[str] = []
    formattingRemoved: int = 0
    # The original had a Word file kept for its exports; the copy doesn't (see the module's note).
    originalFileLeftOut: bool = False


class CleanCopyError(ValueError):
    """What was asked can't make a clean copy: `code` says why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_COMMENT_KINDS = ("comment", "comment_close")
_PROPERTIES = ("author", "lastModifiedBy", "created", "modified", "subject", "keywords", "description", "category")


def _holders(elements: list[Element]):
    """Everything that holds runs or kept fragments: blocks, list items, table cells."""
    for element in walk_elements(elements):
        yield element
        yield from element.listItems or []
        for row in element.table.rows if element.table else []:
            yield from row.cells


def _without_comments(holder) -> int:
    preserved = holder.preservedAttributes
    fragments = preserved.get("ooxml") if isinstance(preserved, dict) else None
    if not isinstance(fragments, list):
        return 0
    kept = [fragment for fragment in fragments if not (isinstance(fragment, dict) and fragment.get("kind") in _COMMENT_KINDS)]
    removed = sum(1 for fragment in fragments if isinstance(fragment, dict) and fragment.get("kind") == "comment")
    if len(kept) != len(fragments):
        holder.preservedAttributes = {**preserved, "ooxml": kept} if kept else {key: value for key, value in preserved.items() if key != "ooxml"} or None
    return removed


def _without_hidden(runs: list[InlineRun] | None) -> tuple[list[InlineRun] | None, int]:
    if not runs:
        return runs, 0
    kept = [run for run in runs if not any(mark.type == MarkType.HIDDEN for mark in run.marks)]
    return kept, len(runs) - len(kept)


def _without_style_marks(runs: list[InlineRun] | None) -> int:
    removed = 0
    for run in runs or []:
        before = len(run.marks)
        run.marks = [mark for mark in run.marks if mark.type != MarkType.TEXT_STYLE]
        removed += before - len(run.marks)
    return removed


def _refreshed(element: Element) -> None:
    """The block's plain text again, after runs went."""
    if element.listItems is not None:
        element.content = "\n".join(plain_text_from_inline(item.inline) for item in element.listItems)
    elif element.table is not None:
        element.content = "\n".join(" | ".join(plain_text_from_inline(cell.inline) for cell in row.cells) for row in element.table.rows)
    elif element.inline is not None:
        element.content = plain_text_from_inline(element.inline)


def clean_copy(document: Document, options: CleanCopyOptions) -> tuple[Document, CleanCopySummary]:
    """The copy -- a new document, the original untouched -- and what was taken out of it."""
    if not any(options.model_dump().values()):
        raise CleanCopyError("nothing_chosen", "Choose what to take out of the clean copy.")
    if document.trackedChanges == "kept" and not options.acceptTrackedChanges:
        raise CleanCopyError(
            "tracked_changes",
            "A clean copy can't keep tracked changes: choose to accept them, or reject them first (Проверка).",
        )
    copy = document.model_copy(deep=True)
    summary = CleanCopySummary(originalFileLeftOut=document.sourcePackage is not None)
    copy.id = str(uuid4())
    copy.revision = None
    copy.metadata.title = f"{document.metadata.title} (clean copy)"[:500]
    copy.proposals = []
    copy.sourcePackage = None
    copy.sourceBlockUse = None
    copy.sourceStyles = None
    copy.importReport = None  # it describes reading the original file, which this copy doesn't have
    copy.unsupportedFeatures = []
    copy.lastSectionEdited = []
    for element in walk_elements(copy.elements):
        element.sourceBlocks = element.sourceHash = None
    if document.trackedChanges is not None:
        summary.trackedChangesAccepted = document.trackedChanges in ("kept", "accepted")
    copy.trackedChanges = None

    holders = list(_holders(copy.elements))
    if options.removeComments:
        summary.commentsRemoved = sum(_without_comments(holder) for holder in holders)
    if options.removeHiddenText or options.normaliseFormatting:
        for holder in holders:
            if options.removeHiddenText:
                holder.inline, removed = _without_hidden(holder.inline)
                summary.hiddenRunsRemoved += removed
            if options.normaliseFormatting:
                summary.formattingRemoved += _without_style_marks(holder.inline)
        for element in walk_elements(copy.elements):
            _refreshed(element)
    if options.removeMetadata and (properties := copy.metadata.sourceProperties) is not None:
        summary.metadataRemoved = [name for name in _PROPERTIES if getattr(properties, name)]
        copy.metadata.sourceProperties = None
    if options.normaliseFormatting:
        ids = {element.id for element in walk_elements(copy.elements)}
        before = len(copy.formattingRules)
        copy.formattingRules = [rule for rule in copy.formattingRules if rule.target not in ids]
        summary.formattingRemoved += before - len(copy.formattingRules)
    return copy, summary
