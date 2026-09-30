import io
import hashlib
import re
from collections import Counter
from collections.abc import Mapping
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, replace

from docx import Document as DocxDocument
from PIL import Image as PILImage
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_UNDERLINE
from docx.image.image import Image as DocxImage
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.oxml.section import CT_SectPr
from docx.shared import Cm, Pt, RGBColor
from docx.text.run import Run

from app.export.images import picture_width_cm, resolve_image_bytes, turned_box
from app.export.provenance import unchanged
from app.fidelity.exports import collecting, note
from app.formatting.list_numbering import LEVEL_INDENT_TWIPS, WORD_LEVELS, Level, list_levels
from app.fidelity.report import FidelityPolicy, ReportBuilder
from app.formatting.colors import NAMED_COLORS
from app.formatting.engine import SOURCE_DOCUMENT_SOURCE
from app.formatting.render_spec import page_size_mm
from app.models.document import (
    COARSE_TARGETS,
    Document,
    DocumentSettings,
    Element,
    ElementType,
    InlineRun,
    ListNumbering,
    Mark,
    MarkType,
    SectionSettings,
    TableContent,
    target_for_element,
)
from app.parsers.docx_comments import COMMENTS_EXTENDED, COMMENTS_EXTENDED_TYPE, PARA_ID, W15, comment_paragraphs, comment_threads, related_part
from app.security.files import parse_xml_part

_ALIGNMENT_MAP = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}

_STYLE_FOR_TYPE = {
    ElementType.QUOTE: "Quote",
    ElementType.CAPTION: "Caption",
    ElementType.FOOTNOTE: "Footnote Text",
}

# The Word styles each kind of block is written with (корекции.docx §24: native
# Word semantics, not inline CSS on every run). Each is set explicitly from that
# kind's resolved style, so changing "Heading 1" in Word restyles every heading,
# and nothing of python-docx's own template (blue Calibri Light headings, 10 pt
# after every paragraph) leaks into the file. Styles the template lacks are added.
_WORD_STYLES: dict[str, tuple[str, ...]] = {
    "Paragraph": ("Normal",),
    **{f"Heading {level}": (f"Heading {level}",) for level in range(1, 7)},
    "Quote": ("Quote",),
    "Caption": ("Caption",),
    "Footnote": ("Footnote Text",),
    "List": ("List Bullet", "List Number", "List Paragraph"),
    "Table": ("Table Text",),
    "CodeBlock": ("Code",),
}
_LIST_STYLES = ("List Bullet", "List Number", "List Paragraph")
# The children of w:pPr in schema order, for inserting ones python-docx has no API for.
_P_PR_ORDER = (
    "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs "
    "suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd "
    "snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment "
    "textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange"
).split()
_AFTER_SHADING = tuple(qn(f"w:{name}") for name in _P_PR_ORDER[_P_PR_ORDER.index("shd") + 1 :])
_AFTER_CONTEXTUAL_SPACING = tuple(qn(f"w:{name}") for name in _P_PR_ORDER[_P_PR_ORDER.index("contextualSpacing") + 1 :])

# Background colours Word can show as a real highlight; any other becomes run shading.
_WORD_HIGHLIGHTS = {
    "FFFF00": "yellow",
    "00FF00": "green",
    "00FFFF": "cyan",
    "FF00FF": "magenta",
    "0000FF": "blue",
    "FF0000": "red",
    "000080": "darkBlue",
    "008080": "darkCyan",
    "008000": "darkGreen",
    "800080": "darkMagenta",
    "800000": "darkRed",
    "808000": "darkYellow",
    "808080": "darkGray",
    "C0C0C0": "lightGray",
    "000000": "black",
}

_PAGE_FIELD = re.compile(r"(\{PAGE\}|\{NUMPAGES\})")


def build_docx(
    document: Document,
    *,
    assets: Mapping[str, bytes] | None = None,
    source: bytes | None = None,
    include_headers: bool = True,
    include_page_numbers: bool = True,
    include_page_breaks: bool = True,
    report: ReportBuilder | None = None,
) -> bytes:
    """Real, editable .docx (spec §7.17) built from the same resolved styles
    the editor already renders -- no separate style computation. Independent
    of pdf_export.py's reportlab-based builder (LibreOffice isn't available
    on this machine to convert one into the other -- see the Phase 6 plan);
    both read the same document.resolvedStyles, so there's nothing to keep
    in sync beyond that shared source of truth.

    The three include_* flags are export-time-only overrides (spec's export
    options screen) -- they never touch the persisted document.settings, so
    exporting once without page numbers doesn't turn them off for next time.
    All default True, matching this function's behavior before these flags
    existed. With page numbers left out, header/footer text built around a
    page-number field ({PAGE}, {NUMPAGES}) is left out too.

    `source`: the Word file the document was imported from (SourcePackage).
    The content is then written into it -- its body replaced, everything else
    kept: styles (rewritten only where the document's look was changed),
    numbering, headers and footers of every kind (rewritten only where their
    text was changed), footnotes, custom properties, theme, settings (DOCX-011).

    `report` collects what this export approximates or leaves out (app/fidelity)."""
    with collecting(report):
        return _build_docx(document, assets or {}, source, include_headers, include_page_numbers, include_page_breaks)


def _build_docx(
    document: Document,
    assets: Mapping[str, bytes],
    source: bytes | None,
    include_headers: bool,
    include_page_numbers: bool,
    include_page_breaks: bool,
) -> bytes:
    emptied = _emptied(source) if source is not None else None
    docx_document, originals, threads = emptied if emptied is not None else (None, [], {})
    if source is not None and docx_document is None:
        note(
            "export.docx.source_unreadable",
            FidelityPolicy.LOSSY,
            "The original Word file couldn't be opened, so this export was built without it: its styles, headers and "
            "footers and properties aren't kept.",
        )
    into_source = docx_document is not None
    if docx_document is None:
        docx_document = DocxDocument()
    _set_properties(docx_document, document)
    zoom = docx_document.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")  # required by the schema; python-docx's template leaves it out
    _define_styles(docx_document, document, keep_unchanged=into_source)
    links = {rel_id: rel.target_ref for rel_id, rel in docx_document.part.rels.items() if rel.reltype == RELATIONSHIP_TYPE.HYPERLINK}
    plan, rewritten, after = _copy_plan(document, originals, include_page_breaks=include_page_breaks, links=links) if into_source else (None, [], {})
    token = _RESERVED_BOOKMARKS.set(_bookmark_ids(originals))
    regions = _BALANCED_REGIONS.set(_balanced_regions(document))
    written_comments: dict[str, dict] = {}
    comments = _WRITTEN_COMMENTS.set(written_comments)
    open_comments = _OPEN_COMMENTS.set({})
    starts = "nextPage"  # how the section being written started: the break before it says (DOCX-015)
    written_sections: list[tuple[object, SectionSettings]] = []  # the sections written from their breaks
    try:
        for element in document.elements:
            action = plan.get(element.id) if plan is not None else None
            if action is not None:
                if action:  # the first element of a group copied as it is: its children, once
                    _copy_children(docx_document, [originals[index] for index in action], include_headers=include_headers)
            elif element.type == ElementType.PAGE_BREAK and not include_page_breaks:
                continue
            elif element.type == ElementType.SECTION_BREAK:
                sect_pr = _add_section_break(docx_document, element, starts=starts, include_page_breaks=include_page_breaks)
                written_sections.append((sect_pr, element.sectionBreak or SectionSettings()))
            else:
                _add_element(_Place(docx_document, owner=element.id), element, document, assets)
                if plan is not None:  # written anew into the original: its drawings go back with it (DOCX-019)
                    _put_back_drawings(docx_document, element, originals)
            if element.id in after:  # the drawings in paragraphs of their own after it, as they were
                _copy_children(docx_document, [originals[index] for index in after[element.id]], include_headers=include_headers)
                for index in after[element.id]:
                    originals[index].set(_PUT_BACK, "1")
            if element.type == ElementType.SECTION_BREAK and element.sectionBreak is not None:
                starts = element.sectionBreak.start if include_page_breaks else "continuous"
    finally:
        _RESERVED_BOOKMARKS.reset(token)
        _BALANCED_REGIONS.reset(regions)
        _WRITTEN_COMMENTS.reset(comments)
        _OPEN_COMMENTS.reset(open_comments)
    if not into_source or plan is not None and _written_anew(document, plan):
        _set_start(docx_document.sections[-1]._sectPr, starts)
    # After the body: the earlier sections copied from the original are in it, and
    # take what the page setup, header or footer changed here (DOCX-028).
    _apply_page_setup(
        docx_document, document, include_headers=include_headers, include_page_numbers=include_page_numbers, into_source=into_source
    )
    _section_headers(docx_document, written_sections, include_headers=include_headers, include_page_numbers=include_page_numbers)
    if not into_source:  # the last section's first-page and even-page ones, its numbering, and whether even pages have their own
        # Its main header and footer are DocumentSettings' (written above); lastSection's are "" for own empty ones.
        last = (document.lastSection or SectionSettings()).model_copy(update={key: None for key in ("header", "footer") if getattr(document.settings, key)})
        _section_headers(docx_document, [(docx_document.sections[-1]._sectPr, last)], include_headers=include_headers, include_page_numbers=include_page_numbers)
        _page_numbering(docx_document.sections[-1]._sectPr, document.lastSection)
        _section_layout(docx_document.sections[-1], document.lastSection)
        docx_document.settings.odd_and_even_pages_header_footer = document.evenAndOddHeaders
    _define_comment_styles(docx_document)
    _unique_drawing_ids(docx_document)
    if into_source:
        _drop_unused_comments(docx_document)
    _thread_comments(docx_document, written_comments, threads)
    if into_source:
        _drop_unused_relationships(docx_document)
        if plan and any(plan.values()):
            note(
                "export.docx.original_blocks",
                FidelityPolicy.DETECTED_PRESERVED,
                "Blocks the document didn't change were written as they are in the original file, with their fields, "
                "content controls and formatting.",
            )
        if losses := _rewritten_losses(originals, rewritten, docx_document.part.related_parts):
            blocks, kinds = losses
            note(
                "export.docx.rewritten_blocks",
                FidelityPolicy.LOSSY,
                f"{blocks} {'block' if blocks == 1 else 'blocks'} changed or restyled here {'was' if blocks == 1 else 'were'} "
                f"written anew, without what the app doesn't hold in {'it' if blocks == 1 else 'them'}: {', '.join(kinds)}.",
                count=blocks,
            )
        if lost := _lost_sections(originals, plan, document):
            note(
                "export.docx.section_lost",
                FidelityPolicy.LOSSY,
                "A section ended in a paragraph that was changed or restyled here, so its own page setup, headers and "
                "footers weren't kept: its pages follow the section after it.",
                count=lost,
            )
        note(
            "export.docx.source_package",
            FidelityPolicy.DETECTED_PRESERVED,
            "Written into the original Word file: its styles, headers and footers of every kind, footnotes, properties "
            "and theme are kept.",
        )

    buffer = io.BytesIO()
    docx_document.save(buffer)
    return buffer.getvalue()


# Word's own styles for comments (python-docx refers to them without defining them).
_COMMENT_STYLES = (
    ("CommentReference", "annotation reference", WD_STYLE_TYPE.CHARACTER, '<w:rPr><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr>'),
    ("CommentText", "annotation text", WD_STYLE_TYPE.PARAGRAPH, '<w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr>'),
)


def _define_comment_styles(docx_document: DocxDocument) -> None:
    """When the file has comments, the styles their references and text use."""
    if docx_document.element.body.find(f".//{qn('w:commentReference')}") is None:
        return
    ids = {style.style_id for style in docx_document.styles}
    for style_id, name, kind, properties in _COMMENT_STYLES:
        if style_id in ids:
            continue
        kind_name = "character" if kind == WD_STYLE_TYPE.CHARACTER else "paragraph"
        docx_document.styles.element.append(
            parse_xml(
                f'<w:style {nsdecls("w")} w:type="{kind_name}" w:styleId="{style_id}"><w:name w:val="{name}"/>'
                f'<w:basedOn w:val="{"DefaultParagraphFont" if kind == WD_STYLE_TYPE.CHARACTER else "Normal"}"/>'
                f"<w:uiPriority w:val=\"99\"/><w:semiHidden/><w:unhideWhenUsed/>{properties}</w:style>"
            )
        )
        if kind == WD_STYLE_TYPE.CHARACTER and "DefaultParagraphFont" not in ids:
            docx_document.styles.element[-1].remove(docx_document.styles.element[-1].find(qn("w:basedOn")))


# -- writing into the original Word file (DOCX-011) --------------------------------

_COMMENT_EXTRAS = frozenset(
    {
        "http://schemas.microsoft.com/office/2011/relationships/commentsExtended",
        "http://schemas.microsoft.com/office/2016/09/relationships/commentsIds",
        "http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible",
    }
)
# What the body refers to by relationship id: once the body is rewritten, the old
# body's pictures, links, objects and charts are left out of the file.
_BODY_RELATIONSHIPS = frozenset(
    {
        RELATIONSHIP_TYPE.IMAGE,
        RELATIONSHIP_TYPE.HYPERLINK,
        RELATIONSHIP_TYPE.OLE_OBJECT,
        RELATIONSHIP_TYPE.PACKAGE,
        RELATIONSHIP_TYPE.CHART,
        RELATIONSHIP_TYPE.DIAGRAM_DATA,
        RELATIONSHIP_TYPE.DIAGRAM_LAYOUT,
        RELATIONSHIP_TYPE.DIAGRAM_QUICK_STYLE,
        RELATIONSHIP_TYPE.DIAGRAM_COLORS,
        RELATIONSHIP_TYPE.CONTROL,
        "http://schemas.microsoft.com/office/2007/relationships/diagramDrawing",
        "http://schemas.microsoft.com/office/2007/relationships/hdphoto",
    }
)
_R_NAMESPACE = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _emptied(source: bytes) -> "tuple[DocxDocument, list, dict[str, tuple[str | None, bool]]] | None":
    """The original Word file with its body emptied -- the last section's
    properties (page setup, header and footer references, columns) kept -- and
    the body's children as they were, for copying the unchanged ones (DOCX-028).
    Its comments stay until the body is written: those no copied block refers
    to go then (_drop_unused_comments). Their threads, as the original has them,
    come with it: its parts saying so are written again for the comments the
    export has (_thread_comments, DOCX-021). None when it can't be opened."""
    try:
        docx_document = DocxDocument(io.BytesIO(source))
    except Exception:  # noqa: BLE001 -- any unreadable package: the export is built without it, and says so
        return None
    body = docx_document.element.body
    originals = [child for child in body if child.tag != qn("w:sectPr")]
    for child in originals:
        body.remove(child)
    part = docx_document.part
    try:
        threads = comment_threads(part)
    except Exception:  # noqa: BLE001 -- unreadable threads: the comments are written without them
        threads = {}
    for rel_id, rel in list(part.rels.items()):
        if rel.reltype in _COMMENT_EXTRAS:
            del part.rels[rel_id]  # they name comments by paragraphs some of which won't be in the file
    return docx_document, originals, threads


