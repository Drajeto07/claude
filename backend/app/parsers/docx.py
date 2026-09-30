"""Deterministic DOCX import: structure and formatting read straight from the
file, no AI involved (confidence 1.0 throughout).

What it keeps: headings (Heading/Title styles, or outline levels), paragraphs,
quotes, captions (the Caption style, or "Figure 1:"-style lines next to a
picture or table), lists (numbered on the paragraph or through its style, with
levels, and ☐/☑ checklists), code blocks (paragraphs set entirely in a
monospace font), tables (real colspan/rowspan, cell shading, column
alignment), pictures (size and alignment), page breaks, horizontal rules,
footnotes and endnotes (moved to the end), equations and text boxes (as text).

What the editor can't show -- equations (as the original OMML), Word fields,
bookmarks, links to bookmarks, comments -- is kept with its paragraph in
Element.preservedAttributes["ooxml"], with where its text sits, and the DOCX
export puts it back (корекции.docx §11, the preservation layer).

How it looks: the file's Word styles and page setup become a StyleSystem
(docx_styles.py) at the SOURCE_DOCUMENT priority, and whatever a single
paragraph sets differently becomes a rule for just that element. Character
formatting that varies inside a paragraph (a highlighted word, a different
font) stays on the text as marks. Anything that can't be kept is described in
Document.unsupportedFeatures, never dropped silently."""

import base64
import io
import re
import zipfile
from contextvars import ContextVar
from dataclasses import dataclass, field, replace

from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from lxml import etree

from app.fidelity.report import FidelityPolicy, FidelityReport, FidelityStage
from app.formatting.list_numbering import DEFAULT_BULLETS, DEFAULT_FORMATS, LEVEL_INDENT_TWIPS, WORD_LEVELS
from app.formatting.engine import DEFAULT_RULES, SOURCE_DOCUMENT_SOURCE, recompute_styles
from app.formatting.priorities import Priority
from app.formatting.style_system import compile_rules
from app.formatting.values import is_valid_rule_value
from app.models.document import (
    WEB_IMAGE_TYPES,
    Document,
    DocumentMetadata,
    Element,
    ElementType,
    FormattingProperty,
    FormattingRule,
    ImageContent,
    InlineRun,
    ListItem,
    ListLevel,
    ListNumbering,
    Mark,
    MarkType,
    Section,
    SectionSettings,
    SourceProperties,
    TableCell,
    TableContent,
    TableRow,
    plain_text_from_inline,
    target_for_element,
)
from app.parsers.docx_inline import (
    TRACKED_CHANGES_NOTE,
    NoteRegistry,
    control_of,
    Notes,
    ParagraphContent,
    ParagraphReader,
    RawRun,
    RunFormat,
    autolink,
    is_monospace,
)
from app.parsers.docx_comments import comment_threads
from app.parsers.docx_tables import TableStyles, cell_properties, row_properties, table_properties
from app.parsers.docx_pictures import picture_properties
from app.parsers.docx_styles import (
    Numbering,
    ParaProps,
    StyleResolver,
    TextProps,
    as_word_draws,
    extract_style_system,
    inherit_from_normal,
    para_props_of,
    safe_color,
    safe_font,
    section_break_of,
    w,
)
from app.security.files import UnsafeFileError, check_docx

_CONTENT_TYPE_ALIASES = {"image/jpg": "image/jpeg"}
_EMU_PER_TWIP = 635
_CHECKBOXES = {"☐": False, "□": False, "☑": True, "☒": True, "✓": True, "✔": True}
_CHECKLIST = "checklist"  # stands in for a numbering id: groups unnumbered checkbox paragraphs
# "Figure 1: ...", "Таблица 2.3 - ...": a label, a number, then a separator.
_CAPTION = re.compile(
    r"^\s*(фигура|фиг\.|figure|fig\.|таблица|табл\.|table|схема|диаграма|графика|снимка|chart|image|изображение)"
    r"\s*\d+(?:[.\-]\d+)*\s*[:.\-–—)]",
    re.IGNORECASE,
)
_LIST_STYLE_LEVEL = re.compile(r"^list (?:bullet|number|continue|paragraph)?\s*(\d)$", re.IGNORECASE)
_LIST_FAMILY = re.compile(r"^list (bullet|number)(?:\s*\d)?$", re.IGNORECASE)
_HEADING_STYLE = re.compile(r"^heading\s+(\d)$", re.IGNORECASE)

# What the editor can't show yet but an export to Word puts back (корекции.docx §11).
_UNSUPPORTED = FidelityPolicy.UNSUPPORTED
# The Word number formats the document model holds (models/document.py NumberFormat).
_LIST_FORMATS = frozenset({"decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman", "decimalZero", "russianLower", "russianUpper"})
_WORD_LEVELS = WORD_LEVELS
# Word's bullets drawn from symbol fonts, as the characters they show: (font, code) -> character.
_SYMBOL_BULLETS = {
    ("symbol", 0xB7): "•",
    ("symbol", 0xA8): "♦",
    ("wingdings", 0xA7): "▪",
    ("wingdings", 0x6E): "■",
    ("wingdings", 0x71): "❑",
    ("wingdings", 0x76): "❖",
    ("wingdings", 0xD8): "➢",
    ("wingdings", 0xFC): "✓",
    ("courier new", ord("o")): "◦",
}
_SYMBOL_FONTS = frozenset({"symbol", "wingdings", "wingdings 2", "wingdings 3", "webdings"})
_DEFAULT_BULLETS = DEFAULT_BULLETS  # the exporters' own, level by level
_DEFAULT_NUMBERS = DEFAULT_FORMATS


def _exported_anyway(level: ListLevel, index: int, ordered: bool) -> bool:
    """A level a Word export writes by itself at `index`: 1., a., i. in turn (the top one
    in the list's own format and start) or •, ◦, ▪, from 1, at no indent of its own or
    the exporters' (LEVEL_INDENT_TWIPS a level)."""
    if ordered and index == 0:
        same = level.format not in ("bullet", "none") and level.text == "%1."
    elif ordered:
        same = (level.format, level.text, level.start) == (_DEFAULT_NUMBERS[index % 3], f"%{index + 1}.", 1)
    else:
        same = (level.format, level.text, level.start) == ("bullet", _DEFAULT_BULLETS[index % 3], 1)
    indents = (level.indentCm, level.hangingCm) in (
        (None, None),
        (_twips_to_cm(LEVEL_INDENT_TWIPS * (index + 1)), _twips_to_cm(LEVEL_INDENT_TWIPS)),
    )
    return same and indents and not level.legal and level.restartAfter is None and level.suffix == "tab"


def _usual(levels: list[ListLevel], ordered: bool) -> bool:
    """Levels the exporters write anyway -- which the model then doesn't hold
    (ListNumbering.levels None)."""
    return all(_exported_anyway(level, index, ordered) for index, level in enumerate(levels))

_KEPT_NOTES = {
    "equation": "Equations show as linear text in the editor; exporting to Word puts the original equations back, unless their text is changed.",
    "field": "Word fields (dates, cross-references and the like) show the text they last had; exporting to Word puts the fields back.",
    "bookmark": "Bookmarks aren't shown in the editor; exporting to Word puts them back.",
    "link": "Links to places inside the document show as plain text in the editor; exporting to Word puts the links back.",
    "comment": "Comments aren't shown in the editor yet; exporting to Word puts them back, with their replies and which are resolved.",
}
_KEPT_NAMES = {
    "equation": "equations",
    "field": "Word fields",
    "bookmark": "bookmarks",
    "link": "links to places in the document",
    "comment": "comments",
}


def _around(text: str, fragment: dict) -> dict:
    """The text just before a content control and just after it: where it is once what
    is in it was changed -- filled in, chosen again (DOCX-023)."""
    return {"before": text[max(0, fragment["start"] - 40) : fragment["start"]], "after": text[fragment["end"] : fragment["end"] + 40]}


def _comments(docx_document) -> dict[str, dict]:
    """The document's comments by id: who wrote them, when, what they say, and their
    thread -- the comment each answers and whether it is resolved (DOCX-021)."""
    try:
        threads = comment_threads(docx_document.part)
    except Exception:  # noqa: BLE001 -- unreadable threads: the comments are kept without them
        threads = {}
    try:
        comments = {}
        for comment in docx_document.comments:
            comment_id = str(comment.comment_id)
            reply_to, done = threads.get(comment_id, (None, False))
            comments[comment_id] = {
                "author": comment.author or "",
                "initials": comment.initials or "",
                "date": comment.timestamp.isoformat() if comment.timestamp else None,
                "comment": comment.text or "",
                "commentId": comment_id,
                "replyTo": reply_to,
                "done": done,
            }
        return comments
    except Exception:  # noqa: BLE001 -- an unreadable comments part mustn't stop the import
        return {}


class DocxParseError(Exception):
    """Raised when the uploaded bytes aren't a readable .docx file."""


