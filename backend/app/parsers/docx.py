"""Deterministic DOCX import: structure and formatting read straight from the
file, no AI involved (confidence 1.0 throughout).

What it keeps: headings (Heading/Title styles, or outline levels), paragraphs,
quotes, captions (the Caption style, or "Figure 1:"-style lines next to a
picture or table), lists (numbered on the paragraph or through its style, with
levels, and ☐/☑ checklists), code blocks (paragraphs set entirely in a
monospace font), tables (real colspan/rowspan, cell shading, column
alignment), pictures (size and alignment), page breaks, horizontal rules,
footnotes and endnotes (moved to the end), equations and text boxes (as text).

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
from dataclasses import dataclass, field, replace

from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from lxml import etree

from app.formatting.engine import DEFAULT_RULES, SOURCE_DOCUMENT_SOURCE, recompute_styles
from app.formatting.priorities import Priority
from app.formatting.style_system import compile_rules
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
    Mark,
    MarkType,
    Section,
    TableCell,
    TableContent,
    TableRow,
    plain_text_from_inline,
    target_for_element,
)
from app.parsers.docx_inline import (
    NoteRegistry,
    Notes,
    ParagraphContent,
    ParagraphReader,
    RawRun,
    RunFormat,
    autolink,
    is_monospace,
)
from app.parsers.docx_styles import (
    Numbering,
    ParaProps,
    StyleResolver,
    TextProps,
    extract_style_system,
    para_props_of,
    safe_color,
    safe_font,
    w,
)

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
_HEADING_STYLE = re.compile(r"^heading\s+(\d)$", re.IGNORECASE)


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
    list_indent_levels: int = 0
    table: TableContent | None = None
    image: ImageContent | None = None
    image_alignment: str | None = None
    image_width_percent: float | None = None
    code: str | None = None


def parse_docx(file_bytes: bytes, filename: str, title: str | None = None) -> Document:
    try:
        docx_document = DocxDocument(io.BytesIO(file_bytes))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError) as exc:
        raise DocxParseError(f"{filename!r} is not a valid .docx file") from exc

    importer = _Importer(docx_document)
    importer.read_body()
    return importer.build(filename, title)


class _Importer:
    def __init__(self, docx_document) -> None:
        self.docx = docx_document
        self.resolver = StyleResolver(docx_document)
        self.numbering = Numbering(docx_document)
        self.notes = Notes()
        self.note_registry = NoteRegistry(docx_document)
        self.reader = ParagraphReader(self.resolver, docx_document.part, self.notes, self.note_registry)
        self.blocks: list[_Block] = []
        self.pending_list: list[tuple[ParagraphContent, str, int, str | None]] = []  # (content, num_id, level, style)
        self.pending_drop_cap: list[RawRun] = []
        self.used_styles: dict[str, int] = {}
        body = docx_document.element.body
        sect_pr = body.find(w("sectPr"))
        self.content_width_emu = _content_width_emu(sect_pr)

    # -- reading -------------------------------------------------------------

    def read_body(self) -> None:
        self._read_container(self.docx.element.body)
        self._flush_list()
        self._mark_captions()
        self._append_notes()

    def _read_container(self, container: etree._Element) -> None:
        for child in container:
            if child.tag == w("p"):
                self._paragraph(child)
            elif child.tag == w("tbl"):
                self._flush_list()
                self._table(child)
            elif child.tag == w("sdt"):
                content = child.find(w("sdtContent"))
                if content is not None:
                    self._read_container(content)
            elif child.tag == w("customXml"):
                self._read_container(child)

    def _paragraph(self, p: etree._Element) -> None:
        ppr = p.find(w("pPr"))
        style_id = _style_id(ppr)
        content = self.reader.read(p)
        direct = para_props_of(ppr)

        if ppr is not None and ppr.find(w("framePr")) is not None and ppr.find(w("framePr")).get(w("dropCap")):
            self.pending_drop_cap.extend(content.runs)  # the big first letter, merged into the next paragraph
            return
        if self.pending_drop_cap and content.runs:
            content.runs[:0] = self.pending_drop_cap
            self.pending_drop_cap = []

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
        is_list_item = num_id is not None and heading_level is None and content.text.strip() != ""
        if is_list_item:
            if content.drawings:
                self.notes.add("Images inside list items were not imported.")
            if self.pending_list and self.pending_list[-1][1] != num_id:
                self._flush_list()
            level = ilvl + self._style_list_level(style_id)
            self.pending_list.append((content, num_id, level, style_id))
        else:
            self._flush_list()
            if heading_level is not None and num_id is not None:
                label = self.numbering.next_label(num_id, ilvl)
                if label and content.runs:
                    content.runs.insert(0, RawRun(f"{label} ", content.runs[0].fmt))
            self._text_paragraph(content, style_id, direct, heading_level)
            self._images(content, style_id, direct)

        for box in content.text_boxes:
            for box_paragraph in box:
                self._paragraph(box_paragraph)

        section_break = ppr.find(w("sectPr")) if ppr is not None else None
        if content.page_break_after or _is_page_section_break(section_break):
            self._flush_list()
            self._add(_Block(kind=ElementType.PAGE_BREAK))

    def _text_paragraph(self, content: ParagraphContent, style_id: str | None, direct: ParaProps, heading_level: int | None) -> None:
        if not content.text.strip():
            if content.horizontal_rule and not content.drawings:
                self._add(_Block(kind=ElementType.HORIZONTAL_RULE))
            return
        style_para, style_text = self.resolver.paragraph_style(style_id)
        para = direct.over(style_para)
        lifted, runs = _lift(content.runs)
        text = lifted.over(style_text)
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
        else:
            kind = ElementType.PARAGRAPH
        self._add(
            _Block(kind=kind, style_id=style_id, para=para, text=text, inline=_inline(runs, text.font), level=heading_level)
        )

    def _images(self, content: ParagraphContent, style_id: str | None, direct: ParaProps) -> None:
        if not content.drawings:
            return
        alignment = direct.over(self.resolver.paragraph_style(style_id)[0]).alignment
        for drawing in content.drawings:
            image, width_emu, floating = self._image(drawing)
            if image is None:
                continue
            if floating:
                self.notes.add("Floating pictures were placed in line with the text.")
            width = None
            if width_emu and self.content_width_emu:
                width = round(min(100.0, width_emu / self.content_width_emu * 100), 1)
            self._add(
                _Block(
                    kind=ElementType.IMAGE,
                    image=image,
                    image_alignment=alignment if alignment in ("left", "center", "right") else None,
                    image_width_percent=width,
                )
            )

    def _image(self, drawing: etree._Element) -> tuple[ImageContent | None, int | None, bool]:
        """The picture as an inline data: URI (image_assets.py moves it into asset
        storage before the document is saved), its width in EMU, and whether it floated."""
        try:
            blip = next(drawing.iter(qn("a:blip")), None)
            rel_id = blip.get(qn("r:embed")) if blip is not None else None
            if not rel_id:
                self.notes.add("A linked (not embedded) image was not imported.")
                return None, None, False
            part = self.docx.part.related_parts[rel_id]
            content_type = (part.content_type or "").lower()
            content_type = _CONTENT_TYPE_ALIASES.get(content_type, content_type)
            if content_type not in WEB_IMAGE_TYPES:
                self.notes.add(f"An image in an unsupported format ({content_type or 'unknown'}) was not imported.")
                return None, None, False
            doc_pr = next(drawing.iter(qn("wp:docPr")), None)
            alt = (doc_pr.get("descr") or doc_pr.get("title")) if doc_pr is not None else None
            extent = next(drawing.iter(qn("wp:extent")), None)
            width = int(extent.get("cx")) if extent is not None and (extent.get("cx") or "").isdigit() else None
            floating = drawing.find(qn("wp:anchor")) is not None
            encoded = base64.b64encode(part.blob).decode("ascii")
            return ImageContent(src=f"data:{content_type};base64,{encoded}", alt=alt or None), width, floating
        except Exception:  # noqa: BLE001 -- untrusted file; one broken picture must not abort the import
            self.notes.add("An image could not be read and was not imported.")
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

    def _flush_list(self) -> None:
        if not self.pending_list:
            return
        entries, self.pending_list = self.pending_list, []
        first_content, num_id, first_level, style_id = entries[0]
        bullet = self.numbering.is_bullet(num_id, first_level)
        ordered = (not bullet) if bullet is not None else "number" in self.resolver.name_of(style_id).lower()
        lifted, _ = _lift([run for content, *_ in entries for run in content.runs])
        style_para, style_text = self.resolver.paragraph_style(style_id)
        text = lifted.over(style_text)
        min_level = min(level for _, _, level, _ in entries)
        items: list[ListItem] = []
        checkbox_items = 0
        for content, _, level, _ in entries:
            _, runs = _lift(content.runs, only=lifted)
            runs, checked = _strip_checkbox(runs)
            checkbox_items += checked is not None
            items.append(ListItem(inline=_inline(runs, text.font), level=level - min_level, checked=checked))
        if 0 < checkbox_items < len(items):
            for item in items:  # a checklist is all checkboxes or none
                item.checked = item.checked if item.checked is not None else False
        self.used_styles[style_id or ""] = self.used_styles.get(style_id or "", 0) + len(items)
        self._add(
            _Block(
                kind=ElementType.LIST,
                style_id=style_id,
                para=style_para,
                text=text,
                items=items,
                ordered=ordered and checkbox_items == 0,
                list_indent_levels=min_level,
            )
        )

    def _table(self, tbl: etree._Element) -> None:
        rows: list[TableRow] = []
        open_vertical: dict[int, TableCell] = {}  # grid column -> cell still spanning down
        all_runs: list[RawRun] = []
        column_alignments: dict[int, set[str | None]] = {}
        has_image = has_nested_table = False
        cell_runs: list[tuple[TableCell, list[RawRun]]] = []
        for row_index, tr in enumerate(tbl.findall(w("tr"))):
            cells: list[TableCell] = []
            column = 0
            for tc in _row_cells(tr):
                tc_pr = tc.find(w("tcPr"))
                span = _int_val(tc_pr.find(w("gridSpan")) if tc_pr is not None else None, 1)
                v_merge = tc_pr.find(w("vMerge")) if tc_pr is not None else None
                if v_merge is not None and v_merge.get(w("val"), "continue") != "restart" and column in open_vertical:
                    open_vertical[column].rowspan += 1
                    column += span
                    continue
                runs: list[RawRun] = []
                alignment = None
                for index, paragraph in enumerate(tc.findall(w("p"))):
                    content = self.reader.read(paragraph)
                    has_image = has_image or bool(content.drawings)
                    if index == 0:
                        alignment = para_props_of(paragraph.find(w("pPr"))).alignment
                    if index > 0:
                        runs.append(RawRun("\n", RunFormat()))
                    runs.extend(content.runs)
                for nested in tc.findall(w("tbl")):
                    has_nested_table = True
                    for nested_row in nested.findall(w("tr")):
                        line = " | ".join(self.reader.read(p).text for c in _row_cells(nested_row) for p in c.findall(w("p")))
                        runs.append(RawRun(f"\n{line}", RunFormat()))
                shading = tc_pr.find(w("shd")) if tc_pr is not None else None
                background = safe_color(_hex(shading.get(w("fill")))) if shading is not None else None
                cell = TableCell(inline=[], header=row_index == 0, colspan=span, background=background)
                cell_runs.append((cell, runs))
                all_runs.extend(runs)
                column_alignments.setdefault(column, set()).add(alignment)
                if v_merge is not None:
                    open_vertical[column] = cell
                else:
                    for covered in range(column, column + span):
                        open_vertical.pop(covered, None)
                cells.append(cell)
                column += span
            rows.append(TableRow(cells=cells))
        if has_image:
            self.notes.add("Images inside table cells were not imported.")
        if has_nested_table:
            self.notes.add("Tables inside table cells were imported as lines of text.")
        lifted, _ = _lift(all_runs)
        base_text = self.resolver.paragraph_style(None)[1]
        text = lifted.over(base_text)
        for cell, runs in cell_runs:
            _, own = _lift(runs, only=lifted)
            cell.inline = _inline(own, text.font)
        width = max((sum(cell.colspan for cell in row.cells) for row in rows), default=0)
        alignments = [
            next(iter(values)) if len(values := column_alignments.get(index, {None})) == 1 else None for index in range(width)
        ]
        table = TableContent(
            rows=rows,
            hasHeaderRow=bool(rows),
            alignments=alignments if any(alignments) else None,
        )
        self._add(_Block(kind=ElementType.TABLE, text=text, table=table))

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

    def _add(self, block: _Block) -> None:
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
        self.notes.extend(styles.notes)

        section = Section(order=0)
        elements: list[Element] = []
        rules: list[FormattingRule] = []
        for block in self.blocks:
            element = self._element(block, section.id, len(elements))
            elements.append(element)
            rules.extend(self._element_rules(element, block, styles.base))

        document = Document(
            metadata=DocumentMetadata(
                title=title or self._title(elements, filename),
                sourceType="uploaded_docx",
                originalFilename=filename,
            ),
            sections=[section],
            elements=elements,
            unsupportedFeatures=self.notes.as_list(),
        )
        document.formattingRules = [
            *DEFAULT_RULES,
            *compile_rules(styles.style_system, priority=Priority.SOURCE_DOCUMENT, source=SOURCE_DOCUMENT_SOURCE),
            *rules,
        ]
        recompute_styles(document)
        return document

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

    def _title(self, elements: list[Element], filename: str) -> str:
        if elements and elements[0].type == ElementType.HEADING and elements[0].content.strip():
            return elements[0].content.strip()[:500]
        core_title = (self.docx.core_properties.title or "").strip()
        return core_title[:500] if core_title else filename

    def _element(self, block: _Block, section_id: str, order: int) -> Element:
        common = {"parentId": section_id, "order": order, "confidence": 1.0}
        if block.kind == ElementType.LIST:
            content = "\n".join(plain_text_from_inline(item.inline) for item in block.items or [])
            return Element(type=ElementType.LIST, content=content, listItems=block.items, ordered=block.ordered, **common)
        if block.kind == ElementType.TABLE:
            table = block.table
            content = "\n".join(" | ".join(plain_text_from_inline(cell.inline) for cell in row.cells) for row in table.rows)
            return Element(type=ElementType.TABLE, content=content, table=table, **common)
        if block.kind == ElementType.IMAGE:
            return Element(type=ElementType.IMAGE, content="", image=block.image, **common)
        if block.kind == ElementType.CODE_BLOCK:
            return Element(type=ElementType.CODE_BLOCK, content=block.code or "", **common)
        if block.kind in (ElementType.PAGE_BREAK, ElementType.HORIZONTAL_RULE):
            return Element(type=block.kind, content="", inline=[], **common)
        inline = block.inline or []
        return Element(type=block.kind, content=plain_text_from_inline(inline), inline=inline, level=block.level, **common)

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
        if block.kind in (ElementType.PAGE_BREAK, ElementType.HORIZONTAL_RULE):
            return rules

        base_para, base_text = base.get(target_for_element(element), (ParaProps(), TextProps()))
        para, text = block.para, block.text
        if block.kind == ElementType.LIST:
            para = replace(para, indent_left_cm=None, first_line_cm=None)
            if block.list_indent_levels:
                add(FormattingProperty.INDENT_LEFT, round(0.63 * block.list_indent_levels, 2), "cm")
        if block.kind == ElementType.TABLE:
            para = ParaProps()

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


def _is_page_section_break(sect_pr: etree._Element | None) -> bool:
    if sect_pr is None:
        return False
    kind = sect_pr.find(w("type"))
    return (kind.get(w("val")) if kind is not None else "nextPage") != "continuous"


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
        RawRun(run.text, replace(run.fmt, **{attr: None for attr in cleared if getattr(run.fmt, attr) == getattr(lifted, attr)}))
        for run in runs
    ]


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
    look the same merged, plain-text addresses turned into links."""
    result: list[InlineRun] = []
    for run in autolink(runs):
        if not run.text:
            continue
        fmt = run.fmt
        marks: list[Mark] = []
        if fmt.bold:
            marks.append(Mark(type=MarkType.BOLD))
        if fmt.italic:
            marks.append(Mark(type=MarkType.ITALIC))
        if fmt.underline:
            marks.append(Mark(type=MarkType.UNDERLINE))
        if fmt.strike:
            marks.append(Mark(type=MarkType.STRIKE))
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
        }
        if any(value is not None for value in style.values()):
            marks.append(Mark(type=MarkType.TEXT_STYLE, **style))
        if fmt.href:
            marks.append(Mark(type=MarkType.LINK, href=fmt.href))
        if result and result[-1].marks == marks:
            result[-1].text += run.text
        else:
            result.append(InlineRun(text=run.text, marks=marks))
    return result