# The comments written anew, by the id each was given: the id it had in the file, the
# one it answers there and whether it is resolved, as the import kept them (DOCX-021).
_WRITTEN_COMMENTS: ContextVar[dict[str, dict] | None] = ContextVar("written_comments", default=None)
_MC_NAMESPACE = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_FIRST_PARA_ID = 0x10000000  # Word's paraIds are 8 hex digits below 0x80000000


def _para_ids(docx_document: DocxDocument) -> set[str]:
    """Every paraId the package's Word parts use: a new one mustn't be any of them."""
    taken = set()
    for part in docx_document.part.package.iter_parts():
        if hasattr(part, "element"):
            root = part.element
        elif part.content_type.endswith("+xml") and "wordprocessingml" in part.content_type:
            try:
                root = parse_xml_part(part.blob)
            except Exception:  # noqa: BLE001 -- a part that isn't XML names no paragraphs
                continue
        else:
            continue
        taken.update(node.get(PARA_ID) for node in root.iter() if isinstance(node.tag, str) and node.get(PARA_ID))
    return taken


def _thread_comments(docx_document: DocxDocument, written: dict[str, dict], original: dict[str, tuple[str | None, bool]]) -> None:
    """Which comment answers which and which are resolved, back into the file (DOCX-021):
    commentsExtended written for the comments the file has now -- one copied from the
    original with what the original says of it (`original`, by its id), one written anew
    with what the import kept (`written`, by the id it was given), each naming the
    comment it answers by the id that one has now. Nothing is written when no comment
    answers another or is resolved: comments.xml says all there is."""
    comments_part = related_part(docx_document.part, RELATIONSHIP_TYPE.COMMENTS)
    if comments_part is None or not hasattr(comments_part, "element"):
        return
    ids = [comment.get(qn("w:id")) for comment in comments_part.element.iter(qn("w:comment")) if comment.get(qn("w:id")) is not None]
    now = {comment_id: comment_id for comment_id in ids if comment_id not in written}  # copied: the id it had
    now |= {info["commentId"]: new for new, info in written.items() if info.get("commentId") and new in ids}
    threads = {}
    for comment_id in ids:
        if comment_id in written:
            reply_to, done = written[comment_id].get("replyTo"), bool(written[comment_id].get("done"))
        else:
            reply_to, done = original.get(comment_id, (None, False))
        parent = now.get(reply_to) if reply_to else None
        threads[comment_id] = (parent if parent != comment_id else None, done)
    if not any(parent or done for parent, done in threads.values()):
        return
    paragraphs = comment_paragraphs(comments_part.element)
    taken, next_id = _para_ids(docx_document), _FIRST_PARA_ID
    for comment in comments_part.element.iter(qn("w:comment")):
        last = comment.findall(qn("w:p"))[-1:]
        if last and comment.get(qn("w:id")) not in paragraphs:  # one without (written anew): given one, as Word would
            while f"{next_id:08X}" in taken:
                next_id += 1
            taken.add(f"{next_id:08X}")
            last[0].set(PARA_ID, f"{next_id:08X}")
            paragraphs[comment.get(qn("w:id"))] = f"{next_id:08X}"
    entries = "".join(
        f'<w15:commentEx w15:paraId="{paragraphs[comment_id]}"'
        + (f' w15:paraIdParent="{paragraphs[parent]}"' if parent in paragraphs else "")
        + f' w15:done="{int(done)}"/>'
        for comment_id, (parent, done) in threads.items()
        if comment_id in paragraphs
    )
    names = {str(part.partname) for part in docx_document.part.package.iter_parts()}
    name = next(name for name in (f"/word/commentsExtended{n or ''}.xml" for n in range(100)) if name not in names)
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w15:commentsEx xmlns:mc="{_MC_NAMESPACE}" xmlns:w15="{W15}" mc:Ignorable="w15">{entries}</w15:commentsEx>'
    )
    extended = Part(PackURI(name), COMMENTS_EXTENDED_TYPE, xml.encode("utf-8"), docx_document.part.package)
    docx_document.part.relate_to(extended, COMMENTS_EXTENDED)


# -- copying unchanged blocks (DOCX-028) ----------------------------------------------

_TRACKED_CHANGES = frozenset(
    qn(f"w:{name}")
    for name in ("ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange", "sectPrChange", "tblPrChange", "trPrChange", "tcPrChange", "tblGridChange", "numberingChange")
)
# Footnote references would be written twice (the import moved the notes' text to the end); an altChunk or
# a sub-document points at content the document never read.
_NOT_COPIED = frozenset((qn("w:footnoteReference"), qn("w:endnoteReference"), qn("w:altChunk"), qn("w:subDoc")))
_RESERVED_BOOKMARKS: ContextVar[frozenset[int]] = ContextVar("reserved_bookmarks", default=frozenset())


def _region_fragments(element: Element) -> list[dict]:
    return [
        f
        for f in (element.preservedAttributes or {}).get("ooxml") or []
        if isinstance(f, dict) and (f.get("kind") in _REGION_KINDS or f.get("kind") == "comment" and "region" in f)
    ]


def _balanced_regions(document: Document) -> frozenset[str]:
    """The fields and comments running across paragraphs whose start comes before their
    end, each once, among the document's blocks (DOCX-020, DOCX-021). A field whose start
    or end was deleted with its paragraph is written as its text, a comment on the text of
    the paragraph it begins in; the export says so."""
    opened: set[str] = set()
    balanced: set[str] = set()
    times: Counter[tuple[bool, str]] = Counter()
    comments: set[str] = set()
    for element in document.elements:
        for fragment in _region_fragments(element):
            region = fragment.get("region")
            if not isinstance(region, str):
                continue
            starts = fragment["kind"] in _REGION_STARTS
            times[(starts, region)] += 1
            if fragment["kind"] in ("comment", "comment_close"):
                comments.add(region)
            if starts:
                opened.add(region)
            elif region in opened:
                balanced.add(region)
    kept = frozenset(region for region in balanced if times[(True, region)] == times[(False, region)] == 1)
    lost = {region for _, region in times} - kept
    if lost & comments:
        note(
            "export.docx.comment_range",
            FidelityPolicy.LOSSY,
            "A comment running across paragraphs lost the paragraph it ends in here, so it covers the text of the "
            "paragraph it begins in.",
        )
    if lost - comments:
        note(
            "export.docx.field_region",
            FidelityPolicy.LOSSY,
            "A table of contents or another field running across paragraphs lost its first or last paragraph here, so it "
            "was written as its text.",
        )
    return kept


def _bookmark_ids(children: list) -> frozenset[int]:
    return frozenset(
        int(mark.get(qn("w:id"))) for child in children for mark in child.iter(qn("w:bookmarkStart")) if (mark.get(qn("w:id")) or "").isdigit()
    )


def _self_contained(children: list) -> bool:
    """XML that can be copied on its own: no tracked changes or note references,
    and every field, bookmark and comment range that starts in it ends in it."""
    fields = 0
    marks: Counter[tuple[str, str | None]] = Counter()
    for child in children:
        for node in child.iter():
            tag = node.tag
            if tag in _TRACKED_CHANGES or tag in _NOT_COPIED:
                return False
            if tag == qn("w:fldChar"):
                kind = node.get(qn("w:fldCharType"))
                fields += 1 if kind == "begin" else -1 if kind == "end" else 0
            elif tag in (qn("w:bookmarkStart"), qn("w:commentRangeStart")):
                marks[(tag, node.get(qn("w:id")))] += 1
            elif tag == qn("w:bookmarkEnd"):
                marks[(qn("w:bookmarkStart"), node.get(qn("w:id")))] -= 1
            elif tag == qn("w:commentRangeEnd"):
                marks[(qn("w:commentRangeStart"), node.get(qn("w:id")))] -= 1
    return fields == 0 and not any(marks.values())


