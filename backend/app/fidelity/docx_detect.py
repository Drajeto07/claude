"""Word features the importer changes or leaves out without saying so while it
reads, found by looking at the file itself, so the import report can name them
(the capability matrix rows marked with these report keys). Each finding gives
an example of the text it concerns, since the file's paragraphs don't map one
to one onto the document's elements."""

import io
import zipfile
from collections import Counter
from dataclasses import dataclass

from lxml import etree

from app.fidelity.docx_source import _RT, _relationships
from app.fidelity.report import FidelityItem, FidelityPolicy, ReportBuilder
from app.parsers.docx_inline import _EMAIL, _URL
from app.security.files import parse_xml_part

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W14 = "{http://schemas.microsoft.com/office/word/2010/wordml}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_CUSTOM = "{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}"
_CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_DIAGRAM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
_PLAIN_UNDERLINES = {None, "none", "single", "words"}
_PLAIN_TABLE_STYLES = {None, "TableGrid", "TableNormal"}

_LOSSY, _UNSUPPORTED = FidelityPolicy.LOSSY, FidelityPolicy.UNSUPPORTED


def _on(element: etree._Element | None) -> bool | None:
    """A Word on/off property: None when not set here."""
    if element is None:
        return None
    return element.get(f"{_W}val", "true").lower() not in ("0", "false", "off", "none")


@dataclass
class _RunLook:
    hidden: bool | None = None
    caps: bool | None = None
    underline: str | None = None
    double_strike: bool | None = None

    def over(self, base: "_RunLook") -> "_RunLook":
        return _RunLook(
            hidden=self.hidden if self.hidden is not None else base.hidden,
            caps=self.caps if self.caps is not None else base.caps,
            underline=self.underline if self.underline is not None else base.underline,
            double_strike=self.double_strike if self.double_strike is not None else base.double_strike,
        )


def _look(rpr: etree._Element | None) -> _RunLook:
    if rpr is None:
        return _RunLook()
    caps = [_on(rpr.find(f"{_W}{name}")) for name in ("caps", "smallCaps")]
    underline = rpr.find(f"{_W}u")
    return _RunLook(
        hidden=_on(rpr.find(f"{_W}vanish")),
        caps=True if True in caps else (False if False in caps else None),
        underline=underline.get(f"{_W}val", "single") if underline is not None else None,
        double_strike=_on(rpr.find(f"{_W}dstrike")),
    )


class _Styles:
    """How each style (with the styles it is based on) makes text look."""

    def __init__(self, root: etree._Element | None) -> None:
        self._own: dict[str, tuple[_RunLook, str | None]] = {}
        self._cache: dict[str, _RunLook] = {}
        self.defaults = _RunLook()
        if root is None:
            return
        defaults = root.find(f"{_W}docDefaults/{_W}rPrDefault/{_W}rPr")
        self.defaults = _look(defaults)
        for style in root.findall(f"{_W}style"):
            based = style.find(f"{_W}basedOn")
            self._own[style.get(f"{_W}styleId", "")] = (
                _look(style.find(f"{_W}rPr")),
                based.get(f"{_W}val") if based is not None else None,
            )

    def look(self, style_id: str | None, depth: int = 0) -> _RunLook:
        if not style_id or style_id not in self._own or depth > 20:
            return _RunLook()
        if style_id not in self._cache:
            own, based = self._own[style_id]
            self._cache[style_id] = own.over(self.look(based, depth + 1))
        return self._cache[style_id]


def _number(value: str | None) -> int:
    """A DrawingML integer ("12500", or "12.5%" in strict files); 0 when absent or odd."""
    try:
        return int(float((value or "0").rstrip("%")))
    except ValueError:
        return 0


def _text(node: etree._Element) -> str:
    return "".join(t.text or "" for t in node.iter(f"{_W}t"))


def _example(text: str) -> str:
    text = " ".join(text.split())
    return f"e.g. “{text[:60]}{'…' if len(text) > 60 else ''}”" if text else ""


class _Findings:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.examples: dict[str, str] = {}

    def add(self, key: str, example: str = "", count: int = 1) -> None:
        self.counts[key] += count
        if example and key not in self.examples:
            self.examples[key] = _example(example)


