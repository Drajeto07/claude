"""The text of a Word document read straight from its XML, independently of the
importer, for the content check.

Every piece of text counts, wherever it sits, except where the importer's way
of showing it is a deliberate choice made in the open: tracked changes are
taken as accepted, field codes aren't text (their results are), an equation is
its linear text, a drop cap is the first letter of the paragraph it starts, a
text box's paragraphs follow the paragraph it is anchored in, and footnotes and
endnotes follow the body behind the labels the importer gives them (1, 2 / i,
ii). So a
word the importer silently skips -- in a container it doesn't walk, say --
shows up as missing."""

import io
import posixpath
import zipfile
from dataclasses import dataclass

from lxml import etree

from app.parsers.docx_inline import RunFormat, _math_runs
from app.parsers.docx_styles import format_number
from app.security.files import parse_xml_part

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"

# Property blocks never hold visible text.
_SKIP = frozenset(f"{_W}{name}" for name in ("pPr", "rPr", "sdtPr", "sdtEndPr", "tblPr", "tblGrid", "trPr", "tcPr", "sectPr"))


@dataclass
class DocxSource:
    body: str  # the body, then footnotes and endnotes
    header_footer: str  # every header and footer
    # The last section's headers and footers (every kind): what a Word export
    # written into the original file keeps (DOCX-011).
    last_section_header_footer: str = ""