@dataclass
class _Block:
    """One future element, before its formatting rules are worked out (those
    need the style system, which needs to know which styles the blocks used)."""

    kind: ElementType
    style_id: str | None = None
    para: ParaProps = field(default_factory=ParaProps)  # effective: style, then direct
    text: TextProps = field(default_factory=TextProps)  # effective: style, then uniform run values
    inline: list[InlineRun] | None = None
    level: int | None = None
    items: list[ListItem] | None = None
    ordered: bool = False
    numbering: ListNumbering | None = None
    list_indent_levels: int = 0
    table: TableContent | None = None
    image: ImageContent | None = None
    image_alignment: str | None = None
    image_width_percent: float | None = None
    code: str | None = None
    # Fragments kept for DOCX export (equations, fields, bookmarks, links, comments).
    keep: list[dict] | None = None
    # A content control around blocks, where it starts and ends (DOCX-023): {"edge": "open",
    # "region", "properties", "endProperties"?} on its first block, {"edge": "close", "region"} on its last.
    controls: list[dict] = field(default_factory=list)
    picture_control: dict | None = None  # the picture content control an image is in
    # The indices of the body's children it was read from (Element.sourceBlocks).
    sources: tuple[int, ...] = ()
    # A section break's settings (Element.sectionBreak, DOCX-015).
    section: dict | None = None


def _picture_blocks(pictures: list[ImageContent]) -> list[Element] | None:
    """A list item's pictures as the blocks it holds after its text (DOCX-027)."""
    return [Element(type=ElementType.IMAGE, content="", image=image, order=index) for index, image in enumerate(pictures)] or None


# The kinds of block a paragraph becomes that carry what the import kept (_Block.keep).
_WITH_FRAGMENTS = (ElementType.PARAGRAPH, ElementType.HEADING, ElementType.CAPTION, ElementType.QUOTE, ElementType.FOOTNOTE)
# What Word keeps of a change made while tracking them (DOCX-022).
_REVISIONS = tuple(
    w(name)
    for name in (
        "ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange", "sectPrChange", "tblPrChange", "trPrChange",
        "tcPrChange", "tblGridChange", "numberingChange", "cellIns", "cellDel", "cellMerge",
    )
)


@dataclass
class _CellPart:
    """One thing a table cell holds, in order (DOCX-017): a paragraph's runs ("text"),
    a list item ("item"), a picture ("image"), a table ("table")."""

    kind: str
    runs: list[RawRun] = field(default_factory=list)
    style_id: str | None = None
    num_id: str | None = None
    level: int = 0
    ilvl: int = 0
    image: ImageContent | None = None
    table: TableContent | None = None
    pictures: list[ImageContent] = field(default_factory=list)  # a list item's


@dataclass
class DocxImport:
    document: Document
    # The notes about page setup, layout and styles only (columns, watermarks,
    # style values out of range), without the ones about content.
    style_notes: list[str]


# Whether this import turns web and e-mail addresses written as plain text into links
# (DOCX-026): off unless asked for -- Word links them only while one types, so a file's
# plain "see www.example.com" is what its author left.
_AUTOLINK: ContextVar[bool] = ContextVar("docx_autolink", default=False)


def import_docx(file_bytes: bytes, filename: str, title: str | None = None, *, autolink: bool = False) -> DocxImport:
    token = _AUTOLINK.set(autolink)
    try:
        return _import_docx(file_bytes, filename, title)
    finally:
        _AUTOLINK.reset(token)


def _import_docx(file_bytes: bytes, filename: str, title: str | None) -> DocxImport:
    # Whoever calls this, the package's limits hold before python-docx opens it (zip bombs).
    try:
        check_docx(file_bytes)
    except UnsafeFileError as exc:
        raise DocxParseError(str(exc)) from exc
    try:
        docx_document = DocxDocument(io.BytesIO(file_bytes))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError) as exc:
        raise DocxParseError(f"{filename!r} is not a valid .docx file") from exc

    importer = _Importer(docx_document)
    importer.read_body()
    document = importer.build(filename, title)
    return DocxImport(document=document, style_notes=importer.style_notes)


def parse_docx(file_bytes: bytes, filename: str, title: str | None = None, *, autolink: bool = False) -> Document:
    return import_docx(file_bytes, filename, title, autolink=autolink).document