def _paragraph_findings(body: etree._Element, styles: _Styles, found: _Findings) -> None:
    for paragraph in body.iter(f"{_W}p"):
        properties = paragraph.find(f"{_W}pPr")
        style = properties.find(f"{_W}pStyle") if properties is not None else None
        paragraph_look = styles.look(style.get(f"{_W}val") if style is not None else None).over(styles.defaults)
        text = _text(paragraph)
        if properties is not None and _on(properties.find(f"{_W}bidi")):
            found.add("rtl", text)
        in_cell = any(ancestor.tag == f"{_W}tc" for ancestor in paragraph.iterancestors())
        if in_cell and properties is not None and properties.find(f"{_W}numPr") is not None and text.strip():
            found.add("cell_list", text)
        for run in paragraph.iter(f"{_W}r"):
            if any(ancestor.tag in (f"{_W}del", f"{_W}moveFrom") for ancestor in run.iterancestors()):
                continue
            run_text = "".join(t.text or "" for t in run.findall(f"{_W}t"))
            if not run_text.strip():
                continue
            rpr = run.find(f"{_W}rPr")
            character = rpr.find(f"{_W}rStyle") if rpr is not None else None
            look = _look(rpr).over(styles.look(character.get(f"{_W}val") if character is not None else None)).over(paragraph_look)
            if look.hidden:
                found.add("hidden", run_text)
            if look.caps:
                found.add("caps", run_text)
            if look.underline not in _PLAIN_UNDERLINES or look.double_strike:
                found.add("underline", run_text)
            if rpr is not None and _on(rpr.find(f"{_W}rtl")):
                found.add("rtl", run_text)
            if not any(ancestor.tag == f"{_W}hyperlink" for ancestor in run.iterancestors()):
                addresses = [*_URL.findall(run_text), *_EMAIL.findall(run_text)]
                if addresses:
                    found.add("autolink", run_text, len(addresses))


def _structure_findings(body: etree._Element, found: _Findings) -> None:
    for sdt in body.iter(f"{_W}sdt"):
        properties = sdt.find(f"{_W}sdtPr")
        if properties is None:
            continue
        # Checkboxes become checklists; Word's own building blocks (a table of contents...) aren't controls to keep.
        if properties.find(f"{_W14}checkbox") is not None or properties.find(f"{_W}docPartObj") is not None:
            continue
        found.add("content_control", _text(sdt))
    for crop in body.iter(f"{_A}srcRect"):
        if any(_number(crop.get(side)) for side in ("l", "t", "r", "b")):
            found.add("crop")
    for transform in body.iter(f"{_A}xfrm"):
        if _number(transform.get("rot")) % 21_600_000:
            found.add("rotation")
    for data in body.iter(f"{_A}graphicData"):
        uri = data.get("uri", "")
        if uri == _CHART:
            found.add("chart")
        elif uri == _DIAGRAM:
            found.add("smartart")
    for table in body.iter(f"{_W}tbl"):
        properties = table.find(f"{_W}tblPr")
        style = properties.find(f"{_W}tblStyle") if properties is not None else None
        widths = [col.get(f"{_W}w") for col in table.findall(f"{_W}tblGrid/{_W}gridCol")]
        if (
            (style is not None and style.get(f"{_W}val") not in _PLAIN_TABLE_STYLES)
            or (properties is not None and properties.find(f"{_W}tblBorders") is not None)
            or len(set(widths)) > 1
            or table.find(f"{_W}tr/{_W}trPr/{_W}trHeight") is not None
        ):
            found.add("table_geometry", _text(table))


def _page_setup(sect_pr: etree._Element | None) -> tuple | None:
    """Size, orientation, margins and columns, as the file gives them."""
    if sect_pr is None:
        return None
    size, margins, columns = (sect_pr.find(f"{_W}{name}") for name in ("pgSz", "pgMar", "cols"))

    def value(element: etree._Element | None, name: str, default: str | None = None) -> str | None:
        return element.get(f"{_W}{name}", default) if element is not None else default

    return (
        value(size, "w"),
        value(size, "h"),
        value(size, "orient", "portrait"),
        *(value(margins, side) for side in ("top", "right", "bottom", "left")),
        value(columns, "num", "1"),
    )


def _section_findings(body: etree._Element, found: _Findings, *, last_too: bool = True) -> None:
    """The app has one page setup for the whole document (the last section's).
    `last_too=False`: only what the earlier sections have -- a Word export written
    into the original file keeps the last section's properties (DOCX-011)."""
    ends = [
        ppr.find(f"{_W}sectPr")
        for ppr in body.iter(f"{_W}pPr")
        if ppr.find(f"{_W}sectPr") is not None and ppr.getparent() is not None and ppr.getparent().tag == f"{_W}p"
    ]
    last = body.find(f"{_W}sectPr")
    sections = [*ends, last] if last is not None else ends
    main = _page_setup(last)
    for section in ends:
        if _page_setup(section) != main:
            found.add("section_setup")
    for index, section in enumerate(sections):
        if not last_too and section is last:
            continue
        kind = section.find(f"{_W}type")
        if index and kind is not None and kind.get(f"{_W}val") in ("evenPage", "oddPage"):
            found.add("section_break")
        numbering = section.find(f"{_W}pgNumType")
        if numbering is not None:
            start, style = numbering.get(f"{_W}start"), numbering.get(f"{_W}fmt")
            if (start is not None and (index or start != "1")) or style not in (None, "decimal"):
                found.add("page_numbering")
        if section.find(f"{_W}pgBorders") is not None:
            found.add("page_borders")
        if section.find(f"{_W}lnNumType") is not None:
            found.add("line_numbers")
        alignment = section.find(f"{_W}vAlign")
        if alignment is not None and alignment.get(f"{_W}val", "top") != "top":
            found.add("vertical_alignment")