def _copy_plan(
    document: Document, originals: list, *, include_page_breaks: bool, links: Mapping[str, str] | None = None
) -> tuple[dict[str, list[int]], list[list[int]], dict[str, list[int]]]:
    """Which elements are written as their original XML. Elements and the body
    children they came from form groups (a list and its items, a paragraph and its
    picture, a content control and its blocks); a group is copied when every one
    of its elements is unchanged -- in what it holds and how it looks
    (app/export/provenance.py) -- in its original
    order, and its XML is self-contained. Children no element came from (empty
    spacing paragraphs, a chart the import left out) go with the group before
    them. A group whose links aren't safe to keep (parsers/docx_inline.py
    safe_href) is written anew, without them. The answer maps each copied element
    to the children to write in its place -- the group's first element gets them,
    the others nothing -- lists the children of each group written anew, and maps
    the last element of each such group to the paragraphs of its children holding
    nothing but drawings a Word export puts back (DOCX-019), to write after it."""
    elements = document.elements
    count = len(originals)
    parent = list(range(len(elements)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owner: dict[int, int] = {}
    invalid: set[int] = set()
    for position, element in enumerate(elements):
        for child in element.sourceBlocks or []:
            if not 0 <= child < count:
                invalid.add(position)
            elif child in owner:
                parent[root(position)] = root(owner[child])
            else:
                owner[child] = position
    starts: dict[str, int] = {}
    for position, element in enumerate(elements):
        for fragment in _region_fragments(element):
            if fragment["kind"] in _REGION_STARTS:
                starts[fragment.get("region")] = position
            elif (first := starts.pop(fragment.get("region"), None)) is not None and elements[first].sourceBlocks:
                for between in range(first + 1, position + 1):  # a table of contents' entries, a comment's paragraphs
                    if elements[between].sourceBlocks:
                        parent[root(between)] = root(first)
    groups: dict[int, list[int]] = {}
    for position, element in enumerate(elements):
        if element.sourceBlocks:
            groups.setdefault(root(position), []).append(position)
    children: dict[int, set[int]] = {group: {child for p in members for child in elements[p].sourceBlocks or [] if 0 <= child < count} for group, members in groups.items()}
    covered = sorted(owner)
    for child in range(count):
        if child in owner or not covered:
            continue
        neighbour = max((index for index in covered if index < child), default=covered[0])
        children[root(owner[neighbour])].add(child)

    plan: dict[str, list[int]] = {}
    rewritten: list[list[int]] = []
    after: dict[str, list[int]] = {}
    for group, members in groups.items():
        taken = sorted(children[group])
        first_sources = [min(elements[p].sourceBlocks or [0]) for p in members]
        if (
            invalid.intersection(members)
            or not all(unchanged(document, elements[p]) for p in members)
            or members != list(range(members[0], members[0] + len(members)))  # together, where the document has them
            or first_sources != sorted(first_sources)  # in their original order
            or taken != list(range(taken[0], taken[-1] + 1))
            or (not include_page_breaks and any(elements[p].type in (ElementType.PAGE_BREAK, ElementType.SECTION_BREAK) for p in members))
            or not _self_contained([originals[child] for child in taken])
            or not _safe_links([originals[child] for child in taken], links or {})
        ):
            rewritten.append(taken)
            if drawings := [child for child in taken if child not in owner and _drawings_only(originals[child])]:
                after[elements[members[-1]].id] = drawings
            continue
        plan[elements[members[0]].id] = taken
        for position in members[1:]:
            plan[elements[position].id] = []
    return plan, rewritten, after


_HYPERLINK_FIELD = re.compile(r'^\s*HYPERLINK\s+(?!\\l)"?([^"\s]+)', re.IGNORECASE)


def _safe_links(children: list, links: Mapping[str, str]) -> bool:
    """Every link in the XML goes where the app lets a link go: web, mail, phone
    (the importer made the others plain text; a copy mustn't bring them back)."""
    from app.parsers.docx_inline import safe_href

    for child in children:
        for link in child.iter(qn("w:hyperlink")):
            rel_id = link.get(qn("r:id"))
            if rel_id and safe_href(links.get(rel_id)) is None:
                return False
        codes = [node.text or "" for node in child.iter(qn("w:instrText"))]
        codes += [node.get(qn("w:instr"), "") for node in child.iter(qn("w:fldSimple"))]
        for code in codes:
            match = _HYPERLINK_FIELD.match(code)
            if match and safe_href(match.group(1)) is None:
                return False
    return True


_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_PICTURE_URI = "http://schemas.openxmlformats.org/drawingml/2006/picture"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_VML_IMAGE = "{urn:schemas-microsoft-com:vml}imagedata"
# What a block written anew leaves behind, in the order the export report names it.
_LOSS_ORDER = (
    "content controls",
    "text boxes",
    "charts, shapes and SmartArt",
    "embedded objects",
    "drop caps",
    "empty spacing paragraphs",
    "underline styles",
    "stretched text",
    "text effects",
    "right-to-left runs",
    "proofing exclusions",
    "pictures in sections' headers and footers",
    "page borders",
    "line numbering",
    "vertical alignment on the page",
)


def _number(value: str | None) -> float:
    try:
        return float((value or "0").rstrip("%"))
    except ValueError:
        return 0.0


def _lost_in(child, related=None) -> set[str]:
    """What the model doesn't hold in this original block (FID-007): the import
    report says a Word export keeps it while the block is unchanged. What went back
    into a block written anew (DOCX-019) isn't lost, nor what the model holds now:
    a picture's crop, turn and floating position (DOCX-018)."""
    from app.fidelity.docx_detect import _APPROXIMATED_UNDERLINES, effects_of, scale_of

    if child.get(_PUT_BACK):
        return set()
    lost: set[str] = set()
    # Elements themselves, not id()s: lxml's stand-ins for a node live only while referenced.
    skipped = {node for part in child.iter() if isinstance(part.tag, str) and (part.tag == _MC_FALLBACK or part.get(_PUT_BACK)) for node in part.iter()}
    for node in child.iter():
        if node in skipped or not isinstance(node.tag, str):
            continue
        tag = node.tag
        if tag == qn("w:sdt"):
            lost.add("content controls")
        elif tag == qn("w:txbxContent"):
            lost.add("text boxes")
        elif tag == qn("w:object"):
            lost.add("embedded objects")
        elif tag == f"{_A}graphicData" and node.get("uri") != _PICTURE_URI and node.find(f".//{_TEXT_BOX}") is None:
            lost.add("charts, shapes and SmartArt")  # a shape with text is a text box, named as one
        elif tag == qn("w:pict") and node.find(f".//{_VML_IMAGE}") is None and node.find(f".//{_TEXT_BOX}") is None:
            lost.add("charts, shapes and SmartArt")
        elif tag == qn("w:framePr") and node.get(qn("w:dropCap")) in ("drop", "margin"):
            lost.add("drop caps")
        elif tag == qn("w:sectPr"):
            for reference in [*node.findall(qn("w:headerReference")), *node.findall(qn("w:footerReference"))]:
                part = (related or {}).get(reference.get(qn("r:id")))
                root = getattr(part, "element", None)
                if root is not None and (root.find(f".//{qn('w:drawing')}") is not None or root.find(f".//{qn('w:pict')}") is not None):
                    lost.add("pictures in sections' headers and footers")
            if node.find(qn("w:pgBorders")) is not None:
                lost.add("page borders")
            if node.find(qn("w:lnNumType")) is not None:
                lost.add("line numbering")
            if (align := node.find(qn("w:vAlign"))) is not None and align.get(qn("w:val"), "top") != "top":
                lost.add("vertical alignment on the page")
        elif tag == qn("w:rPr") and node.getparent() is not None and node.getparent().tag == qn("w:r"):
            underline = node.find(qn("w:u"))
            if underline is not None and underline.get(qn("w:val")) in _APPROXIMATED_UNDERLINES:
                lost.add("underline styles")
            if scale_of(node) not in (None, 100):
                lost.add("stretched text")
            if effects_of(node):
                lost.add("text effects")
            if (rtl := node.find(qn("w:rtl"))) is not None and rtl.get(qn("w:val"), "true") not in ("0", "false", "off"):
                lost.add("right-to-left runs")
            if (proof := node.find(qn("w:noProof"))) is not None and proof.get(qn("w:val"), "true") not in ("0", "false", "off"):
                lost.add("proofing exclusions")
    if child.tag == qn("w:p") and not "".join(t.text or "" for t in child.iter(qn("w:t"))).strip():
        has_content = any(True for tag in ("w:drawing", "w:pict", "w:object") for _ in child.iter(qn(tag)))
        if not has_content and child.find(f"{qn('w:pPr')}/{qn('w:sectPr')}") is None:
            lost.add("empty spacing paragraphs")
    return lost


def _rewritten_losses(originals: list, rewritten: list[list[int]], related=None) -> tuple[int, list[str]] | None:
    """How many groups written anew lost something the model doesn't hold, and what."""
    blocks, kinds = 0, set()
    for children in rewritten:
        lost = set().union(*(_lost_in(originals[index], related) for index in children)) if children else set()
        if lost:
            blocks += 1
            kinds |= lost
    return (blocks, [kind for kind in _LOSS_ORDER if kind in kinds]) if blocks else None



# -- drawings a block written anew keeps (DOCX-019) ------------------------------------

_PUT_BACK = "{urn:smartdoc:export}put-back"  # on an original put back in a block written anew (in memory only)
_DRAWING_PARTS = (qn("w:drawing"), qn("w:pict"), qn("w:object"))
_TEXT_BOX = qn("w:txbxContent")
# The kinds of element written as one paragraph, where their paragraph's drawings go back.
_ONE_PARAGRAPH = (ElementType.PARAGRAPH, ElementType.HEADING, ElementType.CAPTION, ElementType.QUOTE)


def _kept_drawing(run) -> bool:
    """A run holding what the model doesn't hold and a Word export puts back as it
    was: a chart, SmartArt, a shape, an embedded object, a VML drawing -- not a
    picture (the model has it) nor a text box (its text is the document's own)."""
    if run.tag != qn("w:r") or run.find(f".//{_TEXT_BOX}") is not None:
        return False
    fallback = {node for part in run.iter(_MC_FALLBACK) for node in part.iter()}
    for node in run.iter(*_DRAWING_PARTS):
        if node in fallback:
            continue
        if node.tag == qn("w:drawing"):
            data = next(node.iter(f"{_A}graphicData"), None)
            return data is not None and data.get("uri") != _PICTURE_URI
        return True
    return False


def _drawing_runs(paragraph) -> list[tuple[int, object]]:
    """The runs of an original paragraph a Word export puts back, each with how much
    of the paragraph's text comes before it."""
    found, offset = [], 0
    for run in paragraph.iter(qn("w:r")):
        if any(ancestor.tag in _DRAWING_PARTS for ancestor in run.iterancestors()):
            continue  # a run inside a shape of its own
        if _kept_drawing(run):
            found.append((offset, run))
        offset += sum(len(text.text or "") for text in run.iter(qn("w:t")))
    return found


def _drawings_only(child) -> bool:
    """An original paragraph holding nothing but drawings a Word export puts back."""
    if child.tag != qn("w:p") or "".join(text.text or "" for text in child.iter(qn("w:t"))).strip():
        return False
    return child.find(f".//{_TEXT_BOX}") is None and bool(_drawing_runs(child))


def _insert_at(paragraph, run, offset: int) -> None:
    """`run` into `paragraph` where `offset` characters of its text come before it --
    splitting the run of text it falls in, when that is one piece of text."""
    seen = 0
    for child in list(paragraph):
        if child.tag not in (qn("w:r"), qn("w:hyperlink")):
            continue
        texts = list(child.iter(qn("w:t")))
        length = sum(len(text.text or "") for text in texts)
        if seen >= offset:
            child.addprevious(run)
            return
        if seen + length > offset:
            if child.tag == qn("w:r") and len(texts) == 1:
                cut, tail = offset - seen, deepcopy(child)
                head_text, tail_text = texts[0], tail.find(qn("w:t"))
                head_text.text, tail_text.text = head_text.text[:cut], head_text.text[cut:]
                for piece in (head_text, tail_text):
                    piece.set(qn("xml:space"), "preserve")
                child.addnext(tail)
            child.addnext(run)  # a run that can't be split: right after it
            return
        seen += length
    paragraph.append(run)


def _put_back_drawings(docx_document: DocxDocument, element: Element, originals: list) -> None:
    """The charts, SmartArt, shapes and embedded objects of the original paragraph an
    element written anew came from, back in the paragraph written for it, where they
    were in its text (DOCX-019). They come from the kept original file, the server's
    own copy -- nothing the browser sent."""
    if element.type not in _ONE_PARAGRAPH or element.children:
        return
    written = next((child for child in reversed(docx_document.element.body) if child.tag == qn("w:p")), None)
    if written is None:
        return
    for index in element.sourceBlocks or []:
        if not 0 <= index < len(originals) or originals[index].tag != qn("w:p"):
            continue
        for offset, run in _drawing_runs(originals[index]):
            if run.get(_PUT_BACK):
                continue  # another element of the same paragraph took it
            _insert_at(written, deepcopy(run), offset)
            run.set(_PUT_BACK, "1")


def _unique_drawing_ids(docx_document: DocxDocument) -> None:
    """Each drawing's id once: Word repairs a file that has one twice, and drawings
    copied from the original keep theirs beside the ones written anew."""
    nodes = list(docx_document.element.body.iter(qn("wp:docPr")))
    top = max((int(node.get("id")) for node in nodes if (node.get("id") or "").isdigit()), default=0)
    seen: set[str | None] = set()
    for node in nodes:
        if node.get("id") in seen:
            top += 1
            node.set("id", str(top))
        seen.add(node.get("id"))


def _copy_children(docx_document: DocxDocument, children: list, *, include_headers: bool) -> None:
    body = docx_document.element.body
    for child in children:
        copied = deepcopy(child)
        if not include_headers:  # an earlier section's own header and footer references
            for reference in [*copied.iter(qn("w:headerReference")), *copied.iter(qn("w:footerReference"))]:
                reference.getparent().remove(reference)
        body.insert(len(body) - 1 if body[-1].tag == qn("w:sectPr") else len(body), copied)


def _ends_section(child) -> bool:
    return child.tag == qn("w:p") and child.find(f"{qn('w:pPr')}/{qn('w:sectPr')}") is not None


def _lost_sections(originals: list, plan: dict[str, list[int]] | None, document: Document | None = None) -> int:
    """Earlier sections that are gone: their ending paragraph wasn't copied, and no
    section break of the document's comes from it (it was deleted). One written
    anew from its section break is still there (DOCX-015)."""
    if plan is None:
        return 0
    written = {index for children in plan.values() for index in children}
    breaks = {
        child
        for element in (document.elements if document is not None else [])
        if element.type == ElementType.SECTION_BREAK
        for child in element.sourceBlocks or []
    }
    return sum(1 for index, child in enumerate(originals) if index not in written and index not in breaks and _ends_section(child))


def _written_anew(document: Document, plan: dict[str, list[int]]) -> bool:
    """Whether any section break was written from the model rather than copied."""
    return any(element.type == ElementType.SECTION_BREAK and element.id not in plan for element in document.elements)


_SECTION_TYPES = {
    "nextPage": WD_SECTION.NEW_PAGE,
    "continuous": WD_SECTION.CONTINUOUS,
    "evenPage": WD_SECTION.EVEN_PAGE,
    "oddPage": WD_SECTION.ODD_PAGE,
}


def _set_start(sect_pr, start: str) -> None:
    """How a section starts: its sectPr's w:type, where the schema puts it (none: the next page)."""
    sect_pr.start_type = _SECTION_TYPES.get(start, WD_SECTION.NEW_PAGE)


def _add_section_break(docx_document: DocxDocument, element: Element, *, starts: str, include_page_breaks: bool) -> CT_SectPr:
    """The end of a section: a paragraph holding its sectPr, written from the
    section break's settings (DOCX-015). The pages above it are that section's."""
    settings = element.sectionBreak or SectionSettings()
    body = docx_document.element.body
    paragraph = OxmlElement("w:p")
    properties = OxmlElement("w:pPr")
    paragraph.append(properties)
    sect_pr = OxmlElement("w:sectPr")
    properties.append(sect_pr)
    _set_start(sect_pr, starts if include_page_breaks else "continuous")
    template = docx_document.sections[-1]  # the document's own page setup, where the section has none of its own
    width = settings.pageWidthMm if settings.pageWidthMm else template.page_width.mm
    height = settings.pageHeightMm if settings.pageHeightMm else template.page_height.mm
    landscape = (settings.orientation or ("landscape" if width > height else "portrait")) == "landscape"
    size = OxmlElement("w:pgSz")
    size.set(qn("w:w"), str(round(width * 56.6929)))
    size.set(qn("w:h"), str(round(height * 56.6929)))
    if landscape:
        size.set(qn("w:orient"), "landscape")
    sect_pr.append(size)
    margins = OxmlElement("w:pgMar")
    for name, value, fallback in (
        ("top", settings.marginTopCm, template.top_margin),
        ("right", settings.marginRightCm, template.right_margin),
        ("bottom", settings.marginBottomCm, template.bottom_margin),
        ("left", settings.marginLeftCm, template.left_margin),
        ("header", settings.headerDistanceCm, template.header_distance),
        ("footer", settings.footerDistanceCm, template.footer_distance),
    ):
        twips = round(value * 566.929) if value is not None else (fallback.twips if fallback is not None else 720)
        margins.set(qn(f"w:{name}"), str(twips))
    margins.set(qn("w:gutter"), "0")
    sect_pr.append(margins)
    _page_numbering(sect_pr, settings)
    columns = OxmlElement("w:cols")
    if settings.columns and settings.columns > 1:
        columns.set(qn("w:num"), str(settings.columns))
    columns.set(qn("w:space"), str(round((settings.columnSpacingCm if settings.columnSpacingCm is not None else 1.25) * 566.929)))
    sect_pr.append(columns)
    body.insert(len(body) - 1 if body[-1].tag == qn("w:sectPr") else len(body), paragraph)
    return sect_pr


# What follows w:pgNumType in a sectPr, in the schema's order.
_AFTER_PAGE_NUMBERING = (
    "w:cols",
    "w:formProt",
    "w:vAlign",
    "w:noEndnote",
    "w:titlePg",
    "w:textDirection",
    "w:bidi",
    "w:rtlGutter",
    "w:docGrid",
    "w:printerSettings",
    "w:sectPrChange",
)


def _page_numbering(sect_pr: CT_SectPr, settings: SectionSettings | None) -> None:
    """A section's page numbering, where its settings have one: the number it restarts
    at and its style (DOCX-015)."""
    if settings is None or (settings.pageNumberStart is None and not settings.pageNumberFormat):
        return
    numbering = sect_pr.find(qn("w:pgNumType"))
    if numbering is None:
        numbering = OxmlElement("w:pgNumType")
        sect_pr.insert_element_before(numbering, *_AFTER_PAGE_NUMBERING)
    if settings.pageNumberFormat:
        numbering.set(qn("w:fmt"), settings.pageNumberFormat)
    if settings.pageNumberStart is not None:
        numbering.set(qn("w:start"), str(settings.pageNumberStart))


def _section_layout(section, settings: SectionSettings | None) -> None:
    """The last section's own columns and header and footer distances
    (Document.lastSection, DOCX-015), over the defaults a fresh file has."""
    if settings is None:
        return
    if settings.headerDistanceCm is not None:
        section.header_distance = Cm(settings.headerDistanceCm)
    if settings.footerDistanceCm is not None:
        section.footer_distance = Cm(settings.footerDistanceCm)
    if (settings.columns or 1) > 1 or settings.columnSpacingCm is not None:
        sect_pr = section._sectPr
        columns = sect_pr.find(qn("w:cols"))
        if columns is None:
            columns = OxmlElement("w:cols")
            sect_pr.insert_element_before(columns, *_AFTER_PAGE_NUMBERING[1:])
        if (settings.columns or 1) > 1:
            columns.set(qn("w:num"), str(settings.columns))
        if settings.columnSpacingCm is not None:
            columns.set(qn("w:space"), str(round(settings.columnSpacingCm * 566.929)))


_HEADER_PARTS = (
    ("header", "header"),
    ("footer", "footer"),
    ("firstHeader", "first_page_header"),
    ("firstFooter", "first_page_footer"),
    ("evenHeader", "even_page_header"),
    ("evenFooter", "even_page_footer"),
)


def _section_headers(docx_document: DocxDocument, sections: list, *, include_headers: bool, include_page_numbers: bool) -> None:
    """Each section's own headers and footers, as its settings have them (DOCX-015):
    one it has none of (None) stays linked to the previous section's; one with page
    numbers, with page numbers left out, is its own empty one."""
    if not include_headers:
        return
    from docx.section import Section

    for sect_pr, settings in sections:
        section = Section(sect_pr, docx_document.part)
        for key, name in _HEADER_PARTS:
            text = getattr(settings, key)
            if text is None:
                continue
            if not include_page_numbers and _PAGE_FIELD.search(text):
                text = ""
            part = getattr(section, name)
            part.is_linked_to_previous = False
            for block in list(part._element):
                part._element.remove(block)
            paragraph = part.add_paragraph()
            if text:
                _write_page_text(paragraph, text)
        if settings.differentFirstPage:
            section.different_first_page_header_footer = True


def _drop_unused_comments(docx_document: DocxDocument) -> None:
    """Comments nothing in the written body refers to any more."""
    body = docx_document.element.body
    used = {node.get(qn("w:id")) for tag in ("w:commentReference", "w:commentRangeStart") for node in body.iter(qn(tag))}
    for rel in docx_document.part.rels.values():
        if rel.reltype == RELATIONSHIP_TYPE.COMMENTS and hasattr(rel.target_part, "element"):
            comments = rel.target_part.element
            for comment in list(comments):
                if comment.get(qn("w:id")) not in used:
                    comments.remove(comment)


_DIAGRAM_DRAWING = "{http://schemas.microsoft.com/office/drawing/2008/diagram}dataModelExt"


def _drop_unused_relationships(docx_document: DocxDocument) -> None:
    part = docx_document.part
    used = {value for node in part.element.iter() for name, value in node.attrib.items() if name.startswith(_R_NAMESPACE)}
    # A SmartArt's data part names its drawing by one of the document's own relationships.
    for rel_id in list(used):
        rel = part.rels.get(rel_id)
        if rel is not None and not rel.is_external and rel.reltype == RELATIONSHIP_TYPE.DIAGRAM_DATA:
            data = parse_xml(rel.target_part.blob)
            used.update(node.get("relId") for node in data.iter(_DIAGRAM_DRAWING) if node.get("relId"))
    for rel_id, rel in list(part.rels.items()):
        if rel.reltype in _BODY_RELATIONSHIPS and rel_id not in used:
            del part.rels[rel_id]


def _restyled(document: Document) -> set[str]:
    """The kinds of block whose look a template, an instruction or a person set:
    their Word styles are written; the others keep the original file's."""
    return {
        rule.target
        for rule in document.formattingRules
        if rule.target in COARSE_TARGETS and rule.source not in ("default", SOURCE_DOCUMENT_SOURCE)
    }


def _set_properties(docx_document: DocxDocument, document: Document) -> None:
    """The document's own properties -- the source file's, when it came from
    Word -- instead of python-docx's template's ("python-docx", 2013)."""
    metadata = document.metadata
    source = metadata.sourceProperties
    properties = docx_document.core_properties
    # A Word file's own title -- none, often -- while the document keeps the title it was
    # given at import (one made from its first heading or its name); a new name once renamed.
    kept = source is not None and source.title is not None and metadata.title == source.importedTitle
    properties.title = source.title if kept else metadata.title
    properties.author = (source.author if source else None) or ""
    properties.last_modified_by = (source.lastModifiedBy if source else None) or ""
    properties.created = (source.created if source and source.created else None) or metadata.createdAt
    properties.modified = metadata.updatedAt
    properties.subject = (source.subject if source else None) or ""
    properties.keywords = (source.keywords if source else None) or ""
    properties.comments = (source.description if source else None) or ""
    properties.category = (source.category if source else None) or ""


def _page_dimensions_mm(settings: DocumentSettings) -> tuple[float, float]:
    return page_size_mm(settings.pageSize, settings.orientation)


_TEMPLATE: list[DocxDocument] = []


def _template_style(docx_document: DocxDocument, name: str):
    """A built-in style the file lacks (Word files define only the styles they
    use), copied from python-docx's template so it keeps its look -- a table
    grid its borders -- without references to styles or numbering the file
    doesn't have. None when the template lacks it too."""
    if not _TEMPLATE:
        _TEMPLATE.append(DocxDocument())
    try:
        element = deepcopy(_TEMPLATE[0].styles[name].element)
    except KeyError:
        return None
    ids = {style.style_id for style in docx_document.styles}
    for tag in ("w:basedOn", "w:next", "w:link"):
        reference = element.find(qn(tag))
        if reference is not None and reference.get(qn("w:val")) not in ids:
            element.remove(reference)
    for num_pr in list(element.iter(qn("w:numPr"))):
        num_pr.getparent().remove(num_pr)
    docx_document.styles.element.append(element)
    return docx_document.styles[name]


def _word_style(docx_document: DocxDocument, name: str, kind: WD_STYLE_TYPE = WD_STYLE_TYPE.PARAGRAPH):
    try:
        return docx_document.styles[name]
    except KeyError:
        copied = _template_style(docx_document, name)
        if copied is not None:
            return copied
        style = docx_document.styles.add_style(name, kind)
        if kind == WD_STYLE_TYPE.PARAGRAPH:
            style.base_style = docx_document.styles["Normal"]
            style.quick_style = True
        return style


def _set_style(style, css: dict[str, str]) -> None:
    """Everything the renderers show for this kind of block, set on its Word
    style; whatever the resolved style leaves out gets the neutral value the
    editor and the PDF use (left, regular, single spacing, no space)."""
    font = style.font
    family = (css.get("font-family") or "").strip('"')
    if family:
        font.name = family
        r_fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        r_fonts.set(qn("w:cs"), family)
        for theme in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            r_fonts.attrib.pop(qn(theme), None)  # a theme font wins over the name in Word
    if css.get("font-size", "").endswith("pt"):
        font.size = Pt(_parse_pt(css["font-size"]))
    font.bold = css.get("font-weight") == "bold"
    font.italic = css.get("font-style") == "italic"
    font.underline = css.get("text-decoration") == "underline"
    color = _parse_color(css.get("color") or "")
    r_pr = style.element.get_or_add_rPr()
    for old in r_pr.findall(qn("w:color")):
        r_pr.remove(old)  # the template's theme colours included
    if color is not None:
        font.color.rgb = color

    paragraph_format = style.paragraph_format
    paragraph_format.alignment = _ALIGNMENT_MAP.get(css.get("text-align", ""), WD_ALIGN_PARAGRAPH.LEFT)
    line_height = css.get("--line-spacing") or css.get("line-height", "")  # Word's own value
    try:
        paragraph_format.line_spacing = Pt(_parse_pt(line_height)) if line_height.endswith("pt") else float(line_height or 1)
    except ValueError:
        paragraph_format.line_spacing = 1.0
    paragraph_format.space_before = Pt(_parse_pt(css.get("margin-top", "0pt")))
    paragraph_format.space_after = Pt(_parse_pt(css.get("margin-bottom", "0pt")))
    margin_left, text_indent = css.get("margin-left", ""), css.get("text-indent", "")
    paragraph_format.left_indent = Cm(_parse_cm(margin_left)) if margin_left.endswith("cm") else Cm(0)
    paragraph_format.first_line_indent = Cm(_parse_cm(text_indent)) if text_indent.endswith("cm") else Cm(0)
    _apply_paragraph_extras(paragraph_format, style.element.get_or_add_pPr(), css)


def _contextual_spacing(style) -> None:
    """No space between paragraphs of this style, only after the last one --
    how list items sit together in the editor and the PDF."""
    p_pr = style.element.get_or_add_pPr()
    if p_pr.find(qn("w:contextualSpacing")) is not None:
        return
    element = OxmlElement("w:contextualSpacing")
    successor = next((child for child in p_pr if child.tag in _AFTER_CONTEXTUAL_SPACING), None)
    if successor is not None:
        successor.addprevious(element)
    else:
        p_pr.append(element)


def _has_style(docx_document: DocxDocument, name: str) -> bool:
    try:
        docx_document.styles[name]
    except KeyError:
        return False
    return True


def _define_styles(docx_document: DocxDocument, document: Document, *, keep_unchanged: bool = False) -> None:
    """`keep_unchanged`: writing into the original Word file -- a style its
    document's look didn't change stays as the file has it."""
    restyled = _restyled(document) if keep_unchanged else None
    if restyled is not None and "Paragraph" in restyled:
        # Every kind's Word style is based on Normal: a new Normal would restyle them all in
        # Word, so each gets the look it has here written out (TEST-022).
        restyled = set(_WORD_STYLES)
    for target, names in _WORD_STYLES.items():
        css = document.resolvedStyles.get(target, {})
        if target == "Table":  # cell text: the space after belongs to the table, not to each cell
            css = {key: value for key, value in css.items() if key not in ("margin-top", "margin-bottom")}
        for name in names:
            existed = _has_style(docx_document, name)
            style = _word_style(docx_document, name)
            if restyled is not None and existed and target not in restyled:
                continue
            _set_style(style, css)
            if name in _LIST_STYLES:
                _contextual_spacing(style)
    hyperlink_existed = _has_style(docx_document, "Hyperlink")
    code = docx_document.styles["Code"]
    p_pr = code.element.get_or_add_pPr()
    if p_pr.find(qn("w:shd")) is None:
        shading = parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="F0F0F0"/>')
        successor = next((child for child in p_pr if child.tag in _AFTER_SHADING), None)
        if successor is not None:
            successor.addprevious(shading)
        else:
            p_pr.append(shading)
    hyperlink = _word_style(docx_document, "Hyperlink", WD_STYLE_TYPE.CHARACTER)
    if restyled is None or not hyperlink_existed:
        hyperlink.font.color.rgb = RGBColor(0x05, 0x63, 0xC1)
        hyperlink.font.underline = True


def _own_css(element: Element, document: Document) -> dict[str, str]:
    """What this element sets differently from its kind's style: the only
    formatting it carries itself, the rest comes from its Word style."""
    if not element.styleRef or element.styleRef == target_for_element(element):
        return {}
    kind = document.resolvedStyles.get(target_for_element(element), {})
    return {key: value for key, value in _resolved_css(element, document).items() if kind.get(key) != value}


def _set_length(section, name: str, value, *, keep_close: bool) -> bool:
    """Sets a page length; writing into the original file, one within 0.02 cm of
    the file's own is left as the file has it (the app's values are rounded).
    Whether it was set."""
    current = getattr(section, name)
    if keep_close and current is not None and abs(current - value) <= Cm(0.02):
        return False
    setattr(section, name, value)
    return True


_MARGINS = ("top_margin", "bottom_margin", "left_margin", "right_margin")


def _earlier_sections_follow(docx_document: DocxDocument, changed: set[str]) -> None:
    """The app has one page setup, read from the original's last section: what
    was changed here applies to the earlier sections the export keeps too
    (DOCX-028). Each keeps its orientation unless that is what changed -- a
    landscape section's page stays turned to a new paper size."""
    sections = list(docx_document.sections)
    last = sections[-1]
    for section in sections[:-1]:
        if "orientation" in changed:
            section.orientation = last.orientation
        if changed & {"orientation", "page_width", "page_height"}:
            turned = (section.orientation == WD_ORIENT.LANDSCAPE) != (last.orientation == WD_ORIENT.LANDSCAPE)
            section.page_width, section.page_height = (last.page_height, last.page_width) if turned else (last.page_width, last.page_height)
        for name in _MARGINS:
            if name in changed:
                setattr(section, name, getattr(last, name))


def _apply_page_setup(
    docx_document: DocxDocument, document: Document, *, include_headers: bool, include_page_numbers: bool, into_source: bool = False
) -> None:
    settings = document.settings
    section = docx_document.sections[-1]
    width_mm, height_mm = _page_dimensions_mm(settings)
    orientation = WD_ORIENT.LANDSCAPE if settings.orientation == "landscape" else WD_ORIENT.PORTRAIT
    changed: set[str] = set()
    if not into_source or section.orientation != orientation:
        section.orientation = orientation
        changed.add("orientation")
    for name, value in (
        ("page_width", Cm(width_mm / 10)),
        ("page_height", Cm(height_mm / 10)),
        ("top_margin", Cm(settings.marginTopCm)),
        ("bottom_margin", Cm(settings.marginBottomCm)),
        ("left_margin", Cm(settings.marginLeftCm)),
        ("right_margin", Cm(settings.marginRightCm)),
    ):
        if _set_length(section, name, value, keep_close=into_source):
            changed.add(name)
    if into_source:
        _earlier_sections_follow(docx_document, changed)
        _source_headers_and_footers(
            docx_document, section, settings, document.lastSection, include_headers=include_headers, include_page_numbers=include_page_numbers
        )
        return

    header = _page_text(settings.header, include_headers, include_page_numbers)
    footer = _page_text(settings.footer, include_headers, include_page_numbers)
    if header:
        section.header.is_linked_to_previous = False  # its own, not the earlier section's it would inherit (DOCX-015)
        _write_page_text(section.header.paragraphs[0], header)
    if footer:
        section.footer.is_linked_to_previous = False
        _write_page_text(section.footer.paragraphs[0], footer)
    if include_page_numbers and settings.showPageNumbers:
        page_number_paragraph = section.footer.add_paragraph() if footer else section.footer.paragraphs[0]
        page_number_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _append_field(page_number_paragraph, "PAGE")


def _source_headers_and_footers(
    docx_document, section, settings: DocumentSettings, last: SectionSettings | None, *, include_headers: bool, include_page_numbers: bool
) -> None:
    """The original file's headers and footers -- first-page, even-page, pictures,
    fields, earlier sections' -- are kept; the last section's main one is rewritten
    only when the document's differs from the file's (it was changed here, or a
    template set it). The document's is that section's own (DOCX-015): a text, one
    left empty ("" in Document.lastSection), or none, which shows the previous
    section's (Word's link to previous). A text for a section that showed the
    previous one's becomes its own, so the earlier sections keep theirs, as the
    pages here and a PDF show them."""
    sect_pr = section._sectPr
    if not include_headers:
        for reference in [*sect_pr.findall(qn("w:headerReference")), *sect_pr.findall(qn("w:footerReference"))]:
            sect_pr.remove(reference)
        return
    from app.parsers.docx_styles import section_texts  # the importer's reading of them, to compare with

    if not include_page_numbers:
        _drop_page_numbers(docx_document)
    before = section_texts(docx_document, sect_pr)  # its own ones only: none is the previous section's
    for kind in ("header", "footer"):
        now = getattr(settings, kind)
        if now is None and last is not None:
            now = getattr(last, kind)
        if not include_page_numbers and _PAGE_FIELD.search(now or ""):
            now = ""  # left out whole, as in a PDF
        if now == before.get(kind):
            continue
        target = section.header if kind == "header" else section.footer
        if now is None:
            target.is_linked_to_previous = True
            continue
        target.is_linked_to_previous = False  # a part of its own, where it showed the previous section's
        for block in list(target._element):
            target._element.remove(block)
        paragraph = target.add_paragraph()
        if now:
            _write_page_text(paragraph, now)
    if include_page_numbers and settings.showPageNumbers:
        for each in docx_document.sections:  # asked for here: on every section's pages, as the app shows them
            footer_part = each.footer  # its own, or the one it shows from the section before
            if not _shows_page_numbers(footer_part._element):
                page_number_paragraph = footer_part.add_paragraph()
                page_number_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _append_field(page_number_paragraph, "PAGE")


def _shows_page_numbers(root) -> bool:
    from app.parsers.docx_styles import field_aware_text, part_paragraphs

    return "{PAGE}" in field_aware_text(part_paragraphs(root))


def _drop_page_numbers(docx_document: DocxDocument) -> None:
    """Page numbers left out: every section's headers and footers that show them
    -- first-page and even-page ones too -- are, whole, as in a PDF. Each stays its
    section's own, empty: none would show the previous section's (DOCX-015)."""
    from app.parsers.docx_styles import field_aware_text, part_paragraphs

    related = docx_document.part.related_parts
    for each in docx_document.sections:
        sect_pr = each._sectPr
        for reference in [*sect_pr.findall(qn("w:headerReference")), *sect_pr.findall(qn("w:footerReference"))]:
            part = related.get(reference.get(qn("r:id")))
            root = getattr(part, "element", None)
            if root is not None and _PAGE_FIELD.search(field_aware_text(part_paragraphs(root))):
                for block in list(root):
                    root.remove(block)
                root.append(OxmlElement("w:p"))


def _page_text(text: str | None, include_headers: bool, include_page_numbers: bool) -> str | None:
    if not include_headers or not text:
        return None
    if not include_page_numbers and _PAGE_FIELD.search(text):
        return None
    return text


def _write_page_text(paragraph, text: str) -> None:
    """Header/footer text, with {PAGE}/{NUMPAGES} written as the Word fields."""
    for part in _PAGE_FIELD.split(text):
        if part == "{PAGE}":
            _append_field(paragraph, "PAGE")
        elif part == "{NUMPAGES}":
            _append_field(paragraph, "NUMPAGES")
        elif part:
            paragraph.add_run(part)


def _append_field(paragraph, instruction: str) -> None:
    """python-docx has no high-level API for field codes -- raw XML, as for
    hyperlinks below."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def _content_width_cm(document: Document) -> float:
    width_mm, _ = _page_dimensions_mm(document.settings)
    return width_mm / 10 - document.settings.marginLeftCm - document.settings.marginRightCm


def _resolved_css(element: Element, document: Document) -> dict[str, str]:
    if not element.styleRef:
        return {}
    return document.resolvedStyles.get(element.styleRef, {})


def _parse_pt(value: str) -> float:
    try:
        return float(value.replace("pt", "").strip())
    except ValueError:
        return 0.0


def _parse_cm(value: str) -> float:
    try:
        return float(value.replace("cm", "").strip())
    except ValueError:
        return 0.0


def _hex6(value: str | None) -> str | None:
    """#rgb/#rrggbb/named colour as RRGGBB, or None."""
    if not value:
        return None
    value = value.strip().lower()
    if value.startswith("#"):
        hex_value = value.lstrip("#")
        if len(hex_value) == 3:
            hex_value = "".join(ch * 2 for ch in hex_value)
        return hex_value.upper() if re.fullmatch(r"[0-9a-f]{6}", hex_value) else None
    return NAMED_COLORS.get(value)


def _parse_color(value: str) -> RGBColor | None:
    hex_value = _hex6(value)
    return RGBColor.from_string(hex_value) if hex_value else None


def _apply_run_css(run, css: dict[str, str]) -> None:
    font_family = css.get("font-family")
    if font_family:
        run.font.name = font_family.strip('"')
    font_size = css.get("font-size")
    if font_size:
        run.font.size = Pt(_parse_pt(font_size))
    color = css.get("color")
    if color:
        rgb = _parse_color(color)
        if rgb is not None:
            run.font.color.rgb = rgb
    # An element's own "normal"/"none" undoes what its style sets.
    if css.get("font-weight"):
        run.font.bold = css["font-weight"] == "bold"
    if css.get("font-style"):
        run.font.italic = css["font-style"] == "italic"
    if css.get("text-decoration"):
        run.font.underline = css["text-decoration"] == "underline"


_WORD_UNDERLINES = {
    None: True,
    "double": WD_UNDERLINE.DOUBLE,
    "thick": WD_UNDERLINE.THICK,
    "dotted": WD_UNDERLINE.DOTTED,
    "dashed": WD_UNDERLINE.DASH,
    "wavy": WD_UNDERLINE.WAVY,
}
# The order of a w:rPr's children (ECMA-376 CT_RPr): Word refuses them out of order.
_RPR_ORDER = tuple(
    qn(f"w:{name}")
    for name in (
        "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline", "shadow", "emboss",
        "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing", "w", "kern", "position", "sz", "szCs",
        "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
        "specVanish", "oMath",
    )
)


def _put_in_rpr(run, tag: str, **attributes: str) -> None:
    """Sets a w:rPr child python-docx has no property for, where the schema puts it."""
    r_pr = run._r.get_or_add_rPr()
    for existing in r_pr.findall(qn(tag)):
        r_pr.remove(existing)
    element = OxmlElement(tag)
    for name, value in attributes.items():
        element.set(qn(f"w:{name}"), value)
    later = _RPR_ORDER[_RPR_ORDER.index(qn(tag)) + 1 :]
    following = next((child for child in r_pr if child.tag in later), None)
    if following is None:
        r_pr.append(element)
    else:
        following.addprevious(element)


def _apply_text_style(run, mark: Mark) -> None:
    """A textStyle mark on this run: its values win over the element's CSS."""
    if mark.fontFamily:
        run.font.name = mark.fontFamily
    if mark.fontSizePt:
        run.font.size = Pt(mark.fontSizePt)
    if (rgb := _parse_color(mark.color or "")) is not None:
        run.font.color.rgb = rgb
    background = _hex6(mark.backgroundColor)
    if background:
        if background in _WORD_HIGHLIGHTS:
            _put_in_rpr(run, "w:highlight", val=_WORD_HIGHLIGHTS[background])
        else:
            _put_in_rpr(run, "w:shd", val="clear", color="auto", fill=background)
    if mark.caps:
        run.font.all_caps = True
    elif mark.smallCaps:
        run.font.small_caps = True
    if mark.letterSpacingPt:
        _put_in_rpr(run, "w:spacing", val=str(round(mark.letterSpacingPt * 20)))
    if mark.baselineShiftPt:
        _put_in_rpr(run, "w:position", val=str(round(mark.baselineShiftPt * 2)))
    if mark.lang:
        _put_in_rpr(run, "w:lang", val=mark.lang)


def _apply_paragraph_css(paragraph, css: dict[str, str]) -> None:
    alignment = _ALIGNMENT_MAP.get(css.get("text-align", ""))
    if alignment is not None:
        paragraph.alignment = alignment
    line_height = css.get("--line-spacing") or css.get("line-height")  # Word's own value
    if line_height:
        try:
            # "12pt" is an exact line height; a plain number is a multiple.
            paragraph.paragraph_format.line_spacing = Pt(_parse_pt(line_height)) if line_height.endswith("pt") else float(line_height)
        except ValueError:
            pass
    margin_top = css.get("margin-top")
    if margin_top:
        paragraph.paragraph_format.space_before = Pt(_parse_pt(margin_top))
    margin_bottom = css.get("margin-bottom")
    if margin_bottom:
        paragraph.paragraph_format.space_after = Pt(_parse_pt(margin_bottom))
    margin_left = css.get("margin-left")
    if margin_left and margin_left.endswith("cm"):
        paragraph.paragraph_format.left_indent = Cm(_parse_cm(margin_left))
    text_indent = css.get("text-indent")
    if text_indent:
        paragraph.paragraph_format.first_line_indent = Cm(_parse_cm(text_indent))
    _apply_paragraph_extras(paragraph.paragraph_format, paragraph._p.get_or_add_pPr(), css)


def _put_in_ppr(p_pr, tag: str, element=None, **attributes: str) -> None:
    """Sets a w:pPr child python-docx has no property for, where the schema puts it."""
    for existing in p_pr.findall(qn(tag)):
        p_pr.remove(existing)
    if element is None:
        element = OxmlElement(tag)
    for name, value in attributes.items():
        element.set(qn(f"w:{name}"), value)
    name = tag.split(":", 1)[1]
    later = {qn(f"w:{following}") for following in _P_PR_ORDER[_P_PR_ORDER.index(name) + 1 :]}
    successor = next((child for child in p_pr if child.tag in later), None)
    if successor is None:
        p_pr.append(element)
    else:
        successor.addprevious(element)


def _apply_paragraph_extras(paragraph_format, p_pr, css: dict[str, str]) -> None:
    """Paragraph formatting beyond spacing and indents (DOCX-014), where the CSS
    says it: the right indent, Word's pagination controls, a background colour,
    the writing direction and contextual spacing."""
    margin_right = css.get("margin-right", "")
    if margin_right.endswith("cm"):
        paragraph_format.right_indent = Cm(_parse_cm(margin_right))
    if "break-after" in css:
        paragraph_format.keep_with_next = css["break-after"] == "avoid"
    if "break-inside" in css:
        paragraph_format.keep_together = css["break-inside"] == "avoid"
    if "widows" in css:
        paragraph_format.widow_control = css["widows"] != "1"
    if fill := _hex6(css.get("background-color")):
        _put_in_ppr(p_pr, "w:shd", val="clear", color="auto", fill=fill)
    if css.get("direction") in ("ltr", "rtl"):
        _put_in_ppr(p_pr, "w:bidi", val="1" if css["direction"] == "rtl" else "0")
    if "--contextual-spacing" in css:
        _put_in_ppr(p_pr, "w:contextualSpacing", val="1" if css["--contextual-spacing"] == "true" else "0")
    sides = [(side, css[f"border-{side}"]) for side in ("top", "left", "bottom", "right") if f"border-{side}" in css]
    if sides:
        _put_in_ppr(p_pr, "w:pBdr", _paragraph_borders(sides))
    if stops := css.get("--tab-stops"):
        _put_in_ppr(p_pr, "w:tabs", _tab_stops(stops))


_WORD_BORDERS = {"solid": "single", "double": "double", "dotted": "dotted", "dashed": "dashed"}
_TAB_STOP = re.compile(r"(\w+) ([\d.]+)cm(?: (\w+))?")


def _paragraph_borders(sides: list[tuple[str, str]]):
    """w:pBdr from border rules ("solid 0.5pt #000000", "none"), sides in schema order."""
    borders = OxmlElement("w:pBdr")
    for side, value in sides:
        element = OxmlElement(f"w:{side}")
        if value == "none":
            element.set(qn("w:val"), "nil")
        else:
            style, width, color = value.split(" ")
            element.set(qn("w:val"), _WORD_BORDERS.get(style, "single"))
            element.set(qn("w:sz"), str(max(2, min(96, round(float(width.removesuffix("pt")) * 8)))))
            element.set(qn("w:space"), "1")
            element.set(qn("w:color"), _hex6(color) or "000000")
        borders.append(element)
    return borders


def _tab_stops(value: str):
    """w:tabs from a tab stops rule ("right 16cm dot; left 2cm")."""
    tabs = OxmlElement("w:tabs")
    for stop in value.split(";"):
        match = _TAB_STOP.fullmatch(stop.strip())
        if not match:
            continue
        tab = OxmlElement("w:tab")
        tab.set(qn("w:val"), match.group(1))
        if match.group(3):
            tab.set(qn("w:leader"), match.group(3))
        tab.set(qn("w:pos"), str(round(float(match.group(2)) * 567)))
        tabs.append(tab)
    return tabs


def _add_hyperlink_run(paragraph, text: str, url: str, title: str | None = None) -> Run:
    """python-docx has no high-level hyperlink API -- same raw-XML pattern
    already used elsewhere in this file for numbering and the page-number
    field. Returns a real Run wrapper around the new <w:r> inside the
    hyperlink, so the caller applies bold/italic/underline/etc. through the
    normal .font API exactly as for any other run."""
    r_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    if title:
        hyperlink.set(qn("w:tooltip"), title)  # Word's ScreenTip

    run_element = OxmlElement("w:r")
    run_properties = OxmlElement("w:rPr")
    style = OxmlElement("w:rStyle")
    style.set(qn("w:val"), "Hyperlink")
    run_properties.append(style)
    run_element.append(run_properties)
    hyperlink.append(run_element)
    paragraph._p.append(hyperlink)

    run = Run(run_element, paragraph)
    run.text = text
    return run


def _add_inline_run(paragraph, inline_run: InlineRun, css: dict[str, str]) -> Run:
    marks = {mark.type: mark for mark in inline_run.marks}
    link = marks.get(MarkType.LINK) if marks.get(MarkType.LINK) and marks[MarkType.LINK].href else None
    # run.text turns "\n" into a line break and "\t" into a tab.
    run = _add_hyperlink_run(paragraph, inline_run.text, link.href, link.title) if link else paragraph.add_run(inline_run.text)
    _apply_run_css(run, css)
    if MarkType.BOLD in marks:
        run.font.bold = True
    if MarkType.ITALIC in marks:
        run.font.italic = True
    if MarkType.UNDERLINE in marks:
        run.font.underline = _WORD_UNDERLINES[marks[MarkType.UNDERLINE].lineStyle]
    if MarkType.STRIKE in marks:
        if marks[MarkType.STRIKE].lineStyle == "double":
            run.font.double_strike = True
        else:
            run.font.strike = True
    if MarkType.SUPERSCRIPT in marks:
        run.font.superscript = True
    elif MarkType.SUBSCRIPT in marks:
        run.font.subscript = True
    if MarkType.CODE in marks:
        run.font.name = "Courier New"
    if MarkType.TEXT_STYLE in marks:
        _apply_text_style(run, marks[MarkType.TEXT_STYLE])
    if MarkType.HIDDEN in marks:
        run.font.hidden = True
    return run


def _add_inline_runs(paragraph, inline_runs: list[InlineRun], css: dict[str, str]) -> None:
    for inline_run in inline_runs:
        _add_inline_run(paragraph, inline_run, css)


# -- what the import kept for export (корекции.docx §11) -----------------------------

_KEPT_KINDS = ("equation", "field", "bookmark", "link", "comment", "field_open", "field_close", "comment_close")
# A field running across paragraphs (a table of contents, a bibliography): its start on the
# element it begins in, its end on the one it ends in, the two named by one region (DOCX-020).
# So is a comment running across paragraphs: the comment itself, with its region, then where it ends (DOCX-021).
_REGION_KINDS = ("field_open", "field_close", "comment_close")
_REGION_STARTS = ("field_open", "comment")
_REGION = re.compile(r"[\w:.\-]{1,40}")
# The regions whose start comes before their end, each once, among the elements written.
_BALANCED_REGIONS: ContextVar[frozenset[str]] = ContextVar("balanced_regions", default=frozenset())
# The comments written that end in a later paragraph, by region: their end and reference, to move there.
_OPEN_COMMENTS: ContextVar[dict[str, tuple] | None] = ContextVar("open_comments", default=None)
_BOOKMARK_NAME = re.compile(r"[\w.\-]{1,40}")  # Word's own limit is 40 characters
_COMMENT_ID = re.compile(r"[0-9]{1,10}")
_MATH_ROOTS = (qn("m:oMath"), qn("m:oMathPara"))
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _short_text(value, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit and not _CONTROL.search(value)


def _valid_fragment(fragment) -> bool:
    """preservedAttributes travels through the browser on every autosave, so
    nothing in it is trusted: anything malformed is left out of the export."""
    if not isinstance(fragment, dict) or fragment.get("kind") not in _KEPT_KINDS:
        return False
    start, end = fragment.get("start"), fragment.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end:
        return False
    if not _short_text(fragment.get("text", ""), 10_000):
        return False
    kind = fragment["kind"]
    if kind == "equation":
        xml = fragment.get("xml")
        if not isinstance(xml, str) or len(xml) > 200_000:
            return False
        try:
            return parse_xml(xml).tag in _MATH_ROOTS
        except Exception:  # noqa: BLE001 -- not XML at all
            return False
    if kind == "field":
        return _short_text(fragment.get("instr"), 2_000) and bool(fragment["instr"].strip())
    if kind == "bookmark":
        return isinstance(fragment.get("name"), str) and bool(_BOOKMARK_NAME.fullmatch(fragment["name"]))
    if kind == "link":
        return isinstance(fragment.get("anchor"), str) and bool(_BOOKMARK_NAME.fullmatch(fragment["anchor"]))
    if kind in _REGION_KINDS:
        if not (isinstance(fragment.get("region"), str) and _REGION.fullmatch(fragment["region"])):
            return False
        if kind == "field_open":
            return _short_text(fragment.get("instr"), 2_000) and bool(fragment["instr"].strip())
        return isinstance(fragment.get("paragraph", False), bool)
    if fragment.get("region") is not None and not (isinstance(fragment["region"], str) and _REGION.fullmatch(fragment["region"])):
        return False  # it runs on into a later paragraph (DOCX-021)
    for name in ("commentId", "replyTo"):  # the ids the import read, naming a thread's comments (DOCX-021)
        if fragment.get(name) is not None and not (isinstance(fragment[name], str) and _COMMENT_ID.fullmatch(fragment[name])):
            return False
    if not isinstance(fragment.get("done", False), bool):
        return False
    return all(_short_text(fragment.get(name, ""), limit) for name, limit in (("author", 255), ("initials", 16), ("comment", 20_000)))


def _find_near(text: str, wanted: str, near: int) -> int | None:
    """Where `wanted` is in `text`: at `near` if it's still there, else the closest occurrence."""
    if text.startswith(wanted, near):
        return near
    best, found = None, text.find(wanted)
    while found != -1:
        if best is None or abs(found - near) < abs(best - near):
            best = found
        found = text.find(wanted, found + 1)
    return best


def _place_fragments(text: str, fragments: list) -> list[tuple[int, int, dict]]:
    """Each kept fragment's span in the element's current text. A fragment whose
    text was edited away is dropped (the text itself stays, as edited); so is
    anything that would cut into an equation or cross another internal link. A
    field running across paragraphs whose start or end is gone is left to its
    text (the export says so once, _balanced_regions)."""
    balanced = _BALANCED_REGIONS.get()
    fragments = [fragment for fragment in fragments if not (isinstance(fragment, dict) and fragment.get("kind") in _REGION_KINDS and fragment.get("region") not in balanced)]
    placed: list[tuple[int, int, dict]] = []
    for fragment in fragments:
        if not _valid_fragment(fragment):
            continue
        wanted = fragment.get("text") or ""
        if wanted:
            start = _find_near(text, wanted, fragment["start"])
            if start is not None:
                placed.append((start, start + len(wanted), fragment))
        elif fragment["kind"] != "equation" and fragment["kind"] != "link":
            position = min(fragment["start"], len(text))
            placed.append((position, position, fragment))
    kept: list[tuple[int, int, dict]] = []
    for start, end, fragment in sorted(placed, key=lambda item: (item[0], -item[1])):
        exclusive = [(s, e) for s, e, f in kept if f["kind"] == "equation" or (f["kind"] == "link" and fragment["kind"] == "link")]
        if any(s < start < e or s < end < e or (start < s < end and fragment["kind"] == "equation") for s, e in exclusive):
            continue
        kept.append((start, end, fragment))
    if len(kept) < len(fragments):
        note(
            "export.docx.kept_fragment",
            FidelityPolicy.LOSSY,
            "Equations, fields, bookmarks or comments whose text was edited are written as plain text.",
        )
    return kept


def _cut(inline_runs: list[InlineRun], cuts: list[int]) -> list[tuple[int, int, InlineRun]]:
    """The runs split at every cut position, each piece with where it starts and ends."""
    pieces: list[tuple[int, int, InlineRun]] = []
    position = 0
    for run in inline_runs:
        start, end = position, position + len(run.text)
        edges = [start, *(cut for cut in cuts if start < cut < end), end]
        pieces.extend(
            (a, b, InlineRun(text=run.text[a - start : b - start], marks=run.marks)) for a, b in zip(edges, edges[1:]) if b > a
        )
        position = end
    return pieces


def _field_char(kind: str) -> OxmlElement:
    element = OxmlElement("w:fldChar")
    element.set(qn("w:fldCharType"), kind)
    return element


def _add_inline_runs_keeping(paragraph, inline_runs: list[InlineRun], css: dict[str, str], fragments: list) -> None:
    """The runs, with the equations, fields, bookmarks, internal links and
    comments the import kept put back around (or, for an equation, in place of)
    their text."""
    text = "".join(run.text for run in inline_runs)
    placed = _place_fragments(text, fragments)
    if not placed:
        _add_inline_runs(paragraph, inline_runs, css)
        return
    cuts = sorted({0, len(text), *(start for start, _, _ in placed), *(end for _, end, _ in placed)})
    pieces = {start: (start, end, run) for start, end, run in _cut(inline_runs, cuts)}
    body = paragraph.part.element.body
    state = {"container": paragraph._p, "skip_until": -1}
    bookmark_ids: dict[int, str] = {}
    made: list[tuple[int, int, Run]] = []
    state["ends_after"] = 0  # fields that end in a paragraph of their own after this one, as Word ends a table of contents

    def into_container(run: Run) -> None:
        if state["container"] is not paragraph._p and run._r.getparent() is paragraph._p:
            state["container"].append(run._r)

    def open_(index: int, start: int, end: int, fragment: dict) -> None:
        kind = fragment["kind"]
        if kind == "equation":
            state["container"].append(parse_xml(fragment["xml"]))
            state["skip_until"] = end
        elif kind in ("field", "field_open"):
            run = paragraph.add_run()
            into_container(run)
            instr = OxmlElement("w:instrText")
            instr.set(qn("xml:space"), "preserve")
            instr.text = fragment["instr"]
            run._r.append(_field_char("begin"))
            run._r.append(instr)
            run._r.append(_field_char("separate"))
        elif kind == "comment_close":  # a comment that began in an earlier paragraph ends here (DOCX-021)
            open_comments = _OPEN_COMMENTS.get()
            for node in open_comments.pop(fragment["region"], ()) if open_comments is not None else ():
                state["container"].append(node)
        elif kind == "field_close":
            if fragment.get("paragraph"):
                state["ends_after"] += 1
            else:
                run = paragraph.add_run()
                into_container(run)
                run._r.append(_field_char("end"))
        elif kind == "bookmark":
            taken = [int(mark.get(qn("w:id"))) for mark in body.iter(qn("w:bookmarkStart")) if (mark.get(qn("w:id")) or "").isdigit()]
            taken.extend(_RESERVED_BOOKMARKS.get())  # the original blocks copied as they are (DOCX-028)
            bookmark_ids[index] = str(max(taken, default=-1) + 1)
            mark = OxmlElement("w:bookmarkStart")
            mark.set(qn("w:id"), bookmark_ids[index])
            mark.set(qn("w:name"), fragment["name"])
            state["container"].append(mark)
        elif kind == "link":
            hyperlink = OxmlElement("w:hyperlink")
            hyperlink.set(qn("w:anchor"), fragment["anchor"])
            paragraph._p.append(hyperlink)
            state["container"] = hyperlink

    def close(index: int, fragment: dict) -> None:
        kind = fragment["kind"]
        if kind == "field":
            run = paragraph.add_run()
            into_container(run)
            run._r.append(_field_char("end"))
        elif kind == "bookmark":
            mark = OxmlElement("w:bookmarkEnd")
            mark.set(qn("w:id"), bookmark_ids[index])
            state["container"].append(mark)
        elif kind == "link":
            state["container"] = paragraph._p

    indexed = list(enumerate(placed))
    # Every place a piece of text starts, not only where a fragment starts or ends: a run
    # of other formatting between two of those is text too (it used to be left out).
    for position in sorted({*cuts, *pieces}):
        for index, (start, end, fragment) in sorted(indexed, key=lambda item: -item[1][0]):
            if end == position and start < position:  # the one opened last closes first
                close(index, fragment)
        for index, (start, end, fragment) in indexed:
            if start == end == position:
                open_(index, start, end, fragment)
                close(index, fragment)
        for index, (start, end, fragment) in sorted(indexed, key=lambda item: -item[1][1]):
            if start == position and end > position:  # the one closing last opens first
                open_(index, start, end, fragment)
        piece = pieces.get(position)
        if piece is not None and not piece[0] < state["skip_until"]:
            run = _add_inline_run(paragraph, piece[2], css)
            into_container(run)
            made.append((piece[0], piece[1], run))
    for _ in range(state["ends_after"]):
        holder, run = OxmlElement("w:p"), OxmlElement("w:r")
        run.append(_field_char("end"))
        holder.append(run)
        paragraph._p.addnext(holder)

    comments = [item for item in placed if item[2]["kind"] == "comment"]
    at = {fragment["commentId"]: index for index, (_, _, fragment) in enumerate(comments) if fragment.get("commentId")}

    def thread(index: int) -> tuple[int, bool]:  # a thread's comments together, its first before its replies, as Word lists them
        answers = at.get(comments[index][2].get("replyTo") or "")
        return (index, False) if answers is None else (answers, True)

    for start, end, fragment in (comments[index] for index in sorted(range(len(comments)), key=thread)):
        runs = [run for piece_start, piece_end, run in made if start <= piece_start and piece_end <= end]
        runs = runs or [run for piece_start, piece_end, run in made if piece_start <= start < piece_end] or [run for *_, run in made[-1:]]
        if not runs:
            continue
        comment = paragraph.part.document.add_comment(
            runs=[runs[0], runs[-1]],
            text=fragment.get("comment", ""),
            author=fragment.get("author", ""),
            initials=fragment.get("initials", ""),
        )
        if isinstance(fragment.get("date"), str) and re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:\d\d)?", fragment["date"]):
            comment._comment_elm.set(qn("w:date"), fragment["date"])
        _after_earlier_ends(runs[-1]._r)
        open_comments = _OPEN_COMMENTS.get()
        if fragment.get("region") in _BALANCED_REGIONS.get() and open_comments is not None:  # its end goes where it ends
            comment_id = str(comment.comment_id)
            end = next(node for node in paragraph._p.iter(qn("w:commentRangeEnd")) if node.get(qn("w:id")) == comment_id)
            reference = next(node for node in paragraph._p.iter(qn("w:commentReference")) if node.get(qn("w:id")) == comment_id)
            open_comments[fragment["region"]] = (end, reference.getparent())
        written = _WRITTEN_COMMENTS.get()
        if written is not None:
            written[str(comment.comment_id)] = {name: fragment.get(name) for name in ("commentId", "replyTo", "done")}


def _is_comment_end(node) -> bool:
    return node.tag == qn("w:commentRangeEnd") or node.tag == qn("w:r") and node.find(qn("w:commentReference")) is not None


def _after_earlier_ends(last_run) -> None:
    """The end and reference of the comment just added after `last_run` go after those of
    comments added there before it: python-docx puts them right after the run, so before
    those. Word writes them in the comments' order, and takes a reply whose reference
    comes before its comment's for a comment of its own (measured, DOCX-021)."""
    end = last_run.getnext()
    reference = end.getnext() if end is not None and end.tag == qn("w:commentRangeEnd") else None
    if reference is None or not _is_comment_end(reference):
        return
    anchor = reference
    while anchor.getnext() is not None and _is_comment_end(anchor.getnext()):
        anchor = anchor.getnext()
    if anchor is not reference:
        anchor.addnext(end)
        end.addnext(reference)


def _add_runs(paragraph, element: Element, document: Document) -> None:
    css = _own_css(element, document)
    inline_runs = element.inline or ([InlineRun(text=element.content)] if element.content else [])
    kept = (element.preservedAttributes or {}).get("ooxml")
    if isinstance(kept, list) and kept:
        _add_inline_runs_keeping(paragraph, inline_runs, css, kept)
    else:
        _add_inline_runs(paragraph, inline_runs, css)
    _apply_paragraph_css(paragraph, css)


@dataclass(frozen=True)
class _Place:
    """Where blocks are written: the document body or a table cell, how far in
    they start (the blocks of a list item sit under its text) and how wide they
    may be (None: the page's content width). Inside a cell, plain paragraphs use
    the cell text style."""

    container: object
    indent_cm: float = 0.0
    width_cm: float | None = None
    paragraph_style: str | None = None
    # The top-level element being written: what the export report points at.
    owner: str | None = None


def _indent(paragraph, place: _Place) -> None:
    if place.indent_cm and paragraph.paragraph_format.left_indent is None:
        paragraph.paragraph_format.left_indent = Cm(place.indent_cm)


def _add_heading(place: _Place, element: Element, document: Document) -> None:
    heading = place.container.add_paragraph(style=_word_style(place.container.part.document, f"Heading {min(max(element.level or 1, 1), 9)}"))
    _add_runs(heading, element, document)
    _indent(heading, place)


def _add_paragraph(place: _Place, element: Element, document: Document) -> None:
    style = _STYLE_FOR_TYPE.get(element.type) or place.paragraph_style
    paragraph = place.container.add_paragraph(style=style)
    _add_runs(paragraph, element, document)
    _indent(paragraph, place)


def _add_quote(place: _Place, element: Element, document: Document, assets: Mapping[str, bytes]) -> None:
    """A quote of one paragraph is one Quote-style paragraph; a quote holding more
    (paragraphs, a list, code) writes its paragraphs in the Quote style and the
    rest indented like them."""
    if not element.children:
        _add_paragraph(place, element, document)
        return
    quote_indent = _parse_cm(document.resolvedStyles.get("Quote", {}).get("margin-left", "")) or 1.0
    inner = replace(place, indent_cm=place.indent_cm + quote_indent)
    for child in element.children:
        if child.type == ElementType.PARAGRAPH:
            paragraph = place.container.add_paragraph(style="Quote")
            _add_runs(paragraph, child, document)
            if place.indent_cm:
                paragraph.paragraph_format.left_indent = Cm(place.indent_cm + quote_indent)
        else:
            _add_element(inner, child, document, assets)


def _add_checkbox(paragraph, checked: bool) -> None:
    """A real Word checkbox (a content control): clickable in Word 2010 and
    later, a ☒/☐ character anywhere else -- and imported back as a checklist."""
    glyph = "☒" if checked else "☐"
    paragraph._p.append(
        parse_xml(
            f"<w:sdt {nsdecls('w', 'w14')}><w:sdtPr><w14:checkbox>"
            f'<w14:checked w14:val="{1 if checked else 0}"/>'
            '<w14:checkedState w14:val="2612" w14:font="MS Gothic"/>'
            '<w14:uncheckedState w14:val="2610" w14:font="MS Gothic"/>'
            "</w14:checkbox></w:sdtPr><w:sdtContent><w:r><w:rPr>"
            '<w:rFonts w:ascii="MS Gothic" w:eastAsia="MS Gothic" w:hAnsi="MS Gothic" w:hint="eastAsia"/>'
            f"</w:rPr><w:t>{glyph}</w:t></w:r></w:sdtContent></w:sdt>"
        )
    )
    paragraph.add_run(" ")


_LIST_LEVELS = WORD_LEVELS  # Word's maximum
_LEVEL_INDENT_TWIPS = LEVEL_INDENT_TWIPS  # 0.63 cm per level
_LEVEL_INDENT_CM = 0.63


def _child(parent, tag: str, **attributes: str):
    element = OxmlElement(tag)
    for name, value in attributes.items():
        element.set(qn(f"w:{name}"), value)
    parent.append(element)
    return element


def _abstract_numbering(numbering, levels: list[Level]) -> str:
    """The id of this document's multi-level list definition with these levels, added
    the first time it's needed (python-docx's template only has single-level lists).
    Built element by element: a label is the document's text, never markup."""
    name = "SmartDoc " + hashlib.sha256(repr(levels).encode("utf-8")).hexdigest()[:16]
    for abstract in numbering.findall(qn("w:abstractNum")):
        name_element = abstract.find(qn("w:name"))
        if name_element is not None and name_element.get(qn("w:val")) == name:
            return abstract.get(qn("w:abstractNumId"))
    abstract_id = str(1 + max((int(a.get(qn("w:abstractNumId"))) for a in numbering.findall(qn("w:abstractNum"))), default=-1))
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), abstract_id)
    _child(abstract, "w:multiLevelType", val="hybridMultilevel")
    _child(abstract, "w:name", val=name)
    for ilvl, level in enumerate(levels):  # CT_Lvl's children in the schema's order
        lvl = _child(abstract, "w:lvl", ilvl=str(ilvl))
        _child(lvl, "w:start", val=str(level.start))
        _child(lvl, "w:numFmt", val=level.fmt)
        if level.restart is not None:
            _child(lvl, "w:lvlRestart", val=str(level.restart))
        if level.legal:
            _child(lvl, "w:isLgl")
        if level.suffix != "tab":
            _child(lvl, "w:suff", val=level.suffix)
        _child(lvl, "w:lvlText", val=level.text)
        _child(lvl, "w:lvlJc", val="left")
        indent = _child(_child(lvl, "w:pPr"), "w:ind", left=str(level.left))
        indent.set(qn("w:hanging" if level.hanging >= 0 else "w:firstLine"), str(abs(level.hanging)))
    first_num = numbering.find(qn("w:num"))  # the schema puts every abstractNum before the nums
    if first_num is not None:
        first_num.addprevious(abstract)
    else:
        numbering.append(abstract)
    return abstract_id