class _Importer:
    def __init__(self, docx_document) -> None:
        self.docx = docx_document
        self.resolver = StyleResolver(docx_document)
        self.table_styles = TableStyles(self.resolver)
        self.numbering = Numbering(docx_document)
        self.notes = Notes()
        self.note_registry = NoteRegistry(docx_document)
        self.reader = ParagraphReader(
            self.resolver, docx_document.part, self.notes, self.note_registry, comments=_comments(docx_document)
        )
        self.attached: set[str] = set()  # keys of the kept fragments attached to an element
        self.open_fields: dict[str, str] = {}  # fields that began in an earlier paragraph: key -> region (DOCX-020)
        self.open_comments: dict[str, str] = {}  # comments that began in an earlier paragraph: key -> region (DOCX-021)
        self.control_count = 0  # content controls around blocks, for their regions (DOCX-023)
        self.blocks: list[_Block] = []
        self.pending_list: list[tuple[ParagraphContent, str, int, str | None]] = []  # (content, num_id, level, style)
        # Top-level items numbered so far per list instance: Word keeps counting
        # across a paragraph that interrupts a list.
        # How many numbers each list level has used so far, by what it numbers on with
        # (Numbering.counted_with), and the instances already met (a restart counts once).
        self.list_counts: dict[tuple[str, int], int] = {}
        self.list_instances: set[tuple[str, int]] = set()
        self.pending_drop_cap: list[RawRun] = []
        # Where in the body the blocks being read come from (Element.sourceBlocks):
        # the top-level child, plus any merged into it (a drop cap), plus a list's items.
        self.source: int | None = None
        self.merged_sources: set[int] = set()
        self.drop_cap_source: int | None = None
        self.list_sources: list[int] = []
        self.used_styles: dict[str, int] = {}
        self.style_notes: list[str] = []
        body = docx_document.element.body
        sect_pr = body.find(w("sectPr"))
        self.content_width_emu = _content_width_emu(sect_pr)
        self.next_section_start = _next_section_starts(body)

    # -- reading -------------------------------------------------------------

    def read_body(self) -> None:
        self._read_container(self.docx.element.body, top=True)
        self._flush_list()
        self.source, self.merged_sources = None, set()  # what follows (notes) isn't a body child
        self._mark_captions()
        self._append_notes()

    def _read_container(self, container: etree._Element, *, top: bool = False) -> None:
        for index, child in enumerate(container):
            if top:
                self.source, self.merged_sources = index, set()
            if child.tag == w("p"):
                self._paragraph(child)
            elif child.tag == w("tbl"):
                self._flush_list()
                self._table(child)
            elif child.tag == w("sdt"):
                content = child.find(w("sdtContent"))
                if content is not None:
                    self._flush_list()  # its blocks are its own, a list in it too
                    first = len(self.blocks)
                    self._read_container(content)
                    self._flush_list()
                    self._mark_control(child, first)
            elif child.tag == w("customXml"):
                self._read_container(child)

    def _mark_control(self, sdt: etree._Element, first: int) -> None:
        """A content control around the blocks read from `first` on: where it starts and
        ends, for a Word export to put it back around them (DOCX-023). One outside
        another starts before it and ends after it."""
        if sdt.find(w("sdtPr")) is None or first >= len(self.blocks):
            return
        self.control_count += 1
        region = f"control:{self.control_count}"
        self.blocks[first].controls.insert(0, {"edge": "open", "region": region, **control_of(sdt)})
        self.blocks[-1].controls.append({"edge": "close", "region": region})

    def _paragraph(self, p: etree._Element) -> None:
        ppr = p.find(w("pPr"))
        style_id = _style_id(ppr)
        content = self.reader.read(p)
        direct = para_props_of(ppr)

        if ppr is not None and ppr.find(w("framePr")) is not None and ppr.find(w("framePr")).get(w("dropCap")):
            self.pending_drop_cap.extend(content.runs)  # the big first letter, merged into the next paragraph
            self.drop_cap_source = self.source
            return
        if self.pending_drop_cap and content.runs:
            content.runs[:0] = self.pending_drop_cap
            self.pending_drop_cap = []
            if self.drop_cap_source is not None:
                self.merged_sources.add(self.drop_cap_source)

        break_before = content.page_break_before or self.resolver.page_break_before(style_id)
        if ppr is not None and ppr.find(w("pageBreakBefore")) is not None:
            break_before = bool(_on(ppr.find(w("pageBreakBefore"))))
        if break_before:
            self._flush_list()
            self._add(_Block(kind=ElementType.PAGE_BREAK))

        heading_level = self._heading_level(style_id, ppr)
        num_id, ilvl = self._numbering(style_id, ppr)
        if num_id is None and heading_level is None and content.text.lstrip()[:1] in _CHECKBOXES:
            num_id, ilvl = _CHECKLIST, 0  # checkbox paragraphs without bullets are a checklist too
        # A numbered paragraph holding only a picture is an item too: the picture is what it holds (DOCX-027).
        is_list_item = num_id is not None and heading_level is None and (content.text.strip() != "" or bool(content.drawings))
        if is_list_item:
            if self.pending_list and self.pending_list[-1][1] != num_id and not self._same_list_family(self.pending_list[-1][3], style_id):
                self._flush_list()
            level = ilvl + self._style_list_level(style_id)
            self.pending_list.append((content, num_id, level, style_id))
            if self.source is not None:
                self.list_sources.extend([self.source, *self.merged_sources])
        else:
            self._flush_list()
            if num_id is not None and num_id != _CHECKLIST and heading_level is None:
                # An empty numbered item still takes its number in Word: what follows keeps counting.
                key = self._count_key(num_id, ilvl + self._style_list_level(style_id))
                self.list_counts[key] = self.list_counts.get(key, 0) + 1
                self.notes.add("Empty numbered list items were left out; the numbers after them are kept.", "docx.list_numbering.empty_item")
            if heading_level is not None and num_id is not None:
                label = self.numbering.next_label(num_id, ilvl)
                if label and content.runs:
                    content.runs.insert(0, RawRun(f"{label} ", content.runs[0].fmt))
                    self.notes.add(
                        "Numbers Word gives headings became part of the headings' text; they won't renumber.",
                        "docx.numbered_headings",
                        content=True,
                    )
            self._text_paragraph(content, style_id, direct, heading_level)
            self._images(content, style_id, direct)

        for box in content.text_boxes:
            for box_paragraph in box:
                self._paragraph(box_paragraph)

        section_break = ppr.find(w("sectPr")) if ppr is not None else None
        if content.page_break_after:
            self._flush_list()
            self._add(_Block(kind=ElementType.PAGE_BREAK))
        if section_break is not None:  # the section ends here: a section break of its own (DOCX-015)
            self._flush_list()
            start = self.next_section_start.get(section_break, "nextPage")
            notes: list[str] = []
            self._add(_Block(kind=ElementType.SECTION_BREAK, section=section_break_of(section_break, start, self.docx, notes)))
            self.notes.extend(notes)

    def _text_paragraph(self, content: ParagraphContent, style_id: str | None, direct: ParaProps, heading_level: int | None) -> None:
        if not content.text.strip():
            self._close_comments_in(content.runs)
            if self._close_fields_in(content.runs):
                return  # a paragraph only ending a field: the export writes it again
            if content.horizontal_rule and not content.drawings:
                self._add(_Block(kind=ElementType.HORIZONTAL_RULE))
            elif not content.drawings and not content.text_boxes:
                self.notes.add("Empty paragraphs used for spacing were left out.", "docx.empty_paragraph")
            return
        style_para, style_text = self.resolver.paragraph_style(style_id)
        para = direct.over(style_para)
        lifted, runs = _lift(content.runs)
        text, released = _release(lifted.over(style_text), runs)
        runs = _carry(runs, released)
        self.used_styles[style_id or ""] = self.used_styles.get(style_id or "", 0) + 1

        visible = [run for run in runs if run.text.strip()]
        if heading_level is None and visible and all(is_monospace(run.fmt.font or text.font) for run in visible):
            code_text = content.text.strip("\n")
            self._add(_Block(kind=ElementType.CODE_BLOCK, style_id=style_id, para=para, text=text, code=code_text))
            return

        style_name = self.resolver.name_of(style_id).lower()
        if heading_level is not None:
            kind = ElementType.HEADING
        elif style_name == "caption":
            kind = ElementType.CAPTION
        elif style_name in ("quote", "intense quote") or "quote" in style_name:
            kind = ElementType.QUOTE
        elif style_name in ("footnote text", "endnote text"):
            # In the body only when a note was moved there -- as the app's own DOCX export does.
            kind = ElementType.FOOTNOTE
        else:
            kind = ElementType.PARAGRAPH
        self._add(
            _Block(
                kind=kind,
                style_id=style_id,
                para=para,
                text=text,
                inline=_inline(runs, text.font),
                level=heading_level,
                keep=self._attach(runs) or None,
            )
        )

    def _attach(self, runs: list[RawRun]) -> list[dict]:
        """The kept fragments in this paragraph, each with where its text starts
        and ends in the element's content (a bookmark or comment that goes on into
        a later paragraph ends here). A fragment only half in this paragraph (a
        field running across paragraphs) can't be placed and isn't attached."""
        position = 0
        opened: dict[str, dict] = {}
        fragments: list[tuple[str, dict]] = []
        for run in runs:
            if run.keep is None:
                position += len(run.text)
                continue
            key = run.keep["key"]
            if run.keep["edge"] == "start":
                opened[key] = {name: value for name, value in run.keep.items() if name not in ("key", "edge")} | {"start": position}
            elif key in opened:
                fragments.append((key, opened.pop(key) | {"end": position}))
            elif key in self.open_fields:  # a field that began in an earlier paragraph ends here (DOCX-020)
                fragments.append((key, {"kind": "field_close", "region": self.open_fields.pop(key), "start": position, "end": position}))
            elif key in self.open_comments:  # a comment that began in an earlier paragraph ends here (DOCX-021)
                fragments.append((key, {"kind": "comment_close", "region": self.open_comments.pop(key), "start": position, "end": position}))
        for key, fragment in opened.items():
            if fragment["kind"] == "bookmark":
                fragments.append((key, fragment | {"end": fragment["start"]}))
            elif fragment["kind"] == "comment":  # it runs on into later paragraphs, to where it ends (DOCX-021)
                self.open_comments[key] = key
                fragments.append((key, fragment | {"end": position, "region": key}))
        for key, fragment in list(opened.items()):
            if fragment["kind"] == "field":  # it runs on into later paragraphs: where it starts (DOCX-020)
                self.open_fields[key] = key
                fragments.append((key, {"kind": "field_open", "instr": fragment["instr"], "region": key, "start": fragment["start"], "end": fragment["start"]}))
        text = "".join(run.text for run in runs if run.keep is None)
        self.attached.update(key for key, _ in fragments)
        return [
            fragment | {"text": text[fragment["start"] : fragment["end"]]} | (_around(text, fragment) if fragment["kind"] == "control" else {})
            for _, fragment in sorted(fragments, key=lambda item: item[1]["start"])
        ]

    def _close_comments_in(self, runs: list[RawRun]) -> None:
        """Comments that ran on from earlier paragraphs and end in this one, which is left out
        (empty): each ends where the block before does (DOCX-021)."""
        previous = next((block for block in reversed(self.blocks) if block.kind in _WITH_FRAGMENTS), None)
        for run in runs:
            if not (run.keep and run.keep["edge"] == "end" and run.keep["key"] in self.open_comments and previous is not None):
                continue
            region = self.open_comments.pop(run.keep["key"])
            opener = next((kept for kept in previous.keep or [] if kept.get("kind") == "comment" and kept.get("region") == region), None)
            if opener is not None:
                del opener["region"]  # it began in that block: it ends where that block does
            else:
                at = len(plain_text_from_inline(previous.inline or []))
                previous.keep = [*(previous.keep or []), {"kind": "comment_close", "region": region, "start": at, "end": at, "text": ""}]

    def _settle_open_comments(self) -> None:
        """Comments whose end was never reached where fragments are kept -- in a list, a
        table or code: they end where the paragraph they begin in does, and the report says so."""
        if not self.open_comments:
            return
        for block in self.blocks:
            for kept in block.keep or []:
                if kept.get("kind") == "comment" and kept.get("region") in self.open_comments.values():
                    del kept["region"]
        self.notes.add(
            "Comments running on into a list, a table or code cover only the text before it.",
            "docx.comment_range",
            FidelityPolicy.LOSSY,
        )
        self.open_comments.clear()

    def _close_fields_in(self, runs: list[RawRun]) -> bool:
        """Fields that ran on from earlier paragraphs and end in this one, which is left
        out (empty): each one's end goes on the element before, in a paragraph of its
        own after it, as Word ends a table of contents or a bibliography (DOCX-020)."""
        previous = next((block for block in reversed(self.blocks) if block.kind in _WITH_FRAGMENTS), None)
        closed = False
        for run in runs:
            if run.keep and run.keep["edge"] == "end" and run.keep["key"] in self.open_fields and previous is not None:
                region = self.open_fields.pop(run.keep["key"])
                at = len(plain_text_from_inline(previous.inline or []))
                previous.keep = [*(previous.keep or []), {"kind": "field_close", "region": region, "start": at, "end": at, "text": "", "paragraph": True}]
                closed = True
        return closed

    def _images(self, content: ParagraphContent, style_id: str | None, direct: ParaProps) -> None:
        if not content.drawings:
            return
        alignment = direct.over(self.resolver.paragraph_style(style_id)[0]).alignment
        for index, drawing in enumerate(content.drawings):
            image, width_emu, floating = self._image(drawing)
            if image is None:
                continue
            if floating:
                self._note_floating()
            width = None
            if width_emu and self.content_width_emu:
                width = round(min(100.0, width_emu / self.content_width_emu * 100), 1)
            self._add(
                _Block(
                    kind=ElementType.IMAGE,
                    image=image,
                    image_alignment=alignment if alignment in ("left", "center", "right") else None,
                    image_width_percent=width,
                    picture_control=content.drawing_controls.get(index),
                )
            )

    def _pictures(self, drawings: list[etree._Element]) -> list[ImageContent]:
        """A paragraph's pictures, in order; a floating one is noted as shown in line."""
        pictures = []
        for drawing in drawings:
            image, _, floating = self._image(drawing)
            if image is not None:
                pictures.append(image)
                if floating:
                    self._note_floating()
        return pictures

    def _note_floating(self) -> None:
        self.notes.add(
            "Floating pictures are shown in line with the text here and in a PDF; a Word export keeps where they float "
            "and how text wraps around them.",
            "docx.image.floating",
            FidelityPolicy.DETECTED_NOT_EDITABLE,
        )

    def _image(self, drawing: etree._Element) -> tuple[ImageContent | None, int | None, bool]:
        """The picture as an inline data: URI (image_assets.py moves it into asset
        storage before the document is saved), its width in EMU, and whether it floated."""
        try:
            blip = next(drawing.iter(qn("a:blip")), None)
            if blip is None:
                # No picture at all: a chart or SmartArt (the import report names those),
                # a text box (read as paragraphs) or a drawn shape.
                graphic = next(drawing.iter(qn("a:graphicData")), None)
                uri = graphic.get("uri", "") if graphic is not None else ""
                if uri.endswith(("wordprocessingShape", "wordprocessingGroup", "wordprocessingCanvas")) and next(drawing.iter(w("txbxContent")), None) is None:
                    self.notes.add("Shapes (lines, arrows, drawn figures) weren't imported.", "docx.shape", _UNSUPPORTED, content=True)
                return None, None, False
            rel_id = blip.get(qn("r:embed"))
            if not rel_id:
                self.notes.add("A linked (not embedded) image was not imported.", "docx.image.linked", _UNSUPPORTED, content=True)
                return None, None, False
            part = self.docx.part.related_parts[rel_id]
            content_type = (part.content_type or "").lower()
            content_type = _CONTENT_TYPE_ALIASES.get(content_type, content_type)
            if content_type not in WEB_IMAGE_TYPES:
                self.notes.add(f"An image in an unsupported format ({content_type or 'unknown'}) was not imported.", "docx.image.format", _UNSUPPORTED, content=True)
                return None, None, False
            extent = next(drawing.iter(qn("wp:extent")), None)
            width = int(extent.get("cx")) if extent is not None and (extent.get("cx") or "").isdigit() else None
            floating = drawing.find(qn("wp:anchor")) is not None
            encoded = base64.b64encode(part.blob).decode("ascii")
            # Its name, alt text and title, size, crop, turn and flips, and where it floats (DOCX-018).
            picture = picture_properties(drawing)
            return ImageContent(src=f"data:{content_type};base64,{encoded}", mime=content_type, **picture), width, floating
        except Exception:  # noqa: BLE001 -- untrusted file; one broken picture must not abort the import
            self.notes.add("An image could not be read and was not imported.", "docx.image.unreadable", _UNSUPPORTED, content=True)
            return None, None, False

    def _heading_level(self, style_id: str | None, ppr: etree._Element | None) -> int | None:
        name = self.resolver.name_of(style_id)
        if name.lower() == "title":
            return 1
        match = _HEADING_STYLE.match(name)
        if match:
            return min(max(int(match.group(1)), 1), 6)
        outline = ppr.find(w("outlineLvl")) if ppr is not None else None
        level = None
        if outline is not None and (outline.get(w("val")) or "").isdigit():
            level = int(outline.get(w("val")))
        elif style_id:
            level = self.resolver.outline_level(style_id)
        return level + 1 if level is not None and 0 <= level <= 5 else None

    def _numbering(self, style_id: str | None, ppr: etree._Element | None) -> tuple[str | None, int]:
        num_id = ilvl = None
        num_pr = ppr.find(w("numPr")) if ppr is not None else None
        if num_pr is not None:
            num_id_el, ilvl_el = num_pr.find(w("numId")), num_pr.find(w("ilvl"))
            num_id = num_id_el.get(w("val")) if num_id_el is not None else None
            ilvl = ilvl_el.get(w("val")) if ilvl_el is not None else None
        if num_id is None:
            style_num, style_ilvl = self.resolver.numbering_of_style(style_id)
            num_id = style_num
            ilvl = ilvl if ilvl is not None else style_ilvl
        if num_id in (None, "0"):  # numId 0 switches inherited numbering off
            return None, 0
        return num_id, int(ilvl) if ilvl and ilvl.isdigit() else 0

    def _style_list_level(self, style_id: str | None) -> int:
        """"List Bullet 2" is Word's second-level bullet even though its own
        numbering starts at level 0."""
        match = _LIST_STYLE_LEVEL.match(self.resolver.name_of(style_id))
        return max(int(match.group(1)) - 1, 0) if match else 0

    def _same_list_family(self, style_a: str | None, style_b: str | None) -> bool:
        """Word's built-in list styles come in families -- "List Bullet", "List
        Bullet 2", "List Bullet 3" -- and each level has numbering of its own, so
        moving to another style of one family is the same list going a level
        deeper or back, not a new list. (The same style with other numbering
        is a new list.)"""
        if style_a == style_b:
            return False
        family_a = _LIST_FAMILY.match(self.resolver.name_of(style_a))
        family_b = _LIST_FAMILY.match(self.resolver.name_of(style_b))
        return family_a is not None and family_b is not None and family_a.group(1).lower() == family_b.group(1).lower()

    def _flush_list(self) -> None:
        if not self.pending_list:
            return
        entries, self.pending_list = self.pending_list, []
        sources, self.list_sources = tuple(sorted(set(self.list_sources))), []
        first_content, num_id, first_level, style_id = entries[0]
        bullet = self.numbering.is_bullet(num_id, first_level)
        ordered = (not bullet) if bullet is not None else "number" in self.resolver.name_of(style_id).lower()
        lifted, _ = _lift([run for content, *_ in entries for run in content.runs])
        style_para, style_text = self.resolver.paragraph_style(style_id)
        text, released = _release(lifted.over(style_text), [run for content, *_ in entries for run in content.runs])
        min_level = min(level for _, _, level, _ in entries)
        items: list[ListItem] = []
        checkbox_items = 0
        for content, _, level, _ in entries:
            _, runs = _lift(content.runs, only=lifted)
            runs = _carry(runs, released)
            runs, checked = _strip_checkbox(runs)
            checkbox_items += checked is not None
            items.append(ListItem(inline=_inline(runs, text.font), level=level - min_level, checked=checked, blocks=_picture_blocks(self._pictures(content.drawings))))
        if 0 < checkbox_items < len(items):
            for item in items:  # a checklist is all checkboxes or none
                item.checked = item.checked if item.checked is not None else False
        self.used_styles[style_id or ""] = self.used_styles.get(style_id or "", 0) + len(items)
        ordered = ordered and checkbox_items == 0
        numbering = self._list_numbering(entries, min_level, items, ordered) if checkbox_items == 0 else None
        self._add(
            _Block(
                kind=ElementType.LIST,
                style_id=style_id,
                para=style_para,
                text=text,
                items=items,
                ordered=ordered,
                numbering=numbering,
                list_indent_levels=min_level,
            ),
            sources,
        )

    def _list_numbering(self, entries: list, top: int, items: list[ListItem], ordered: bool) -> ListNumbering | None:
        """How a list counts, as Word would number it -- continuing where the same list
        left off before an interruption -- with each of its levels from the list's top
        one (DOCX-016): format, label, start, indent, legal numbering, restart, what
        follows the label; a bullet level's bullet. A level its items are at is defined
        where its first item's numbering says ("List Bullet 2" has its own); the others
        where the list's first item's does. Levels at the end that a Word export writes
        anyway aren't kept."""
        # Where each level is defined: (numbering, its Word level). The list's first item's
        # numbering for all of them; then, for a level items are at, its first item's.
        _, num_id, _, first_style = entries[0]
        offset = top - self._style_list_level(first_style)  # that numbering's Word level for the list's top
        where = {index: (num_id, offset + index) for index in range(_WORD_LEVELS) if 0 <= offset + index < _WORD_LEVELS}
        met: set[int] = set()
        for _, entry_num, entry_level, style_id in entries:
            if entry_level - top not in met:
                met.add(entry_level - top)
                where[entry_level - top] = (entry_num, entry_level - self._style_list_level(style_id))
        definitions = [self.numbering.level(*where[index]) if index in where else None for index in range(_WORD_LEVELS)]
        if definitions[0] is None:
            return None
        levels = [
            self._list_level(definition, where[index][1] - index) if definition is not None else ListLevel()
            for index, definition in enumerate(definitions)
        ]
        while len(levels) > 1 and (definitions[len(levels) - 1] is None or _exported_anyway(levels[-1], len(levels) - 1, ordered)):
            levels.pop()
        start = 1
        if ordered:
            key = self._count_key(num_id, top)
            earlier = self.list_counts.get(key, 0)
            self.list_counts[key] = earlier + sum(1 for item in items if item.level == 0)
            start = self.numbering.start(num_id, top) + earlier
        used = [(level, definitions[level]) for level in sorted({item.level for item in items}) if level < len(levels) and definitions[level]]
        self._note_numbering(levels, used)
        top_format = levels[0].format if levels[0].format in _LIST_FORMATS else "decimal"
        numbering = ListNumbering(start=max(0, min(start, 999_999)), format=top_format, levels=None if _usual(levels, ordered) else levels)
        return None if numbering == ListNumbering() else numbering

    def _count_key(self, num_id: str, level: int) -> tuple[str, int]:
        """Where a list level's count is kept: every instance of one definition numbers on
        together, as in Word, and one that restarts the level starts it again from zero
        the first time it's met."""
        key = (self.numbering.counted_with(num_id), level)
        if (num_id, level) not in self.list_instances:
            self.list_instances.add((num_id, level))
            if self.numbering.restarts(num_id, level):
                self.list_counts[key] = 0
        return key

    def _list_level(self, definition, top: int) -> ListLevel:
        """A Word level as the model's, its label's references (%n) counted from the list's top."""
        if definition.fmt == "bullet":
            text = self._bullet(definition)
        else:
            text = re.sub(r"%([1-9])", lambda match: f"%{int(match.group(1)) - top}" if int(match.group(1)) > top else "", definition.text)
        restart = definition.restart
        if restart is not None and restart > 0:
            restart = restart - top if restart > top else 0  # after a level above the list: never within it
        return ListLevel(
            format=definition.fmt if definition.fmt in _LIST_FORMATS or definition.fmt in ("bullet", "none") else "decimal",
            text="".join(character for character in text if ord(character) >= 32)[:50],
            start=definition.start,
            indentCm=_twips_to_cm(definition.indent),
            hangingCm=_twips_to_cm(definition.hanging),
            legal=definition.legal,
            restartAfter=restart,
            suffix=definition.suffix,
        )

    def _bullet(self, definition) -> str:
        """A bullet level's bullet: a character drawn from a symbol font as the one it shows."""
        font = (definition.font or "").lower()
        character = definition.text[:1] or "•"
        code = ord(character) - 0xF000 if 0xF000 <= ord(character) <= 0xF0FF else ord(character)
        shown = _SYMBOL_BULLETS.get((font, code))
        if shown is not None:
            return shown
        if font in _SYMBOL_FONTS or 0xF000 <= ord(character) <= 0xF0FF:
            self.notes.add("Bullets drawn from symbol fonts the app doesn't know are shown and exported as •.", "docx.list_numbering.bullet_font")
            return "•"
        return definition.text[:5]

    def _note_numbering(self, levels: list[ListLevel], used: list) -> None:
        """What nothing shows of a list's levels: a number style the app doesn't have.
        Everything else of them -- labels, multi-level numbers, bullets, 01 and а б в,
        indents -- is kept, shown here and in both exports (DOCX-016)."""
        for _, definition in used:
            if definition.fmt not in _LIST_FORMATS and definition.fmt not in ("bullet", "none"):
                self.notes.add(
                    "Lists numbered in a style the app doesn't have (first, one, 一 二...) are numbered 1, 2, 3.",
                    "docx.list_numbering.format",
                    content=True,
                )

    def _table(self, tbl: etree._Element) -> None:
        table, text = self._table_content(tbl, lift=True)
        self._add(_Block(kind=ElementType.TABLE, text=text, table=table))

    def _table_content(self, tbl: etree._Element, *, lift: bool) -> tuple[TableContent, TextProps]:
        """A table as the model holds it, and the look its text shares. A cell holding
        more than one plain paragraph -- several paragraphs, a list, a picture, a table --
        holds them as its blocks (DOCX-017). `lift`: the font, size and colour its text
        shares are the table's look (a table in the body); a table inside a cell keeps
        them on its runs, since blocks in a cell have no look of their own."""
        rows: list[TableRow] = []
        open_vertical: dict[int, TableCell] = {}  # grid column -> cell still spanning down
        all_runs: list[RawRun] = []
        column_alignments: dict[int, set[str | None]] = {}
        cell_alignments: list[tuple[TableCell, int, str | None]] = []
        cell_parts: list[tuple[TableCell, list[_CellPart]]] = []
        # The table's geometry and look (DOCX-017): its style's, under its own.
        properties = table_properties(tbl, self.table_styles)
        style_look = properties.pop("_style_look")
        shows = properties.get("look") or {"firstRow": True, "lastRow": False, "firstColumn": True, "lastColumn": False, "bandedRows": True, "bandedColumns": False}
        styled_first_row = style_look.first_row and shows["firstRow"]
        if properties.get("floating"):
            self.notes.add(
                "Tables text flows around are shown in line with the text here and in a PDF; a Word export keeps where they float.",
                "docx.table.floating",
                FidelityPolicy.DETECTED_NOT_EDITABLE,
            )
        if style_look.by_position and (shows["lastRow"] or shows["firstColumn"] or shows["lastColumn"] or shows["bandedRows"] or shows["bandedColumns"]):
            self.notes.add(
                "Colours and bold a table's style gives by position -- banded rows, a first or last column, a last row -- aren't "
                "shown here or in a PDF; a Word export written into the original keeps them.",
                "docx.table.style_look",
            )
        # A row deleted while changes were tracked: as accepted, it is gone (DOCX-022).
        kept_rows = [tr for tr in tbl.findall(w("tr")) if tr.find(f"{w('trPr')}/{w('del')}") is None]
        if len(kept_rows) < len(tbl.findall(w("tr"))):
            self.notes.add(TRACKED_CHANGES_NOTE, "docx.tracked_changes", content=True)
        for row_index, tr in enumerate(kept_rows):
            cells: list[TableCell] = []
            column = 0
            row_values = row_properties(tr)
            # A header row: one Word repeats on each page, or the first row as the table's style draws it.
            header_row = bool(row_values.get("repeatHeader")) or (row_index == 0 and styled_first_row)
            for tc in _row_cells(tr):
                tc_pr = tc.find(w("tcPr"))
                span = _int_val(tc_pr.find(w("gridSpan")) if tc_pr is not None else None, 1)
                v_merge = tc_pr.find(w("vMerge")) if tc_pr is not None else None
                if v_merge is not None and v_merge.get(w("val"), "continue") != "restart" and column in open_vertical:
                    open_vertical[column].rowspan += 1
                    column += span
                    continue
                parts, alignment = self._cell_parts(tc)
                shading = tc_pr.find(w("shd")) if tc_pr is not None else None
                background = safe_color(_hex(shading.get(w("fill")))) if shading is not None else None
                if row_index == 0 and styled_first_row:
                    background = background or safe_color(style_look.first_row_fill)
                    if style_look.first_row_bold:  # the style's first row is bold where the run doesn't say otherwise
                        for part in parts:
                            part.runs = [run if run.fmt.bold or "bold" in run.fmt.turned_off else replace(run, fmt=replace(run.fmt, bold=True)) for run in part.runs]
                cell = TableCell(inline=[], header=header_row, colspan=span, background=background, **cell_properties(tc_pr))
                cell_parts.append((cell, parts))
                all_runs.extend(run for part in parts for run in part.runs)
                column_alignments.setdefault(column, set()).add(alignment)
                cell_alignments.append((cell, column, alignment))
                if v_merge is not None:
                    open_vertical[column] = cell
                else:
                    for covered in range(column, column + span):
                        open_vertical.pop(covered, None)
                cells.append(cell)
                column += span
            rows.append(TableRow(cells=cells, **row_values))
        lifted = _lift(all_runs)[0] if lift else TextProps()
        base_text = self.resolver.paragraph_style(None)[1]
        text = lifted.over(base_text)
        for cell, parts in cell_parts:
            cell.inline, cell.blocks = self._cell_body(parts, lifted, text.font)
        width = max((sum(cell.colspan for cell in row.cells) for row in rows), default=0)
        alignments = [
            next(iter(values)) if len(values := column_alignments.get(index, {None})) == 1 else None for index in range(width)
        ]
        for cell, column, alignment in cell_alignments:  # a cell whose column's cells differ keeps its own (EDIT-011)
            if alignment in ("left", "center", "right", "justify") and column < width and alignments[column] is None:
                cell.align = alignment
        table = TableContent(
            rows=rows,
            hasHeaderRow=any(cell.header for row in rows[:1] for cell in row.cells),
            alignments=alignments if any(alignments) else None,
            headerBold=False,
            **properties,
        )
        return table, text

    def _cell_parts(self, container: etree._Element) -> tuple[list[_CellPart], str | None]:
        """What a cell holds, in order -- paragraphs, list items, pictures, tables (read
        the same way, recursively) -- and its first paragraph's alignment."""
        parts: list[_CellPart] = []
        alignment: str | None = None
        first = True
        for child in container:
            if child.tag == w("p"):
                ppr = child.find(w("pPr"))
                style_id = _style_id(ppr)
                content = self.reader.read(child)
                if first:
                    alignment = para_props_of(ppr).alignment
                    first = False
                num_id, ilvl = self._numbering(style_id, ppr)
                if num_id is not None and self._heading_level(style_id, ppr) is None and (content.text.strip() or content.drawings):
                    # A list item, its pictures with it (DOCX-027).
                    level = ilvl + self._style_list_level(style_id)
                    parts.append(_CellPart("item", content.runs, style_id, num_id, level, ilvl, pictures=self._pictures(content.drawings)))
                else:
                    if content.text.strip() or not content.drawings:
                        parts.append(_CellPart("text", content.runs, style_id))
                    # At the size each is drawn at (ImageContent.widthCm).
                    parts.extend(_CellPart("image", image=image) for image in self._pictures(content.drawings))
                for box in content.text_boxes:
                    parts.extend(_CellPart("text", self.reader.read(paragraph).runs, _style_id(paragraph.find(w("pPr")))) for paragraph in box)
            elif child.tag == w("tbl"):
                table, _ = self._table_content(child, lift=False)
                parts.append(_CellPart("table", table=table))
                first = False
            elif child.tag in (w("sdt"), w("customXml")):
                inner = child.find(w("sdtContent")) if child.tag == w("sdt") else child
                if inner is not None:
                    more, inner_alignment = self._cell_parts(inner)
                    if first and more:
                        alignment, first = inner_alignment, False
                    parts.extend(more)
        return parts, alignment

    def _cell_body(self, parts: list[_CellPart], lifted: TextProps, font: str | None) -> tuple[list[InlineRun], list[Element] | None]:
        """A cell's text, and its blocks when it holds more than one plain paragraph: the
        paragraphs, lists, pictures and tables, in order (their plain text is its text)."""
        if not parts:
            return [], None
        if len(parts) == 1 and parts[0].kind == "text":
            return _inline(_lift(parts[0].runs, only=lifted)[1], font), None
        blocks: list[Element] = []
        pending: list[_CellPart] = []

        def flush() -> None:
            if pending:
                blocks.append(self._cell_list(list(pending), lifted, font, order=len(blocks)))
                pending.clear()

        for part in parts:
            if part.kind == "item":
                if pending and pending[-1].num_id != part.num_id:
                    flush()
                pending.append(part)
                continue
            flush()
            if part.kind == "text":
                inline = _inline(_lift(part.runs, only=lifted)[1], font)
                blocks.append(Element(type=ElementType.PARAGRAPH, content=plain_text_from_inline(inline), inline=inline, order=len(blocks)))
            elif part.kind == "image":
                blocks.append(Element(type=ElementType.IMAGE, content="", image=part.image, order=len(blocks)))
            elif part.kind == "table":
                content = "\n".join(" | ".join(plain_text_from_inline(cell.inline) for cell in row.cells) for row in part.table.rows)
                blocks.append(Element(type=ElementType.TABLE, content=content, table=part.table, order=len(blocks)))
        flush()
        text = "\n".join(block.content for block in blocks if block.content)
        return ([InlineRun(text=text)] if text else []), blocks

    def _cell_list(self, items_parts: list[_CellPart], lifted: TextProps, font: str | None, *, order: int) -> Element:
        """A list inside a cell, numbered as Word numbers it (DOCX-016)."""
        top = min(part.level for part in items_parts)
        items = [
            ListItem(inline=_inline(_lift(part.runs, only=lifted)[1], font), level=part.level - top, blocks=_picture_blocks(part.pictures))
            for part in items_parts
        ]
        first = items_parts[0]
        bullet = self.numbering.is_bullet(first.num_id, first.ilvl)
        ordered = (not bullet) if bullet is not None else "number" in self.resolver.name_of(first.style_id).lower()
        entries = [(None, part.num_id, part.level, part.style_id) for part in items_parts]
        numbering = self._list_numbering(entries, top, items, ordered)
        content = "\n".join(plain_text_from_inline(item.inline) for item in items)
        return Element(type=ElementType.LIST, content=content, listItems=items, ordered=ordered, numbering=numbering, order=order)

    def _mark_captions(self) -> None:
        """"Фигура 1: ..." right before or after a picture or table is its caption."""
        for index, block in enumerate(self.blocks):
            if block.kind != ElementType.PARAGRAPH or not block.inline:
                continue
            if not _CAPTION.match(plain_text_from_inline(block.inline)):
                continue
            neighbours = [self.blocks[i].kind for i in (index - 1, index + 1) if 0 <= i < len(self.blocks)]
            if ElementType.IMAGE in neighbours or ElementType.TABLE in neighbours:
                block.kind = ElementType.CAPTION

    def _append_notes(self) -> None:
        for kind, note_id, label in self.note_registry.referenced:
            runs: list[RawRun] = [RawRun(label, RunFormat(superscript=True)), RawRun(" ", RunFormat())]
            for index, paragraph in enumerate(self.note_registry.body(kind, note_id)):
                if index:
                    runs.append(RawRun("\n", RunFormat()))
                runs.extend(self.reader.read(paragraph).runs)
            lifted, own = _lift(runs[2:])
            self._add(_Block(kind=ElementType.FOOTNOTE, text=lifted, inline=_inline(runs[:2] + own, lifted.font)))

    def _add(self, block: _Block, sources: tuple[int, ...] | None = None) -> None:
        if sources is not None:
            block.sources = sources
        elif self.source is not None:
            block.sources = tuple(sorted({self.source, *self.merged_sources}))
        self.blocks.append(block)

    # -- building ------------------------------------------------------------

    def build(self, filename: str, title: str | None) -> Document:
        quote_style = self._most_used(lambda name: "quote" in name)
        list_style = self._most_used_list_style()
        caption_style = self.resolver.id_for_name("caption") if self.used_styles.get(self.resolver.id_for_name("caption") or "-") else None
        styles = extract_style_system(self.docx, self.resolver, quote_style=quote_style, list_style=list_style)
        if caption_style is None:
            # No real Caption-style paragraph: captions found by their wording look like body text.
            styles.style_system = styles.style_system.model_copy(update={"captions": styles.style_system.paragraph})
            styles.base["Caption"] = styles.base["Paragraph"]
        styles.style_system = inherit_from_normal(styles.style_system)
        self.notes.extend(styles.notes)
        self.style_notes = list(styles.notes)

        self._settle_open_comments()
        section = Section(order=0)
        elements: list[Element] = []
        rules: list[FormattingRule] = []
        for block in self.blocks:
            element = self._element(block, section.id, len(elements))
            elements.append(element)
            rules.extend(self._element_rules(element, block, styles.base))
        self._note_kept_fragments()

        tracked = next(self.docx.element.body.iter(*_REVISIONS), None) is not None
        if tracked and TRACKED_CHANGES_NOTE not in self.notes.as_list():  # formatting changes only
            self.notes.add(TRACKED_CHANGES_NOTE, "docx.tracked_changes", content=True)
        shown = title or self._title(elements, filename)
        properties = self._source_properties()
        if properties is not None:
            properties.importedTitle = shown[:500]
        document = Document(
            metadata=DocumentMetadata(
                title=shown,
                sourceType="uploaded_docx",
                originalFilename=filename,
                sourceProperties=properties,
            ),
            sections=[section],
            elements=elements,
            lastSection=self._last_section(),
            evenAndOddHeaders=bool(self.docx.settings.odd_and_even_pages_header_footer),
            trackedChanges="kept" if tracked else None,
            unsupportedFeatures=self.notes.as_list(),
            importReport=FidelityReport(stage=FidelityStage.IMPORT, sourceType="docx", items=self.notes.report_items()),
        )
        document.formattingRules = [
            *DEFAULT_RULES,
            *compile_rules(styles.style_system, priority=Priority.SOURCE_DOCUMENT, source=SOURCE_DOCUMENT_SOURCE),
            *rules,
        ]
        recompute_styles(document)
        return document

    # What Document.lastSection holds of the last section: DocumentSettings has its page
    # setup and main header and footer (DOCX-015).
    _LAST_SECTION_KEYS = (
        "firstHeader",
        "firstFooter",
        "evenHeader",
        "evenFooter",
        "differentFirstPage",
        "headerDistanceCm",
        "footerDistanceCm",
        "columns",
        "columnSpacingCm",
        "pageNumberStart",
        "pageNumberFormat",
    )

    def _last_section(self) -> SectionSettings | None:
        body = self.docx.element.body
        sect_pr = body.find(w("sectPr"))
        if sect_pr is None:
            return None
        notes: list[str] = []
        earlier = next(body.iter(w("sectPr")), None) is not sect_pr  # a section before, which "linked" would show
        values = {
            key: value
            for key, value in section_break_of(sect_pr, "nextPage", self.docx, notes).items()
            if key in self._LAST_SECTION_KEYS or (earlier and key in ("header", "footer") and value == "")
        }
        self.notes.extend(notes)
        return SectionSettings.model_validate(values) if values else None

    def _note_kept_fragments(self) -> None:
        kept = {self.reader.kept[key] for key in self.attached}
        for kind in _KEPT_NOTES:
            if kind in kept:
                self.notes.add(_KEPT_NOTES[kind], f"docx.{kind}", FidelityPolicy.DETECTED_NOT_EDITABLE)
        lost_kinds = {kind for key, kind in self.reader.kept.items() if key not in self.attached}
        lost = [kind for kind in _KEPT_NOTES if kind in lost_kinds]
        if lost:
            names = [_KEPT_NAMES[kind] for kind in lost]
            listed = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
            self.notes.add(f"{listed[0].upper()}{listed[1:]} inside lists, tables, footnotes or code were kept only as their text.", "docx.preserved.flattened")

    def _most_used(self, predicate) -> str | None:
        candidates = [
            (count, style_id) for style_id, count in self.used_styles.items() if style_id and predicate(self.resolver.name_of(style_id).lower())
        ]
        return max(candidates)[1] if candidates else None

    def _most_used_list_style(self) -> str | None:
        counts: dict[str, int] = {}
        for block in self.blocks:
            if block.kind == ElementType.LIST and block.style_id and block.items:
                counts[block.style_id] = counts.get(block.style_id, 0) + len(block.items)
        return max(counts, key=counts.get) if counts else None

    def _source_properties(self) -> SourceProperties | None:
        """The file's author, dates, subject and the like (docProps/core.xml)."""
        try:
            core = self.docx.core_properties
        except Exception:  # noqa: BLE001 -- a broken properties part mustn't stop the import
            return None

        def text(value, limit: int = 255) -> str | None:
            value = (value or "").strip() if isinstance(value, str) else ""
            return value[:limit] or None

        properties = SourceProperties(
            author=text(core.author),
            lastModifiedBy=text(core.last_modified_by),
            created=core.created,
            modified=core.modified,
            subject=text(core.subject),
            keywords=text(core.keywords),
            description=text(core.comments, 2000),
            category=text(core.category),
            title=text(core.title, 500) or "",  # "": the file has none, and gets none back
        )
        return properties

    def _title(self, elements: list[Element], filename: str) -> str:
        if elements and elements[0].type == ElementType.HEADING and elements[0].content.strip():
            return elements[0].content.strip()[:500]
        core_title = (self.docx.core_properties.title or "").strip()
        return core_title[:500] if core_title else filename

    def _element(self, block: _Block, section_id: str, order: int) -> Element:
        common = {"parentId": section_id, "order": order, "confidence": 1.0, "sourceBlocks": list(block.sources) or None}
        preserved = {
            **({"ooxml": block.keep} if block.keep else {}),
            **({"controls": block.controls} if block.controls else {}),  # DOCX-023
            **({"control": block.picture_control} if block.picture_control else {}),
        }
        if preserved:
            common["preservedAttributes"] = preserved
        if block.kind == ElementType.LIST:
            content = "\n".join(plain_text_from_inline(item.inline) for item in block.items or [])
            return Element(
                type=ElementType.LIST, content=content, listItems=block.items, ordered=block.ordered, numbering=block.numbering, **common
            )
        if block.kind == ElementType.TABLE:
            table = block.table
            content = "\n".join(" | ".join(plain_text_from_inline(cell.inline) for cell in row.cells) for row in table.rows)
            return Element(type=ElementType.TABLE, content=content, table=table, **common)
        if block.kind == ElementType.IMAGE:
            return Element(type=ElementType.IMAGE, content="", image=block.image, **common)
        if block.kind == ElementType.CODE_BLOCK:
            return Element(type=ElementType.CODE_BLOCK, content=block.code or "", **common)
        if block.kind == ElementType.SECTION_BREAK:
            return Element(type=block.kind, content="", inline=[], sectionBreak=SectionSettings.model_validate(block.section or {}), **common)
        if block.kind in (ElementType.PAGE_BREAK, ElementType.HORIZONTAL_RULE):
            return Element(type=block.kind, content="", inline=[], **common)
        inline = block.inline or []
        return Element(
            type=block.kind,
            content=plain_text_from_inline(inline),
            inline=inline,
            level=block.level,
            **common,
        )

    def _element_rules(self, element: Element, block: _Block, base: dict[str, tuple[ParaProps, TextProps]]) -> list[FormattingRule]:
        """What this element sets differently from its type's style, as rules
        for just this element."""
        rules: list[FormattingRule] = []

        def add(prop: FormattingProperty, value, unit: str | None = None) -> None:
            text = "true" if value is True else "false" if value is False else f"{value:g}" if isinstance(value, float) else str(value)
            rules.append(
                FormattingRule(
                    target=element.id,
                    property=prop,
                    value=text,
                    unit=unit,
                    priority=Priority.SOURCE_DOCUMENT,
                    source=SOURCE_DOCUMENT_SOURCE,
                )
            )

        if block.kind == ElementType.IMAGE:
            if block.image_alignment:
                add(FormattingProperty.IMAGE_ALIGNMENT, block.image_alignment)
            if block.image_width_percent:
                add(FormattingProperty.IMAGE_WIDTH, float(block.image_width_percent), "%")
            return rules
        if block.kind in (ElementType.PAGE_BREAK, ElementType.SECTION_BREAK, ElementType.HORIZONTAL_RULE):
            return rules

        base_para, base_text = as_word_draws(*base.get(target_for_element(element), (ParaProps(), TextProps())))
        para, text = block.para, block.text
        if block.kind == ElementType.LIST:
            para = replace(para, indent_left_cm=None, first_line_cm=None)
            if block.list_indent_levels:
                add(FormattingProperty.INDENT_LEFT, round(0.63 * block.list_indent_levels, 2), "cm")
        if block.kind == ElementType.TABLE:
            para = ParaProps()
        if block.kind not in (ElementType.TABLE, ElementType.FOOTNOTE):
            # Resolved through its own style: what that leaves unset is what Word draws (FMT-004).
            # A table's or a note's look is only what its text shares; the rest is its kind's.
            para, text = as_word_draws(para, text)

        font = safe_font(text.font)
        if font and font != safe_font(base_text.font):
            add(FormattingProperty.FONT_FAMILY, font)
        if text.size_pt and text.size_pt != base_text.size_pt and 0 < text.size_pt <= 400:
            add(FormattingProperty.FONT_SIZE, float(text.size_pt), "pt")
        color = safe_color(text.color)
        if color and color != base_text.color:
            add(FormattingProperty.COLOR, color)
        for prop, value, base_value in (
            (FormattingProperty.BOLD, text.bold, base_text.bold),
            (FormattingProperty.ITALIC, text.italic, base_text.italic),
            (FormattingProperty.UNDERLINE, text.underline, base_text.underline),
        ):
            if bool(value) != bool(base_value):
                add(prop, bool(value))

        if para.alignment and para.alignment != base_para.alignment:
            add(FormattingProperty.ALIGNMENT, para.alignment)
        if para.space_before_pt is not None and para.space_before_pt != base_para.space_before_pt and 0 <= para.space_before_pt <= 500:
            add(FormattingProperty.SPACE_BEFORE, float(para.space_before_pt), "pt")
        if para.space_after_pt is not None and para.space_after_pt != base_para.space_after_pt and 0 <= para.space_after_pt <= 500:
            add(FormattingProperty.PARAGRAPH_SPACING, float(para.space_after_pt), "pt")
        if para.line_spacing is not None and para.line_spacing != base_para.line_spacing:
            value, unit = para.line_spacing
            if value > 0:
                add(FormattingProperty.LINE_SPACING, float(value), unit)
        if para.indent_left_cm is not None and para.indent_left_cm != base_para.indent_left_cm and -10 <= para.indent_left_cm <= 20:
            add(FormattingProperty.INDENT_LEFT, float(para.indent_left_cm), "cm")
        if para.first_line_cm is not None and para.first_line_cm != base_para.first_line_cm and -10 <= para.first_line_cm <= 10:
            add(FormattingProperty.FIRST_LINE_INDENT, float(para.first_line_cm), "cm")
        if para.indent_right_cm is not None and para.indent_right_cm != base_para.indent_right_cm and -10 <= para.indent_right_cm <= 20:
            add(FormattingProperty.INDENT_RIGHT, float(para.indent_right_cm), "cm")
        if para.shading and para.shading != base_para.shading:
            add(FormattingProperty.SHADING, para.shading)
        for prop, value, base_value in (
            (FormattingProperty.KEEP_WITH_NEXT, para.keep_next, base_para.keep_next),
            (FormattingProperty.KEEP_LINES_TOGETHER, para.keep_lines, base_para.keep_lines),
            (FormattingProperty.WIDOW_CONTROL, para.widow_control, base_para.widow_control),
            (FormattingProperty.CONTEXTUAL_SPACING, para.contextual_spacing, base_para.contextual_spacing),
        ):
            if value is not None and bool(value) != bool(base_value):
                add(prop, bool(value))
        if para.bidi is not None and bool(para.bidi) != bool(base_para.bidi):
            add(FormattingProperty.DIRECTION, "rtl" if para.bidi else "ltr")
        for prop, value, base_value in (
            (FormattingProperty.BORDER_TOP, para.border_top, base_para.border_top),
            (FormattingProperty.BORDER_BOTTOM, para.border_bottom, base_para.border_bottom),
            (FormattingProperty.BORDER_LEFT, para.border_left, base_para.border_left),
            (FormattingProperty.BORDER_RIGHT, para.border_right, base_para.border_right),
            (FormattingProperty.TAB_STOPS, para.tab_stops, base_para.tab_stops),
        ):
            if value and value != base_value and is_valid_rule_value(prop, value, None):
                add(prop, value)
        return rules


