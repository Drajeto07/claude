"""An independent check of a Word file's package (tracker TEST-023): what makes
Word refuse a file, or open it "with unreadable content", that python-docx
itself doesn't look at. Every XML part must parse and have a content type;
every relationship must point at a part that is there; every relationship id
a part's XML uses must be one of its relationships; every style, list and
comment the body refers to must be defined. It reads the zip directly, never
through the code that wrote it."""

import posixpath
import zipfile
from collections import Counter
from io import BytesIO

from lxml import etree

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_EXTERNAL = "External"
_PARA_ID = "{http://schemas.microsoft.com/office/word/2010/wordml}paraId"
_W15 = "{http://schemas.microsoft.com/office/word/2012/wordml}"
_COMMENTS_EXTENDED = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"


def _rels_name(part: str) -> str:
    folder, name = posixpath.split(part)
    return posixpath.join(folder, "_rels", f"{name}.rels")


def _target(part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(part), target))


def package_problems(data: bytes) -> list[str]:
    """What is wrong with the package, one line each; empty when nothing is."""
    problems: list[str] = []
    try:
        package = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return ["not a zip package"]
    names = set(package.namelist())
    if "[Content_Types].xml" not in names:
        return ["no [Content_Types].xml"]

    types = etree.fromstring(package.read("[Content_Types].xml"))
    defaults = {node.get("Extension", "").lower() for node in types.iter(f"{_CT}Default")}
    overrides = {node.get("PartName", "").lstrip("/") for node in types.iter(f"{_CT}Override")}
    for name in sorted(names):
        if name.endswith("/") or name == "[Content_Types].xml":
            continue
        base = posixpath.basename(name)
        extension = base.rsplit(".", 1)[1].lower() if "." in base else ""  # ".rels" has one; splitext says it hasn't
        if name not in overrides and extension not in defaults:
            problems.append(f"{name}: no content type")
    for missing in sorted(overrides - names):
        problems.append(f"[Content_Types].xml names a part that isn't there: {missing}")

    trees: dict[str, etree._Element] = {}
    for name in sorted(names):
        if name.endswith((".xml", ".rels")):
            try:
                trees[name] = etree.fromstring(package.read(name))
            except etree.XMLSyntaxError as exc:
                problems.append(f"{name}: not well-formed XML ({exc})")

    for part in sorted(trees):
        if part.endswith(".rels"):
            continue
        rels_name = _rels_name(part) if part != "" else "_rels/.rels"
        rel_ids: set[str] = set()
        if rels_name in trees:
            for rel in trees[rels_name].iter(f"{_REL}Relationship"):
                rel_ids.add(rel.get("Id", ""))
                if rel.get("TargetMode") != _EXTERNAL and _target(part, rel.get("Target", "")) not in names:
                    problems.append(f"{rels_name}: {rel.get('Id')} points at a missing part {rel.get('Target')}")
        # An empty id names nothing: Word writes r:blip="" in its own SmartArt layouts.
        used = {value for node in trees[part].iter() for key, value in node.attrib.items() if key.startswith(_R) and value}
        for rel_id in sorted(used - rel_ids):
            problems.append(f"{part}: uses relationship {rel_id}, which it doesn't have")
    if "_rels/.rels" in trees:
        for rel in trees["_rels/.rels"].iter(f"{_REL}Relationship"):
            if rel.get("TargetMode") != _EXTERNAL and rel.get("Target", "").lstrip("/") not in names:
                problems.append(f"_rels/.rels: {rel.get('Id')} points at a missing part {rel.get('Target')}")

    body = trees.get("word/document.xml")
    if body is not None:
        styles = trees.get("word/styles.xml")
        defined = {node.get(f"{_W}styleId") for node in styles.iter(f"{_W}style")} if styles is not None else set()
        times = Counter(node.get(f"{_W}styleId") for node in styles.iter(f"{_W}style")) if styles is not None else Counter()
        for style_id, count in sorted(times.items(), key=lambda item: str(item[0])):
            if count > 1:
                problems.append(f"word/styles.xml: style {style_id!r} is defined {count} times")
        for tag in ("pStyle", "rStyle", "tblStyle"):
            for node in body.iter(f"{_W}{tag}"):
                if node.get(f"{_W}val") not in defined:
                    problems.append(f"word/document.xml: style {node.get(f'{_W}val')!r} isn't defined")
        numbering = trees.get("word/numbering.xml")
        lists = {node.get(f"{_W}numId") for node in numbering.iter(f"{_W}num")} if numbering is not None else set()
        for node in body.iter(f"{_W}numId"):
            if node.get(f"{_W}val") not in lists | {"0"}:
                problems.append(f"word/document.xml: list {node.get(f'{_W}val')!r} isn't defined")
        drawings = Counter(node.get("id") for node in body.iter(f"{_WP}docPr"))
        for drawing, times in sorted(drawings.items(), key=lambda item: str(item[0])):
            if times > 1:
                problems.append(f"word/document.xml: drawing id {drawing!r} is used {times} times")
        # A footnote or endnote reference names a note its part has (DOCX-024).
        rels = trees.get("word/_rels/document.xml.rels")
        for kind in ("footnote", "endnote"):
            reltype = f"http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}s"
            target = next((rel.get("Target", "") for rel in rels.iter(f"{_REL}Relationship") if rel.get("Type") == reltype), None) if rels is not None else None
            part = trees.get(_target("word/document.xml", target)) if target else None
            have = {node.get(f"{_W}id") for node in part.iter(f"{_W}{kind}")} if part is not None else set()
            for node in body.iter(f"{_W}{kind}Reference"):
                if node.get(f"{_W}id") not in have:
                    problems.append(f"word/document.xml: {kind} {node.get(f'{_W}id')!r} isn't defined")
        comments = trees.get("word/comments.xml")
        kept = {node.get(f"{_W}id") for node in comments.iter(f"{_W}comment")} if comments is not None else set()
        for node in body.iter(f"{_W}commentReference"):
            if node.get(f"{_W}id") not in kept:
                problems.append(f"word/document.xml: comment {node.get(f'{_W}id')!r} isn't defined")
        # A thread's entries name comments by their paragraphs' paraIds (DOCX-021).
        paragraphs = {node.get(_PARA_ID) for node in comments.iter(f"{_W}p")} if comments is not None else set()
        rels = trees.get("word/_rels/document.xml.rels")
        for rel in rels.iter(f"{_REL}Relationship") if rels is not None else ():
            extended = trees.get(_target("word/document.xml", rel.get("Target", ""))) if rel.get("Type") == _COMMENTS_EXTENDED else None
            for entry in extended.iter(f"{_W15}commentEx") if extended is not None else ():
                for name in ("paraId", "paraIdParent"):
                    if entry.get(f"{_W15}{name}") is not None and entry.get(f"{_W15}{name}") not in paragraphs:
                        problems.append(f"{rel.get('Target')}: {name} {entry.get(f'{_W15}{name}')!r} names no comment")
    return list(dict.fromkeys(problems))


def is_sound(data: bytes) -> bool:
    return not package_problems(data)