def _new_list_numbering(part, kind: str, list_numbering: ListNumbering | None = None, base_level: int = 0) -> int:
    """A numbering instance of its own for one list: levels nest for real (Tab
    and Shift+Tab work in Word, and a re-import keeps them), and a numbered
    list starts again at 1 -- or where the list says it starts, in its format --
    instead of continuing the previous one. `base_level`: the Word level the
    list's own first level sits at (a list inside a list item)."""
    numbering = part.numbering_part.element
    levels = list_levels(kind, list_numbering, base_level)
    abstract_id = _abstract_numbering(numbering, levels)
    num_id = 1 + max((int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))), default=0)
    first = list_numbering.start if list_numbering is not None and kind == "number" else 1
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    _child(num, "w:abstractNumId", val=abstract_id)
    for ilvl, level in enumerate(levels):
        _child(_child(num, "w:lvlOverride", ilvl=str(ilvl)), "w:startOverride", val=str(first if ilvl == base_level else level.start))
    numbering.append(num)
    return num_id


def _set_numbering(paragraph, num_id: int, level: int) -> None:
    num_pr = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    num_pr.get_or_add_ilvl().val = min(max(level, 0), _LIST_LEVELS - 1)
    num_pr.get_or_add_numId().val = num_id


def _add_list(place: _Place, element: Element, document: Document, assets: Mapping[str, bytes], base_level: int = 0) -> None:
    full_css = _resolved_css(element, document)
    own = {key: value for key, value in _own_css(element, document).items() if key != "margin-left"}
    checklist = any(item.checked is not None for item in element.listItems or [])
    style_name = "List Paragraph" if checklist else "List Number" if element.ordered else "List Bullet"
    kind = "none" if checklist else "number" if element.ordered else "bullet"
    num_id = _new_list_numbering(place.container.part, kind, element.numbering, base_level)
    levels = (element.numbering.levels or []) if element.numbering is not None else []
    # The numbering's own indent beats a style's, so a list indent goes on each item.
    margin = full_css.get("margin-left", "")
    base_indent = (_parse_cm(margin) if margin.endswith("cm") else 0.0) + place.indent_cm
    for item in element.listItems or []:
        level = item.level + base_level
        paragraph = place.container.add_paragraph(style=style_name)
        _set_numbering(paragraph, num_id, level)
        if base_indent:  # otherwise the list level sets the indent
            level_indent = levels[item.level].indentCm if item.level < len(levels) else None
            paragraph.paragraph_format.left_indent = Cm(base_indent + (level_indent if level_indent is not None else _LEVEL_INDENT_CM * (level + 1)))
        if item.checked is not None:
            _add_checkbox(paragraph, item.checked)
        _add_inline_runs(paragraph, item.inline, own)
        _apply_paragraph_css(paragraph, own)
        # What the item holds after its first paragraph sits under its text; a list
        # there nests one level deeper, with a numbering of its own.
        under_text = replace(place, indent_cm=base_indent + _LEVEL_INDENT_CM * (level + 1))
        blocks = list(item.blocks or [])
        # Its pictures before anything else it holds are in its own paragraph, where Word keeps them (DOCX-027).
        while blocks and blocks[0].type == ElementType.IMAGE:
            _add_image(under_text, blocks.pop(0), document, assets, into=paragraph)
        for block in blocks:
            if block.type == ElementType.LIST:
                _add_list(replace(place, indent_cm=base_indent), block, document, assets, base_level=level + 1)
            else:
                _add_element(under_text, block, document, assets)