def _content_width_emu(sect_pr: etree._Element | None) -> int | None:
    if sect_pr is None:
        return None
    pg_sz, pg_mar = sect_pr.find(w("pgSz")), sect_pr.find(w("pgMar"))
    try:
        width = int(pg_sz.get(w("w")))
        if pg_sz.get(w("orient")) == "landscape" and int(pg_sz.get(w("h"))) > width:
            width = int(pg_sz.get(w("h")))
        left = int(pg_mar.get(w("left"))) if pg_mar is not None else 1440
        right = int(pg_mar.get(w("right"))) if pg_mar is not None else 1440
    except (AttributeError, TypeError, ValueError):
        return None
    content = width - left - right
    return content * _EMU_PER_TWIP if content > 0 else None


def _style_id(ppr: etree._Element | None) -> str | None:
    style = ppr.find(w("pStyle")) if ppr is not None else None
    return style.get(w("val")) if style is not None else None


def _on(element: etree._Element | None) -> bool | None:
    if element is None:
        return None
    return element.get(w("val"), "true").lower() not in ("0", "false", "off")


def _int_val(element: etree._Element | None, default: int) -> int:
    try:
        return max(int(element.get(w("val"))), 1) if element is not None else default
    except (TypeError, ValueError):
        return default


def _hex(value: str | None) -> str | None:
    if not value or value.lower() == "auto" or not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        return None
    return f"#{value.upper()}"