def _metadata_items(package: zipfile.ZipFile, builder: ReportBuilder) -> None:
    # Title, author, dates, subject and keywords are kept (DocumentMetadata.sourceProperties).
    names = set(package.namelist())
    if "docProps/custom.xml" in names:
        custom = parse_xml_part(package.read("docProps/custom.xml"))
        properties = custom.findall(f"{_CUSTOM}property")
        labels = [p for p in properties if (p.get("name") or "").startswith("MSIP_Label_")]
        others = len(properties) - len(labels)
        if labels:
            builder.add(
                "docx.metadata.sensitivity_label",
                _UNSUPPORTED,
                "The document carries a sensitivity label, which isn't kept: check it before sharing an export.",
            )
        if others:
            builder.add(
                "docx.metadata.custom_properties",
                _UNSUPPORTED,
                f"The document's custom properties ({others}) aren't kept.",
                count=others,
            )


_REPORTS = {
    "hidden": ("docx.hidden_text", _LOSSY, "Hidden text is shown as normal text.", True),
    "caps": ("docx.caps", _LOSSY, "Text set in all caps or small caps shows in the case it was typed in.", False),
    "underline": ("docx.underline_variant", _LOSSY, "Double, wavy or dotted underlines and double strikethrough became single ones.", False),
    "autolink": ("docx.autolink", _LOSSY, "Web and e-mail addresses written as plain text became links.", False),
    "content_control": ("docx.content_control", _LOSSY, "Content controls (drop-downs, dates, text fields) were imported as their text.", False),
    "crop": ("docx.image.crop", _LOSSY, "Cropped pictures are shown whole.", False),
    "rotation": ("docx.image.rotation", _LOSSY, "Rotated pictures and shapes are shown upright.", False),
    "chart": ("docx.chart", _UNSUPPORTED, "Charts weren't imported.", True),
    "smartart": ("docx.smartart", _UNSUPPORTED, "SmartArt graphics weren't imported.", True),
    "table_geometry": ("docx.table.geometry", _LOSSY, "Table column widths, borders, row heights and table styles aren't kept.", False),
    "cell_list": ("docx.table.cell_list", _LOSSY, "Bullets and numbers of lists inside table cells were lost; their text is kept.", False),
    "rtl": ("docx.rtl", _LOSSY, "Right-to-left settings aren't kept; the text is.", False),
    "section_setup": (
        "docx.sections.page_setup",
        _LOSSY,
        "Sections with their own page size, orientation, margins or columns use the document's main page setup.",
        False,
    ),
    "section_break": ("docx.sections.break_type", _LOSSY, "Section breaks to the next odd or even page became ordinary page breaks.", False),
    "page_numbering": (
        "docx.sections.page_numbering",
        _LOSSY,
        "Page numbers that restart, start at another number or use another style (i, ii, iii...) are numbered 1, 2, 3... from the first page.",
        False,
    ),
    "page_borders": ("docx.sections.page_borders", _LOSSY, "Page borders aren't kept.", False),
    "line_numbers": ("docx.sections.line_numbers", _LOSSY, "Line numbering isn't kept.", False),
    "vertical_alignment": ("docx.sections.vertical_alignment", _LOSSY, "Text centred vertically on the page is placed at the top.", False),
}


_SECTION_KEYS = ("section_setup", "section_break", "page_numbering", "page_borders", "line_numbers", "vertical_alignment")


def section_findings(file_bytes: bytes, *, last_too: bool) -> dict[str, int]:
    """How often each section finding occurs, by its report key ("docx.sections.page_borders"...)."""
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as package:
        main = next((target for kind, target in _relationships(package, "") if kind == f"{_RT}officeDocument"), "word/document.xml")
        body = parse_xml_part(package.read(main)).find(f"{_W}body")
    found = _Findings()
    if body is not None:
        _section_findings(body, found, last_too=last_too)
    return {_REPORTS[key][0]: found.counts[key] for key in _SECTION_KEYS if found.counts[key]}


def detect_docx_features(file_bytes: bytes) -> list[FidelityItem]:
    """Raises zipfile.BadZipFile, KeyError or lxml errors for a package it can't read."""
    builder = ReportBuilder()
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as package:
        main = next((target for kind, target in _relationships(package, "") if kind == f"{_RT}officeDocument"), "word/document.xml")
        related = _relationships(package, main)
        styles_part = next((target for kind, target in related if kind == f"{_RT}styles" and target in package.namelist()), None)
        styles = _Styles(parse_xml_part(package.read(styles_part)) if styles_part else None)
        body = parse_xml_part(package.read(main)).find(f"{_W}body")
        found = _Findings()
        if body is not None:
            _paragraph_findings(body, styles, found)
            _structure_findings(body, found)
            _section_findings(body, found)
        for key, (feature, policy, reason, content) in _REPORTS.items():
            if found.counts[key]:
                builder.add(feature, policy, reason, source=found.examples.get(key) or None, content_changed=content, count=found.counts[key])
        _metadata_items(package, builder)
    return builder.items()
