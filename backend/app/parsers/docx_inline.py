"""The content of a Word paragraph, run by run, the way Word shows it.

Included: tracked insertions (and never tracked deletions), content controls,
field results, hyperlinks (also the HYPERLINK-field kind), footnote/endnote
references, equations as linear text with super/subscripts, and symbol-font
checkboxes. Drawings and text boxes are collected for docx.py to place.
Equations, fields, bookmarks, links to bookmarks and comments also leave marker
runs where they start and end, so docx.py can keep them for the DOCX export.
Everything is reported through `Notes` when it can't be kept as-is."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from urllib.parse import urlparse

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from lxml import etree

from app.fidelity.report import FidelityItem, FidelityPolicy
from app.parsers.docx_styles import StyleResolver, TextProps, format_number, hex_color, on_off, text_props_of, w
from app.security.files import parse_xml_part

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

_SAFE_LINK_SCHEMES = ("http", "https", "mailto", "tel", "ftp")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+[^\s<>\"'.,;:!?)\]}]", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)

# Word's highlight colour names (w:highlight) as hex.
_HIGHLIGHTS = {
    "yellow": "#FFFF00",
    "green": "#00FF00",
    "cyan": "#00FFFF",
    "magenta": "#FF00FF",
    "blue": "#0000FF",
    "red": "#FF0000",
    "darkBlue": "#000080",
    "darkCyan": "#008080",
    "darkGreen": "#008000",
    "darkMagenta": "#800080",
    "darkRed": "#800000",
    "darkYellow": "#808000",
    "darkGray": "#808080",
    "lightGray": "#C0C0C0",
    "black": "#000000",
    "white": "#FFFFFF",
}

# Symbol-font characters Word uses for checkboxes and ticks (w:sym, Wingdings).
_WINGDINGS = {"F06F": "☐", "F0A8": "☐", "F071": "☐", "F0FE": "☑", "F0FD": "☒", "F078": "☒", "F0FC": "✓", "F0FB": "✗"}


def field_name(instr: str) -> str:
    """ "DATE", "PAGEREF", ... from a field instruction like ' DATE \\@ "d.M.yyyy" '."""
    words = instr.split()
    return words[0].upper() if words else ""

MONOSPACE_FONTS = frozenset(
    name.lower()
    for name in (
        "Courier",
        "Courier New",
        "Consolas",
        "Lucida Console",
        "Lucida Sans Typewriter",
        "Menlo",
        "Monaco",
        "Source Code Pro",
        "Cascadia Code",
        "Cascadia Mono",
        "Fira Code",
        "Fira Mono",
        "JetBrains Mono",
        "DejaVu Sans Mono",
        "Liberation Mono",
        "Roboto Mono",
        "Ubuntu Mono",
        "SF Mono",
        "Andale Mono",
        "Inconsolata",
        "PT Mono",
    )
)


def is_monospace(font: str | None) -> bool:
    return bool(font) and font.strip().lower() in MONOSPACE_FONTS


def safe_href(value: str | None) -> str | None:
    """Links the editor and exports may keep: web, mail, phone, ftp. Anything
    else (javascript:, file:, internal bookmarks) becomes plain text."""
    if not value:
        return None
    value = value.strip()
    if value.lower().startswith("www."):
        value = f"https://{value}"
    scheme = urlparse(value).scheme.lower()
    return value if scheme in _SAFE_LINK_SCHEMES else None


_LOSSY, _UNSUPPORTED = FidelityPolicy.LOSSY, FidelityPolicy.UNSUPPORTED
_TRACKED = "Tracked changes were imported as accepted (insertions kept, deletions removed)."

# The page-setup, header/footer and style notes (docx_styles.py), by their wording:
# (start of the note, feature, policy, content lost).
_STYLE_NOTES = (
    ("The watermark", "docx.watermark", _UNSUPPORTED, True),
    ("Pictures in the", "docx.header_footer.picture", _UNSUPPORTED, True),
    ("The page margins", "docx.page_setup.margins", _LOSSY, False),
    ("The document is laid out in", "docx.layout", FidelityPolicy.DETECTED_NOT_EDITABLE, False),  # Document.lastSection
)


class Notes:
    """Notes about what couldn't be kept, each said once: for people (the text)
    and for the fidelity report (its feature, policy, whether content was lost,
    and how often it came up)."""

    def __init__(self) -> None:
        self._items: dict[str, list] = {}  # text -> [feature, policy, content lost, count]

    def add(self, text: str, feature: str = "docx.other", policy: FidelityPolicy = _LOSSY, *, content: bool = False) -> None:
        entry = self._items.get(text)
        if entry is None:
            self._items[text] = [feature, policy, content, 1]
        else:
            entry[3] += 1

    def extend(self, texts: list[str] | tuple[str, ...]) -> None:
        """Page-setup, header/footer and style notes, classified by their wording."""
        for text in texts:
            default = ("docx.style.value" if text.endswith("isn't supported and was left out.") else "docx.layout", _LOSSY, False)
            feature, policy, content = next(((f, p, c) for start, f, p, c in _STYLE_NOTES if text.startswith(start)), default)
            self.add(text, feature, policy, content=content)

    def as_list(self) -> list[str]:
        return list(self._items)

    def report_items(self) -> list[FidelityItem]:
        return [
            FidelityItem(feature=feature, policy=policy, reason=text, contentChanged=content, count=count)
            for text, (feature, policy, content, count) in self._items.items()
        ]


@dataclass(frozen=True)
class RunFormat:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    superscript: bool = False
    subscript: bool = False
    font: str | None = None
    size_pt: float | None = None
    color: str | None = None
    background: str | None = None
    href: str | None = None
    link_title: str | None = None  # the link's tooltip (ScreenTip)
    hidden: bool = False  # w:vanish, from the run, its character style, the paragraph's style or the defaults
    # Resolved the same way (DOCX-013): the underline's line style (Mark.lineStyle), a
    # double strikethrough, capitals, character spacing and baseline position in points.
    line_style: str | None = None
    double_strike: bool = False
    caps: bool = False
    small_caps: bool = False
    spacing_pt: float | None = None
    position_pt: float | None = None
    lang: str | None = None  # where it isn't the document's own language
    # Bold, italic or underline the run (or its character style) turns off -- what
    # its paragraph's style sets can then be no block's look (docx.py _release).
    turned_off: frozenset[str] = frozenset()


# Word's underline styles (w:u/@w:val) as the model's Mark.lineStyle: the closest one
# for those it doesn't have (fidelity/docx_detect.py names them). "single" and
# "words" are a plain underline.
LINE_STYLES = {
    "double": "double",
    "thick": "thick",
    "dotted": "dotted",
    "dottedHeavy": "dotted",
    "dash": "dashed",
    "dashedHeavy": "dashed",
    "dashLong": "dashed",
    "dashLongHeavy": "dashed",
    "dotDash": "dashed",
    "dashDotHeavy": "dashed",
    "dotDotDash": "dashed",
    "dashDotDotHeavy": "dashed",
    "wave": "wavy",
    "wavyHeavy": "wavy",
    "wavyDouble": "wavy",
}


_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")


def _tooltip(value: str | None) -> str | None:
    """A tooltip as the model keeps it (Mark.title: at most 500 characters; Word's own limit is 255)."""
    return " ".join((value or "").split())[:500] or None


def field_link_title(instr: str) -> str | None:
    """The ScreenTip of a HYPERLINK field: its \\o "..." switch."""
    match = re.search(r'\\o\s+"([^"]*)"', instr)
    return _tooltip(match.group(1)) if match else None


@dataclass
class RawRun:
    text: str
    fmt: RunFormat
    # A marker (empty text): where something kept for export starts or ends --
    # {"key", "edge": "start"|"end", "kind", ...its data}. See ParagraphReader.kept.
    keep: dict | None = None


@dataclass
class ParagraphContent:
    runs: list[RawRun] = field(default_factory=list)
    page_break_before: bool = False
    page_break_after: bool = False
    drawings: list[etree._Element] = field(default_factory=list)
    # Each text box: its own paragraphs, to be imported after this one.
    text_boxes: list[list[etree._Element]] = field(default_factory=list)
    horizontal_rule: bool = False

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


class NoteRegistry:
    """Footnotes and endnotes by id, labelled in the order the text refers to
    them (1, 2, 3 for footnotes; i, ii, iii for endnotes, as Word does)."""

    def __init__(self, docx_document) -> None:
        self._bodies: dict[tuple[str, str], list[etree._Element]] = {}
        for kind, reltype in (("footnote", RT.FOOTNOTES), ("endnote", RT.ENDNOTES)):
            try:
                part = docx_document.part.part_related_by(reltype)
            except (KeyError, ValueError):
                continue
            root = part.element if hasattr(part, "element") else parse_xml_part(part.blob)
            for note in root.findall(w(kind)):
                if note.get(w("type")) in ("separator", "continuationSeparator", "continuationNotice"):
                    continue
                self._bodies[(kind, note.get(w("id")))] = note.findall(w("p"))
        self.referenced: list[tuple[str, str, str]] = []  # (kind, id, label)

    def reference(self, kind: str, note_id: str | None) -> str | None:
        if note_id is None or (kind, note_id) not in self._bodies:
            return None
        count = sum(1 for entry in self.referenced if entry[0] == kind) + 1
        label = str(count) if kind == "footnote" else format_number(count, "lowerRoman")
        self.referenced.append((kind, note_id, label))
        return label

    def body(self, kind: str, note_id: str) -> list[etree._Element]:
        return self._bodies.get((kind, note_id), [])


class ParagraphReader:
    """Reads paragraphs one after another. Field state carries across
    paragraphs, because a field (a table of contents, say) can span several."""

    def __init__(
        self,
        resolver: StyleResolver,
        part,
        notes: Notes,
        note_registry: NoteRegistry,
        comments: dict[str, dict] | None = None,
    ) -> None:
        self._resolver = resolver
        self._part = part
        self._notes = notes
        self._note_registry = note_registry
        self._fields: list[dict] = []
        self._link_title: str | None = None  # the tooltip of the w:hyperlink or field being read
        self._paragraph_text = TextProps()  # the paragraph's style over the defaults, for what runs carry (hidden, caps...)
        self._comments = comments or {}
        # What the editor can't show but a DOCX export can put back (корекции.docx
        # §11): equations, fields, bookmarks, links to bookmarks, comments. Each
        # gets start/end marker runs; this maps each key to its kind, so docx.py
        # can tell what it attached to an element from what it couldn't.
        self.kept: dict[str, str] = {}
        self._keep_count = 0

    def _keep_start(self, content: ParagraphContent, kind: str, key: str | None = None, **data) -> str:
        if key is None:
            self._keep_count += 1
            key = f"{kind}:{self._keep_count}"
        self.kept[key] = kind
        content.runs.append(RawRun("", RunFormat(), keep={"key": key, "edge": "start", "kind": kind, **data}))
        return key

    @staticmethod
    def _keep_end(content: ParagraphContent, key: str) -> None:
        content.runs.append(RawRun("", RunFormat(), keep={"key": key, "edge": "end"}))

    def read(self, paragraph: etree._Element) -> ParagraphContent:
        content = ParagraphContent()
        ppr = paragraph.find(w("pPr"))
        style = ppr.find(w("pStyle")) if ppr is not None else None
        self._paragraph_text = self._resolver.paragraph_style(style.get(w("val")) if style is not None else None)[1]
        if ppr is not None:
            border = ppr.find(w("pBdr"))
            if border is not None and (border.find(w("bottom")) is not None or border.find(w("top")) is not None):
                content.horizontal_rule = True  # only kept when the paragraph turns out empty
            if ppr.find(w("framePr")) is not None and ppr.find(w("framePr")).get(w("dropCap")) in ("drop", "margin"):
                self._notes.add("Drop caps are shown as normal text.", "docx.drop_cap")
        self._walk(paragraph, content, href=None)
        return content

    # -- structure -----------------------------------------------------------

    def _walk(self, node: etree._Element, content: ParagraphContent, href: str | None) -> None:
        for child in node:
            tag = child.tag
            if tag == w("r"):
                self._run(child, content, href)
            elif tag == w("hyperlink"):
                target = self._hyperlink_target(child)
                anchor = child.get(w("anchor"))
                if target is None and anchor and not anchor.startswith("_Toc"):  # table of contents entries: plain text
                    key = self._keep_start(content, "link", anchor=anchor)
                    self._walk(child, content, None)
                    self._keep_end(content, key)
                else:
                    outer, self._link_title = self._link_title, _tooltip(child.get(w("tooltip"))) if target else None
                    self._walk(child, content, target)
                    self._link_title = outer
            elif tag in (w("ins"), w("moveTo")):
                self._notes.add(_TRACKED, "docx.tracked_changes", content=True)
                self._walk(child, content, href)
            elif tag in (w("del"), w("moveFrom")):
                self._notes.add(_TRACKED, "docx.tracked_changes", content=True)
            elif tag in (w("smartTag"), w("customXml"), w("dir"), w("bdo")):
                self._walk(child, content, href)
            elif tag == w("fldSimple"):
                instr = child.get(w("instr"), "")
                field_href = self._field_href(instr)
                if field_href or not self._keeps_field(instr):
                    outer = self._link_title
                    if field_href:
                        self._link_title = field_link_title(instr)
                    self._walk(child, content, field_href or href)
                    self._link_title = outer
                else:
                    key = self._keep_start(content, "field", instr=instr)
                    self._walk(child, content, href)
                    self._keep_end(content, key)
            elif tag == w("sdt"):
                sdt_content = child.find(w("sdtContent"))
                if sdt_content is not None:
                    self._walk(sdt_content, content, href)
            elif tag in (qn("m:oMathPara"), qn("m:oMath")):
                key = self._keep_start(content, "equation", xml=etree.tostring(child, encoding="unicode", with_tail=False))
                content.runs.extend(_math_runs(child, RunFormat()))
                self._keep_end(content, key)
            elif tag == w("commentRangeStart"):
                comment = self._comments.get(child.get(w("id")) or "")
                if comment is not None:
                    self._keep_start(content, "comment", key=f"comment:{child.get(w('id'))}", **comment)
            elif tag == w("commentRangeEnd"):
                key = f"comment:{child.get(w('id'))}"
                if key in self.kept:
                    self._keep_end(content, key)
            elif tag == w("bookmarkStart"):
                name = child.get(w("name")) or ""
                if name and name != "_GoBack" and child.get(w("id")) is not None:  # _GoBack: Word's last-edit position
                    self._keep_start(content, "bookmark", key=f"bookmark:{child.get(w('id'))}", name=name)
            elif tag == w("bookmarkEnd"):
                key = f"bookmark:{child.get(w('id'))}"
                if key in self.kept:
                    self._keep_end(content, key)

    def _hyperlink_target(self, link: etree._Element) -> str | None:
        """An external link's address; None for a link to a place inside the document."""
        rel_id = link.get(qn("r:id"))
        if rel_id and rel_id in self._part.rels:
            return self._safe(self._part.rels[rel_id].target_ref)
        return None

    def _field_href(self, instr: str) -> str | None:
        match = re.match(r'\s*HYPERLINK\s+"([^"]+)"', instr, re.IGNORECASE)
        return self._safe(match.group(1)) if match else None

    def _safe(self, address: str | None) -> str | None:
        href = safe_href(address)
        if href is None and address and address.strip():
            self._notes.add(
                "Links to addresses that aren't safe to open (javascript:, file: and the like) were kept as plain text.",
                "docx.link.unsafe",
            )
        return href

    def _keeps_field(self, instr: str) -> bool:
        """Every field goes back into an exported file -- a table of contents too, its
        entries the paragraphs it runs across (DOCX-020)."""
        if field_name(instr) == "TOC":
            self._notes.add(
                "The table of contents is shown as its entries; a Word export keeps it a table of contents, for Word to update.",
                "docx.toc",
                FidelityPolicy.DETECTED_NOT_EDITABLE,
            )
        return True

    def _current_field_href(self) -> str | None:
        return self._current_field_link()[0]

    def _current_field_link(self) -> tuple[str | None, str | None]:
        """The address and ScreenTip of the HYPERLINK field whose result this is."""
        for entry in reversed(self._fields):
            if entry["result"] and entry["href"]:
                return entry["href"], field_link_title(entry["instr"])
        return None, None

    def _in_field_instruction(self) -> bool:
        return bool(self._fields) and not self._fields[-1]["result"]

    # -- runs ------------------------------------------------------------------

    def _run(self, run: etree._Element, content: ParagraphContent, href: str | None) -> None:
        title = self._link_title
        if not href:
            href, title = self._current_field_link()
        fmt = self._run_format(run.find(w("rPr")), href, title)
        for child in run:
            self._run_child(child, run, fmt, content)

    def _run_child(self, child: etree._Element, run: etree._Element, fmt: RunFormat, content: ParagraphContent) -> None:
        tag = child.tag
        if tag == w("t"):
            if not self._in_field_instruction():
                _append(content, child.text or "", fmt)
        elif tag in (w("tab"), w("ptab")):
            _append(content, "\t", fmt)
        elif tag == w("br"):
            if child.get(w("type")) == "page":
                if content.text.strip():
                    content.page_break_after = True
                else:
                    content.page_break_before = True
            else:
                _append(content, "\n", fmt)
        elif tag == w("cr"):
            _append(content, "\n", fmt)
        elif tag == w("noBreakHyphen"):
            _append(content, "-", fmt)
        elif tag == w("sym"):
            glyph = _WINGDINGS.get((child.get(w("char")) or "").upper())
            if glyph:
                _append(content, glyph, replace(fmt, font=None))
            else:
                self._notes.add("Characters from symbol fonts (Wingdings and the like) were left out.", "docx.symbol_characters", _UNSUPPORTED, content=True)
        elif tag == w("fldChar"):
            kind = child.get(w("fldCharType"))
            if kind == "begin":
                self._fields.append({"instr": "", "result": False, "href": None, "key": None})
            elif kind == "separate" and self._fields:
                entry = self._fields[-1]
                entry["result"] = True
                entry["href"] = self._field_href(entry["instr"])
                if not entry["href"] and self._keeps_field(entry["instr"]):
                    entry["key"] = self._keep_start(content, "field", instr=entry["instr"])
            elif kind == "end" and self._fields:
                entry = self._fields.pop()
                if entry["key"]:
                    self._keep_end(content, entry["key"])
                elif not entry["result"] and entry["instr"].strip() and self._keeps_field(entry["instr"]):
                    # Never calculated (no result yet): kept all the same, for Word to fill in.
                    self._keep_end(content, self._keep_start(content, "field", instr=entry["instr"]))
        elif tag == w("instrText"):
            if self._fields:
                self._fields[-1]["instr"] += child.text or ""
        elif tag == w("drawing"):
            content.drawings.append(child)
            self._collect_text_boxes(child, content)
        elif tag == w("pict"):
            self._legacy_picture(child, content)
        elif tag == f"{_MC}AlternateContent":
            choice = child.find(f"{_MC}Choice")
            if choice is not None:
                for grandchild in choice:
                    self._run_child(grandchild, run, fmt, content)
        elif tag == w("footnoteReference"):
            self._note_reference("footnote", child, fmt, content)
        elif tag == w("endnoteReference"):
            self._note_reference("endnote", child, fmt, content)
        elif tag == w("commentReference"):
            key = f"comment:{child.get(w('id'))}"
            comment = self._comments.get(child.get(w("id")) or "")
            if key not in self.kept and comment is not None:  # a comment on a point, without a range
                self._keep_end(content, self._keep_start(content, "comment", key=key, **comment))
        elif tag == w("object"):
            self._notes.add("Embedded (OLE) objects, such as spreadsheets, weren't imported.", "docx.embedded_object", _UNSUPPORTED, content=True)

    def _note_reference(self, kind: str, reference: etree._Element, fmt: RunFormat, content: ParagraphContent) -> None:
        label = self._note_registry.reference(kind, reference.get(w("id")))
        if label:
            _append(content, label, replace(fmt, superscript=True, subscript=False))
            self._notes.add("Footnotes and endnotes were moved to the end of the document.", "docx.notes.moved")

    def _collect_text_boxes(self, container: etree._Element, content: ParagraphContent) -> None:
        for box in container.iter(w("txbxContent")):
            paragraphs = box.findall(w("p"))
            if paragraphs:
                content.text_boxes.append(paragraphs)
                self._notes.add("Text boxes were imported as ordinary paragraphs.", "docx.text_box")

    def _legacy_picture(self, pict: etree._Element, content: ParagraphContent) -> None:
        xml = etree.tostring(pict, encoding="unicode")
        if 'o:hr="t"' in xml:
            content.horizontal_rule = True
            return
        self._collect_text_boxes(pict, content)
        if "imagedata" in xml:
            self._notes.add("Pictures in the older Word format (VML) weren't imported.", "docx.image.vml", _UNSUPPORTED, content=True)

    def _run_format(self, rpr: etree._Element | None, href: str | None, title: str | None = None) -> RunFormat:
        title = title if href else None
        if rpr is None:
            return self._styled(RunFormat(href=href, link_title=title), TextProps(), href)
        style = rpr.find(w("rStyle"))
        char_style = self._resolver.character_style(style.get(w("val"))) if style is not None else TextProps()
        text = text_props_of(rpr, self._resolver.theme).over(char_style)
        vert = rpr.find(w("vertAlign"))
        vert_value = vert.get(w("val")) if vert is not None else None
        background = None
        highlight = rpr.find(w("highlight"))
        if highlight is not None:
            background = _HIGHLIGHTS.get(highlight.get(w("val"), ""))
        shading = rpr.find(w("shd"))
        if background is None and shading is not None:
            background = hex_color(shading.get(w("fill")))
        # A link looks like a link in the app; Word's blue underline would just double it.
        fmt = RunFormat(
            bold=bool(text.bold),
            italic=bool(text.italic),
            underline=bool(text.underline) and href is None,
            superscript=vert_value == "superscript",
            subscript=vert_value == "subscript",
            font=text.font,
            size_pt=text.size_pt,
            color=None if href else text.color,
            background=background,
            href=href,
            link_title=title,
            turned_off=frozenset(attr for attr in ("bold", "italic", "underline") if getattr(text, attr) is False),
        )
        return self._styled(fmt, text, href)

    def _styled(self, fmt: RunFormat, text: TextProps, href: str | None) -> RunFormat:
        """What a block's look can't hold, so each run carries it: resolved from the run
        and its character style (`text`), else the paragraph's style and the defaults,
        as Word does -- hidden text (DOCX-025), an underline's line style, strikethrough,
        capitals, spacing and position (DOCX-013)."""
        full = text.over(self._paragraph_text)
        underline_style = full.underline_style if full.underline_style not in (None, "none") else None
        line_style = LINE_STYLES.get(underline_style or "")
        strike = bool(full.strike) or bool(full.double_strike)
        return replace(
            fmt,
            underline=(fmt.underline or line_style is not None) and href is None,
            line_style=line_style if href is None else None,
            strike=strike,
            double_strike=bool(full.double_strike),
            caps=bool(full.caps),
            small_caps=bool(full.small_caps) and not full.caps,
            spacing_pt=full.spacing_pt or None,
            position_pt=full.position_pt or None,
            hidden=bool(full.hidden),
            lang=full.lang if full.lang and _LANGUAGE.match(full.lang) and full.lang.lower() != (self._resolver.default_language or "").lower() else None,
        )


def _append(content: ParagraphContent, text: str, fmt: RunFormat) -> None:
    if not text:
        return
    if content.runs and content.runs[-1].fmt == fmt and content.runs[-1].keep is None:
        content.runs[-1].text += text
    else:
        content.runs.append(RawRun(text=text, fmt=fmt))


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _math_runs(math: etree._Element, fmt: RunFormat) -> list[RawRun]:
    """An equation as linear text: fractions as (a)/(b), roots as √(x), powers
    and indices as super/subscripts."""
    runs: list[RawRun] = []

    def emit(text: str, current: RunFormat) -> None:
        if text:
            if runs and runs[-1].fmt == current:
                runs[-1].text += text
            else:
                runs.append(RawRun(text=text, fmt=current))

    def part(node: etree._Element | None, name: str) -> etree._Element | None:
        return node.find(f"{{{M_NS}}}{name}") if node is not None else None

    def walk(node: etree._Element | None, current: RunFormat) -> None:
        if node is None:
            return
        name = _local(node.tag)
        if name == "r":
            emit("".join(t.text or "" for t in node.iter(f"{{{M_NS}}}t")), current)
        elif name == "sSup":
            walk(part(node, "e"), current)
            walk(part(node, "sup"), replace(current, superscript=True, subscript=False))
        elif name == "sSub":
            walk(part(node, "e"), current)
            walk(part(node, "sub"), replace(current, subscript=True, superscript=False))
        elif name == "sSubSup":
            walk(part(node, "e"), current)
            walk(part(node, "sub"), replace(current, subscript=True, superscript=False))
            walk(part(node, "sup"), replace(current, superscript=True, subscript=False))
        elif name == "f":
            emit("(", current)
            walk(part(node, "num"), current)
            emit(")/(", current)
            walk(part(node, "den"), current)
            emit(")", current)
        elif name == "rad":
            degree = part(node, "deg")
            degree_text = "".join(t.text or "" for t in degree.iter(f"{{{M_NS}}}t")) if degree is not None else ""
            if degree_text:
                emit(degree_text, replace(current, superscript=True))
            emit("√(", current)
            walk(part(node, "e"), current)
            emit(")", current)
        elif name == "d":
            properties = part(node, "dPr")
            begin = part(properties, "begChr")
            end = part(properties, "endChr")
            emit(begin.get(f"{{{M_NS}}}val", "(") if begin is not None else "(", current)
            for index, element in enumerate(node.findall(f"{{{M_NS}}}e")):
                if index:
                    emit(", ", current)
                walk(element, current)
            emit(end.get(f"{{{M_NS}}}val", ")") if end is not None else ")", current)
        elif name == "nary":
            properties = part(node, "naryPr")
            symbol = part(properties, "chr")
            emit(symbol.get(f"{{{M_NS}}}val", "∫") if symbol is not None else "∫", current)
            walk(part(node, "sub"), replace(current, subscript=True, superscript=False))
            walk(part(node, "sup"), replace(current, superscript=True, subscript=False))
            emit(" ", current)
            walk(part(node, "e"), current)
        elif name in ("rPr", "ctrlPr", "dPr", "naryPr", "fPr", "radPr", "sSupPr", "sSubPr", "sSubSupPr", "oMathParaPr"):
            return
        else:
            for child in node:
                walk(child, current)

    walk(math, replace(fmt, italic=True))
    return runs


def autolink(runs: list[RawRun]) -> list[RawRun]:
    """Plain-text web and e-mail addresses become links, as Word does while typing."""
    result: list[RawRun] = []
    for run in runs:
        if run.fmt.href or not ("@" in run.text or "http" in run.text.lower() or "www." in run.text.lower()):
            result.append(run)
            continue
        position = 0
        matches = sorted([*_URL.finditer(run.text), *_EMAIL.finditer(run.text)], key=lambda match: match.start())
        for match in matches:
            if match.start() < position:
                continue  # an e-mail inside a URL, say
            target = match.group(0)
            href = safe_href(f"mailto:{target}" if "@" in target and "://" not in target else target)
            if not href:
                continue
            if match.start() > position:
                result.append(RawRun(run.text[position : match.start()], run.fmt))
            result.append(RawRun(target, replace(run.fmt, href=href, underline=False, color=None)))
            position = match.end()
        if position < len(run.text):
            result.append(RawRun(run.text[position:], run.fmt))
    return result