def _grid_positions(table_content: TableContent) -> tuple[list[tuple[int, int, object]], int]:
    """(row, column, cell) for every cell, with spans taken into account."""
    occupied: set[tuple[int, int]] = set()
    placed: list[tuple[int, int, object]] = []
    width = 0
    for row_index, row in enumerate(table_content.rows):
        column = 0
        for cell in row.cells:
            while (row_index, column) in occupied:
                column += 1
            placed.append((row_index, column, cell))
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    occupied.add((row_index + dr, column + dc))
            column += cell.colspan
            width = max(width, column)
    return placed, width


_CELL_PADDING_CM = 0.4  # Word's default left + right cell margins


# The schema's order of a table's, a row's and a cell's properties (CT_TblPr, CT_TrPr, CT_TcPr).
_TBL_PR_ORDER = (
    "tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize", "tblW", "jc",
    "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription",
)
_TR_PR_ORDER = ("cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore", "wAfter", "cantSplit", "trHeight", "tblHeader", "tblCellSpacing", "jc", "hidden")
_TC_PR_ORDER = (
    "cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar", "textDirection", "tcFitText",
    "vAlign", "hideMark",
)
_BORDER_ORDER = ("top", "left", "start", "bottom", "right", "end", "insideH", "insideV", "tl2br", "tr2bl")
_TABLE_ALIGNMENTS = {"left": WD_TABLE_ALIGNMENT.LEFT, "center": WD_TABLE_ALIGNMENT.CENTER, "right": WD_TABLE_ALIGNMENT.RIGHT}
_V_ALIGN = {"top": "top", "center": "center", "bottom": "bottom"}