def _relationships(package: zipfile.ZipFile, part: str) -> list[tuple[str, str]]:
    """(type, target part) for each internal relationship of `part`."""
    folder, name = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", f"{name}.rels")
    if rels_name not in package.namelist():
        return []
    root = parse_xml_part(package.read(rels_name))
    found = []
    for rel in root.findall(f"{_REL}Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        target = posixpath.normpath(posixpath.join(folder, rel.get("Target", ""))).lstrip("/")
        found.append((rel.get("Type", ""), target))
    return found


class _Reader:
    def __init__(self, notes: dict[tuple[str, str], list[etree._Element]]) -> None:
        self.notes = notes
        self.referenced: list[tuple[str, str, str]] = []  # (kind, id, label), as the importer numbers them
        self.fields: list[bool] = []  # per open field: has its result begun?
        self.drop_cap = ""  # a drop cap's letter, waiting for the paragraph it starts

    def blocks(self, node: etree._Element, out: list[str]) -> None:
        for child in node:
            if child.tag in _SKIP or child.tag == f"{_MC}Fallback":
                continue
            if child.tag == f"{_W}p":
                self.paragraph(child, out)
            elif child.tag == f"{_MC}AlternateContent":
                choice = child.find(f"{_MC}Choice")
                if choice is not None:
                    self.blocks(choice, out)
            else:  # tables, rows, cells, content controls, custom XML...
                self.blocks(child, out)

    def paragraph(self, paragraph: etree._Element, out: list[str]) -> None:
        parts: list[str] = []
        boxes: list[list[etree._Element]] = []
        self._inline(paragraph, parts, boxes)
        text = "".join(parts)
        properties = paragraph.find(f"{_W}pPr")
        frame = properties.find(f"{_W}framePr") if properties is not None else None
        if frame is not None and frame.get(f"{_W}dropCap"):
            self.drop_cap += text  # the importer shows it as the next paragraph's first letter
            return
        if self.drop_cap and text:
            text, self.drop_cap = self.drop_cap + text, ""
        out.append(text)
        for box in boxes:
            for box_paragraph in box:
                self.paragraph(box_paragraph, out)

    def _inline(self, node: etree._Element, parts: list[str], boxes: list[list[etree._Element]]) -> None:
        for child in node:
            tag = child.tag
            if tag in _SKIP or tag in (f"{_W}del", f"{_W}moveFrom", f"{_W}delText", f"{_W}instrText", f"{_MC}Fallback"):
                continue
            if tag == f"{_W}t":
                if not (self.fields and not self.fields[-1]):
                    parts.append(child.text or "")
            elif tag in (f"{_M}oMath", f"{_M}oMathPara"):
                # The importer's linear form, e.g. (b²−4ac)/(2a): its brackets part the words.
                parts.append("".join(run.text for run in _math_runs(child, RunFormat())))
            elif tag in (f"{_W}tab", f"{_W}ptab"):
                parts.append("\t")
            elif tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
            elif tag == f"{_W}noBreakHyphen":
                parts.append("-")
            elif tag == f"{_W}fldChar":
                kind = child.get(f"{_W}fldCharType")
                if kind == "begin":
                    self.fields.append(False)
                elif kind == "separate" and self.fields:
                    self.fields[-1] = True
                elif kind == "end" and self.fields:
                    self.fields.pop()
            elif tag in (f"{_W}footnoteReference", f"{_W}endnoteReference"):
                kind = "footnote" if tag == f"{_W}footnoteReference" else "endnote"
                note_id = child.get(f"{_W}id")
                if note_id is not None and (kind, note_id) in self.notes:
                    count = sum(1 for entry in self.referenced if entry[0] == kind) + 1
                    label = str(count) if kind == "footnote" else format_number(count, "lowerRoman")
                    self.referenced.append((kind, note_id, label))
                    parts.append(label)
            elif tag == f"{_W}txbxContent":
                boxes.append(child.findall(f"{_W}p"))
            elif tag == f"{_MC}AlternateContent":
                choice = child.find(f"{_MC}Choice")
                if choice is not None:
                    self._inline(choice, parts, boxes)
            else:  # runs, links, insertions, smart tags, fields, content controls, drawings, math, ruby...
                self._inline(child, parts, boxes)


def read_docx_source(file_bytes: bytes) -> DocxSource:
    """Raises zipfile.BadZipFile, KeyError or lxml errors for a package it can't read."""
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as package:
        main = next((target for kind, target in _relationships(package, "") if kind == f"{_RT}officeDocument"), "word/document.xml")
        related = _relationships(package, main)
        notes: dict[tuple[str, str], list[etree._Element]] = {}
        for kind in ("footnote", "endnote"):
            for rel_type, target in related:
                if rel_type == f"{_RT}{kind}s" and target in package.namelist():
                    for note in parse_xml_part(package.read(target)).findall(f"{_W}{kind}"):
                        if note.get(f"{_W}type") not in ("separator", "continuationSeparator", "continuationNotice"):
                            notes[(kind, note.get(f"{_W}id", ""))] = note.findall(f"{_W}p")

        reader = _Reader(notes)
        body: list[str] = []
        document = parse_xml_part(package.read(main))
        reader.blocks(document.find(f"{_W}body"), body)
        for kind, note_id, label in list(reader.referenced):
            note_text: list[str] = []
            for paragraph in notes[(kind, note_id)]:
                reader.paragraph(paragraph, note_text)
            body.append(f"{label} " + "\n".join(note_text))

        last_section = _last_section_parts(package, main, document)
        shown = _section_parts(package, main, document)  # a part no section refers to shows nowhere, not even in Word
        header_footer: list[str] = []
        last: list[str] = []
        for rel_type, target in related:
            if rel_type in (f"{_RT}header", f"{_RT}footer") and target in package.namelist() and target in shown:
                part_text: list[str] = []
                _Reader({}).blocks(parse_xml_part(package.read(target)), part_text)
                header_footer.extend(part_text)
                if target in last_section:
                    last.extend(part_text)
    return DocxSource(body="\n".join(body), header_footer="\n".join(header_footer), last_section_header_footer="\n".join(last))


def _last_section_parts(package: zipfile.ZipFile, main: str, document: etree._Element) -> set[str]:
    """The header and footer parts the body's last section refers to."""
    body = document.find(f"{_W}body")
    sect_pr = body.find(f"{_W}sectPr") if body is not None else None
    return _parts_of(package, main, [sect_pr] if sect_pr is not None else [])


def _section_parts(package: zipfile.ZipFile, main: str, document: etree._Element) -> set[str]:
    """The header and footer parts any section refers to."""
    body = document.find(f"{_W}body")
    return _parts_of(package, main, list(body.iter(f"{_W}sectPr")) if body is not None else [])


def _parts_of(package: zipfile.ZipFile, main: str, sections: list[etree._Element]) -> set[str]:
    ids = {
        reference.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        for sect_pr in sections
        for tag in ("headerReference", "footerReference")
        for reference in sect_pr.findall(f"{_W}{tag}")
    }
    if not ids:
        return set()
    folder, name = posixpath.split(main)
    rels_name = posixpath.join(folder, "_rels", f"{name}.rels")
    if rels_name not in package.namelist():
        return set()
    return {
        posixpath.normpath(posixpath.join(folder, rel.get("Target", ""))).lstrip("/")
        for rel in parse_xml_part(package.read(rels_name)).findall(f"{_REL}Relationship")
        if rel.get("Id") in ids
    }
