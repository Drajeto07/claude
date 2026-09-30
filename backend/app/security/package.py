"""The Word file kept as a document's original, made safe once, at upload (SEC-015,
SEC-016): every Word export of the document is written into it, so whatever it holds goes
out again -- from its body, headers, footers, notes, comments and settings.

- Fields that run a program or pull in outside content keep their last result
  (security/fields.py).
- Nothing in it points outside the file but links a link may have (SEC-014). A Word file
  follows some external targets on its own, when it is opened: a remote template (a
  known way in for macros), a linked picture (a tracking pixel), a sub-document, a linked
  object, a mail-merge data source and its query. Each such relationship goes, with what
  referred to it; a link to an address a link may not have keeps its text.
"""

import io
import posixpath
import zipfile
from dataclasses import dataclass

from lxml import etree

from app.security.fields import STORIES, neutralize_fields
from app.security.files import UnsafeFileError, check_docx, parse_xml_part
from app.security.links import safe_href

_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"


@dataclass(frozen=True)
class Cleaned:
    data: bytes
    fields: int = 0  # fields made their last result
    links: int = 0  # links to an address a link may not have, now their text
    external: int = 0  # other external targets taken out: templates, linked pictures, data sources...


def clean_package(data: bytes) -> Cleaned:
    """The Word file made safe to keep and to export into -- the same bytes when there was
    nothing to do. A file the parser will refuse anyway (damaged, a zip bomb, a DTD) is left
    as it is, for it to say why."""
    try:
        check_docx(data)
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            entries = package.infolist()
            parts = {entry.filename: package.read(entry) for entry in entries}
    except (UnsafeFileError, zipfile.BadZipFile, KeyError, ValueError, EOFError):
        return Cleaned(data)
    trees: dict[str, etree._Element] = {}
    changed: set[str] = set()

    def tree(name: str) -> etree._Element | None:
        if name not in trees:
            root = parse_xml_part(parts[name])
            trees[name] = None if root.getroottree().docinfo.doctype else root
        return trees[name]

    fields = links = external = 0
    try:
        for name, content in parts.items():
            if name.endswith(".xml") and (b"fldSimple" in content or b"instrText" in content):
                root = tree(name)
                if root is not None and root.tag in STORIES and (found := neutralize_fields(root)):
                    fields += found
                    changed.add(name)
        for name, content in parts.items():
            if not name.endswith(".rels") or b"External" not in content:
                continue
            rels = tree(name)
            if rels is None:
                continue
            refused: dict[str, bool] = {}  # id -> whether it was a link
            for rel in list(rels.findall(f"{_PR}Relationship")):
                if rel.get("TargetMode") != "External":
                    continue
                is_link = rel.get("Type") == _HYPERLINK
                if is_link and safe_href(rel.get("Target")) is not None:
                    continue
                refused[rel.get("Id") or ""] = is_link
                rels.remove(rel)
            if not refused:
                continue
            changed.add(name)
            links += sum(refused.values())
            external += len(refused) - sum(refused.values())
            source = _source_of(name)
            if source in parts and source.endswith(".xml") and (root := tree(source)) is not None:
                if _unreference(root, set(refused)):
                    changed.add(source)
        settings = "word/settings.xml"
        if settings in parts and b"mailMerge" in parts[settings] and (root := tree(settings)) is not None:
            for merge in list(root.iter(f"{_W}mailMerge")):
                merge.getparent().remove(merge)
                external += 1
                changed.add(settings)
    except etree.XMLSyntaxError:
        return Cleaned(data)
    if not changed:
        return Cleaned(data)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for entry in entries:
            content = parts[entry.filename]
            if entry.filename in changed:
                content = etree.tostring(trees[entry.filename].getroottree(), xml_declaration=True, encoding="UTF-8", standalone=True)
            package.writestr(entry, content)
    return Cleaned(buffer.getvalue(), fields, links, external)


def _source_of(rels_name: str) -> str:
    """The part a relationships part belongs to: word/_rels/document.xml.rels -> word/document.xml."""
    folder, file = posixpath.split(rels_name)
    return posixpath.join(posixpath.dirname(folder), file.removesuffix(".rels"))


def _unreference(root: etree._Element, ids: set[str]) -> bool:
    """What in a part referred to relationships that are gone: a link keeps its text, a
    linked picture its place (without the link), and anything else goes -- nothing may be
    left pointing at a relationship that isn't there."""
    found = False
    for element in list(root.iter()):
        names = [name for name, value in element.attrib.items() if name.startswith(_R) and value in ids]
        if not names or element.getroottree().getroot() is not root:
            continue  # nothing of it, or inside something already taken out
        found = True
        if element.tag == f"{_W}hyperlink":
            parent = element.getparent()
            for offset, child in enumerate(list(element)):
                parent.insert(parent.index(element) + offset, child)
            parent.remove(element)
        elif element.tag == f"{_A}blip" and names == [f"{_R}link"]:
            del element.attrib[f"{_R}link"]
        elif element.getparent() is not None:
            element.getparent().remove(element)
    return found