def _section_ends(body: etree._Element) -> list[etree._Element]:
    """The section properties that end a section inside the body, in order
    (not the ones a tracked change remembers)."""
    return [
        ppr.find(w("sectPr"))
        for ppr in body.iter(w("pPr"))
        if ppr.find(w("sectPr")) is not None and ppr.getparent() is not None and ppr.getparent().tag == w("p")
    ]


def _next_section_starts(body: etree._Element) -> dict[etree._Element, str]:
    """How the section after each section ending starts: "continuous",
    "nextPage", "evenPage"... A section's w:type describes how that section
    starts (ECMA-376 17.6.22), so it sits on the section after the break."""
    ends = _section_ends(body)
    following = [*ends[1:], body.find(w("sectPr"))]
    starts: dict[etree._Element, str] = {}
    for end, after in zip(ends, following):
        kind = after.find(w("type")) if after is not None else None
        starts[end] = kind.get(w("val"), "nextPage") if kind is not None else "nextPage"
    return starts


def _row_cells(tr: etree._Element) -> list[etree._Element]:
    """A row's cells, including ones wrapped in content controls."""
    cells: list[etree._Element] = []
    for child in tr:
        if child.tag == w("tc"):
            cells.append(child)
        elif child.tag == w("sdt"):
            content = child.find(w("sdtContent"))
            if content is not None:
                cells.extend(content.findall(w("tc")))
    return cells