def _put_in(parent, tag: str, order: tuple[str, ...], element=None, **attributes: str):
    """Sets a child element where the schema puts it (replacing one already there)."""
    for existing in parent.findall(qn(tag)):
        parent.remove(existing)
    if element is None:
        element = OxmlElement(tag)
    for name, value in attributes.items():
        element.set(qn(f"w:{name}"), value)
    later = {qn(f"w:{following}") for following in order[order.index(tag.split(":", 1)[1]) + 1 :]}
    successor = next((child for child in parent if child.tag in later), None)
    if successor is None:
        parent.append(element)
    else:
        successor.addprevious(element)
    return element


def _border_sides(tag: str, sides: dict[str, str | None]):
    """w:tblBorders or w:tcBorders from border values ("solid 0.5pt #000000", "none")."""
    borders = OxmlElement(tag)
    for side in _BORDER_ORDER:
        value = sides.get(side)
        if value is None:
            continue
        element = OxmlElement(f"w:{side}")
        if value == "none":
            element.set(qn("w:val"), "nil")
        else:
            style, width, color = value.split(" ")
            element.set(qn("w:val"), _WORD_BORDERS.get(style, "single"))
            element.set(qn("w:sz"), str(max(2, min(96, round(float(width.removesuffix("pt")) * 8)))))
            element.set(qn("w:space"), "0")
            element.set(qn("w:color"), _hex6(color) or "000000")
        borders.append(element)
    return borders