def _lift(runs: list[RawRun], only: TextProps | None = None) -> tuple[TextProps, list[RawRun]]:
    """Font, size and colour that every visible run shares belong to the
    paragraph (as element formatting a template can override); what varies stays
    on the runs. With `only`, clears exactly those already-lifted values."""
    if only is not None:
        lifted = only
    else:
        visible = [run for run in runs if run.text.strip()]
        values = {}
        for attr in ("font", "size_pt", "color"):
            seen = {getattr(run.fmt, attr) for run in visible}
            values[attr] = seen.pop() if len(seen) == 1 and None not in seen else None
        lifted = TextProps(font=values["font"], size_pt=values["size_pt"], color=values["color"])
    cleared = {attr: None for attr in ("font", "size_pt", "color") if getattr(lifted, attr) is not None}
    if not cleared:
        return lifted, runs
    return lifted, [
        replace(run, fmt=replace(run.fmt, **{attr: None for attr in cleared if getattr(run.fmt, attr) == getattr(lifted, attr)}))
        for run in runs
    ]


_STYLE_FLAGS = ("bold", "italic", "underline")


def _release(text: TextProps, runs: list[RawRun]) -> tuple[TextProps, tuple[str, ...]]:
    """Bold, italic or underline that a paragraph's style sets but one of its runs
    turns off (w:b w:val="0") can't be the block's look: that run would show it
    anyway. The look drops it, and the runs that keep it carry it (DOCX-013)."""
    visible = [run for run in runs if run.text.strip()]
    released = tuple(attr for attr in _STYLE_FLAGS if getattr(text, attr) and any(attr in run.fmt.turned_off for run in visible))
    return (replace(text, **{attr: False for attr in released}) if released else text), released


def _carry(runs: list[RawRun], released: tuple[str, ...]) -> list[RawRun]:
    if not released:
        return runs
    carried: list[RawRun] = []
    for run in runs:
        kept = {attr: True for attr in released if attr not in run.fmt.turned_off and not (attr == "underline" and run.fmt.href)}
        carried.append(replace(run, fmt=replace(run.fmt, **kept)) if run.text and kept else run)
    return carried


def _strip_checkbox(runs: list[RawRun]) -> tuple[list[RawRun], bool | None]:
    text = "".join(run.text for run in runs).lstrip()
    if not text or text[0] not in _CHECKBOXES:
        return runs, None
    checked = _CHECKBOXES[text[0]]
    remaining: list[RawRun] = []
    stage = "glyph"  # then the spaces after it (possibly in later runs), then the text
    for run in runs:
        body = run.text
        if stage == "glyph":
            body = body.lstrip()
            if not body:
                continue
            body, stage = body[1:], "space"
        if stage == "space":
            body = body.lstrip("  \t")
            if not body:
                continue
            stage = "text"
        remaining.append(RawRun(body, run.fmt))
    return remaining, checked


def _inline(runs: list[RawRun], paragraph_font: str | None) -> list[InlineRun]:
    """RawRuns as the model's InlineRuns: formatting as marks, adjacent runs that
    look the same merged, plain-text addresses turned into links when asked for."""
    result: list[InlineRun] = []
    for run in autolink(runs) if _AUTOLINK.get() else runs:
        if not run.text:
            continue
        fmt = run.fmt
        marks: list[Mark] = []
        if fmt.bold:
            marks.append(Mark(type=MarkType.BOLD))
        if fmt.italic:
            marks.append(Mark(type=MarkType.ITALIC))
        if fmt.underline:
            marks.append(Mark(type=MarkType.UNDERLINE, lineStyle=fmt.line_style))
        if fmt.strike:
            marks.append(Mark(type=MarkType.STRIKE, lineStyle="double" if fmt.double_strike else None))
        if fmt.superscript:
            marks.append(Mark(type=MarkType.SUPERSCRIPT))
        elif fmt.subscript:
            marks.append(Mark(type=MarkType.SUBSCRIPT))
        code = is_monospace(fmt.font) and not is_monospace(paragraph_font)
        if code:
            marks.append(Mark(type=MarkType.CODE))
        style = {
            "fontFamily": None if code else safe_font(fmt.font),
            "fontSizePt": fmt.size_pt if fmt.size_pt and 0 < fmt.size_pt <= 400 else None,
            "color": safe_color(fmt.color),
            "backgroundColor": safe_color(fmt.background),
            "caps": fmt.caps or None,
            "smallCaps": fmt.small_caps or None,
            "letterSpacingPt": fmt.spacing_pt if fmt.spacing_pt and -100 <= fmt.spacing_pt <= 100 else None,
            "baselineShiftPt": fmt.position_pt if fmt.position_pt and -100 <= fmt.position_pt <= 100 else None,
            "lang": fmt.lang if fmt.lang and len(fmt.lang) <= 35 else None,
        }
        if any(value is not None for value in style.values()):
            marks.append(Mark(type=MarkType.TEXT_STYLE, **style))
        if fmt.href:
            marks.append(Mark(type=MarkType.LINK, href=fmt.href, title=fmt.link_title))
        if fmt.hidden:
            marks.append(Mark(type=MarkType.HIDDEN))
        if result and result[-1].marks == marks:
            result[-1].text += run.text
        else:
            result.append(InlineRun(text=run.text, marks=marks))
    return result


def _twips_to_cm(twips: int | None) -> float | None:
    return None if twips is None else max(-50.0, min(50.0, round(twips / 566.929, 2)))