def _cell_margins(tag: str, margins) -> object:
    element = OxmlElement(tag)
    for side in ("top", "left", "bottom", "right"):
        value = getattr(margins, f"{side}Cm")
        if value is not None:
            margin = OxmlElement(f"w:{side}")
            margin.set(qn("w:w"), str(round(value * 566.929)))
            margin.set(qn("w:type"), "dxa")
            element.append(margin)
    return element


def _table_style(docx_document: DocxDocument, name: str | None):
    """The document's table style of that name, when it has one."""
    if not name:
        return None
    for style in docx_document.styles:
        if style.type == WD_STYLE_TYPE.TABLE and (style.name or "").lower() == name.lower():
            return style
    return None


def _add_table(place: _Place, element: Element, document: Document, assets: Mapping[str, bytes]) -> None:
    """A table as the model has it (DOCX-017): its grid's widths, width, alignment and
    indent, borders and cell margins, its Word style where this file has it, each
    row's height and header, each cell's borders, margins and alignment. A table
    with none of that -- made here -- gets a grid, centred, as before."""
    table_content = element.table
    if table_content is None or not table_content.rows:
        return
    css = {key: value for key, value in _own_css(element, document).items() if not key.startswith("margin")}
    placed, width = _grid_positions(table_content)
    if width == 0:
        return
    height = len(table_content.rows)
    table = place.container.add_table(rows=height, cols=width)
    tc = getattr(place.container, "_tc", None)
    if tc is not None and tc[-1].tag == qn("w:p") and not len(tc[-1]):
        tc.remove(tc[-1])  # python-docx's paragraph after a table in a cell: the cell's own blocks follow, or one is added at its end
    docx_document = place.container.part.document
    own_style = _table_style(docx_document, table_content.style)
    plain = table_content.style is None and table_content.borders is None and table_content.columnWidthsCm is None and table_content.align is None
    if own_style is not None:
        table.style = own_style
    elif plain:
        table.style = _word_style(docx_document, "Table Grid", WD_STYLE_TYPE.TABLE)
    elif table_content.style is not None:
        note(
            "export.docx.table_style",
            FidelityPolicy.LOSSY,
            "A table's Word style isn't in this file: it is written with its borders and margins as they look; what the "
            "style colours by position (banded rows, first or last columns) isn't.",
            element_id=place.owner,
        )
    if table_content.align or plain:  # none of its own: Word's, on the left
        table.alignment = _TABLE_ALIGNMENTS[table_content.align or "center"]
    tbl_pr = table._tbl.tblPr
    if table_content.widthCm is not None:
        _put_in(tbl_pr, "w:tblW", _TBL_PR_ORDER, w=str(round(table_content.widthCm * 566.929)), type="dxa")
    elif table_content.widthPercent is not None:
        _put_in(tbl_pr, "w:tblW", _TBL_PR_ORDER, w=str(round(table_content.widthPercent * 50)), type="pct")
    if table_content.indentCm is not None:
        _put_in(tbl_pr, "w:tblInd", _TBL_PR_ORDER, w=str(round(table_content.indentCm * 566.929)), type="dxa")
    if table_content.borders is not None:
        _put_in(tbl_pr, "w:tblBorders", _TBL_PR_ORDER, _border_sides("w:tblBorders", table_content.borders.model_dump()))
    if table_content.cellMargins is not None:
        _put_in(tbl_pr, "w:tblCellMar", _TBL_PR_ORDER, _cell_margins("w:tblCellMar", table_content.cellMargins))
    if table_content.floating is not None:
        floating = table_content.floating
        position = {"horzAnchor": floating.horizontalAnchor, "vertAnchor": floating.verticalAnchor}
        for name, value in (("leftFromText", floating.leftFromTextCm), ("rightFromText", floating.rightFromTextCm),
                            ("topFromText", floating.topFromTextCm), ("bottomFromText", floating.bottomFromTextCm),
                            ("tblpX", floating.xCm), ("tblpY", floating.yCm)):
            if value is not None:
                position[name] = str(round(value * 566.929))
        if floating.xAlign:
            position["tblpXSpec"] = floating.xAlign
        if floating.yAlign:
            position["tblpYSpec"] = floating.yAlign
        _put_in(tbl_pr, "w:tblpPr", _TBL_PR_ORDER, **position)
    if table_content.look is not None:
        look = table_content.look
        _put_in(
            tbl_pr,
            "w:tblLook",
            _TBL_PR_ORDER,
            firstRow=str(int(look.firstRow)),
            lastRow=str(int(look.lastRow)),
            firstColumn=str(int(look.firstColumn)),
            lastColumn=str(int(look.lastColumn)),
            noHBand=str(int(not look.bandedRows)),
            noVBand=str(int(not look.bandedColumns)),
        )
    widths = table_content.columnWidthsCm if table_content.columnWidthsCm and len(table_content.columnWidthsCm) == width else None
    if widths is not None:
        for column, grid_col in zip(table.columns, table._tbl.tblGrid.findall(qn("w:gridCol"))):
            grid_col.set(qn("w:w"), str(round(widths[column._index] * 566.929)))
    for row, tr in zip(table_content.rows, table._tbl.tr_lst):
        if row.heightCm is not None or row.repeatHeader or row.cantSplit:
            tr_pr = tr.get_or_add_trPr()
            if row.cantSplit:
                _put_in(tr_pr, "w:cantSplit", _TR_PR_ORDER)
            if row.heightCm is not None:
                _put_in(tr_pr, "w:trHeight", _TR_PR_ORDER, val=str(round(row.heightCm * 566.929)), hRule=row.heightRule)
            if row.repeatHeader:
                _put_in(tr_pr, "w:tblHeader", _TR_PR_ORDER)
    alignments = table_content.alignments or []
    room = (place.width_cm if place.width_cm is not None else _content_width_cm(document)) - place.indent_cm
    for row_index, column, cell in placed:
        last_row = min(row_index + cell.rowspan - 1, height - 1)
        last_column = min(column + cell.colspan - 1, width - 1)
        target = table.cell(row_index, column)
        if (last_row, last_column) != (row_index, column):
            target = target.merge(table.cell(last_row, last_column))
        first = target.paragraphs[0]
        first.style = "Table Text"
        if cell.blocks:
            cell_width = sum(widths[column : last_column + 1]) - _CELL_PADDING_CM if widths else room * cell.colspan / width - _CELL_PADDING_CM
            inner = _Place(container=target, width_cm=max(cell_width, 1.0), paragraph_style="Table Text", owner=place.owner)
            for block in cell.blocks:
                _add_element(inner, block, document, assets)
            # Every new cell starts with an empty paragraph; it goes once content follows.
            if not first.runs and len(target._tc.findall(qn("w:p"))) + len(target._tc.findall(qn("w:tbl"))) > 1:
                target._tc.remove(first._p)
            if target._tc[-1].tag == qn("w:tbl"):
                target._tc.append(OxmlElement("w:p"))  # Word ends every cell with a paragraph
        else:
            _add_inline_runs(first, cell.inline, css)
        paragraphs = target.paragraphs
        if cell.header and table_content.headerBold:
            for paragraph in paragraphs:
                for run in paragraph.runs:
                    run.font.bold = True
        alignment = _ALIGNMENT_MAP.get(cell.align or (alignments[column] if column < len(alignments) else None) or "")
        if alignment is not None:
            for paragraph in paragraphs:
                paragraph.alignment = alignment
        tc_pr = target._tc.get_or_add_tcPr()
        if widths is not None:
            _put_in(tc_pr, "w:tcW", _TC_PR_ORDER, w=str(round(sum(widths[column : last_column + 1]) * 566.929)), type="dxa")
        if cell.borders is not None:
            _put_in(tc_pr, "w:tcBorders", _TC_PR_ORDER, _border_sides("w:tcBorders", cell.borders.model_dump()))
        background = _hex6(cell.background)
        if background:
            _put_in(tc_pr, "w:shd", _TC_PR_ORDER, val="clear", color="auto", fill=background)
        if cell.margins is not None:
            _put_in(tc_pr, "w:tcMar", _TC_PR_ORDER, _cell_margins("w:tcMar", cell.margins))
        if cell.verticalAlign is not None:
            _put_in(tc_pr, "w:vAlign", _TC_PR_ORDER, val=_V_ALIGN[cell.verticalAlign])


def _image_alignment(css: dict[str, str]):
    left, right = css.get("margin-left"), css.get("margin-right")
    if left == "auto" and right == "auto":
        return WD_ALIGN_PARAGRAPH.CENTER
    if left == "auto":
        return WD_ALIGN_PARAGRAPH.RIGHT
    return None


def _native_width_cm(image_bytes: bytes) -> float | None:
    try:
        image = DocxImage.from_blob(image_bytes)
    except Exception:
        return None
    return image.width.cm if image.width else None


# Picture formats python-docx (and older Word) can hold; anything else goes in as PNG.
_WORD_PICTURES = {"PNG", "JPEG", "GIF", "BMP", "TIFF"}
_EMU_PER_CM = 360_000
_WRAP_TAGS = {"square": "wp:wrapSquare", "tight": "wp:wrapTight", "through": "wp:wrapThrough", "topAndBottom": "wp:wrapTopAndBottom"}
_RECTANGLE = (
    '<wp:wrapPolygon edited="0"><wp:start x="0" y="0"/><wp:lineTo x="0" y="21600"/>'
    '<wp:lineTo x="21600" y="21600"/><wp:lineTo x="21600" y="0"/><wp:lineTo x="0" y="0"/></wp:wrapPolygon>'
)


def _word_picture(image_bytes: bytes) -> bytes:
    """The picture as Word can hold it: WebP (or any format it can't) as PNG (DOCX-018)."""
    try:
        with PILImage.open(io.BytesIO(image_bytes)) as picture:
            if (picture.format or "").upper() in _WORD_PICTURES:
                return image_bytes
            converted = io.BytesIO()
            picture.convert("RGBA" if "A" in picture.getbands() else "RGB").save(converted, format="PNG")
            return converted.getvalue()
    except (OSError, ValueError):
        return image_bytes  # python-docx says what it can't read


def _add_image(place: _Place, element: Element, document: Document, assets: Mapping[str, bytes], *, into=None) -> None:
    """A picture at its size -- the width rule's, or its own from Word, never wider than
    the room -- with its own proportions, crop, turn and flips, and, floating, where it
    floats and how text wraps around it (DOCX-018). `into`: the paragraph it goes in (a
    list item's, DOCX-027); else it has one of its own."""
    image_bytes = resolve_image_bytes(element.image, assets) if element.image else None
    if image_bytes is None:
        note(
            "export.image.missing",
            FidelityPolicy.UNSUPPORTED,
            "A picture couldn't be found for the export and was left out.",
            element_id=place.owner,
            content_changed=True,
        )
        return
    image = element.image
    image_bytes = _word_picture(image_bytes)

    css = _resolved_css(element, document)
    width_cm = picture_width_cm(image, css.get("width", ""), _content_width_cm(document))
    width = Cm(width_cm) if width_cm else None
    if place.width_cm is not None or place.indent_cm:
        # Inside a cell or a list item a picture never gets wider than the room there.
        room = (place.width_cm if place.width_cm is not None else _content_width_cm(document)) - place.indent_cm
        native = width.cm if width is not None else _native_width_cm(image_bytes)
        if native is not None and room > 0:
            width = Cm(min(native, room))
    height = Cm(width.cm * image.heightCm / image.widthCm) if width is not None and image.widthCm and image.heightCm else None

    paragraph = into if into is not None else place.container.add_paragraph()
    run = paragraph.add_run()
    try:
        shape = run.add_picture(io.BytesIO(image_bytes), width=width, height=height)
    except Exception:
        left_out = run._r if into is not None else paragraph._p
        left_out.getparent().remove(left_out)
        note(
            "export.docx.image_format",
            FidelityPolicy.UNSUPPORTED,
            "A picture Word can't read was left out.",
            element_id=place.owner,
            content_changed=True,
        )
        return
    inline = shape._inline
    # Alt text and title, as Word's own "Alt Text" pane writes them, and its name.
    if image.alt:
        inline.docPr.set("descr", image.alt)
    if image.title:
        inline.docPr.set("title", image.title)
    if image.name:
        inline.docPr.set("name", image.name)
    pic = inline.graphic.graphicData.pic
    if image.crop is not None:
        crop = OxmlElement("a:srcRect")
        for side, key in (("left", "l"), ("top", "t"), ("right", "r"), ("bottom", "b")):
            value = round(getattr(image.crop, side) * 100_000)
            if value:
                crop.set(key, str(value))
        pic.blipFill.find(qn("a:blip")).addnext(crop)
    if image.rotation or image.flipHorizontal or image.flipVertical:
        xfrm = pic.spPr.find(qn("a:xfrm"))
        if image.rotation:
            xfrm.set("rot", str(round(image.rotation * 60_000)))
        if image.flipHorizontal:
            xfrm.set("flipH", "1")
        if image.flipVertical:
            xfrm.set("flipV", "1")
    _turn_room(inline, image.rotation)
    if image.placement is not None:
        _float(inline, image.placement)
    if into is None:
        alignment = _image_alignment(css)
        if alignment is not None:
            paragraph.alignment = alignment
        _indent(paragraph, place)


_ANCHOR_ORDER = 251_658_240  # Word's own starting z-order for floating pictures


def _turn_room(inline, rotation: float | None) -> None:
    """A turned picture takes the room of its turned outline, as Word writes it: its
    size stays the picture's, and wp:effectExtent adds to (or takes from) each side."""
    extent = inline.find(qn("wp:extent"))
    width, height = int(extent.get("cx")), int(extent.get("cy"))
    wide, high = turned_box(width, height, rotation)
    across, down = round((wide - width) / 2), round((high - height) / 2)
    if across or down:
        extent.addnext(parse_xml(f'<wp:effectExtent {nsdecls("wp")} l="{across}" t="{down}" r="{across}" b="{down}"/>'))


def _float(inline, placement) -> None:
    """Turns a picture in line into one that floats as `placement` says (wp:anchor),
    moving the parts python-docx made -- its size, name and picture -- into it."""
    emu = lambda cm: str(round((cm or 0) * _EMU_PER_CM))  # noqa: E731
    anchor = parse_xml(
        f'<wp:anchor {nsdecls("wp")} distT="{emu(placement.distanceTopCm)}" distB="{emu(placement.distanceBottomCm)}" '
        f'distL="{emu(placement.distanceLeftCm)}" distR="{emu(placement.distanceRightCm)}" simplePos="0" '
        f'relativeHeight="{_ANCHOR_ORDER}" behindDoc="{int(placement.wrap == "behind")}" locked="0" '
        f'layoutInCell="{int(placement.layoutInCell)}" allowOverlap="{int(placement.allowOverlap)}"><wp:simplePos x="0" y="0"/></wp:anchor>'
    )
    for axis, tag, relative, align, offset in (
        ("horizontal", "wp:positionH", placement.horizontalFrom, placement.horizontalAlign, placement.horizontalCm),
        ("vertical", "wp:positionV", placement.verticalFrom, placement.verticalAlign, placement.verticalCm),
    ):
        position = OxmlElement(tag)
        position.set("relativeFrom", relative)
        if align:
            child = OxmlElement("wp:align")
            child.text = align
        else:
            child = OxmlElement("wp:posOffset")
            child.text = emu(offset)
        position.append(child)
        anchor.append(position)
    anchor.append(inline.find(qn("wp:extent")))
    room = inline.find(qn("wp:effectExtent"))
    anchor.append(room if room is not None else parse_xml(f'<wp:effectExtent {nsdecls("wp")} l="0" t="0" r="0" b="0"/>'))
    if placement.wrap in _WRAP_TAGS:
        wrap = OxmlElement(_WRAP_TAGS[placement.wrap])
        if placement.wrap != "topAndBottom":
            wrap.set("wrapText", "bothSides")
        if placement.wrap in ("tight", "through"):
            wrap.append(parse_xml(_RECTANGLE.replace("<wp:wrapPolygon", f'<wp:wrapPolygon {nsdecls("wp")}', 1)))
    else:
        wrap = OxmlElement("wp:wrapNone")
    anchor.append(wrap)
    for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
        part = inline.find(qn(tag))
        if part is not None:
            anchor.append(part)
    inline.getparent().replace(inline, anchor)


def _add_code_block(place: _Place, element: Element, document: Document) -> None:
    """The Code style carries the monospace font and the grey shading."""
    own = _own_css(element, document)
    paragraph = place.container.add_paragraph(style="Code")
    _apply_run_css(paragraph.add_run(element.content), own)
    _apply_paragraph_css(paragraph, own)
    _indent(paragraph, place)


def _add_horizontal_rule(place: _Place) -> None:
    paragraph = place.container.add_paragraph()
    paragraph._p.get_or_add_pPr().append(
        parse_xml(f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" w:sz="6" w:space="1" w:color="9CA3AF"/></w:pBdr>')
    )
    _indent(paragraph, place)


def _add_page_break(place: _Place) -> None:
    # python-docx has a real, first-class page break -- a run-level WD_BREAK,
    # not a styled paragraph standing in for one.
    place.container.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _add_element(place: _Place, element: Element, document: Document, assets: Mapping[str, bytes]) -> None:
    if element.type == ElementType.HEADING:
        _add_heading(place, element, document)
    elif element.type == ElementType.LIST:
        _add_list(place, element, document, assets)
    elif element.type == ElementType.TABLE:
        _add_table(place, element, document, assets)
    elif element.type == ElementType.IMAGE:
        _add_image(place, element, document, assets)
    elif element.type == ElementType.CODE_BLOCK:
        _add_code_block(place, element, document)
    elif element.type == ElementType.PAGE_BREAK:
        _add_page_break(place)
    elif element.type == ElementType.HORIZONTAL_RULE:
        _add_horizontal_rule(place)
    elif element.type == ElementType.QUOTE:
        _add_quote(place, element, document, assets)
    else:
        _add_paragraph(place, element, document)
